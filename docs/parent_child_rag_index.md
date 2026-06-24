# 父子 RAG 索引设计

## 结论

统一项目继续采用父子索引：父级是单条新闻，用于去重、引用和评测归因；子级是 chunk，用于向量召回、hybrid 排序、reranker 精排和最终证据。

## 为什么不是只建父级索引

只索引标题或摘要会让长正文的大部分内容不可检索。新闻联播、政策报道、财经长文的答案经常在中后段，单靠标题和开头摘要会导致 hard case 召回失败。

## 为什么不是全量 body 默认召回

body chunk 噪声更大，特别是标题/实体型问题会被正文里的泛化词、重复播报、模板句干扰。默认生产策略仍然 summary-first，只在 Query Router 判断为内容细节、时间线或来源约束查询时给 body fallback 一个槽位。

## 当前统一结构

```text
News(parent)
  id
  title
  author/source
  publish_time
  content

Qdrant chunk(child)
  news_id / parent_news_id
  chunk_index
  chunk_type(summary/body, 新索引建议携带)
  title
  source
  publish_ts
  chunk_text
```

## 检索流程

```text
query
  -> query_router
  -> summary chunk recall
  -> optional body fallback
  -> hybrid lexical/vector ranking
  -> bge-reranker in Harness
  -> parent aggregation
  -> answer with [news:ID] evidence
```

## 评测口径

Recall@5 按 parent news_id 归因；EvidenceRecall@5 看 top5 chunk 是否包含金标关键词；BodyEvidence@5 看 top5 parent 是否补到了 body evidence。
