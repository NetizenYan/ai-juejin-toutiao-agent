# Context Manager + Memory v1

## 1. 目标

3.1 阶段实现新闻 Agent 的短期记忆、会话摘要和上下文压缩，让多轮新闻问答不断片，并让用户在会话内提出的约束可以延续，例如“简单点”“不超过 120 字”“保留引用”。

本阶段不做股票预测、不做投资建议、不新增 RAG collection、不重建索引、不扩大 Validator enforce 范围。

## 2. 为什么需要上下文压缩

新闻问答天然会出现指代追问：

```text
用户：最近新质生产力有什么新闻？
用户：那它对制造业有什么影响？
```

如果每轮只看当前问题，模型很容易不知道“它”指什么；如果无限带入历史，又会造成上下文膨胀、延迟上升和旧回答被误当事实证据。因此 v1 采用：

```text
最近 4-6 轮原文 + 结构化 session summary
```

压缩触发条件：

```text
messages_count > 12
或 total_chars > 6000
```

代码中保留 `context_budget_chars` 扩展点，后续可以接入模型 token budget。

## 3. 短期记忆

短期记忆保留：

```text
recent_messages
active_constraints
last_route
last_evidence_ids
user_preferences
```

其中 `last_evidence_ids` 只用于理解“刚才那个”“它”等指代，不能作为本轮新闻事实来源。

当前显式要求优先于历史偏好。例如历史偏好是“简单点”，本轮用户说“这次详细分析”，则本轮按详细回答。

## 4. 会话摘要

会话摘要是结构化 JSON：

```json
{
  "user_goal": "",
  "confirmed_topics": [],
  "active_constraints": [],
  "open_questions": [],
  "last_valid_state": {},
  "last_route": "",
  "last_evidence_ids": [],
  "relevant_preferences": []
}
```

摘要只总结用户意图、话题、约束和未完成问题，不复制旧 evidence 正文，不记录敏感个人信息，也不作为事实证据。

v1 不新增数据库表。摘要写入助手消息的 `ai_message.evidence.context` 扩展字段：

```json
{
  "context": {
    "type": "session_summary",
    "use_as_evidence": false,
    "summary": {},
    "active_constraints": {},
    "last_evidence_ids": []
  }
}
```

## 5. Prompt 分区

Context Manager 注入模型时使用明确分区：

```xml
<session_context use_as_evidence="false">
会话摘要和短期记忆，只用于理解上下文、指代和用户约束，不可作为新闻事实来源。
</session_context>

<recent_messages>
最近 4-6 轮原文。
</recent_messages>

<evidence_pack>
本轮 RAG / MCP 工具返回的证据。
</evidence_pack>
```

System prompt 和 Answer Contract 均要求：新闻事实必须来自本轮 `evidence_pack`。如果证据不支持用户问题，必须拒答或说明站内未找到可靠证据。

## 6. 长期记忆 v1

长期记忆 v1 只定义轻量偏好，不做复杂用户画像，默认关闭：

```env
LONG_TERM_MEMORY_ENABLED=false
```

允许记录：

```text
用户偏好简洁回答
用户偏好带 citation
用户关注经济/政策新闻
用户明确不需要股票预测
```

禁止记录：

```text
敏感个人信息
未经用户确认的事实
新闻事实
投资偏好或具体资产持仓
临时闲聊
```

当前实现只在会话上下文内提取偏好，不做独立长期持久化。

## 7. 与 Answer Contract / Validator 的关系

当前流程：

```text
User Query
→ Context Manager 解析短期上下文和会话约束
→ Query Understanding
→ Answer Contract
→ RAG / MCP
→ Evidence Pack
→ Controlled Generation
→ Validator
→ SSE
```

Context Manager 在 Answer Contract 前生效，因此“后面都不超过 120 字，并保留引用”会影响后续新闻问答合同。

Validator 仍只校验最终 answer 和本轮 evidence pack，不校验 reasoning 内容，也不把 memory 当 evidence。

## 8. 为什么暂不做股票预测

当前产品方向是“可信新闻 Agent”。政策和经济新闻可以用于解释可能影响哪些行业或板块，但不能直接推导股票涨跌，不能给买卖建议，也不能给确定性投资结论。

涉及 A 股或板块影响时，回答必须保守：

```text
可能影响
倾向于
仍需结合行情、资金面和公司基本面判断
```

并且必须基于本轮 evidence。

## 9. 回退方式

如需回退 Context Manager / Memory v1：

```env
CONTEXT_MANAGER_ENABLED=false
SESSION_SUMMARY_ENABLED=false
LONG_TERM_MEMORY_ENABLED=false
```

关闭后，AI chat 回到原先的最近历史消息直接注入模式，不影响 RAG collection、前端 API 或 Validator enforce 配置。
