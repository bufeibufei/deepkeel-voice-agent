from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

import websockets

AudioSink = Callable[[bytes], Awaitable[None]]
TTS_URL = "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"

START_CONNECTION = 1
FINISH_CONNECTION = 2
START_SESSION = 100
CANCEL_SESSION = 101
FINISH_SESSION = 102
TASK_REQUEST = 200
CONNECTION_STARTED = 50
SESSION_STARTED = 150
SESSION_FINISHED = 152
SESSION_FAILED = 153
TTS_RESPONSE = 352


def _client_frame(event: int, session_id: str | None = None, payload: dict | None = None) -> bytes:
    header = bytes([0x11, 0x14, 0x10, 0])
    body = json.dumps(payload or {}, ensure_ascii=False).encode()
    result = header + struct.pack(">i", event)
    if session_id is not None:
        encoded_id = session_id.encode()
        result += struct.pack(">I", len(encoded_id)) + encoded_id
    return result + struct.pack(">I", len(body)) + body


@dataclass(slots=True)
class _ServerFrame:
    message_type: int
    event: int
    payload: bytes
    is_audio: bool
    error_code: int = 0


def _server_frame(data: bytes) -> _ServerFrame:
    if len(data) < 8:
        raise ValueError("TTS frame is incomplete")
    message_type, flags = (data[1] >> 4) & 0xF, data[1] & 0xF
    if message_type == 0xF:
        code = struct.unpack(">I", data[4:8])[0]
        size = struct.unpack(">I", data[8:12])[0] if len(data) >= 12 else 0
        return _ServerFrame(message_type, 0, data[12 : 12 + size], False, code)
    offset = 4
    event = 0
    if flags & 0x4:
        event = struct.unpack(">i", data[offset : offset + 4])[0]
        offset += 4
        id_size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4 + id_size
    size = struct.unpack(">I", data[offset : offset + 4])[0]
    payload = data[offset + 4 : offset + 4 + size]
    return _ServerFrame(message_type, event, payload, message_type == 0xB)


class VolcStreamingTts:
    """Doubao TTS 2.0 Plan bidirectional client with streaming text and PCM output."""

    def __init__(
        self,
        *,
        api_key: str,
        resource_id: str,
        voice: str,
        audio_sink: AudioSink,
    ) -> None:
        self.api_key = api_key
        self.resource_id = resource_id
        self.voice = voice
        self.audio_sink = audio_sink
        self.socket = None
        self.session_id = str(uuid4())
        self._send_lock = asyncio.Lock()
        self._receiver: asyncio.Task | None = None
        self._done = asyncio.Event()
        self._error: Exception | None = None

    async def connect(self) -> None:
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid4()),
        }
        for attempt in range(3):
            try:
                self.socket = await websockets.connect(
                    TTS_URL,
                    additional_headers=headers,
                    open_timeout=10,
                    max_size=20 * 1024 * 1024,
                )
                break
            except (ConnectionError, OSError, TimeoutError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        await self._send(_client_frame(START_CONNECTION))
        frame = _server_frame(await self.socket.recv())
        if frame.event != CONNECTION_STARTED:
            raise RuntimeError(f"Doubao TTS connection failed: event={frame.event}")
        start_payload = {
            "user": {"uid": "deepkeel-voice-agent"},
            "event": START_SESSION,
            "namespace": "BidirectionalTTS",
            "req_params": {
                "speaker": self.voice,
                "audio_params": {"format": "pcm", "sample_rate": 24000},
                "additions": json.dumps({"disable_markdown_filter": False}),
            },
        }
        await self._send(_client_frame(START_SESSION, self.session_id, start_payload))
        frame = _server_frame(await self.socket.recv())
        if frame.event != SESSION_STARTED:
            detail = frame.payload.decode(errors="replace")
            raise RuntimeError(f"Doubao TTS session failed: event={frame.event} {detail}")
        self._receiver = asyncio.create_task(self._receive())

    async def append(self, text: str) -> None:
        if text.strip():
            await self._send(
                _client_frame(TASK_REQUEST, self.session_id, {"req_params": {"text": text}})
            )

    async def finish(self) -> None:
        if self.socket is None:
            return
        await self._send(_client_frame(FINISH_SESSION, self.session_id, {}))
        await asyncio.wait_for(self._done.wait(), timeout=30)
        if self._receiver is not None:
            await self._receiver
            self._receiver = None
        if self._error is not None:
            raise self._error
        await self.close()

    async def cancel(self) -> None:
        if self.socket is not None:
            with suppress(Exception):
                await self._send(_client_frame(CANCEL_SESSION, self.session_id, {}))
        await self.close()

    async def close(self) -> None:
        if self._receiver is not None and self._receiver is not asyncio.current_task():
            self._receiver.cancel()
            await asyncio.gather(self._receiver, return_exceptions=True)
            self._receiver = None
        if self.socket is not None:
            with suppress(Exception):
                await self._send(_client_frame(FINISH_CONNECTION))
            await self.socket.close()
            self.socket = None

    async def _receive(self) -> None:
        try:
            assert self.socket is not None
            async for message in self.socket:
                if not isinstance(message, bytes):
                    continue
                frame = _server_frame(message)
                if frame.event == TTS_RESPONSE and frame.is_audio and frame.payload:
                    await self.audio_sink(frame.payload)
                elif frame.event == SESSION_FINISHED:
                    return
                elif frame.event == SESSION_FAILED or frame.message_type == 0xF:
                    detail = frame.payload.decode(errors="replace")
                    self._error = RuntimeError(
                        f"Doubao TTS failed: code={frame.error_code} {detail}"
                    )
                    return
        except asyncio.CancelledError:
            raise
        except (
            ConnectionError,
            OSError,
            RuntimeError,
            ValueError,
            websockets.WebSocketException,
        ) as exc:
            self._error = exc
        finally:
            self._done.set()

    async def _send(self, payload: bytes) -> None:
        async with self._send_lock:
            if self.socket is not None:
                await self.socket.send(payload)
