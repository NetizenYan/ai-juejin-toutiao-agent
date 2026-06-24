# ADR-20260621-rag-query-router

## 状态

Accepted

## 背景

统一项目以 Claude 版本为可运行底座，Codex 侧提供更强的 RAG 策略、评测口径和 body fallback 消融结果。新闻数据包含标题/摘要型问题，也包含长正文中的内容细节、时间线和来源约束问题。

## 问题

是否应该把 body fallback 全局打开，还是按 query 类型选择性启用。

## 为什么不能全局打开 body fallback

body chunk 覆盖更多正文，但噪声也更大。标题/实体型查询本来适合 summary-first，全局插入 body 结果会挤占 summary 位置，导致严格标题问题的 MRR 下降，也会增加延迟和错误召回。

## 为什么使用 query router

Query Router 用确定性规则在 Harness/RAG 工具层决策，不交给模型自由决定。它默认 summary-first；只有内容细节、时间线/最近进展、来源约束查询才启用 1 个 body fallback 槽位。这样保留 hard case 的召回提升，同时避免对简单标题查询产生全局副作用。

## 实验指标

| Strategy | Hit@5 | MRR | Recall@5 | EvidenceRecall@5 | BodyEvidence@5 | Latency | Notes |
| -------- | ----: | --: | -------: | ---------------: | -------------: | ------: | ----- |
| summary-only | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | baseline |
| global body_fallback_slots=1 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | ablation |
| query_router_v1 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | selected |

## 风险

规则触发词可能误判，尤其是同时包含来源和时间词的查询。旧 Claude chunk 索引可能没有 `chunk_type` 字段，所以实现里保留了 summary 过滤无结果时的无过滤 fallback，以保证现有链路可运行。

## 回退方案

```text
RAG_QUERY_ROUTER_ENABLED=false
RAG_BODY_FALLBACK_SLOTS=0
RAG_RANKING=hybrid
```

## 后续计划

1. 用统一 collection 复跑 48 题和 hard cases。
2. 重建带 `chunk_type=summary/body` 的多颗粒度索引，减少无过滤 fallback。
3. 对 query router 增加实体、日期、来源解析。
4. 再做 embedding 消融：qwen3-embedding、bge-m3、bge-large-zh。
