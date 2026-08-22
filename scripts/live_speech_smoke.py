from __future__ import annotations

import argparse
import asyncio
import sys
from array import array

from backend.app.settings import Settings
from backend.app.voice.asr import VolcRealtimeAsr
from backend.app.voice.tts import VolcStreamingTts


def resample_pcm16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    output_length = int(len(samples) * target_rate / source_rate)
    ratio = source_rate / target_rate
    output = array(
        "h",
        (samples[min(int(index * ratio), len(samples) - 1)] for index in range(output_length)),
    )
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


async def round_trip(text: str) -> tuple[int, str]:
    settings = Settings()
    if not settings.speech_api_key:
        raise RuntimeError("SPEECH_API_KEY is required")

    audio_chunks: list[bytes] = []

    async def collect(chunk: bytes) -> None:
        audio_chunks.append(chunk)

    tts = VolcStreamingTts(
        api_key=settings.speech_api_key,
        resource_id=settings.speech_tts_resource_id,
        voice=settings.speech_voice,
        audio_sink=collect,
    )
    await tts.connect()
    await tts.append(text)
    await tts.finish()
    pcm_24k = b"".join(audio_chunks)
    if not pcm_24k:
        raise RuntimeError("TTS returned no PCM audio")

    pcm_16k = resample_pcm16(pcm_24k, 24000, 16000)
    asr = VolcRealtimeAsr(
        api_key=settings.speech_api_key,
        resource_id=settings.speech_asr_resource_id,
    )
    await asr.connect()
    loop = asyncio.get_running_loop()
    final: asyncio.Future[str] = loop.create_future()

    async def read_events() -> None:
        async for event in asr.events():
            if event.type == "transcript.final" and not final.done():
                final.set_result(event.text)
            elif event.type == "error" and not final.done():
                final.set_exception(RuntimeError(event.detail))

    reader = asyncio.create_task(read_events())
    for start in range(0, len(pcm_16k), 3200):
        await asr.append(pcm_16k[start : start + 3200])
        await asyncio.sleep(0.05)
    await asr.commit()
    transcript = await asyncio.wait_for(final, timeout=20)
    await asr.close()
    reader.cancel()
    await asyncio.gather(reader, return_exceptions=True)
    return len(pcm_24k), transcript


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-trip Doubao TTS audio through SeedASR")
    parser.add_argument("--text", default="杭州今天天气怎么样？")
    args = parser.parse_args()
    audio_bytes, transcript = asyncio.run(round_trip(args.text))
    print(f"TTS_PCM_BYTES={audio_bytes}")
    print(f"ASR_TRANSCRIPT={transcript}")


if __name__ == "__main__":
    main()
