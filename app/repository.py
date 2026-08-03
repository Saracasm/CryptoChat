from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Conversation, Holding, Message, Profile
from sqlalchemy import text

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

    async def get_holdings(self, conversation_id: UUID) -> list[Holding]:
        """All purchase lots in this conversation."""
        stmt = select(Holding).where(Holding.conversation_id == conversation_id)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def holding_exists(self, conversation_id: UUID, coin: str, amount: float, buy_price: float) -> bool:
        """Check if an identical holding was already logged in this conversation.

        Prevents the agent from logging the same purchase twice when it
        re-reads earlier messages in the history.
        """
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
        """Correct an existing holding for a coin in this conversation.

        Finds the matching holding (optionally by its old price) and updates
        its amount and/or buy price. Returns True if something was updated.
        """
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
        """Delete a holding for a coin in this conversation.

        If buy_price is given, only deletes the matching lot; otherwise
        deletes the first holding found for that coin. Returns True if deleted.
        """
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

    async def execute_raw_sql(self, sql: str) -> list[dict]:
        """Execute a read-only SQL query and return rows as plain dicts.
        Only SELECT statements are allowed -- this exists to let the SQL
        subagent answer questions, not to let it mutate data.
        """
        cleaned = sql.strip().rstrip(";")
        if not cleaned.lower().startswith("select"):
            raise ValueError("Only SELECT queries are permitted here.")
        result = await self._session.execute(text(cleaned))
        rows = result.mappings().all()
        return [dict(row) for row in rows]