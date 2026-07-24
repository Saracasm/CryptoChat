from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.agent import CONTEXT_WINDOW, get_reply, summarize_title
from app.dependencies import get_current_profile, get_repository
from app.models import Profile
from app.repository import Repository
from app.schemas import (
    ConversationRead,
    MessageCreate,
    MessageRead,
    ProfileCreate,
    ProfileRead,
)

profiles_router = APIRouter(prefix="/profiles", tags=["profiles"])


@profiles_router.post("", response_model=ProfileRead)
async def create_profile(
    body: ProfileCreate,
    repo: Repository = Depends(get_repository),
):
    return await repo.create_profile(name=body.name)


conversations_router = APIRouter(prefix="/conversations", tags=["conversations"])


@conversations_router.post("", response_model=ConversationRead)
async def create_conversation(
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    return await repo.create_conversation(profile_id=profile.id)


@conversations_router.get("", response_model=list[ConversationRead])
async def list_conversations(
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    return await repo.list_conversations(profile.id)


@conversations_router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await repo.delete_conversation(conversation)


@conversations_router.get(
    "/{conversation_id}/messages", response_model=list[MessageRead]
)
async def load_messages(
    conversation_id: UUID,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await repo.get_history(conversation_id)


@conversations_router.post(
    "/{conversation_id}/messages", response_model=MessageRead
)
async def send_message(
    conversation_id: UUID,
    body: MessageCreate,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 1. Save the user's new message.
    await repo.add_message(conversation_id, "user", body.content)

    # 2. Load the full transcript (prior context) and shape it for the agent.
    history = await repo.get_history(conversation_id)
    llm_messages = [{"role": m.role, "content": m.content} for m in history]

    # 3. Run the agent -- it may call tools (log_holding, get_prices, get_portfolio).
    reply_text = await get_reply(repo, conversation_id, llm_messages, user_id=profile.id)
    
    # 4. Save the assistant's reply.
    reply = await repo.add_message(conversation_id, "assistant", reply_text)

    # 5. Auto-title
    full_messages = llm_messages + [{"role": "assistant", "content": reply_text}]
    total_messages = len(full_messages)
    if conversation.title is None:
        title = await summarize_title(full_messages)
        await repo.set_title(conversation, title)
    elif len(history) < CONTEXT_WINDOW <= total_messages:
        title = await summarize_title(full_messages[:CONTEXT_WINDOW])
        await repo.set_title(conversation, title)

    return reply