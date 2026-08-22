# 执行流程

## 天气问答

1. 用户说“杭州今天天气怎么样”；AudioWorklet 连续上传 PCM。
2. 豆包 SeedASR 返回转写增量并在用户结束说话后产生最终文本。
3. `VoiceSession` 创建 DeepKeel `RuntimeRequest`，激活 `voice-travel-assistant`。
4. Agent 通过 function call 选择 `weather.get_weather`。
5. DeepKeel 经 MCP stdio 调用 `weather`，将结构化结果作为 tool message 返回模型。
6. Agent 综合温度、降水和风力，产生最终答案。
7. 文本增量立即推送页面；完整句子持续送入 TTS；PCM 音频边生成边播放。

## 两日行程规划

1. Agent 判断任务包含多个相互依赖的目标，调用 `runtime.create_plan`。
2. DeepKeel 校验计划边界和步骤参数；无效计划可在预算内修订。
3. 天气与地点步骤并行调用 MCP，路线步骤按依赖执行。
4. 每个 `plan.*` 与 `tool.call.*` 事件都映射到右侧执行轨迹。
5. `plan.synthesis.started` 后，同一个 Agent 基于全部工具证据总结两日安排，并追问预算/节奏/兴趣偏好。

## 多轮省略表达

1. 第一轮“我想去杭州旅行”及 Agent 回答被写入当前 `VoiceSession` 的最近消息。
2. 第二轮“二日游”创建新的 DeepKeel run，但把最近消息放进 `context_bundle.recent_messages`。
3. DeepKeel 上下文窗口去重当前问题并恢复历史，模型继承“杭州”作为目的地，不再重复询问。

## 用户打断

1. 用户在回答播放期间再次按麦克风或开始说话。
2. 浏览器立即停止所有 AudioBufferSource；服务端收到 `audio.start` 或 ASR `speech_started`。
3. 服务端向 DeepKeel run control 请求取消，取消当前协程，并向 TTS 发送 `response.cancel`。
4. 前端收到 `response.cancelled`，清理忙碌状态；新一轮 ASR 继续复用会话。

## 事件时序

```text
session.ready
  └─ binary PCM input × N
      ├─ transcript.delta × N
      └─ transcript.final
          └─ turn.started
              ├─ agent.plan × N        (复杂任务)
              ├─ agent.tool × N
              ├─ assistant.text.delta × N
              ├─ assistant.audio.started
              ├─ binary PCM output × N
              └─ turn.completed
```
