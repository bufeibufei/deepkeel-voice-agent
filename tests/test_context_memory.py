from __future__ import annotations

from deepkeel.context_window import DeterministicContextWindowManager
from deepkeel.context_window_contracts import ContextWindowPolicy

from backend.app.agent.context_memory import RetainedConversationContextWindowManager


def test_compacted_summary_is_reinjected_into_the_next_run() -> None:
    policy = ContextWindowPolicy(
        max_input_tokens=800,
        reserved_output_tokens=100,
        minimum_recent_history_tokens=128,
        working_memory_ratio=0.5,
    )
    manager = RetainedConversationContextWindowManager(
        DeterministicContextWindowManager(policy=policy)
    )
    history = [
        {
            "id": f"message-{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"第 {index} 条历史。" + "很长的上下文" * 100,
        }
        for index in range(10)
    ]

    manager.prepare("新问题", {}, {"thread_id": "thread-1", "recent_messages": history})
    state = manager.snapshot("thread-1")

    assert state is not None
    assert len(state.recent_messages) < len(history)
    assert state.conversation_summary["checkpoint_id"].startswith("context-")

    next_run = manager.prepare(
        "继续问",
        {},
        {"thread_id": "thread-1", "recent_messages": state.recent_messages},
    )
    reinjected = next_run.context_bundle["runtime_context"]["conversation_summary"]
    assert reinjected["checkpoint_id"] == state.conversation_summary["checkpoint_id"]


def test_conversation_context_can_be_discarded() -> None:
    manager = RetainedConversationContextWindowManager()
    manager.prepare("问题", {}, {"thread_id": "thread-1", "recent_messages": []})

    manager.discard("thread-1")

    assert manager.snapshot("thread-1") is None
