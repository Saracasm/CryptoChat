from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Conversation, Document, DocumentEmbedding, Holding, Message, Profile
from sqlalchemy import text
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Repository:
    """All database reads and writes live here, behind simple method calls."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_profile(self, name: str) -> Profile:
        profile = Profile(name=name)
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def get_profile(self, profile_id: UUID) -> Profile|None:
        return await self._session.get(Profile, profile_id)

    async def create_conversation(self, profile_id: UUID) -> Conversation:
        conversation = Conversation(profile_id=profile_id)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_conversation(
        self, profile_id: UUID, conversation_id: UUID) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.profile_id == profile_id,
        )
        return await self._session.scalar(stmt)

    async def list_conversations(self, profile_id: UUID)-> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.profile_id == profile_id)
            .order_by(Conversation.created_at.desc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def set_title(self, conversation: Conversation, title: str) -> None:
        conversation.title = title
        await self._session.flush()

    async def delete_conversation(self, conversation: Conversation) -> None:
        await self._session.delete(conversation)
        await self._session.flush()

    async def _next_seq(self, conversation_id: UUID) -> int:
        stmt = select(func.coalesce(func.max(Message.seq), 0)).where(
            Message.conversation_id == conversation_id
        )
        current_max = await self._session.scalar(stmt)
        return current_max + 1

    async def add_message(self, conversation_id: UUID, role: str, content: str) -> Message:
        seq = await self._next_seq(conversation_id)
        message = Message(
            conversation_id=conversation_id, role=role, content=content, seq=seq
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def get_history(self, conversation_id: UUID) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_message(self, conversation_id: UUID, message_id: UUID) -> Message | None:
        stmt = select(Message).where(
            Message.id == message_id, Message.conversation_id == conversation_id
        )
        return await self._session.scalar(stmt)

    async def delete_message(self, message: Message) -> None:
        await self._session.delete(message)
        await self._session.flush()

    async def add_holding(
        self, conversation_id: UUID, coin: str, amount: float, buy_price: float) -> Holding:
        """Record one purchase (a lot)."""
        holding = Holding(
            conversation_id=conversation_id,
            coin=coin,
            amount=amount,
            buy_price=buy_price,
        )
        self._session.add(holding)
        await self._session.flush()
        return holding

    async def get_holdings(
        self, conversation_id: UUID, coin: str | None = None
    ) -> list[Holding]:
        """All purchase lots in this conversation, optionally filtered to one coin
        (case-insensitive)."""
        stmt = select(Holding).where(Holding.conversation_id == conversation_id)
        if coin is not None:
            stmt = stmt.where(func.lower(Holding.coin) == coin.lower())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def holding_exists(self, conversation_id: UUID, coin: str, amount: float, buy_price: float) -> bool:
        """Check if an identical holding was already logged (prevents duplicate logging)."""
        stmt = select(Holding).where(
            Holding.conversation_id == conversation_id,
            Holding.coin == coin,
            Holding.amount == amount,
            Holding.buy_price == buy_price,
        )
        existing = await self._session.scalar(stmt)
        return existing is not None

    async def update_holding(self,conversation_id: UUID,coin: str,
        new_amount: float | None = None,
        new_buy_price: float | None = None,
        old_buy_price: float | None = None,) -> bool:
        """Correct a holding's amount/price (optionally matched by old price). Returns True if updated."""
        stmt = select(Holding).where(
            Holding.conversation_id == conversation_id,
            Holding.coin == coin,
        )
        if old_buy_price is not None:
            stmt = stmt.where(Holding.buy_price == old_buy_price)

        holding = await self._session.scalar(stmt)
        if holding is None:
            return False

        if new_amount is not None:
            holding.amount = new_amount
        if new_buy_price is not None:
            holding.buy_price = new_buy_price
        await self._session.flush()
        return True

    async def remove_holding(
        self,
        conversation_id: UUID,
        coin: str,
        buy_price: float | None = None,
    ) -> bool:
        """Delete a holding for a coin, or a specific lot if buy_price is given."""
        stmt = select(Holding).where(
            Holding.conversation_id == conversation_id,
            Holding.coin == coin,
        )
        if buy_price is not None:
            stmt = stmt.where(Holding.buy_price == buy_price)

        holding = await self._session.scalar(stmt)
        if holding is None:
            return False

        await self._session.delete(holding)
        await self._session.flush()
        return True

    async def create_document(
        self, profile_id: UUID, filename: str, content_type: str, raw_text: str
    ) -> Document:
        """Create the parent Document row for one uploaded file."""
        document = Document(
            profile_id=profile_id,
            filename=filename,
            content_type=content_type,
            raw_text=raw_text,
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def add_document_embeddings(
        self,
        document_id: UUID,
        chunks: list[tuple[int, str, list[float], dict]],
    ) -> list[DocumentEmbedding]:
        """Bulk-insert one row per (chunk_index, chunk_text, embedding, metadata)."""
        rows = [
            DocumentEmbedding(
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                embedding=embedding,
                chunk_metadata=metadata,
            )
            for chunk_index, chunk_text, embedding, metadata in chunks
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows

    async def list_documents(self, profile_id: UUID) -> list[Document]:
        """All documents a profile has uploaded, newest first."""
        stmt = (
            select(Document)
            .where(Document.profile_id == profile_id)
            .order_by(Document.created_at.desc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_document(self, profile_id: UUID, document_id: UUID) -> Document | None:
        stmt = select(Document).where(
            Document.id == document_id, Document.profile_id == profile_id
        )
        return await self._session.scalar(stmt)

    async def delete_document(self, document: Document) -> None:
        """Delete a document; cascades to its DocumentEmbedding rows."""
        await self._session.delete(document)
        await self._session.flush()

    async def search_document_chunks(
        self, profile_id: UUID, query_embedding: list[float], top_k: int = 5
    ) -> list[dict]:
        """Cosine-similarity search over one profile's chunks; profile_id is
        scoped via the join, not filtered after the fact."""
        distance = DocumentEmbedding.embedding.cosine_distance(query_embedding)
        stmt = (
            select(
                DocumentEmbedding.chunk_text,
                DocumentEmbedding.chunk_index,
                DocumentEmbedding.chunk_metadata,
                Document.filename,
                Document.id.label("document_id"),
                distance.label("distance"),
            )
            .join(Document, Document.id == DocumentEmbedding.document_id)
            .where(Document.profile_id == profile_id)
            .order_by(distance)
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        return [
            {
                "filename": row.filename,
                "chunk_text": row.chunk_text,
                "chunk_index": row.chunk_index,
                "document_id": str(row.document_id),
                "metadata": row.chunk_metadata,
                "similarity": round(1 - row.distance, 4),  # cosine_distance = 1 - similarity
            }
            for row in result.all()
        ]

    async def execute_raw_sql(self, sql: str) -> list[dict]:
        """Execute a read-only SQL query (SELECT only) and return rows as plain dicts."""
        cleaned = sql.strip().rstrip(";")
        if not cleaned.lower().startswith("select"):
            raise ValueError("Only SELECT queries are permitted here.")
        result = await self._session.execute(text(cleaned))
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def rollback(self) -> None:
        """Reset the session after a failed raw query (Postgres aborts the whole transaction)."""
        await self._session.rollback()


    async def create_profile_with_password(self, username: str, password: str) -> Profile:
        profile = Profile(
            username=username,
            password_hash=pwd_context.hash(password),
        )
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def get_profile_by_username(self, username: str) -> Profile | None:
        stmt = select(Profile).where(Profile.username == username)
        return await self._session.scalar(stmt)