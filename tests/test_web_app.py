from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_and_frontend_are_served() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        page = client.get("/")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["mode"] == "demo"
    assert "DeepKeel Voice Agent" in page.text


def test_voice_websocket_streams_plan_tools_and_text() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/voice") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "session.ready"
        assert ready["mcp_tools"] == [
            "weather.get_weather",
            "travel.search_places",
            "travel.estimate_route",
            "search.web_search",
        ]
        ws.send_json(
            {
                "type": "text.submit",
                "text": "我想从杭州去上海两天，喜欢建筑和美食，帮我规划行程",
            }
        )
        events = []
        for _ in range(120):
            event = ws.receive_json()
            events.append(event)
            if event["type"] == "turn.completed":
                break
    types = [event["type"] for event in events]
    assert "turn.started" in types
    assert "agent.plan" in types
    assert "agent.tool" in types
    assert "assistant.text.delta" in types
    assert types[-1] == "turn.completed"
    assert len([event for event in events if event["type"] == "assistant.text.delta"]) > 1


def test_voice_session_remembers_destination_between_turns() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json()["type"] == "session.ready"
        ws.send_json({"type": "text.submit", "text": "我想去上海旅行"})
        for _ in range(120):
            if ws.receive_json()["type"] == "turn.completed":
                break

        ws.send_json({"type": "text.submit", "text": "两日游"})
        second_turn = []
        for _ in range(120):
            event = ws.receive_json()
            second_turn.append(event)
            if event["type"] == "turn.completed":
                break

    answer = "".join(
        event.get("text", "") for event in second_turn if event["type"] == "assistant.text.delta"
    )
    assert "前面提到的上海" in answer
    assert "想去哪里" not in answer
