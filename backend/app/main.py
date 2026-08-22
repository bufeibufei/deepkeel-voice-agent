from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.agent.runtime import build_agent_runtime
from backend.app.agent.travel_pack import MCP_TOOL_NAMES
from backend.app.api.voice_ws import voice_socket
from backend.app.settings import get_settings

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
settings = get_settings()
agent = build_agent_runtime(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    agent.harness.runtime.close()


app = FastAPI(title="DeepKeel Voice Travel Agent", version="0.1.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/tokens.css")
async def design_tokens() -> FileResponse:
    return FileResponse(ROOT / "tokens.css", media_type="text/css")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": "live" if settings.agent_live_enabled else "demo",
        "agent_live": settings.agent_live_enabled,
        "speech_live": settings.speech_live_enabled,
        "deepkeel": "4.1.0",
        "mcp": {
            "servers": ["travel-tools", "doubao-search"],
            "tools": list(MCP_TOOL_NAMES),
        },
    }


@app.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket) -> None:
    await voice_socket(websocket, agent, settings)
