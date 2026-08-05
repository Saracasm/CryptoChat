from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import httpx

from app.agent import CONTEXT_WINDOW, get_portfolio_report, get_reply, summarize_title
from app.dependencies import get_current_profile, get_repository
from app.models import Profile
from app.repository import Repository
from app.schemas import (
    ConversationRead,
    MessageCreate,
    MessageRead,
    PortfolioChartCreate,
    ProfileCreate,
    ProfileRead,
    VisualizationCreate,
)
from app.visualization import (
    PortfolioVisualizationResult,
    VisualizationResult,
    build_market_visualization,
    build_portfolio_visualization,
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


@conversations_router.get("/{conversation_id}/portfolio")
async def get_conversation_portfolio(
    conversation_id: UUID,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """Return the authenticated conversation's live portfolio report."""
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await get_portfolio_report(repo, conversation_id)


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


@conversations_router.post(
    "/{conversation_id}/portfolio-chart", response_model=PortfolioVisualizationResult
)
async def create_portfolio_chart_endpoint(
    conversation_id: UUID,
    body: PortfolioChartCreate,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """Create a private chart (allocation / P&L / cost-vs-value) from the
    authenticated conversation's own portfolio. Reuses get_portfolio_report --
    the same math the chat agent uses -- so figures never drift apart."""
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    portfolio = await get_portfolio_report(repo, conversation_id)
    if "message" in portfolio:
        raise HTTPException(status_code=422, detail=portfolio["message"])
    try:
        return build_portfolio_visualization(portfolio, body.chart_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@conversations_router.post("/{conversation_id}/visualizations", response_model=VisualizationResult)
async def create_visualization(
    conversation_id: UUID,
    body: VisualizationCreate,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """Create chart data, Plotly JSON, and editable Python code for the UI."""
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        return await build_market_visualization(body.coin, body.metric, body.days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Market data provider is unavailable") from exc
