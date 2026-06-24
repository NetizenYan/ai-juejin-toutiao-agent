# RAG Retrieval Decision 2026-06-21

## 决策

默认检索策略设为：

```text
RAG_QUERY_ROUTER_ENABLED=true
RAG_RANKING=hybrid
RAG_CHUNK_TYPE_FILTER=summary
RAG_EXPAND_BODY_EVIDENCE=true
RAG_BODY_CHUNKS_PER_PARENT=1
RAG_BODY_FALLBACK_SLOTS=0
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

## 原因

Codex 侧评测显示，全局 body fallback 对 hard/content case 有帮助，但会拉低标题/实体型问题的 MRR。统一项目因此采用 Query Router：默认 summary-first，只有内容细节、时间线/最近进展、来源约束查询启用 1 个 body fallback 槽位。

## 必须对比的策略

| Strategy | Hit@5 | MRR | Recall@5 | EvidenceRecall@5 | BodyEvidence@5 | Latency | Notes |
| -------- | ----: | --: | -------: | ---------------: | -------------: | ------: | ----- |
| summary-only | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | summary filter, no body fallback |
| global body_fallback_slots=1 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | global body fallback ablation |
| query_router_v1 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | 待复跑 | router controls when body fallback is allowed |

复跑命令：

```bash
python -X utf8 -m evals.retrieval_eval
python -X utf8 -m evals.retrieval_eval --only-hard-cases
```

## 回退

```text
RAG_QUERY_ROUTER_ENABLED=false
RAG_BODY_FALLBACK_SLOTS=0
RAG_RANKING=hybrid
```
