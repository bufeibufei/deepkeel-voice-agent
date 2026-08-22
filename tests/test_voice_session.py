from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.app.api.voice_ws import VoiceSession, spoken_text
from backend.app.settings import Settings


class FakeWebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.events.append(payload)


class FakeOperations:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def request_cancel(self, run_id: str, *, user_id: str) -> None:
        self.cancelled.append(f"{user_id}:{run_id}")


class FakeHarness:
    async def astream(self, _request):
        yield SimpleNamespace(
            event_type="runtime.result",
            payload={
                "result": {
                    "final_answer": {
                        "markdown": "这是一个只在 runtime.result 中返回的规划结果，用于验证分片兜底。"
                    }
                }
            },
        )


class FakeAgent:
    def __init__(self) -> None:
        self.operations = FakeOperations()
        self.harness = FakeHarness()


class FakeTts:
    def __init__(self) -> None:
        self.cancelled = False

    async def cancel(self) -> None:
        self.cancelled = True


def test_spoken_text_removes_markdown_decoration() -> None:
    assert spoken_text("**上午**：[外滩](https://example.com)\n- 看建筑") == "上午：外滩\n看建筑"


async def test_final_answer_without_native_deltas_is_streamed() -> None:
    websocket = FakeWebSocket()
    session = VoiceSession(websocket, FakeAgent(), Settings(voice_agent_demo_mode=True))
    request = SimpleNamespace(run_id="run-final-only")

    await session._stream_agent(request, "turn-0001")

    deltas = [
        event["text"] for event in websocket.events if event["type"] == "assistant.text.delta"
    ]
    assert len(deltas) > 1
    assert "".join(deltas).startswith("这是一个只在 runtime.result 中返回")
    assert websocket.events[-1]["type"] == "turn.completed"


async def test_barge_in_cancels_runtime_task_and_tts() -> None:
    websocket = FakeWebSocket()
    agent = FakeAgent()
    session = VoiceSession(websocket, agent, Settings(voice_agent_demo_mode=True))
    session.run_id = "run-active"
    session.agent_task = asyncio.create_task(asyncio.sleep(30))
    tts = FakeTts()
    session.tts = tts

    await session.cancel_current(reason="speech_started")

    assert agent.operations.cancelled == ["browser-user:run-active"]
    assert tts.cancelled
    assert session.agent_task is None
    assert websocket.events[-1]["type"] == "response.cancelled"
    assert websocket.events[-1]["reason"] == "speech_started"
