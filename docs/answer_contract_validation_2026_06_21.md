# Answer Contract & Validation 设计（2026-06-21）

## 灰度策略

默认策略：

```text
Answer Contract 全局开启
Validator 全局 shadow
econ_finance_query 强制 enforce
其他 route 只记录不拦截
thinking event 默认关闭
done 只返回 validation summary
详细诊断只写后端日志或 message metadata
```

Validation 优先级固定：

```text
ANSWER_VALIDATION_ENABLED=false -> off
route 命中 ANSWER_VALIDATION_ENFORCE_ROUTES -> enforce
其他 route -> ANSWER_VALIDATION_MODE
```

`ANSWER_VALIDATION_ENFORCE_ROUTES` 支持逗号分隔列表，解析时 trim 空格、忽略空字符串，并使用 route 精确匹配。

## Query Understanding

`harness/query_understanding.py` 只做规则型解析：

- “简单说说 / 通俗点 / 总结一下” -> `plain_language + brief`
- “详细分析 / 展开说” -> `detail`
- “不超过120字 / 100字以内” -> `max_chars`
- “列三点 / 两点说明” -> `max_points`
- “保留引用 / 带新闻证据” -> `must_include_citations`
- “最近 / 今天 / 昨天 / 本周 / 今年 / 上个月” -> `time_scope`

它不决定权限、不决定工具调用、不替代 Harness Intent Router。

## Answer Contract

新闻问答默认：

- 简单易懂。
- 最多 2-3 点。
- 新闻事实必须基于 evidence。
- 必须保留 `[news:...]`。
- 经济/政策类最多允许一句通俗背景解释，但不能新增 evidence 外新闻事实。

`general_chat` 不强制 evidence 或新闻引用。

## Validator v1

Validator v1 不宣称证明“完全无幻觉”。它只做：

- citation accuracy
- hard constraints
- obvious unsupported warning
- `hallucination_risk` 标记

`passed=true` 只表示通过当前 Answer Contract v1 校验，不表示答案 100% 无幻觉。

硬失败：

- 有 evidence 且要求引用，但答案缺 `[news:...]`。
- 引用了本轮 evidence 中不存在的 `[news:...]`。
- 用户要求 `max_chars` 且最终展示文本超过 5% 容差。
- 连续复制 evidence 原文超过阈值。
- 出现“根据我的知识 / 据我了解 / 网上资料”等非 evidence 表述。
- 用户问了引号内具体对象，但 evidence 不支持，且答案没有拒答。

无答案拒答是合法通过状态：

- evidence 为空 -> 正确拒答。
- evidence 低相关或不支持问题 -> 正确拒答。

此时：

```text
validation.passed=true
hallucination_risk=low
不强制 [news:...] 引用
```

## SSE 兼容

`ANSWER_THINKING_EVENT_ENABLED=false` 默认关闭。即使未来开启，也只发送：

```json
{"event":"thinking","message":"正在整理证据并生成答案..."}
```

done 事件只返回简要 summary：

```json
{
  "validation": {
    "passed": true,
    "rewriteCount": 1,
    "mode": "enforce",
    "hallucinationRisk": "low"
  }
}
```

详细诊断不进入普通回答，也不完整暴露给前端。
