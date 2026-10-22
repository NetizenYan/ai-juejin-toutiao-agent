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

## 2026-10-22 更新：默认改为同时检索摘要块和正文块

`RAG_CHUNK_TYPE_FILTER` 默认值从 `summary` 改为空（摘要块 + 正文块一起参与向量检索）。

背景变化：embedding 从 qwen3-embedding:4b 换成 BAAI/bge-m3，精排 BAAI/bge-reranker-v2-m3 修复后真正生效，Qdrant 补建了 `chunk_type` payload 索引（此前过滤检索会漏召回）。6 月"正文检索拉低标题类问题 MRR"的结论在新配置下不再成立。

评测（retrieve-only，top-5，bge-m3 + bge-reranker-v2-m3，评测集为迁移后的 expanded115 / splits）：

| 数据集 | 计分题 | Hit@5 summary → 全部块 | MRR | EvidenceRecall@5 |
| --- | ---: | --- | --- | --- |
| expanded115 | 74 | 0.784 → 0.865 | 0.718 → 0.747 | 0.712 → 0.764 |
| train split | 48 | 0.708 → 0.833 | 0.638 → 0.673 | 0.622 → 0.694 |
| heldout split | 26 | 0.923 → 0.923 | 0.865 → 0.885 | 0.878 → 0.891 |

按题型无退步：精确标题问答保持 19/19，相似干扰项 0/8 → 4/8；不应回答题平均返回条数 4.5 → 4.3。代价是检索 P50 延迟 284 → 356 ms。候选池从 50 扩到 100 的对照实验反而变差（Hit@5 0.770），未采用。
