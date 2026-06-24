# ADR-20260621: Answer Contract + Validator v1 灰度

## Status

Accepted for 3.0 econ gray rollout.

## Context

经济 RAG 灰度显示：检索、路由、候选 collection、SSE、登录态和 tool_call 落库均已通过。主要失败点在最终生成层：模型拿到正确 evidence 后仍可能输出过长答案、缺少引用或复制长 chunk 原文。

## Decision

实现 Answer Contract + Validator v1，并采用保守灰度：

```text
Answer Contract 全局启用
Validator 全局 shadow
econ_finance_query 强制 enforce
其他 route 不拦截
rewrite 最多一次
thinking event 默认关闭
```

Validation mode 优先级：

```text
disabled > enforce_routes exact match > global mode
```

无答案拒答是合法通过状态。Validator v1 只输出 `hallucination_risk`，不宣称 fully faithful。

## Non-decisions

- 不重建或修改 RAG collection。
- 不做 Context Manager。
- 不接入 LLM-as-judge。
- 不新增数据库表。
- 不改前端 API 路径。
- 不扩大到全站强制 Validator。

## Consequences

优点：

- 直接修复经济灰度暴露的生成约束问题。
- 允许其他 route shadow 观察，避免全站高频拒答。
- 可通过配置快速回退。

风险：

- Validator v1 不能证明完全无幻觉，只能捕捉明显硬约束和引用问题。
- shadow route 仍可能返回不合规答案，但会记录 `wouldRewrite`。
- 非流式内部生成会让首 token 稍慢，但前端 SSE 协议保持不变。

## Rollback

```env
ANSWER_CONTRACT_ENABLED=false
ANSWER_VALIDATION_ENABLED=false
ANSWER_REWRITE_ON_FAIL=false
ANSWER_THINKING_EVENT_ENABLED=false
```
