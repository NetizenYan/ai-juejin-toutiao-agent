# ADR-20260621-econ-staging-rag-collection

## 状态

Accepted

## 背景

旧生产 RAG collection 对近期经济/财经问题覆盖不足，且旧 chunk payload 存在 `publish_time` / `publish_ts` 缺失。修复 time-aware 排序后，生产链路会安全返回空证据，避免继续错引 2009/2012 等历史新闻。

经济日报 2010-2026.6 与人民日报 2025/2026 数据经过近期窗口筛选、去重、去噪后，构建了实验 collection：

```text
toutiao_exp_econ_recent_20260621
```

对 10 个经济/财经 query 进行生产逻辑对照评测：

```text
production: nonempty_queries=0/10, returned_items=0
staging:    nonempty_queries=10/10, returned_items=50, recent_ratio=94%, evidence_ratio=100%
```

评测报告：

```text
work/econ_rag_experiment/staging_vs_production_eval.json
```

## 决策

不替换全站生产 collection。

新增受控开关，仅当 query 被识别为经济/财经相关，或运行在 test/testing 环境时，RAG 检索切到经济 staging collection：

```text
RAG_ECON_COLLECTION_ENABLED=true
RAG_ECON_COLLECTION_NAME=toutiao_exp_econ_recent_20260621
```

其他新闻 query 继续使用默认 `RAG_CHUNK_COLLECTION_NAME` / `RAG_CHUNK_COLLECTION`。

## 原因

1. staging collection 是经济专题小规模索引，不适合直接替换全站新闻索引。
2. 经济/财经 query 已有小规模评测收益，且证据完整率为 100%。
3. 开关可回滚，不影响模型权限边界；模型仍只通过 Harness/MCP 工具读取证据。

## 风险

1. 经济/财经关键词规则可能误判边界 query。
2. staging collection 目前只有 summary point，body evidence 还不是正式父子索引。
3. staging 数据以近期经济日报为主，来源多样性仍需后续扩展。

## 回滚方案

关闭开关并重启后端：

```text
RAG_ECON_COLLECTION_ENABLED=false
```

或者清空 staging collection 名：

```text
RAG_ECON_COLLECTION_NAME=
```

## 后续计划

1. 扩大 eval set，加入非经济 query，验证误路由率。
2. 将 staging 数据升级为正式父子索引 collection。
3. 为经济/财经 query 增加来源、地域和时间窗口细分。
