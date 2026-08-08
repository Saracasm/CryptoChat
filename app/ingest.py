"""RAG ingestion pipeline: raw uploaded bytes -> extracted text -> token
chunks -> embeddings -> Document + DocumentEmbedding rows."""

from io import BytesIO

from chonkie import TokenChunker
from markitdown import MarkItDown

from app.embeddings import embed_texts
from app.repository import Repository

# filename extension -> MarkItDown's file_extension hint.
ALLOWED_EXTENSIONS = {
    ".pdf": ".pdf",
    ".docx": ".docx",
    ".md": ".md",
    ".markdown": ".md",
    ".txt": ".txt",
    ".csv": ".csv",
}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB

CHUNK_TOKEN_SIZE = 500
CHUNK_TOKEN_OVERLAP = 50

_markitdown = MarkItDown()
_chunker = TokenChunker(chunk_size=CHUNK_TOKEN_SIZE, chunk_overlap=CHUNK_TOKEN_OVERLAP)


def _validate(filename: str, size_bytes: int) -> str:
    """Return the MarkItDown file-extension hint, or raise ValueError."""
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File is {size_bytes / 1024 / 1024:.1f}MB; the limit is "
            f"{MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB."
        )
    if size_bytes == 0:
        raise ValueError("File is empty.")

    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(set(ALLOWED_EXTENSIONS)))
        raise ValueError(f"Unsupported file type '{suffix}'. Allowed: {allowed}")
    return ALLOWED_EXTENSIONS[suffix]


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Convert PDF/DOCX/MD/TXT/CSV bytes to plain text via MarkItDown."""
    extension = _validate(filename, len(file_bytes))
    try:
        result = _markitdown.convert_stream(BytesIO(file_bytes), file_extension=extension)
    except Exception as exc:  # MarkItDown raises its own exception hierarchy
        raise ValueError(f"Could not read '{filename}': {exc}") from exc

    text = (result.text_content or "").strip()
    if not text:
        raise ValueError(f"No extractable text found in '{filename}'.")
    return text


def chunk_text(text: str) -> list[str]:
    """Split text into ~500-token chunks (50-token overlap) for embedding."""
    return [c.text for c in _chunker.chunk(text) if c.text.strip()]


async def ingest_document(
    repo: Repository, profile_id, filename: str, content_type: str, file_bytes: bytes
) -> dict:
    """Run the full pipeline and persist the result. Raises ValueError on
    any validation/extraction failure -- callers turn that into a 4xx.
    """
    raw_text = extract_text(file_bytes, filename)
    chunks = chunk_text(raw_text)
    if not chunks:
        raise ValueError(f"'{filename}' produced no usable chunks after splitting.")

    vectors = await embed_texts(chunks)

    document = await repo.create_document(
        profile_id=profile_id,
        filename=filename,
        content_type=content_type,
        raw_text=raw_text,
    )
    await repo.add_document_embeddings(
        document.id,
        [
            (index, chunk, vector, {})
            for index, (chunk, vector) in enumerate(zip(chunks, vectors))
        ],
    )

    return {
        "document_id": str(document.id),
        "filename": filename,
        "chunk_count": len(chunks),
        "char_count": len(raw_text),
    }
