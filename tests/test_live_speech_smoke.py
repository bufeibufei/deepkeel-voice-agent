from __future__ import annotations

from array import array

from backend.app.voice.asr import _frame, _parse
from backend.app.voice.tts import TTS_RESPONSE, _client_frame, _server_frame
from scripts.live_speech_smoke import resample_pcm16


def test_resample_pcm16_changes_sample_count() -> None:
    source = array("h", range(24)).tobytes()
    result = array("h")
    result.frombytes(resample_pcm16(source, 24000, 16000))

    assert len(result) == 16
    assert result[0] == 0
    assert result[-1] == 22


def test_volc_asr_binary_frame_parser_round_trip() -> None:
    payload = b'{"result":{"text":"\xe6\x9d\xad\xe5\xb7\x9e"}}'
    message_type, flags, decoded = _parse(_frame(9, 2, payload, serialization=1))
    assert (message_type, flags) == (9, 2)
    assert decoded["result"]["text"] == "杭州"


def test_volc_tts_v3_audio_frame_parser() -> None:
    session_id = "session-test"
    audio = b"\x01\x02\x03\x04"
    server_data = (
        bytes([0x11, 0xB4, 0x00, 0x00])
        + TTS_RESPONSE.to_bytes(4, "big", signed=True)
        + len(session_id).to_bytes(4, "big")
        + session_id.encode()
        + len(audio).to_bytes(4, "big")
        + audio
    )
    parsed = _server_frame(server_data)
    assert parsed.is_audio
    assert parsed.event == TTS_RESPONSE
    assert parsed.payload == audio
    assert _client_frame(1).startswith(bytes([0x11, 0x14, 0x10, 0]))
