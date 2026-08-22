from __future__ import annotations

import asyncio
import gzip
import json
import struct
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

import websockets

ASR_URL = "wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_async"


@dataclass(slots=True)
class AsrEvent:
    type: str
    text: str = ""
    raw_type: str = ""
    detail: str = ""


def _header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes([0x11, (message_type << 4) | flags, (serialization << 4) | compression, 0])


def _frame(message_type: int, flags: int, payload: bytes, *, serialization: int) -> bytes:
    compressed = gzip.compress(payload)
    prefix = _header(message_type, flags, serialization, 1)
    return prefix + struct.pack(">I", len(compressed)) + compressed


def _parse(data: bytes) -> tuple[int, int, dict]:
    if len(data) < 8:
        raise ValueError("ASR frame is incomplete")
    offset = (data[0] & 0x0F) * 4
    message_type, flags = data[1] >> 4, data[1] & 0x0F
    compression = data[2] & 0x0F
    if message_type == 0xF:
        code = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
    else:
        code = 0
        if flags in {1, 3}:
            offset += 4
    size = struct.unpack(">I", data[offset : offset + 4])[0]
    payload = data[offset + 4 : offset + 4 + size]
    if compression == 1:
        payload = gzip.decompress(payload)
    decoded = json.loads(payload.decode("utf-8")) if payload else {}
    if code:
        decoded.setdefault("code", code)
    return message_type, flags, decoded


class VolcRealtimeAsr:
    """Doubao SeedASR 2.0 optimized bidirectional streaming client."""

    def __init__(self, *, api_key: str, resource_id: str) -> None:
        self.api_key = api_key
        self.resource_id = resource_id
        self.socket = None
        self._send_lock = asyncio.Lock()
        self._started = False

    async def connect(self) -> None:
        request_id = str(uuid4())
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
            "X-Api-Connect-Id": str(uuid4()),
        }
        for attempt in range(3):
            try:
                self.socket = await websockets.connect(
                    ASR_URL,
                    additional_headers=headers,
                    open_timeout=10,
                    max_size=20 * 1024 * 1024,
                )
                break
            except (ConnectionError, OSError, TimeoutError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        payload = {
            "user": {"uid": "deepkeel-voice-agent"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_nonstream": True,
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
                "result_type": "full",
                "end_window_size": 800,
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        await self._send(_frame(1, 0, encoded, serialization=1))

    async def append(self, pcm: bytes) -> None:
        if self.socket is not None and pcm:
            self._started = True
            await self._send(_frame(2, 0, pcm, serialization=0))

    async def commit(self) -> None:
        if self.socket is not None and self._started:
            await self._send(_frame(2, 2, b"", serialization=0))

    async def events(self) -> AsyncIterator[AsrEvent]:
        if self.socket is None:
            return
        announced = False
        latest = ""
        async for message in self.socket:
            if not isinstance(message, bytes):
                continue
            message_type, flags, payload = _parse(message)
            if message_type == 0xF:
                yield AsrEvent("error", detail=str(payload.get("message") or payload))
                return
            result = payload.get("result") or {}
            text = str(result.get("text") or "")
            if not text:
                text = "".join(
                    str(item.get("text") or "") for item in result.get("utterances") or []
                )
            if text and text != latest:
                if not announced:
                    announced = True
                    yield AsrEvent("speech.started")
                latest = text
                yield AsrEvent("transcript.delta", text=text)
            if flags in {2, 3}:
                if announced:
                    yield AsrEvent("speech.stopped")
                yield AsrEvent("transcript.final", text=latest)
                return

    async def close(self) -> None:
        if self.socket is not None:
            with suppress(Exception):
                await self.socket.close()
            self.socket = None

    async def _send(self, payload: bytes) -> None:
        async with self._send_lock:
            if self.socket is not None:
                await self.socket.send(payload)
