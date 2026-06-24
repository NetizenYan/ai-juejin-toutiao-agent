# Evidence Detail Resolver

Date: `2026-06-21`

## 1. 为什么需要 evidence detail resolver

经济 RAG 回答会输出形如 `[news:jjrb:139aa3760c02aada]` 的 citation。该 ID 来自经济 RAG 知识库，不是 MySQL `news_app.news.id`。

当前前端新闻详情页只支持 MySQL 整数新闻 ID，例如 `news:2726`。因此，经济 citation 可以显示在 AI 回答里，但不能直接跳到现有新闻详情页。

Evidence Detail Resolver 的目标是提供一个只读后端解析层，把 `news:jjrb:...` 解析为可展示的证据详情：

```text
title
source
publish_time
snippet
content_excerpt
collection
parent_id
chunk_index
```

## 2. 为什么短期不全量同步经济数据到 MySQL

当前经济候选集有 `19256` 条 parent 文档和约 `89687` 个 Qdrant points。短期目标是 AI 问答 citation 可解释，不是上线完整经济新闻频道。

全量同步到 MySQL 需要处理：

- source/id/category 映射
- 与现有 `news` 表去重
- 分页、索引、缓存和性能
- 前端频道、详情、收藏、历史的产品设计
- 回滚策略

因此短期优先 resolver，后续如果要做经济新闻频道，再设计 MySQL 同步。

## 3. evidence_id 支持格式

Resolver 支持带中括号和不带中括号：

```text
news:jjrb:8dcc9e6349959132
[news:jjrb:8dcc9e6349959132]
news:2726
[news:2726]
news:cctv-20200101-3
[news:cctv-20200101-3]
```

规则：

- 保留完整 `evidence_id`。
- 不把 `jjrb` / `rmrb` / `cctv-*` 强转为整数。
- 只有纯数字 `news:2726` 才允许作为 MySQL 或 Qdrant 数字 ID fallback。

## 4. 数据来源优先级

当前 resolver 的查询优先级：

1. Qdrant payload：优先读 `evidence_id/doc_id/news_id/parent_news_id/source_doc_id` 匹配项。
2. 本地经济候选 JSONL：`work/econ_rag_experiment/clean_merged_recent_econ.jsonl`。
3. MySQL：仅用于纯数字 `news:<id>` 的业务新闻 fallback。
4. 找不到则返回 `found=false`，不编造。

Qdrant payload 已确认具备：

```text
doc_id
news_id
parent_news_id
source
source_doc_id
title
publish_time
publish_ts
section
category
url
evidence_id
chunk_type
chunk_index
chunk_text
summary
text
```

JSONL parent 文档已确认具备：

```text
doc_id
source
source_doc_id
title
content
publish_time
publish_ts
section
url
category
evidence_id
```

## 5. API endpoint

新增只读接口：

```text
GET /api/ai/evidence-detail?evidence_id=<evidence_id>
```

示例：

```text
GET /api/ai/evidence-detail?evidence_id=news:jjrb:139aa3760c02aada
GET /api/ai/evidence-detail?evidence_id=[news:2726]
```

接口特性：

- 复用现有登录鉴权。
- 不调用 LLM。
- 不调用 Answer Validator。
- 不写 MySQL。
- 不修改 Qdrant。
- 返回普通 JSON。

## 6. 返回字段

找到时：

```json
{
  "evidence_id": "news:jjrb:139aa3760c02aada",
  "found": true,
  "source": "经济日报",
  "title": "织密新就业群体保障网",
  "publish_time": "2026-06-07 00:00:00",
  "snippet": "...",
  "content_excerpt": "...",
  "collection": "toutiao_econ_chunks_candidate_20260621",
  "parent_id": "jjrb:139aa3760c02aada",
  "chunk_index": 0,
  "detail_available": true,
  "storage": "qdrant_payload"
}
```

未找到时：

```json
{
  "evidence_id": "news:jjrb:unknown",
  "found": false,
  "error": "evidence_not_found"
}
```

## 7. 找不到 evidence 的处理

找不到时返回 `found=false` 和明确错误码，不生成标题、正文或来源。

这保持了 Answer Contract 的原则：证据不足时承认未知，不编造。

## 8. 后续前端 citation 点击方案

本阶段不改前端 UI。后续前端可以做：

1. 把回答中的 `[news:jjrb:...]` 渲染为可点击 citation。
2. 点击后调用：

```text
GET /api/ai/evidence-detail?evidence_id=news:jjrb:...
```

3. 在弹窗、右侧 panel 或详情抽屉展示：

```text
标题
来源
发布时间
摘要片段
正文片段
原始 URL（如果存在）
```

4. 对 MySQL 数字 ID `news:2726`，可以继续走现有新闻详情页，也可以统一走 evidence detail endpoint。

## 9. 后续如果要做经济新闻频道

如果产品后续要做经济新闻频道，再考虑把 `19256` 条经济 parent 文档同步到 MySQL。

同步前需要设计：

- source/id 映射
- category 映射
- 与现有 `news` 去重
- 查询索引和分页性能
- 前端频道入口
- 收藏、历史、推荐的业务含义
- 数据更新和回滚策略

## Current Decision

```text
优先使用 evidence detail resolver；
短期不全量同步经济数据到 MySQL；
后续如果要做经济新闻频道，再设计 MySQL 同步。
```

