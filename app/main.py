import logging

import logfire

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Configure tracing before importing anything that creates agents/DB connections,
# so every span is captured from app startup.
logfire.configure(
    token=settings.logfire_token,
    send_to_logfire="if-token-present",
    service_name="cryptochat-api",
)
logfire.instrument_pydantic_ai()  # traces every Agent.run() call, incl. tool calls
logfire.instrument_httpx()  # traces outbound calls: OpenRouter, CoinGecko, Gemini
logfire.instrument_asyncpg()  # traces every DB query

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import conversations_router, documents_router, profiles_router
from app.dependencies import require_api_key

app = FastAPI(title="Chat Demo")
logfire.instrument_fastapi(app)  # traces every HTTP request/response

# Allow the Next.js frontend to call this API from the browser. Defaults to
# localhost for local dev; set ALLOWED_ORIGINS in prod (e.g. the EC2 public
# IP/domain the frontend is served from).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(profiles_router)
app.include_router(conversations_router)
app.include_router(documents_router)

@app.get("/")
async def root():
    return {"status": "ok", "docs": "/docs"}

@app.get("/health", dependencies=[Depends(require_api_key)])
async def health():
    return {"status": "ok"}