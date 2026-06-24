# Policy Macro Source Whitelist Report

Generated at: `2026-06-21`

本阶段只建立 `policy_macro_source_whitelist`，不爬取数据，不批量访问外部站点，不重建索引，不新建 collection，不实现 `policy_macro_query`，不修改 Validator enforce，不做 A 股预测。

## 1. 白名单目标

目标是给后续 `policy_macro_candidate_profile` 建立准入边界：

- 只从官方政策、官方统计、官方披露渠道开始。
- 不使用商业新闻全文爬取。
- 不使用付费财经资讯、研报、会员内容。
- 不绕过登录、验证码、反爬或付费墙。
- 不把白名单等同于可直接全量抓取；白名单只表示可进入下一步小规模画像和条款审核。

默认原则：

```text
官方政策文件：low-to-medium，优先进入 whitelist。
官方统计数据：low-to-medium，优先进入 whitelist。
交易所/公告披露：medium，需要检查条款和下载方式。
商业新闻站全文：high / blocked，不进入 whitelist。
付费资讯/研报/会员内容：blocked。
绕过登录、验证码、反爬、付费墙：blocked。
```

## 2. 已登记来源

| source_id | source_name | source_type | risk_level | decision | access_method |
| --- | --- | --- | --- | --- | --- |
| `gov_policy_library` | 中国政府网 / 国务院政策文件库 | official_policy | low | allow_internal_only | official_page |
| `national_data_administration` | 国家数据局 | official_policy | low | allow_internal_only | official_page |
| `ndrc_policy` | 国家发改委 | official_policy | low | allow_internal_only | official_page |
| `mof_policy_fiscal` | 财政部 | official_policy | low | allow_internal_only | official_page |
| `pbc_policy_statistics` | 人民银行 | official_policy | low | allow_internal_only | official_page |
| `csrc_policy_announcements` | 证监会 | official_policy | low-to-medium | allow_internal_only | official_page |
| `miit_policy` | 工信部 | official_policy | low | allow_internal_only | official_page |
| `mofcom_policy_data` | 商务部 | official_policy | low-to-medium | allow_internal_only | official_page |
| `stats_gov_data` | 国家统计局 | official_statistics | low | allow_internal_only | manual_download |
| `national_data_stats` | 国家数据 | official_statistics | low-to-medium | allow_internal_only | official_page |
| `customs_statistics` | 海关总署 | official_statistics | low-to-medium | allow_internal_only | official_page |
| `mof_fiscal_revenue_data` | 财政部财政收支数据 | official_statistics | low | allow_internal_only | official_page |
| `pbc_financial_statistics` | 央行统计数据 | official_statistics | low-to-medium | allow_internal_only | official_page |
| `sse_announcements` | 上交所公告 | official_disclosure | medium | allow_internal_only | official_page |
| `szse_announcements` | 深交所公告 | official_disclosure | medium | allow_internal_only | official_page |
| `bse_announcements` | 北交所公告 | official_disclosure | medium | allow_internal_only | official_page |
| `cninfo_announcements` | 巨潮资讯 | official_disclosure | medium | allow_internal_only | official_page |
| `csrc_announcements` | 证监会公告 | official_disclosure | medium | allow_internal_only | official_page |

完整字段已写入：

```text
reports/policy_macro_source_whitelist_2026_06_21.json
```

每条来源均包含：

```text
source_id
source_name
source_type
publisher
homepage_url
policy_or_terms_url
access_method
crawl_required
storage_allowed
rag_allowed
external_display_allowed
contains_personal_information
copyright_risk
robots_or_rate_limit_status
risk_level
decision
allowed_use
forbidden_use
notes
```

## 3. 第一批推荐来源

第一批 `policy_macro_candidate_profile` 建议从政策和宏观统计开始，不从交易所公告开始：

```text
gov_policy_library
national_data_administration
ndrc_policy
mof_policy_fiscal
pbc_policy_statistics
csrc_policy_announcements
miit_policy
mofcom_policy_data
stats_gov_data
national_data_stats
customs_statistics
mof_fiscal_revenue_data
pbc_financial_statistics
```

推荐起点再收窄一层：

```text
gov_policy_library
ndrc_policy
mof_policy_fiscal
pbc_policy_statistics
stats_gov_data
national_data_stats
```

原因：

- 覆盖政策宏观、财政、货币、宏观指标。
- 版权和平台风险低于商业新闻。
- 更适合先做人工作业、小样本画像、citation 格式和 Answer Contract 验证。

## 4. allow / allow_internal_only / allow_metadata_only / blocked 分类

### allow

当前不直接给任何外部来源 `allow`。

原因：白名单只是候选准入，不等于已确认可存储、可 RAG、可外部展示、可批量采集。

### allow_internal_only

当前官方政策、官方统计、官方披露来源均先归为 `allow_internal_only`。

可做：

- 内部小规模画像。
- citation。
- summary/snippet RAG evidence。
- 人工下载或官方 API/export 优先。

不可做：

- 高频爬虫。
- 未审查条款的全文镜像。
- 对外再分发全文库。

### allow_metadata_only

以下场景只允许 metadata-only：

- 交易所公告在未确认批量下载和展示条款前，只保留标题、发布时间、证券代码、来源链接等 metadata。
- 第三方转载页面只作为发现线索，不作为正文来源。
- 来源条款允许引用但不清楚是否允许全文存储时，只保留摘要、链接、结构化元数据。

### blocked

以下不进入 whitelist：

```text
商业新闻全文爬取
付费财经资讯
付费研报
会员内容
绕过登录/验证码/反爬/付费墙
采集个人敏感信息
复制后对外提供可替代原站的全文服务
```

## 5. 风险说明

政策文件和统计数据并不等于“可以随便抓”。本阶段的准入判断是：

```text
可以进入小规模画像和条款审核；
不代表可以直接大规模爬取；
不代表可以直接进入 enforce；
不代表可以对外提供全文库。
```

交易所公告和巨潮资讯属于官方披露/指定披露渠道，但风险等级仍是 `medium`：

- 需要确认平台条款。
- 需要确认下载方式。
- 需要限流、缓存、采样。
- 不得绕过限制。
- 不得用于股票涨跌预测或投资建议。

## 6. policy_macro_candidate_profile 推荐起点

建议进入 `policy_macro_candidate_profile`，但第一轮只做小规模、人工/官方入口优先的画像。

第一轮建议来源：

```text
中国政府网 / 国务院政策文件库
国家发改委
财政部
人民银行
国家统计局
国家数据
```

推荐方法：

```text
人工小规模下载
官方 API / export 优先
官方页面整理
不使用爬虫作为第一选择
```

第一轮画像指标：

- source_id
- document count
- time distribution
- policy topic distribution
- macro indicator coverage
- citation fields availability
- title/source/publish_time/url completeness
- duplicate rate
- full-text storage boundary
- RAG snippet feasibility
- no-answer/refusal test samples

## 7. 是否建议进入 policy_macro_candidate_profile 阶段

```text
建议进入 policy_macro_candidate_profile
```

前提条件：

- 只使用第一批官方来源。
- 只做小规模画像和样本测试。
- 不新建 collection。
- 不重建索引。
- 不实现 `policy_macro_query`。
- 不改 Validator enforce。
- 不做商业新闻全文爬取。
- 不做 A 股涨跌预测。

## References

- [国务院政策文件库](https://sousuo.www.gov.cn/zcwjk/policyDocumentLibrary)
- [国家发展改革委](https://www.ndrc.gov.cn/)
- [财政部财政数据](https://www.mof.gov.cn/gkml/caizhengshuju/)
- [国家数据局](https://www.nda.gov.cn/)
- [国家统计局数据](https://www.stats.gov.cn/sj/)
- [国家数据](https://data.stats.gov.cn/)
- [海关统计数据查询平台](https://stats.customs.gov.cn/)
- [商务部](https://www.mofcom.gov.cn/)
- [商务数据中心](https://data.mofcom.gov.cn/)
- [证监会](https://www.csrc.gov.cn/)
- [上交所公告](https://www.sse.com.cn/disclosure/listedinfo/announcement/)
- [巨潮资讯](https://www.cninfo.com.cn/)

## Final Decision

```text
建议进入 policy_macro_candidate_profile
```

