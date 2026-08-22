from __future__ import annotations

import copy
from dataclasses import dataclass
from threading import RLock
from typing import Any

from deepkeel.context_window import DeterministicContextWindowManager
from deepkeel.context_window_contracts import ContextWindowManager, ContextWindowResult


@dataclass(frozen=True, slots=True)
class ConversationContextState:
    recent_messages: list[dict[str, Any]]
    conversation_summary: dict[str, Any]


class RetainedConversationContextWindowManager:
    """Carry DeepKeel's compacted thread context across independent runs."""

    def __init__(self, delegate: ContextWindowManager | None = None) -> None:
        self.delegate = delegate or DeterministicContextWindowManager()
        self._states: dict[str, ConversationContextState] = {}
        self._lock = RLock()

    @property
    def compactor(self) -> Any:
        return getattr(self.delegate, "compactor", None)

    def prepare(
        self,
        question: str,
        short_context: dict[str, Any],
        context_bundle: dict[str, Any],
    ) -> ContextWindowResult:
        bundle = copy.deepcopy(context_bundle)
        thread_id = str(bundle.get("thread_id") or bundle.get("ask_thread_id") or "")
        previous = self.snapshot(thread_id)
        if previous is not None and previous.conversation_summary:
            runtime_context = bundle.get("runtime_context")
            runtime_context = (
                copy.deepcopy(runtime_context) if isinstance(runtime_context, dict) else {}
            )
            runtime_context.setdefault(
                "conversation_summary", copy.deepcopy(previous.conversation_summary)
            )
            bundle["runtime_context"] = runtime_context

        prepared = self.delegate.prepare(question, short_context, bundle)
        prepared_bundle = prepared.context_bundle
        recent = prepared_bundle.get("recent_messages")
        retained_messages = (
            [copy.deepcopy(item) for item in recent if isinstance(item, dict)]
            if isinstance(recent, list)
            else []
        )
        runtime_context = prepared_bundle.get("runtime_context")
        summary = (
            copy.deepcopy(runtime_context.get("conversation_summary"))
            if isinstance(runtime_context, dict)
            and isinstance(runtime_context.get("conversation_summary"), dict)
            else copy.deepcopy(previous.conversation_summary)
            if previous is not None
            else {}
        )
        if thread_id:
            with self._lock:
                self._states[thread_id] = ConversationContextState(
                    recent_messages=retained_messages,
                    conversation_summary=summary,
                )
        return prepared

    def snapshot(self, thread_id: str) -> ConversationContextState | None:
        if not thread_id:
            return None
        with self._lock:
            state = self._states.get(thread_id)
            return copy.deepcopy(state) if state is not None else None

    def discard(self, thread_id: str) -> None:
        if not thread_id:
            return
        with self._lock:
            self._states.pop(thread_id, None)
