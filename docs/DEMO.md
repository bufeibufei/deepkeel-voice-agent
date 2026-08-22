# 演示与答辩建议

## 3 分钟演示脚本

1. 配置 Coding Plan Key 后运行 `.\run.ps1`，展示 `/health` 为 `live`，主页状态为“已连接 / 方舟实时”。
2. 语音提问“杭州今天天气怎么样”，指出字幕是 ASR delta，右侧出现 `weather.get_weather`，回答文本和声音同时流出。
3. 在回答未结束时再次按麦克风，展示 `response.cancelled` 与音频立即停止。
4. 提问“我周末从杭州去上海玩两天，喜欢建筑和美食，帮我规划行程”。
5. 展示 `runtime.create_plan`、天气/地点并行、路线估算、synthesis 和最终追问。
6. 连续输入“我想去杭州旅行”“两日游”，展示第二轮直接继承杭州。
7. 询问一条需要联网核验的临时公告，展示 `search.web_search` 豆包搜索工具。
8. 切换 `.\run.ps1 -Demo`，说明无外部模型也能稳定演示同样的 Agent/MCP 事件链。

## 已验证结果

- 自动化：18 个测试全部通过（默认均为离线确定性测试）；
- Coding Plan：Chat Completions、Responses、SeedASR 2.0、TTS 2.0 均完成真实鉴权；
- 实时语音闭环：TTS 输出 PCM 后由 SeedASR 准确转写“杭州今天天气怎么样？”；
- 方舟 Agent：真实 function call 已调用 `weather.get_weather` 并完成天气回答；
- MCP：`travel-tools` 与官方 `doubao-search` 均完成接入；真实搜索已返回西湖管委会官网公告与 URL，完整工具列表会显示在页面右侧；
- 多轮上下文：“上海旅行 → 两日游”回归测试确认第二轮继承上海；
- 响应式：320、375、414、768 px 均无横向溢出。

截图 `docs/assets/demo.png` 为迁移前的界面示意，不包含 API Key；完成有效方舟与豆包语音凭据联调后应重新录制最终 Demo。
