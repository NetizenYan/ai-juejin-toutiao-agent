# Data Source Risk Gate Report

Generated at: `2026-06-21`

本阶段只建立数据源准入和风险分级机制。未爬取新数据，未调用商业站点，未修改 RAG collection，未重建索引，未改前端，未改 Validator enforce。

说明：本文档是项目治理文档，不构成法律意见；进入公开产品或商业使用前，应对具体来源的授权、条款、robots、版权和个人信息风险做单独审核。

## 1. 为什么需要数据源风险门禁

经济 RAG、Answer Validator、Evidence Detail Resolver 和前端 citation detail 已经打通，下一阶段自然会想扩展到 `policy_macro`、政策宏观、A 股板块影响解释。但此时继续“找数据集”和“批量爬新闻”会把项目带入版权、平台条款、反爬、个人信息和服务压力风险。

关键判断：

```text
公开数据不等于开放数据。
能访问不等于能批量抓取。
能抓取不等于能存储、索引、训练/RAG、对外展示或再分发。
```

因此后续所有数据源必须先过 Risk Gate，再决定是否进入 Dataset Registry、候选集画像、RAG 索引或前端展示。

自动化收集公开数据的底线：

- 不非法侵入网络。
- 不干扰服务正常运行。
- 不破坏技术措施。
- 不损害个人和组织合法权益。
- 不绕过登录、验证码、反爬、付费墙。
- 不采集个人敏感信息。
- 不抓取付费内容。
- 不形成实质性替代原站服务的全文产品。

当前项目的数据使用原则：

- 优先使用已有本地数据。
- 优先使用官方公开数据和合规 API。
- RAG 回答尽量使用摘要、片段和 citation。
- 不公开展示大段原文。
- 不做未经授权的数据再分发。

## 2. 当前已有数据源登记

| source_id | source_type | storage | count | purpose | risk_level | decision |
| --- | --- | --- | --- | --- | --- | --- |
| `mysql_news_business` | internal_course_project / local business DB | MySQL | `7319` | frontend news browsing | low/internal | allow |
| `econ_candidate_20260621` | local_cleaned_candidate | Qdrant + local JSONL | clean docs `19256` | `econ_finance_query` RAG | medium unless source licenses confirmed | allow_internal_only |
| `gov_policy_documents_candidate` | official_public | official pages / official endpoint | TBD | policy_macro RAG | low-to-medium | allow_internal_only_until_terms_checked |
| `stats_macro_data_candidate` | official_public_data | official data portal / API if available | TBD | macro indicators / charts / metadata | low-to-medium | allow_internal_only_until_terms_checked |
| `exchange_announcement_candidate` | official_disclosure | official disclosure pages / download channel | TBD | company announcement evidence / event extraction | medium | allow_internal_only |

### mysql_news_business

```text
source_type = internal_course_project / local business DB
storage = MySQL
count = 7319
purpose = frontend news browsing
risk_level = low/internal
allowed_use = frontend display / RAG baseline / testing
notes = 不代表经济 RAG 数据规模
```

### econ_candidate_20260621

```text
source_type = local_cleaned_candidate
storage = Qdrant + local JSONL
clean_count = 19256
collection = toutiao_econ_chunks_candidate_20260621
purpose = econ_finance_query RAG
risk_level = medium unless source licenses confirmed
allowed_use = internal gray test / RAG evidence / citation detail
forbidden_use = public redistribution of full corpus
notes = 需要补充来源授权/来源清单
```

### gov_policy_documents_candidate

```text
source_type = official_public
source_examples = 国务院政策文件库 / 中国政府网
risk_level = low-to-medium
allowed_use = policy_macro RAG / citation / summary
crawl_required = false preferred
access_method = manual download / official page / official endpoint
notes = 批量采集前检查 robots/terms
```

### stats_macro_data_candidate

```text
source_type = official_public_data
source_examples = 国家统计局国家数据
risk_level = low-to-medium
allowed_use = macro indicators / explanation / chart / RAG metadata
crawl_required = false preferred
notes = 优先 API 或手动下载，不要高频抓取
```

### exchange_announcement_candidate

```text
source_type = official_disclosure
source_examples = 上交所/深交所/巨潮资讯等官方披露渠道
risk_level = medium
allowed_use = company announcement evidence / event extraction
notes = 检查平台条款和下载方式；不要绕过限制
```

## 3. 风险等级标准

### low

```text
自有数据、课程数据、人工整理数据、明确开放下载的数据、官方公开政策文件、小规模手动下载
```

默认决策：`allow`

控制要求：

- 记录来源、URL、下载时间和版本。
- 保留 citation。
- 展示时优先摘要和片段。

### medium

```text
官方公开网页批量收集、第三方 API、交易所公告、公开但条款不清的数据
```

默认决策：`allow_internal_only`

控制要求：

- 检查 robots、terms、下载/接口条款。
- 做限流、缓存、采样。
- 优先 metadata/snippet，不直接对外提供全文库。
- 进入公开展示前再审核。

### high

```text
商业新闻网站批量爬取、财经资讯平台全文抓取、可能有版权限制的数据、反爬明显的数据
```

默认决策：`allow_metadata_only_or_blocked`

控制要求：

- 必须有明确授权或付费 API。
- 禁止未授权全文再分发。
- 需要人工审批和合规审查。

### blocked

```text
绕过登录/验证码/付费墙/反爬
采集个人敏感信息
抓取付费内容
造成服务压力
违反 robots/terms
复制后对外提供可替代原站的全文服务
```

默认决策：`blocked`

处理方式：

- 不采集。
- 不存储。
- 不索引。
- 不进入 RAG collection。

## 4. 数据源准入流程

每个新数据源必须先回答：

```text
1. 数据是否公开？
2. 是否开放或授权使用？
3. 是否有 API / 下载入口？
4. 是否允许存储？
5. 是否允许用于模型/RAG？
6. 是否允许对外展示？
7. 是否包含个人信息？
8. 是否有版权风险？
9. 是否会替代原站服务？
10. 是否需要限流、缓存、采样？
```

准入输出只能是以下之一：

```text
allow
allow_internal_only
allow_metadata_only
blocked
```

推荐决策规则：

| 条件 | 输出 |
| --- | --- |
| 自有/课程/明确授权/官方开放下载，且无个人敏感信息 | `allow` |
| 官方公开但条款、批量方式或展示边界待确认 | `allow_internal_only` |
| 来源可引用但全文版权或再分发不清 | `allow_metadata_only` |
| 需要绕过限制、包含敏感个人信息、付费内容、反爬或会替代原站 | `blocked` |

## 5. 当前经济候选集风险判断

`econ_candidate_20260621` 可以继续用于内部灰度，但在来源授权/来源清单补齐前，不应扩大为公开全文产品。

当前判断：

```text
risk_level = medium unless source licenses confirmed
decision = allow_internal_only
allowed = 内部灰度测试 / RAG evidence / citation detail / 摘要回答
forbidden = 对外再分发全文库 / 未授权批量导出 / 替代原站全文服务
```

原因：

- 已有清洗候选集可支持 `econ_finance_query` 灰度，不需要继续爬新数据。
- 经济 RAG 回答应保持 summary/snippet/citation，而不是全文展示。
- Evidence Detail Resolver 可以展示片段和来源，但不应变成全文内容分发系统。
- 若后续进入公开产品，需要补充来源授权、来源列表、展示边界和版权审查。

## 6. policy_macro 推荐数据源路线

优先：

```text
中国政府网 / 国务院政策文件库
国家统计局
国家数据局
发改委 / 财政部 / 央行 / 证监会等官方发布
交易所公告
```

避免：

```text
商业新闻站全文爬取
付费财经资讯
绕过反爬的数据
条款不清的批量全文数据
```

建议先做：

```text
policy_macro_source_whitelist
policy_macro_candidate_profile
policy_macro shadow
```

不直接做：

```text
policy_macro enforce
股票涨跌预测
商业新闻全文爬取
```

## 7. 哪些数据源不能碰

以下来源或方式直接列为 high / blocked：

- 商业新闻网站批量全文爬取。
- 财经资讯平台全文抓取。
- 付费资讯、研报、专栏、会员内容。
- 明显存在反爬措施、验证码、登录墙、付费墙的页面。
- 需要伪造身份、绕过访问限制或突破技术措施的数据。
- 包含个人敏感信息的数据。
- 高频抓取导致对方服务压力的任务。
- 复制后可对外提供原站替代性全文服务的数据。

对于 A 股方向，当前只允许：

```text
证据摘要
板块/行业影响解释
保守影响方向
风险提示
```

不允许：

```text
未经授权全文库
个股买卖建议
股票涨跌预测
确定性投资结论
```

## 8. 后续 Dataset Registry 如何更新

以后每一个新数据源进入 `reports/dataset_registry_*.json` 或 RAG candidate 之前，必须先登记：

```text
source_id
source_type
owner / publisher
access_method
license_or_terms_url
robots_or_rate_limit_status
storage_allowed
rag_allowed
external_display_allowed
contains_personal_information
copyright_risk
risk_level
decision
allowed_use
forbidden_use
reviewer
review_date
```

如果字段缺失，默认不得进入 enforce，只能保持 blocked 或 allow_internal_only。

## 9. 下一步建议

1. 建立 `policy_macro_source_whitelist`，先只收官方政策、统计、部委、交易所披露渠道。
2. 对每个候选来源补 `license_or_terms_url`、访问方式、限流策略和展示边界。
3. 做 `policy_macro_candidate_profile`，只画像，不直接 enforce。
4. `policy_macro` 先 shadow，观察 citation accuracy、no-answer、wouldRewrite、hallucination_risk。
5. A 股方向只做证据摘要和板块影响解释，不做涨跌预测。

## References

- [中华人民共和国网络安全法](https://www.cac.gov.cn/2016-11/07/c_1119867116_2.htm)
- [个人信息保护政策法规问答](https://www.cac.gov.cn/2026-01/09/c_1769688003183197.htm)
- [国家版权局《关于规范网络转载版权秩序的通知》](https://www.cac.gov.cn/2015-04/22/c_1115052967.htm)
- [信息网络传播权保护条例](https://www.cac.gov.cn/2013-02/08/c_126468776.htm)
- [国务院政策文件库](https://sousuo.www.gov.cn/zcwjk/policyDocumentLibrary)
- [国家统计局数据](https://www.stats.gov.cn/sj/)
- [国家数据](https://data.stats.gov.cn/)
- [上海证券交易所最新公告](https://www.sse.com.cn/disclosure/listedinfo/announcement/)
- [巨潮资讯](https://www.cninfo.com.cn/)

## Final Decision

```text
不建议继续无差别爬虫；
继续使用已有经济候选集做灰度；
policy_macro 优先走官方公开文件和合规 API；
商业新闻全文爬取列为高风险或 blocked；
A 股方向先做证据摘要和板块影响解释，不做未经授权全文库和涨跌预测。
```

