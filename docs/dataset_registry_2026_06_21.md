# Dataset Registry & Decision Boundary Report

Generated at: `2026-06-21`

本阶段只做数据口径统一与 Dataset Registry。未修改 RAG collection，未重建索引，未修改前端，未修改 Validator enforce 配置，未实现股票预测。

## 1. 当前数据源列表

| dataset_id | storage | count / points | status | route_usage | purpose |
| --- | --- | --- | --- | --- | --- |
| `mysql_news_business` | MySQL `news_app.news` | parent news: `7319` | active business source | default `news_qa` / general browsing | 前端新闻列表、分类、详情、收藏、浏览历史 |
| `econ_candidate_20260621` | Qdrant `toutiao_econ_chunks_candidate_20260621` | clean docs: `19256`; build-log points: `89753`; observed points: `89687` | active gray RAG source | `econ_finance_query` | 经济/财经 RAG 灰度问答 |
| `toutiao_news_claude` | Qdrant | observed points: `7319` | active/available parent vector collection | default business RAG lineage | 当前 MySQL 新闻父级向量口径 |
| `toutiao_chunks_claude` | Qdrant | observed points: `54794` | active/available chunk collection | default business RAG lineage | 当前 MySQL 新闻 chunk 口径 |
| `toutiao_exp_econ_recent_20260621` | Qdrant | observed points: `3000` | previous staging collection | historical staging only | 早期经济灰度对比 |
| `news_chunks`, `news_chunks_multi`, `news_chunks_multi_probe` | Qdrant | `7269`, `21943`, `40` | observed legacy/probe | not current decision source | 历史/探针 collection |

决策口径只依赖前两项：`mysql_news_business` 和 `econ_candidate_20260621`。其他 collection 仅登记为 observed，不作为当前 route/enforce 决策依据。

## 2. MySQL 业务库说明

`mysql_news_business`

```text
dataset_id = mysql_news_business
storage = MySQL news_app.news
count = 7319
purpose = 前端新闻列表 / 分类 / 详情 / 收藏 / 浏览历史
dominant_source = CCTV / 新闻联播，约 93.09%
route_usage = default news_qa / general news browsing
limitations = 不代表 3G 经济数据规模；category 粒度粗
```

当前 MySQL `news_app.news` 是业务展示层数据源。它服务前端新闻列表、分类、详情页、收藏和浏览历史。

已确认画像：

- `clean_count = 7319`
- `头条 = 6928`，占 `94.66%`
- `财经 = 54`，占 `0.74%`
- 近 30 天、90 天、180 天新闻均为 `111`
- 来源高度集中，`央视 / 新闻联播` 约 `93.09%`

因此，MySQL 中 `财经` 分类的 54 条、近期 111 条，只能说明前端业务库当前展示数据的情况，不能代表新增 3G 经济数据的规模。

## 3. 经济 RAG 候选库说明

`econ_candidate_20260621`

```text
dataset_id = econ_candidate_20260621
storage = Qdrant
collection = toutiao_econ_chunks_candidate_20260621
raw_scanned = 418328
time_window_count = 35781
candidate_count = 21870
clean_count = 19256
chunk_or_point_count = 89753
observed_qdrant_points = 89687
route_usage = econ_finance_query
validator_mode = enforce
purpose = 经济/财经 RAG 灰度问答
mysql_synced = false
```

说明：

- 构建日志记录初始 points 为 `89753`。
- 后续生产候选验证报告显示，66 个 `source=old` 噪声 points 被移出候选 collection。
- 当前只读 Qdrant 观测到 `89687` points，这与生产候选报告一致。
- parent 文档数仍按清洗口径记录为 `19256`。

该库服务 `econ_finance_query`，并已进入经济灰度 enforce。它不是前端新闻列表的数据源，也没有全量同步到 MySQL。

## 4. 两类数据源不能混算的原因

```text
MySQL news 表是业务展示层数据源。
Qdrant collection 是 RAG 检索层知识源。
二者数量不能直接混算。
前端财经分类数量不代表经济 RAG 数据量。
Qdrant chunk/point 数不等于 parent 新闻数。
```

具体来说：

- MySQL 的 `7319` 是前端业务库 parent 新闻数量。
- MySQL `财经=54` 是前端分类数量，不是经济 RAG 数据规模。
- Qdrant `89753/89687` 是 chunk/point 数，不是 parent 新闻数。
- 经济候选集 parent 文档数应看 `clean_count=19256`。
- `[news:jjrb:...]` 这类 evidence id 不是 MySQL 整数 `news.id`，不能直接调用现有新闻详情页。

## 5. evidence detail 能力检查

当前能力：部分具备。

已确认 Qdrant payload 中具备：

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

本地 source JSONL 也具备：

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

所以，从数据层看，`[news:jjrb:...]` 可以解析出：

```text
title
source
publish_time
snippet
content 或可展示正文片段
```

但当前产品链路还不完整：

- SSE `done.evidence` 当前主要返回 evidence ref 字符串。
- `ai_message.evidence` 保存 refs 和 validation metadata，不是完整详情对象。
- `ai_tool_call.result` 中可以保留 RAG items 的 title/source/publish_time/summary/snippet。
- 前端新闻详情页当前按 MySQL 整数 `news.id` 查询，不能直接打开 `news:jjrb:...`。

结论：目前可以在 AI answer 中显示 `[news:jjrb:...]` 引用，也可以在后端工具轨迹里追溯详情；但普通前端详情页还不能直接打开这类经济 evidence。

## 6. 是否需要把经济数据同步到 MySQL

短期不建议强制同步 `19256` 条经济 parent 文档到 MySQL。推荐先做方案 A。

### 方案 A：轻量 evidence detail resolver

```text
不把经济数据全量写入 MySQL。
通过 Qdrant payload / metadata store / source JSON 解析 [news:jjrb:...]。
适合短期 AI 问答。
```

优点：

- 风险低，不改前端新闻业务库。
- 能较快补齐 evidence 的 title/source/publish_time/snippet/detail。
- 更适合当前 `econ_finance_query` 灰度阶段。

代价：

- 不是完整经济新闻频道。
- 需要增加 evidence resolver endpoint 或后端解析服务。
- 最好为 `evidence_id` 建一个轻量索引或缓存，避免每次扫 JSONL。

推荐：短期优先做方案 A。

### 方案 B：同步经济 parent 到 MySQL

```text
把 19256 条经济 parent 文档写入 MySQL。
前端可浏览、收藏、查看详情。
但需要 category/source/id 映射、去重、分页、性能和 UI 处理。
适合后续做经济新闻频道。
```

优点：

- 前端列表、详情、收藏、历史都能统一。
- 用户能把经济数据当新闻频道浏览。

代价：

- 需要设计 `source/id/category` 映射。
- 需要与现有 `news` 表去重。
- 需要分页、性能、缓存、UI 和回滚方案。
- 会把“AI RAG 知识库”升级成“产品内容库”，范围明显更大。

推荐：等明确要做经济新闻频道后再做。

## 7. policy_macro 后续数据画像建议

不要现在直接实现 `policy_macro_query`，更不要直接 enforce。

当前 MySQL 画像不足以判断 policy_macro 数据规模。原因是：

- MySQL 是前端展示库，不代表 3G clean corpus。
- MySQL 分类粒度粗，`头条` 占比过高。
- policy/macro 与经济、产业、治理高度交叉，不能靠 MySQL category 判断。

下一阶段建议：

```text
构建 policy_macro_candidate_YYYYMMDD：建议
先做 policy_macro shadow route：建议
直接 policy_macro enforce：不建议
```

需要统计指标：

- raw scanned count
- time window count
- policy_macro candidate count
- dedupe/noise 后 clean count
- source distribution
- time distribution
- section/category distribution
- duplicate/noise removal rate
- 样本质量抽检
- route trigger precision/recall
- retrieval non-empty rate
- freshness ratio
- citation accuracy
- no-answer/refusal quality
- shadow validation passed rate
- wouldRewrite rate
- hallucination_risk distribution

判断规则仍然是：数据占比高只说明值得 shadow，不代表可以 enforce。

## 8. A 股影响解释模块边界

当前可以考虑：

```text
政策/经济新闻对行业或板块的可能影响解释
```

暂不做：

```text
股票涨跌预测
个股买卖建议
确定性投资结论
```

如果要进入 A 股影响解释模块，至少需要：

```text
经济/政策/产业新闻 evidence
行业/板块标签
保守影响方向：利好 / 利空 / 中性 / 不确定
风险提示
```

回答必须使用保守表达，例如：

```text
可能影响
可能利好/利空
仍需结合市场资金、公司基本面和行情数据判断
```

如果未来要做预测类能力，还需要：

- 行情数据
- 时间切分
- 回测
- 防止未来函数
- 合规边界审查

当前不建议进入股票涨跌预测。

## 9. 当前决策建议

```text
继续 econ_finance_query enforce；
不基于 MySQL 财经分类判断经济 RAG 数据规模；
短期不强制同步 19256 条经济数据到 MySQL；
优先补 evidence detail resolver；
policy_macro 先做数据画像和 shadow，不 enforce；
A 股方向先做板块影响解释，不做涨跌预测。
```

