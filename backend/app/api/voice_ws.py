from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from time import time
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from websockets import WebSocketException

from backend.app.agent.runtime import AgentRuntime
from backend.app.agent.travel_pack import MCP_TOOL_NAMES
from backend.app.settings import Settings
from backend.app.voice.asr import VolcRealtimeAsr
from backend.app.voice.chunker import SentenceChunker
from backend.app.voice.tts import VolcStreamingTts

logger = logging.getLogger(__name__)


def spoken_text(markdown: str) -> str:
    """Remove common Markdown decoration while preserving readable structure."""
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", markdown)
    text = re.sub(r"(?m)^\s*[-+*]\s+", "", text)
    return re.sub(r"[*_`#>]", "", text).strip()


class VoiceSession:
    def __init__(self, websocket: WebSocket, agent: AgentRuntime, settings: Settings) -> None:
        self.ws = websocket
        self.agent = agent
        self.settings = settings
        self.conversation_id = f"conversation-{uuid4().hex[:12]}"
        self.turn = 0
        self.sequence = 0
        self.send_lock = asyncio.Lock()
        self.agent_task: asyncio.Task | None = None
        self.asr_task: asyncio.Task | None = None
        self.asr: VolcRealtimeAsr | None = None
        self.tts: VolcStreamingTts | None = None
        self.run_id = ""
        self.recent_messages: list[dict[str, str]] = []
        self.closed = False

    async def run(self) -> None:
        await self.ws.accept()
        await self.send(
            "session.ready",
            conversation_id=self.conversation_id,
            live=self.settings.agent_live_enabled,
            agent_live=self.settings.agent_live_enabled,
            speech_live=self.settings.speech_live_enabled,
            asr_connected=False,
            input_sample_rate=16000,
            output_sample_rate=24000,
            mcp_tools=list(MCP_TOOL_NAMES),
            hint="点击麦克风开始，或输入文字验证 Agent。",
        )
        try:
            while True:
                message = await self.ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    if self.asr is not None:
                        await self.asr.append(message["bytes"])
                    continue
                payload = message.get("text")
                if payload is not None:
                    await self._control(payload)
        except WebSocketDisconnect:
            pass
        finally:
            await self.close()

    async def _control(self, raw: str) -> None:
        import json

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await self.send("error", message="无法解析客户端消息。")
            return
        event_type = payload.get("type")
        if event_type == "text.submit":
            text = str(payload.get("text") or "").strip()
            if text:
                await self.start_turn(text, source="text")
        elif event_type == "audio.start":
            await self.cancel_current(reason="user_barge_in")
            await self._ensure_asr()
            await self.send("listening.started")
        elif event_type == "response.cancel":
            await self.cancel_current(reason="user_barge_in")
        elif event_type == "audio.commit":
            if self.asr is not None:
                await self.asr.commit()
            await self.send("listening.committed")
        elif event_type == "ping":
            await self.send("pong")

    async def _read_asr(self) -> None:
        assert self.asr is not None
        try:
            async for event in self.asr.events():
                if event.type == "speech.started":
                    await self.cancel_current(reason="speech_started")
                    await self.send("listening.speech_started")
                elif event.type == "speech.stopped":
                    await self.send("listening.speech_stopped")
                elif event.type == "transcript.delta":
                    await self.send("transcript.delta", text=event.text)
                elif event.type == "transcript.final":
                    text = event.text.strip()
                    await self.send("transcript.final", text=text)
                    if text:
                        await self.start_turn(text, source="voice")
                elif event.type == "error":
                    await self.send("speech.error", message=event.detail)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("ASR stream disconnected", exc_info=True)
            await self.send("speech.error", message=f"实时识别连接中断：{type(exc).__name__}")
        finally:
            if self.asr is not None:
                await self.asr.close()
                self.asr = None
            if self.asr_task is asyncio.current_task():
                self.asr_task = None

    async def _ensure_asr(self) -> None:
        if not self.settings.speech_live_enabled or self.asr is not None:
            return
        try:
            self.asr = VolcRealtimeAsr(
                api_key=self.settings.speech_api_key,
                resource_id=self.settings.speech_asr_resource_id,
            )
            await self.asr.connect()
            self.asr_task = asyncio.create_task(self._read_asr())
        except (ConnectionError, OSError, TimeoutError, WebSocketException) as exc:
            logger.warning("ASR connection failed", exc_info=True)
            self.asr = None
            await self.send("speech.error", message=f"实时语音识别连接失败：{type(exc).__name__}")

    async def start_turn(self, question: str, *, source: str) -> None:
        await self.cancel_current(reason="new_turn")
        self.turn += 1
        turn_id = f"turn-{self.turn:04d}"
        request = self.agent.request(
            question,
            conversation_id=self.conversation_id,
            turn_id=turn_id,
            recent_messages=self.recent_messages,
        )
        self.recent_messages.append({"role": "user", "content": question})
        self.recent_messages = self.recent_messages[-12:]
        self.run_id = request.run_id
        await self.send(
            "turn.started", turn_id=turn_id, run_id=request.run_id, text=question, source=source
        )
        self.agent_task = asyncio.create_task(self._stream_agent(request, turn_id))

    async def _stream_agent(self, request, turn_id: str) -> None:
        chunker = SentenceChunker()
        audio_started = False
        answer_text = ""
        if self.settings.speech_live_enabled:
            try:
                self.tts = VolcStreamingTts(
                    api_key=self.settings.speech_api_key,
                    resource_id=self.settings.speech_tts_resource_id,
                    voice=self.settings.speech_voice,
                    audio_sink=self._audio,
                )
                await self.tts.connect()
            except Exception as exc:
                logger.warning("TTS connection failed", exc_info=True)
                self.tts = None
                await self.send(
                    "speech.error",
                    turn_id=turn_id,
                    message=f"实时语音合成连接失败：{type(exc).__name__}",
                )
        try:
            async for event in self.agent.harness.astream(request):
                event_type = event.event_type
                payload = dict(event.payload)
                if event_type == "answer.delta":
                    delta = str(payload.get("delta") or "")
                    if not delta:
                        continue
                    answer_text += delta
                    audio_started = await self._emit_answer_delta(
                        delta,
                        turn_id=turn_id,
                        chunker=chunker,
                        audio_started=audio_started,
                    )
                elif event_type in {"final_answer", "runtime.result"} and not answer_text:
                    result = payload.get("result") or {}
                    final_answer = payload.get("final_answer") or result.get("final_answer") or {}
                    markdown = spoken_text(
                        str(final_answer.get("markdown") or final_answer.get("summary") or "")
                    )
                    for start in range(0, len(markdown), 24):
                        delta = markdown[start : start + 24]
                        answer_text += delta
                        audio_started = await self._emit_answer_delta(
                            delta,
                            turn_id=turn_id,
                            chunker=chunker,
                            audio_started=audio_started,
                        )
                        await asyncio.sleep(0)
                elif event_type.startswith("plan."):
                    await self.send(
                        "agent.plan",
                        turn_id=turn_id,
                        event=event_type,
                        summary=str(payload.get("summary") or payload.get("title") or ""),
                    )
                elif event_type.startswith("tool.call."):
                    tool_payload = payload.get("tool_call") or payload.get("tool_result") or {}
                    await self.send(
                        "agent.tool",
                        turn_id=turn_id,
                        event=event_type,
                        tool_name=str(tool_payload.get("name") or ""),
                        status=str(tool_payload.get("status") or ""),
                    )
                elif event_type == "runtime.settled":
                    await self.send(
                        "agent.settled", turn_id=turn_id, status=str(payload.get("status") or "")
                    )
            for sentence in chunker.flush():
                if self.tts is not None:
                    if not audio_started:
                        audio_started = True
                        await self.send(
                            "assistant.audio.started", turn_id=turn_id, sample_rate=24000
                        )
                    await self.tts.append(sentence)
            if self.tts is not None:
                await self.tts.finish()
                self.tts = None
            if answer_text.strip():
                self.recent_messages.append({"role": "assistant", "content": answer_text.strip()})
                self.recent_messages = self.recent_messages[-12:]
            await self.send("turn.completed", turn_id=turn_id, run_id=request.run_id)
        except asyncio.CancelledError:
            await self.send("turn.cancelled", turn_id=turn_id, run_id=request.run_id)
            raise
        except Exception as exc:
            logger.exception("Agent turn failed")
            await self.send(
                "turn.failed",
                turn_id=turn_id,
                run_id=request.run_id,
                message=f"Agent 执行失败：{type(exc).__name__}: {exc}",
            )
        finally:
            if self.tts is not None:
                await self.tts.cancel()
                self.tts = None
            if self.agent_task is asyncio.current_task():
                self.agent_task = None

    async def _emit_answer_delta(
        self,
        delta: str,
        *,
        turn_id: str,
        chunker: SentenceChunker,
        audio_started: bool,
    ) -> bool:
        await self.send("assistant.text.delta", turn_id=turn_id, text=delta)
        for sentence in chunker.push(delta):
            if self.tts is not None:
                if not audio_started:
                    audio_started = True
                    await self.send("assistant.audio.started", turn_id=turn_id, sample_rate=24000)
                await self.tts.append(sentence)
        return audio_started

    async def cancel_current(self, *, reason: str) -> None:
        if self.run_id:
            with suppress(Exception):
                self.agent.operations.request_cancel(self.run_id, user_id="browser-user")
        if self.tts is not None:
            await self.tts.cancel()
            self.tts = None
        if self.agent_task is not None and not self.agent_task.done():
            task, self.agent_task = self.agent_task, None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.run_id:
            await self.send("response.cancelled", run_id=self.run_id, reason=reason)
        self.run_id = ""

    async def send(self, event_type: str, **payload) -> None:
        if self.closed:
            return
        self.sequence += 1
        message = {
            "type": event_type,
            "sequence": self.sequence,
            "timestamp_ms": round(time() * 1000),
            **payload,
        }
        async with self.send_lock:
            with suppress(Exception):
                await self.ws.send_json(message)

    async def _audio(self, pcm: bytes) -> None:
        async with self.send_lock:
            if not self.closed:
                await self.ws.send_bytes(pcm)

    async def close(self) -> None:
        if self.closed:
            return
        await self.cancel_current(reason="disconnect")
        self.closed = True
        if self.asr_task is not None:
            self.asr_task.cancel()
            await asyncio.gather(self.asr_task, return_exceptions=True)
        if self.asr is not None:
            await self.asr.close()


async def voice_socket(websocket: WebSocket, agent: AgentRuntime, settings: Settings) -> None:
    await VoiceSession(websocket, agent, settings).run()
