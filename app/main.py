"""FastAPI entrypoint — mounts Slack Bolt async app."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from app.core.config import settings
from app.db.database import init_db
from app.bot.slack_app import app as bolt_app
from app.bot.overdue_daemon import run_daemon

handler = AsyncSlackRequestHandler(bolt_app)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(run_daemon(interval_seconds=3600))
    yield
    task.cancel()


app = FastAPI(title="AssetFlow Copilot", lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok", "service": "assetflow-copilot"}


@app.post("/slack/events")
async def slack_events(request: Request):
    return await handler.handle(request)


@app.post("/slack/interactions")
async def slack_interactions(request: Request):
    return await handler.handle(request)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
