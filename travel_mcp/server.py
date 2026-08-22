from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from travel_mcp.providers import estimate_route, get_weather, search_places

mcp = MCPServer(
    "DeepKeel Travel Tools",
    description="Read-only weather, place and route evidence for a travel agent.",
)


@mcp.tool(description="查询指定中国城市当前或未来七天内某天的天气。")
def weather(city: str, date: str = "") -> dict:
    return get_weather(city, date)


@mcp.tool(description="按兴趣关键词搜索一个城市的地点和景点。")
def places(city: str, keyword: str = "景点", limit: int = 5) -> dict:
    return search_places(city, keyword, limit)


@mcp.tool(description="估算两个城市之间的公路距离和耗时，不执行预订。")
def route(origin: str, destination: str, mode: str = "driving") -> dict:
    return estimate_route(origin, destination, mode)


if __name__ == "__main__":
    mcp.run(transport="stdio")
