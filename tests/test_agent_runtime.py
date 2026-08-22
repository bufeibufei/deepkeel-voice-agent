from __future__ import annotations

import pytest

from backend.app.agent.runtime import build_agent_runtime
from backend.app.settings import Settings


@pytest.fixture(scope="module")
def agent():
    runtime = build_agent_runtime(Settings(voice_agent_demo_mode=True))
    yield runtime
    runtime.harness.runtime.close()


def test_weather_question_uses_mcp_tool(agent) -> None:
    result = agent.harness.run(
        agent.request("杭州今天天气怎么样？", conversation_id="test-weather", turn_id="turn-1")
    )
    events = [event.event_type for event in result.events]
    assert result.status == "completed"
    assert "tool.call.started" in events
    assert "tool.call.completed" in events
    assert result.tool_results[0].name == "weather.get_weather"
    assert result.final_answer.markdown


def test_trip_question_enters_plan_execute_and_synthesizes(agent) -> None:
    result = agent.harness.run(
        agent.request(
            "我想从杭州去上海两天，喜欢建筑和美食，帮我规划行程",
            conversation_id="test-plan",
            turn_id="turn-1",
        )
    )
    events = [event.event_type for event in result.events]
    assert result.status == "completed"
    assert result.mode == "plan_execute"
    assert result.execution_plan["status"] == "completed"
    assert events.count("plan.step.completed") == 3
    assert "plan.synthesis.started" in events
    assert "plan.completed" in events
    assert "你希望" in result.final_answer.markdown


def test_request_passes_recent_messages_to_deepkeel_context(agent) -> None:
    history = [
        {"role": "user", "content": "我想去杭州旅行"},
        {"role": "assistant", "content": "好呀，你打算玩几天？"},
    ]
    request = agent.request(
        "两日游",
        conversation_id="test-context",
        turn_id="turn-2",
        recent_messages=history,
    )
    assert request.context_bundle["recent_messages"] == history
