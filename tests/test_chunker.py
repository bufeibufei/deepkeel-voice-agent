from backend.app.voice.chunker import SentenceChunker


def test_sentence_chunker_waits_for_speakable_boundary() -> None:
    chunker = SentenceChunker(max_chars=20)
    assert chunker.push("杭州今天") == []
    assert chunker.push("适合出行。上海") == ["杭州今天适合出行。"]
    assert chunker.flush() == ["上海"]


def test_sentence_chunker_bounds_long_unpunctuated_text() -> None:
    chunker = SentenceChunker(max_chars=12)
    chunks = chunker.push("这是一个非常长而且完全没有标点符号的句子")
    assert chunks
    assert all(len(item) <= 12 for item in chunks)
