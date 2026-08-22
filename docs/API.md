# WebSocket 与 MCP 协议

## WebSocket `/ws/voice`

浏览器连接后，文本帧使用 JSON，音频帧使用二进制。

### 客户端到服务端

| 类型 | 字段 | 含义 |
| --- | --- | --- |
| 二进制 | PCM16 little-endian | 单声道 16 kHz 输入音频 |
| `audio.start` | 无 | 开始录音并打断当前回答 |
| `audio.commit` | 无 | 客户端结束本段录音 |
| `text.submit` | `text` | 不经 ASR，直接创建 Agent turn |
| `response.cancel` | 无 | 主动取消当前回答 |
| `ping` | 无 | 连接探活 |

### 服务端到客户端

所有 JSON 事件都有 `type`、递增 `sequence` 和 `timestamp_ms`。

| 类型 | 关键字段 | 含义 |
| --- | --- | --- |
| `session.ready` | `agent_live`, `speech_live`, `asr_connected`, sample rates | 会话能力协商完成 |
| `transcript.delta/final` | `text` | ASR 临时/最终转写 |
| `turn.started` | `turn_id`, `run_id`, `text` | DeepKeel 运行开始 |
| `agent.plan` | `event`, `summary` | DeepKeel 规划生命周期 |
| `agent.tool` | `event`, `tool_name`, `status` | function call 生命周期 |
| `assistant.text.delta` | `text` | 增量回答文本 |
| `assistant.audio.started` | `sample_rate` | 后续二进制帧为回答音频 |
| 二进制 | PCM16 little-endian | 单声道 24 kHz 输出音频 |
| `turn.completed/failed/cancelled` | `run_id` | 回合终态 |
| `response.cancelled` | `reason` | 打断已传播到运行时 |

## MCP Server

启动命令：

```powershell
uv run python -u -m travel_mcp.server
```

传输为 stdio，工具如下：

- `weather(city, date="")`：中国城市当前或未来七天天气；
- `places(city, keyword="景点", limit=5)`：按关键词搜索地点；
- `route(origin, destination, mode="driving")`：估算公路距离与耗时。
- `web_search(Query, Count, SearchType="web", ...)`：火山官方豆包搜索 MCP；语音 Agent 将结果限制在 5 条以内，支持时间范围、权威来源、站点过滤和 URL，避免网页全文挤占对话上下文。

DeepKeel 本地绑定名分别是 `weather.get_weather`、`travel.search_places`、`travel.estimate_route` 和 `search.web_search`。参数在 ToolSpec 层再次以 JSON Schema 校验，所有工具均声明为 `read_only` 和 `parallel_safe`。
