import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import conversations_router, profiles_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Week 2 Chat Demo")

# Allow the Next.js frontend (localhost:3000) to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profiles_router)
app.include_router(conversations_router)


@app.get("/")
async def root():
    return {"status": "ok", "docs": "/docs"}
