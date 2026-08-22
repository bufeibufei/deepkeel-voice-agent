from __future__ import annotations

import os
import sys

from deepkeel.extension_sdk import CapabilityContribution, CapabilityPackSpec, ToolSpec
from deepkeel.mcp_sdk import (
    McpCallResult,
    McpClientPool,
    McpNormalizedResult,
    McpServerSpec,
    McpToolBinding,
    McpToolProvider,
)


def _object_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _normalize_search_result(result: McpCallResult, arguments: dict) -> McpNormalizedResult:
    structured = result.structured_content if isinstance(result.structured_content, dict) else {}
    payload = structured.get("result") if isinstance(structured.get("result"), dict) else structured
    search_result = payload.get("Result") if isinstance(payload.get("Result"), dict) else payload
    search_type = str(arguments.get("SearchType") or "web")
    source_items = search_result.get("ImageResults" if search_type == "image" else "WebResults")
    items = []
    for item in source_items or []:
        if not isinstance(item, dict):
            continue
        if search_type == "image":
            items.append(
                {
                    key: item.get(key)
                    for key in ("Title", "ImageUrl", "Url", "Width", "Height")
                    if item.get(key) is not None
                }
            )
        else:
            snippet = str(item.get("Snippet") or item.get("Summary") or "")[:500]
            items.append(
                {
                    "Title": item.get("Title"),
                    "SiteName": item.get("SiteName"),
                    "Url": item.get("Url"),
                    "Snippet": snippet,
                    "PublishTime": item.get("PublishTime"),
                }
            )
    data = {
        "Query": arguments.get("Query"),
        "SearchType": search_type,
        "ResultCount": len(items),
        "Results": items,
    }
    return McpNormalizedResult(
        data=data,
        summary=f"豆包搜索返回 {len(items)} 条结构化结果。",
        error="豆包搜索调用失败。" if result.is_error else "",
    )


WEATHER_SPEC = ToolSpec(
    name="weather.get_weather",
    description="查询中国城市当前或未来七天的天气；时效性问题必须使用此工具。",
    parameters_schema=_object_schema(
        {
            "city": {"type": "string", "minLength": 1},
            "date": {"type": "string", "description": "可选 ISO 日期 YYYY-MM-DD"},
        },
        ["city"],
    ),
    read_only=True,
    parallel_safe=True,
    visible_label="查询天气",
)

PLACES_SPEC = ToolSpec(
    name="travel.search_places",
    description="按兴趣关键词搜索城市地点，用于形成有来源的旅行建议。",
    parameters_schema=_object_schema(
        {
            "city": {"type": "string", "minLength": 1},
            "keyword": {"type": "string", "default": "景点"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
        },
        ["city"],
    ),
    read_only=True,
    parallel_safe=True,
    visible_label="搜索地点",
)

ROUTE_SPEC = ToolSpec(
    name="travel.estimate_route",
    description="估算两座城市之间的路线距离与耗时，不执行购买或预订。",
    parameters_schema=_object_schema(
        {
            "origin": {"type": "string", "minLength": 1},
            "destination": {"type": "string", "minLength": 1},
            "mode": {
                "type": "string",
                "enum": ["driving", "walking", "cycling"],
                "default": "driving",
            },
        },
        ["origin", "destination"],
    ),
    read_only=True,
    parallel_safe=True,
    visible_label="估算路线",
)

SEARCH_SPEC = ToolSpec(
    name="search.web_search",
    description="使用火山引擎官方豆包搜索查询新闻、公告、营业时间等开放网络信息。",
    parameters_schema=_object_schema(
        {
            "Query": {"type": "string", "minLength": 1, "maxLength": 100},
            "Count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "语音问答返回条数，建议 3 条，最多 5 条",
            },
            "SearchType": {"type": "string", "enum": ["web", "image"], "default": "web"},
            "TimeRange": {
                "type": "string",
                "description": "OneDay/OneWeek/OneMonth/OneYear 或 YYYY-MM-DD..YYYY-MM-DD",
            },
            "AuthLevel": {"type": "integer", "enum": [0, 1], "default": 0},
            "NeedUrl": {"type": "boolean", "default": True},
            "Sites": {"type": "string", "description": "以 | 分隔的限定站点"},
            "BlockHosts": {"type": "string", "description": "以 | 分隔的排除站点"},
            "Industry": {"type": "string", "enum": ["finance", "game", "gov"]},
            "QueryRewrite": {"type": "boolean", "default": True},
        },
        ["Query", "Count"],
    ),
    read_only=True,
    parallel_safe=True,
    visible_label="豆包搜索",
)

MCP_TOOL_NAMES = (
    WEATHER_SPEC.name,
    PLACES_SPEC.name,
    ROUTE_SPEC.name,
    SEARCH_SPEC.name,
)


class TravelCapabilityPack:
    spec = CapabilityPackSpec(
        package_id="demo.voice-travel",
        package_version="1.0.0",
        declared_tools=MCP_TOOL_NAMES,
        declared_skills=("voice-travel-assistant",),
        declared_tool_providers=("travel-mcp",),
        declared_resources=("tool-provider:travel-mcp",),
    )

    def __init__(self, *, ark_api_key: str = ""):
        self.ark_api_key = ark_api_key

    def install(self, context):
        travel_server = McpServerSpec(
            id="travel-tools",
            transport="stdio",
            command=sys.executable,
            args=["-u", "-m", "travel_mcp.server"],
            environment={
                "TRAVEL_MCP_OFFLINE": os.getenv("TRAVEL_MCP_OFFLINE", ""),
            },
            startup_timeout_seconds=20,
            request_timeout_seconds=12,
        )
        search_server = McpServerSpec(
            id="doubao-search",
            transport="stdio",
            command="uvx",
            args=[
                "--from",
                "mcp-server-askecho-search-infinity>=0.2.0",
                "mcp-server-askecho-search-infinity",
            ],
            environment={
                "ASK_ECHO_SEARCH_INFINITY_API_KEY": self.ark_api_key
                or os.getenv("ARK_API_KEY", ""),
            },
            startup_timeout_seconds=60,
            request_timeout_seconds=35,
        )
        provider = McpToolProvider(
            McpClientPool([travel_server, search_server]), provider_id="travel-mcp"
        )
        provider.bind(
            McpToolBinding(
                server_id=travel_server.id, remote_name="weather", local_spec=WEATHER_SPEC
            )
        )
        provider.bind(
            McpToolBinding(server_id=travel_server.id, remote_name="places", local_spec=PLACES_SPEC)
        )
        provider.bind(
            McpToolBinding(server_id=travel_server.id, remote_name="route", local_spec=ROUTE_SPEC)
        )
        provider.bind(
            McpToolBinding(
                server_id=search_server.id,
                remote_name="web_search",
                local_spec=SEARCH_SPEC,
                normalize_result=_normalize_search_result,
            )
        )
        context.register_tool_provider(provider)
        context.register_skill(
            "voice-travel-assistant",
            {
                "id": "voice-travel-assistant",
                "label": "中文语音旅行助理",
                "description": "查询天气并规划有证据的城市旅行。",
                "allowed_tools": [
                    WEATHER_SPEC.name,
                    PLACES_SPEC.name,
                    ROUTE_SPEC.name,
                    SEARCH_SPEC.name,
                ],
                "planning_policy": {
                    "mode": "preferred",
                    "max_steps": 6,
                    "max_revisions": 1,
                    "max_parallel_steps": 3,
                    "max_attempts_per_step": 2,
                },
            },
        )
        return CapabilityContribution(package_id=self.spec.package_id)
