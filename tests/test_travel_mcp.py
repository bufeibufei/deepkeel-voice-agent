from types import SimpleNamespace

from backend.app.agent.travel_pack import SEARCH_SPEC, _normalize_search_result
from travel_mcp.providers import estimate_route, get_weather, search_places


def test_offline_weather_is_honestly_labelled() -> None:
    result = get_weather("杭州")
    assert result["source_mode"] == "fallback"
    assert "不得" in result["notice"]


def test_offline_places_and_route_are_structured() -> None:
    places = search_places("上海", "建筑", 3)
    route = estimate_route("杭州", "上海")
    assert places["places"]
    assert len(places["places"]) <= 3
    assert route["distance_km"] > 0
    assert route["source_mode"] == "fallback"


def test_official_doubao_search_spec_matches_remote_mcp_schema() -> None:
    schema = SEARCH_SPEC.parameters_schema
    assert schema["required"] == ["Query", "Count"]
    assert schema["properties"]["SearchType"]["enum"] == ["web", "image"]
    assert schema["properties"]["Count"]["maximum"] == 5


def test_search_result_normalizer_removes_large_page_content() -> None:
    raw = SimpleNamespace(
        structured_content={
            "result": {
                "Result": {
                    "WebResults": [
                        {
                            "Title": "西湖公告",
                            "SiteName": "西湖管委会",
                            "Url": "https://example.test/notice",
                            "Snippet": "简短摘要",
                            "Summary": "不应保留" * 2000,
                            "Content": "网页全文" * 5000,
                            "PublishTime": "2026-08-22",
                        }
                    ]
                }
            }
        },
        is_error=False,
    )
    normalized = _normalize_search_result(raw, {"Query": "西湖公告", "Count": 3})
    assert normalized.data["ResultCount"] == 1
    assert normalized.data["Results"][0]["Snippet"] == "简短摘要"
    assert "Content" not in normalized.data["Results"][0]
