from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

import httpx


def _question(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return ""


def _conversation_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(message.get("content") or "") for message in messages if message.get("role") == "user"
    )


def _tool_names(tools: list[dict[str, Any]] | None) -> set[str]:
    return {str(item.get("function", {}).get("name") or "") for item in tools or []}


class ArkChatProvider:
    """Volcengine Ark Chat Completions adapter for DeepKeel's provider contract."""

    model_role = "reasoning"

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete_chat(self, messages, *, tools=None, tool_choice=None, max_tokens=None, **kwargs):
        body = self._body(messages, tools, tool_choice, max_tokens, stream=False, **kwargs)
        with httpx.Client(timeout=kwargs.get("request_timeout", 120)) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        choice = payload["choices"][0]
        return {
            "message": choice["message"],
            "finish_reason": choice.get("finish_reason", "stop"),
            "model": payload.get("model", self.model),
            "usage": payload.get("usage", {}),
        }

    def stream_chat(self, messages, *, tools=None, tool_choice=None, max_tokens=None, **kwargs):
        body = self._body(messages, tools, tool_choice, max_tokens, stream=True, **kwargs)
        with (
            httpx.Client(timeout=kwargs.get("request_timeout", 120)) as client,
            client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            ) as response,
        ):
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                yield json.loads(data)

    def _body(self, messages, tools, tool_choice, max_tokens, *, stream: bool, **kwargs):
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": 0.2,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
            body["parallel_tool_calls"] = True
        if max_tokens:
            body["max_tokens"] = max_tokens
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body


class DemoTravelProvider:
    """Deterministic offline provider that still exercises DeepKeel tools and plans."""

    model = "deepkeel-demo-travel"
    model_role = "reasoning"

    def complete_chat(self, messages, *, tools=None, tool_choice=None, **_kwargs):
        names = _tool_names(tools)
        question = _question(messages)
        conversation = _conversation_text(messages)
        has_tool_observation = any(item.get("role") == "tool" for item in messages)
        if has_tool_observation:
            content = self._synthesis(question, messages, self._conversation_city(messages))
            return self._answer(content)
        if "runtime.create_plan" in names and self._needs_plan(conversation):
            return self._plan(conversation, names)
        tool = "weather.get_weather" if "weather.get_weather" in names else ""
        if tool and any(word in question for word in ("天气", "温度", "下雨")):
            city = self._city(question)
            return self._call(tool, {"city": city, "date": ""}, "demo-weather")
        return self._answer(
            "你好，我是 DeepKeel 语音旅行助理。你可以问我天气，或让我规划一趟城市旅行。"
        )

    def stream_chat(
        self, messages, *, tools=None, tool_choice=None, **kwargs
    ) -> Iterable[dict[str, Any]]:
        result = self.complete_chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)
        message = result["message"]
        calls = message.get("tool_calls") or []
        if calls:
            yield {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [{"index": i, **call} for i, call in enumerate(calls)]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
            return
        text = str(message.get("content") or "")
        for part in re.findall(r"[^，。！？；]+[，。！？；]?", text):
            if part:
                yield {"choices": [{"delta": {"content": part}, "finish_reason": None}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    @staticmethod
    def _needs_plan(question: str) -> bool:
        return any(
            word in question
            for word in ("规划", "行程", "旅行", "旅游", "怎么玩", "两天", "两日", "二日", "三天")
        )

    @staticmethod
    def _city(question: str) -> str:
        return DemoTravelProvider._explicit_city(question) or "杭州"

    @staticmethod
    def _explicit_city(question: str) -> str:
        for city in ("上海", "杭州", "北京", "深圳"):
            if city in question:
                return city
        return ""

    @classmethod
    def _conversation_city(cls, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            city = cls._explicit_city(str(message.get("content") or ""))
            if city:
                return city
        return "杭州"

    def _plan(self, question: str, names: set[str]):
        destination = self._city(question)
        origin = "杭州" if destination != "杭州" else "上海"
        steps = []
        if "weather.get_weather" in names:
            steps.append(
                {
                    "id": "weather",
                    "title": "查询目的地天气",
                    "objective": "获取行程期间天气证据。",
                    "capability_ref": "weather.get_weather",
                    "arguments": {"city": destination, "date": ""},
                }
            )
        if "travel.search_places" in names:
            steps.append(
                {
                    "id": "places",
                    "title": "筛选地点",
                    "objective": "按用户兴趣寻找可访问地点。",
                    "capability_ref": "travel.search_places",
                    "arguments": {"city": destination, "keyword": "建筑 美食", "limit": 5},
                }
            )
        if "travel.estimate_route" in names:
            steps.append(
                {
                    "id": "route",
                    "title": "估算城际路线",
                    "objective": "估算出发地到目的地距离与耗时。",
                    "capability_ref": "travel.estimate_route",
                    "arguments": {"origin": origin, "destination": destination, "mode": "driving"},
                }
            )
        arguments = {"objective": f"为用户规划一趟前往{destination}的有依据行程。", "steps": steps}
        return self._call("runtime.create_plan", arguments, "demo-plan")

    @staticmethod
    def _synthesis(question: str, messages: list[dict[str, Any]], destination: str) -> str:
        observations = [
            str(item.get("content") or "") for item in messages if item.get("role") == "tool"
        ]
        joined = " ".join(observations)
        if any(
            word in question
            for word in ("规划", "行程", "旅行", "旅游", "两天", "两日", "二日", "三天")
        ):
            notice = (
                "部分外部服务使用了降级数据，请出发前核验开放时间。"
                if "fallback" in joined or "unavailable" in joined
                else "天气、地点和路线信息已经通过工具核验。"
            )
            return f"好的，我按你前面提到的{destination}来安排。我建议把这趟行程安排成慢节奏的两天。第一天先走城市建筑线，上午看历史街区，下午进入博物馆或代表性建筑，晚上集中体验本地餐饮。第二天安排一处核心景点和一段适合步行的街区，午后留出返程缓冲。{notice}你希望我再按预算、住宿位置或具体出发时间细化吗？"
        if "fallback" in joined:
            return "天气服务当前没有返回完整的实时观测。我已经保留了查询结果，但建议出发前再核验一次，避免把演示数据当成实时天气。"
        return "我已经查询了天气。整体条件适合出行，但请同时留意降水概率、体感温度和风力，并在出发前查看最新预报。"

    def _answer(self, content: str):
        return {
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
            "model": self.model,
        }

    def _call(self, name: str, arguments: dict[str, Any], call_id: str):
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
            "model": self.model,
        }
