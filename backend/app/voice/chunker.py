from __future__ import annotations

import re


class SentenceChunker:
    """Turns arbitrary model deltas into short, speakable text segments."""

    def __init__(self, max_chars: int = 48) -> None:
        self.buffer = ""
        self.max_chars = max_chars

    def push(self, delta: str) -> list[str]:
        self.buffer += delta
        chunks: list[str] = []
        while self.buffer:
            match = re.search(r"[。！？；\n]", self.buffer)
            if match:
                end = match.end()
            elif len(self.buffer) >= self.max_chars:
                candidates = [self.buffer.rfind(mark, 0, self.max_chars) for mark in "，、："]
                split = max(candidates)
                end = split + 1 if split >= 16 else self.max_chars
            else:
                break
            chunk, self.buffer = self.buffer[:end].strip(), self.buffer[end:]
            if chunk:
                chunks.append(chunk)
        return chunks

    def flush(self) -> list[str]:
        chunk, self.buffer = self.buffer.strip(), ""
        return [chunk] if chunk else []
