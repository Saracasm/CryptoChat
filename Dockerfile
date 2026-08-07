# Backend image: FastAPI app served via the `fastapi` CLI, dependencies
# managed with uv (matches local dev -- no separate requirements.txt to
# keep in sync).
FROM python:3.13-slim

WORKDIR /app

# markitdown[pdf] shells out to poppler for PDF text extraction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Copy dependency files first so this layer is cached across code-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY create_tables.py ./

EXPOSE 8000

# Runs the (idempotent -- CREATE ... IF NOT EXISTS throughout) table/index
# setup on every start, then serves the API. Simpler than a separate
# migration step for a project this size; swap for a real migration tool
# (alembic) if the schema starts changing after data exists in prod.
CMD ["sh", "-c", "uv run python create_tables.py && uv run fastapi run app/main.py --host 0.0.0.0 --port 8000"]
