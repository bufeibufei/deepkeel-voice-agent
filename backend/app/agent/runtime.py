from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from deepkeel.adapter_sdk import InMemoryRuntimeEventJournal, RuntimePorts
from deepkeel.runtime_sdk import (
    AgentDefaults,
    AgentHarness,
    InMemoryRunControl,
    InMemoryRuntimeStateStore,
    RunOperations,
    RuntimeRequest,
)

from backend.app.agent.context_memory import (
    ConversationContextState,
    RetainedConversationContextWindowManager,
)
from backend.app.agent.provider import ArkChatProvider, DemoTravelProvider
from backend.app.agent.travel_pack import TravelCapabilityPack
from backend.app.settings import Settings

SYSTEM_PROMPT = """你是一个中文语音旅行助理。你的核心决策必须通过 DeepKeel 的工具循环完成。
天气、地点和路线属于时效性事实，必须调用可用工具，禁止编造。
新闻、临时公告、营业时间等开放网络信息优先调用 search.web_search。
简单天气问题只调用必要工具；真正的多步骤旅行任务使用 runtime.create_plan 创建有界计划。
你会收到 recent_messages。遇到“二日游”“换成室内”“那就周末”等省略表达时，继承最近已明确的目的地、出发地和偏好，不要重复询问已经给出的信息。
所有工具完成后再综合最终回答。不要向用户输出内部推理、计划 JSON 或工具参数。
回答适合朗读：先给结论，短句，少用列表和 Markdown。工具返回 fallback 或 unavailable 时必须明确说明没有获得实时数据。
旅行建议结尾询问用户是否需要按预算、节奏或兴趣继续细化。"""


@dataclass(slots=True)
class AgentRuntime:
    harness: AgentHarness
    operations: RunOperations
    context_window_manager: RetainedConversationContextWindowManager
    live: bool

    def conversation_context(self, conversation_id: str) -> ConversationContextState | None:
        return self.context_window_manager.snapshot(conversation_id)

    def discard_conversation_context(self, conversation_id: str) -> None:
        self.context_window_manager.discard(conversation_id)

    def request(
        self,
        question: str,
        *,
        conversation_id: str,
        turn_id: str,
        run_id: str = "",
        recent_messages: list[dict] | None = None,
    ) -> RuntimeRequest:
        return RuntimeRequest(
            question=question,
            user_id="browser-user",
            run_id=run_id or f"run-{uuid4().hex}",
            thread_id=conversation_id,
            turn_id=turn_id,
            context_bundle={
                "conversation_id": conversation_id,
                "channel": "voice",
                "recent_messages": list(recent_messages or []),
            },
            skill_activation={
                "skill_id": "voice-travel-assistant",
                "planning_policy": {
                    "mode": "preferred",
                    "max_steps": 6,
                    "max_revisions": 1,
                    "max_parallel_steps": 3,
                    "max_attempts_per_step": 2,
                },
            },
        )


def build_agent_runtime(settings: Settings) -> AgentRuntime:
    state_store = InMemoryRuntimeStateStore()
    event_journal = InMemoryRuntimeEventJournal()
    run_control = InMemoryRunControl()
    context_window_manager = RetainedConversationContextWindowManager()
    ports = RuntimePorts(
        runtime_state_store=state_store,
        event_journal=event_journal,
        run_control=run_control,
        context_window_manager=context_window_manager,
        planning_enabled=True,
        system_prompt_factory=lambda _skill: SYSTEM_PROMPT,
    )
    provider = (
        ArkChatProvider(
            api_key=settings.ark_api_key,
            model=settings.ark_model,
            base_url=settings.ark_base_url,
        )
        if settings.agent_live_enabled
        else DemoTravelProvider()
    )
    defaults = AgentDefaults(
        user_id="browser-user",
        skill_activation={"skill_id": "voice-travel-assistant"},
    )
    harness = AgentHarness.create(
        provider=provider,
        capability_packs=[TravelCapabilityPack(ark_api_key=settings.ark_api_key)],
        ports=ports,
        profile="development",
        defaults=defaults,
        max_steps=12,
        max_parallel_tools=3,
    )
    return AgentRuntime(
        harness=harness,
        operations=RunOperations(state_store, run_control=run_control),
        context_window_manager=context_window_manager,
        live=settings.agent_live_enabled,
    )
