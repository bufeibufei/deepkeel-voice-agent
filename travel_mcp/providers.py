from __future__ import annotations

import os
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

CITY_FALLBACKS: dict[str, tuple[float, float]] = {
    "杭州": (30.2741, 120.1551),
    "上海": (31.2304, 121.4737),
    "北京": (39.9042, 116.4074),
    "深圳": (22.5431, 114.0579),
}

PLACE_FALLBACKS: dict[str, list[dict[str, Any]]] = {
    "上海": [
        {"name": "外滩", "category": "建筑与城市景观", "address": "黄浦区中山东一路"},
        {"name": "武康大楼", "category": "历史建筑", "address": "徐汇区淮海中路1850号"},
        {"name": "上海博物馆东馆", "category": "博物馆", "address": "浦东新区世纪大道1952号"},
        {"name": "豫园", "category": "园林与美食", "address": "黄浦区福佑路168号"},
    ],
    "杭州": [
        {"name": "西湖", "category": "自然与人文", "address": "西湖区龙井路1号"},
        {"name": "中国丝绸博物馆", "category": "博物馆", "address": "西湖区玉皇山路73-1号"},
        {"name": "小河直街", "category": "历史街区", "address": "拱墅区小河直街"},
    ],
}


def _client() -> httpx.Client:
    return httpx.Client(timeout=8, headers={"User-Agent": "DeepKeelVoiceAgent/0.1"})


def resolve_city(city: str) -> dict[str, Any]:
    city = city.strip()
    if os.getenv("TRAVEL_MCP_OFFLINE", "").lower() in {"1", "true", "yes"}:
        lat, lon = CITY_FALLBACKS.get(city, CITY_FALLBACKS["杭州"])
        return {
            "name": city,
            "latitude": lat,
            "longitude": lon,
            "country": "中国",
            "source_mode": "fallback",
        }
    try:
        with _client() as client:
            response = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
            )
            response.raise_for_status()
            item = (response.json().get("results") or [])[0]
            return {
                "name": item.get("name", city),
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "country": item.get("country", ""),
                "source_mode": "live",
            }
    except (httpx.HTTPError, IndexError, KeyError, TypeError, ValueError):
        lat, lon = CITY_FALLBACKS.get(city, CITY_FALLBACKS["杭州"])
        return {
            "name": city,
            "latitude": lat,
            "longitude": lon,
            "country": "中国",
            "source_mode": "fallback",
        }


def get_weather(city: str, date: str = "") -> dict[str, Any]:
    location = resolve_city(city)
    if os.getenv("TRAVEL_MCP_OFFLINE", "").lower() in {"1", "true", "yes"}:
        return {
            "city": city,
            "date": date or datetime.now(UTC).date().isoformat(),
            "source": "内置演示数据",
            "source_mode": "fallback",
            "notice": "离线测试模式；不得描述为实时天气。",
        }
    params: dict[str, Any] = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Shanghai",
        "forecast_days": 7,
    }
    try:
        with _client() as client:
            response = client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            payload = response.json()
        daily = payload.get("daily", {})
        dates = daily.get("time", [])
        index = dates.index(date) if date and date in dates else 0
        current = payload.get("current", {})
        result = {
            "city": location["name"],
            "date": dates[index] if dates else date,
            "current_temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "temperature_min_c": (daily.get("temperature_2m_min") or [None])[index],
            "temperature_max_c": (daily.get("temperature_2m_max") or [None])[index],
            "precipitation_probability_percent": (
                daily.get("precipitation_probability_max") or [None]
            )[index],
            "weather_code": (daily.get("weather_code") or [None])[index],
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "source": "Open-Meteo",
            "source_mode": "live",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return result
    except (httpx.HTTPError, IndexError, ValueError, TypeError):
        return {
            "city": city,
            "date": date or datetime.now(UTC).date().isoformat(),
            "source": "内置演示数据",
            "source_mode": "fallback",
            "notice": "实时天气服务暂不可用；不得把此结果描述为实时观测。",
        }


def search_places(city: str, keyword: str = "景点", limit: int = 5) -> dict[str, Any]:
    location = resolve_city(city)
    if os.getenv("TRAVEL_MCP_OFFLINE", "").lower() in {"1", "true", "yes"}:
        return {
            "city": city,
            "keyword": keyword,
            "places": PLACE_FALLBACKS.get(city, [])[:limit],
            "source": "内置演示数据",
            "source_mode": "fallback",
            "notice": "离线测试模式。",
        }
    try:
        with _client() as client:
            response = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": f"{keyword}, {city}",
                    "format": "jsonv2",
                    "limit": min(limit, 8),
                    "accept-language": "zh-CN",
                },
            )
            response.raise_for_status()
            items = response.json()
        places = [
            {
                "name": str(item.get("name") or item.get("display_name", "")).split(",")[0],
                "address": item.get("display_name", ""),
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
                "category": item.get("type", "place"),
            }
            for item in items[:limit]
        ]
        if places:
            return {
                "city": location["name"],
                "keyword": keyword,
                "places": places,
                "source": "OpenStreetMap Nominatim",
                "source_mode": "live",
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        pass
    places = PLACE_FALLBACKS.get(city, [])[:limit]
    return {
        "city": city,
        "keyword": keyword,
        "places": places,
        "source": "内置演示数据",
        "source_mode": "fallback",
        "notice": "地点数据可能不完整，请在出发前核验开放时间。",
    }


def estimate_route(origin: str, destination: str, mode: str = "driving") -> dict[str, Any]:
    start, end = resolve_city(origin), resolve_city(destination)
    if os.getenv("TRAVEL_MCP_OFFLINE", "").lower() in {"1", "true", "yes"}:
        distance = _haversine(
            start["latitude"], start["longitude"], end["latitude"], end["longitude"]
        )
        return {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "distance_km": round(distance, 1),
            "duration_minutes": None,
            "source": "直线距离估算",
            "source_mode": "fallback",
            "notice": "离线测试模式。",
        }
    profile = "driving" if mode not in {"walking", "cycling"} else mode
    try:
        with _client() as client:
            response = client.get(
                f"https://router.project-osrm.org/route/v1/{profile}/{start['longitude']},{start['latitude']};{end['longitude']},{end['latitude']}",
                params={"overview": "false"},
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
        return {
            "origin": origin,
            "destination": destination,
            "mode": profile,
            "distance_km": round(route["distance"] / 1000, 1),
            "duration_minutes": round(route["duration"] / 60),
            "source": "OSRM",
            "source_mode": "live",
        }
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        distance = _haversine(
            start["latitude"], start["longitude"], end["latitude"], end["longitude"]
        )
        return {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "distance_km": round(distance, 1),
            "duration_minutes": None,
            "source": "直线距离估算",
            "source_mode": "fallback",
            "notice": "未获得实时路线耗时。",
        }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return radius * 2 * asin(sqrt(value))
