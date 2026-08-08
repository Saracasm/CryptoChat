from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
import httpx

from app.agent import (
    Deps,
    TITLE_SUMMARY_THRESHOLD,
    get_portfolio_report,
    get_reply,
    plan_visualization,
    summarize_title,
)
from app.dependencies import get_current_profile, get_repository
from app.ingest import ingest_document
from app.models import Profile
from app.repository import Repository, pwd_context
from app.sandbox import SandboxError, run_sandboxed_async, validate_code
from app.schemas import (
    ConversationRead,
    CustomChartRequest,
    CustomChartResult,
    DataframeListResult,
    DocumentRead,
    DocumentUploadResult,
    MessageCreate,
    MessageRead,
    PortfolioChartCreate,
    ProfileCreate,
    ProfileRead,
    VisualizationCreate,
)
from app.security import create_access_token
from app.config import settings
from app.visualization import (
    PortfolioVisualizationResult,
    VisualizationResult,
    build_market_visualization,
    build_portfolio_visualization,
    portfolio_dataframe,
)

profiles_router = APIRouter(prefix="/profiles", tags=["profiles"])


@profiles_router.post("", response_model=ProfileRead)
async def create_profile(
    body: ProfileCreate,
    repo: Repository = Depends(get_repository),
):
    return await repo.create_profile(name=body.name)


@profiles_router.post("/signup")
async def signup(
    username: str,
    password: str,
    repo: Repository = Depends(get_repository),
):
    existing = await repo.get_profile_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    profile = await repo.create_profile_with_password(username=username, password=password)
    return {"id": profile.id, "username": profile.username}


@profiles_router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    repo: Repository = Depends(get_repository),
):
    profile = await repo.get_profile_by_username(form_data.username)
    if not profile or not pwd_context.verify(form_data.password, profile.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(
        user_id=profile.id, username=profile.username, secret=settings.jwt_secret
    )
    return {"access_token": token, "token_type": "bearer"}


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


@conversations_router.delete(
    "/{conversation_id}/messages/{message_id}", status_code=204
)
async def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """Delete one message from the conversation, permanently, from the DB."""
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    message = await repo.get_message(conversation_id, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    await repo.delete_message(message)


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

    await repo.add_message(conversation_id, "user", body.content)

    history = await repo.get_history(conversation_id)
    llm_messages = [{"role": m.role, "content": m.content} for m in history]

    reply_text = await get_reply(repo, conversation_id, llm_messages, user_id=profile.id)

    reply = await repo.add_message(conversation_id, "assistant", reply_text)

    full_messages = llm_messages + [{"role": "assistant", "content": reply_text}]
    total_messages = len(full_messages)
    if conversation.title is None:
        title = await summarize_title(full_messages)
        await repo.set_title(conversation, title)
    elif len(history) < TITLE_SUMMARY_THRESHOLD <= total_messages:
        title = await summarize_title(full_messages[:TITLE_SUMMARY_THRESHOLD])
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
    """Create a portfolio chart, reusing get_portfolio_report so figures never drift from the chat agent's."""
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


@conversations_router.get(
    "/{conversation_id}/dataframes", response_model=DataframeListResult
)
async def list_dataframes(
    conversation_id: UUID,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """What "Make your own graph" can plot: columns + a small preview, not the full dataset."""
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    portfolio = await get_portfolio_report(repo, conversation_id)
    rows = portfolio_dataframe(portfolio) if "message" not in portfolio else []
    if not rows:
        return DataframeListResult(dataframes={})

    return DataframeListResult(
        dataframes={
            "portfolio": {
                "columns": list(rows[0].keys()),
                "row_count": len(rows),
                "preview": rows[:3],
            }
        }
    )


@conversations_router.post(
    "/{conversation_id}/custom-chart", response_model=CustomChartResult
)
async def create_custom_chart(
    conversation_id: UUID,
    body: CustomChartRequest,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """"Make your own graph": run user code against the portfolio, or delegate to the
    visualization planner if only `prompt` is given. Code always runs sandboxed."""
    conversation = await repo.get_conversation(profile.id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not body.code and not body.prompt:
        raise HTTPException(status_code=422, detail="Provide either `code` or `prompt`.")

    if body.code:
        portfolio = await get_portfolio_report(repo, conversation_id)
        rows = portfolio_dataframe(portfolio) if "message" not in portfolio else []
        if not rows:
            raise HTTPException(status_code=422, detail="No portfolio data available to chart yet.")
        try:
            validate_code(body.code)
            chart = await run_sandboxed_async(body.code, {"df": rows})
        except SandboxError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return CustomChartResult(dataframe=body.dataframe, code=body.code, chart=chart)

    result = await plan_visualization(
        Deps(repo=repo, conversation_id=conversation_id, user_id=profile.id), body.prompt
    )
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    if "message" in result:
        raise HTTPException(status_code=422, detail=result["message"])
    plan = result["plan"]
    return CustomChartResult(
        dataframe=f"{plan['data_source']}:{','.join(plan['coins']) or 'own holdings'}",
        code=result["code"],
        chart=result["chart"],
        plan=plan,
    )


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


documents_router = APIRouter(prefix="/documents", tags=["documents"])


@documents_router.post("/upload", response_model=DocumentUploadResult)
async def upload_document(
    file: UploadFile,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """Ingest one file into the profile's RAG corpus: extract -> chunk -> embed -> store."""
    file_bytes = await file.read()
    try:
        summary = await ingest_document(
            repo,
            profile.id,
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return summary


@documents_router.get("", response_model=list[DocumentRead])
async def list_documents(
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    return await repo.list_documents(profile.id)


@documents_router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    profile: Profile = Depends(get_current_profile),
    repo: Repository = Depends(get_repository),
):
    """Delete an uploaded document and all of its chunk embeddings."""
    document = await repo.get_document(profile.id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await repo.delete_document(document)