# Policy Macro Candidate Profile Plan Report

Generated at: `2026-06-21`

本阶段只建立 `policy_macro_candidate_profile` 的画像方案和小规模样本审计口径，不爬取数据，不批量访问外部站点，不新建 Qdrant collection，不修改现有 RAG collection，不改前端，不改 Validator enforce，不实现 `policy_macro_query`，不做股票涨跌预测。

## 1. 本阶段目标

目标是把 `policy_macro` 从“有潜力的数据方向”推进到“可审计、可画像、可进入 shadow 观察”的状态。

本阶段产出两类文件：

```text
docs/policy_macro_candidate_profile_plan_2026_06_21.md
reports/policy_macro_candidate_profile_schema_2026_06_21.json
```

本阶段不做：

```text
不爬取数据
不批量访问外部站点
不新建 Qdrant collection
不修改 RAG collection
不改 Validator enforce 配置
不实现 policy_macro_query
不改前端
不做股票涨跌预测
```

关键判断：

```text
数据占比高 ≠ 可以 enforce
shadow 指标稳定 ≠ 可以做投资建议
policy_macro enforce 需要单独评估
```

## 2. 白名单来源复核

已完成的 `policy_macro_source_whitelist` 登记了 18 个官方/披露来源，但本阶段只复核第一批推荐来源，不扩大到全部白名单。

第一批只使用：

```text
国务院政策文件库
国家发改委
财政部
人民银行
国家统计局
国家数据
```

第二批仅作为观察对象：

```text
证监会
工信部
商务部
上交所公告
深交所公告
北交所公告
巨潮资讯
证监会公告
```

第二批不在本阶段直接进入采样实施，也不作为 enforce 依据。

## 3. 第一批候选来源

| source_id | source_name | 画像重点 | 本阶段准入方式 |
| --- | --- | --- | --- |
| `gov_policy_library` | 国务院政策文件库 | 综合宏观政策、高质量发展、新质生产力、扩大内需 | 小规模人工样本整理 / 官方入口确认 |
| `ndrc_policy` | 国家发改委 | 宏观调控、产业政策、区域发展、投资消费 | 小规模人工样本整理 / 官方入口确认 |
| `mof_policy_fiscal` | 财政部 | 财政政策、专项债、财政收支、税费政策 | 小规模人工样本整理 / 官方入口确认 |
| `pbc_policy_statistics` | 人民银行 | 货币政策、金融支持、利率流动性、金融统计 | 小规模人工样本整理 / 官方入口确认 |
| `stats_gov_data` | 国家统计局 | 宏观指标、经济运行、消费投资工业数据 | 小规模人工样本整理 / 官方下载/API 确认 |
| `national_data_stats` | 国家数据 | 宏观指标、时间序列、结构化统计数据 | 小规模人工样本整理 / 官方下载/API 确认 |

推荐的第一轮人工样本规模：

```text
每个第一批来源 5-10 篇/条
总量约 30-60 条
只做字段完整性、引用可用性、标签适配和风险边界审计
```

## 4. 推荐字段 schema

未来如果整理或采集 policy_macro 候选文档，每条文档至少包含：

```text
source_id
source_name
document_id
title
publish_time
publisher
document_type
topic_tags
policy_domain
industry_tags
summary
content_length
source_url
license_or_terms_status
risk_level
allowed_use
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `source_id` | 白名单里的稳定来源 ID |
| `source_name` | 来源名称 |
| `document_id` | 官方文档 ID 或本地确定性 ID |
| `title` | 标题 |
| `publish_time` | 发布时间 |
| `publisher` | 发布机构 |
| `document_type` | 政策文件、公告、统计发布、解读等 |
| `topic_tags` | 标签体系中的一个或多个标签 |
| `policy_domain` | 主政策域，用于画像聚合 |
| `industry_tags` | 可能影响的行业/板块标签，只用于解释 |
| `summary` | 简短摘要，不替代原文 |
| `content_length` | 保留文本或片段长度 |
| `source_url` | 官方来源链接 |
| `license_or_terms_status` | 条款状态：checked / unknown / restricted / blocked |
| `risk_level` | low / medium / high / blocked |
| `allowed_use` | internal_profile / citation / summary / shadow_eval 等 |

建议额外记录：

```text
retrieved_or_collected_at
content_excerpt
language
source_hash
duplicate_group_id
manual_audit_status
citation_ready
display_boundary
risk_notes
```

## 5. policy_macro 标签体系

这些标签只用于“政策/新闻影响解释”，不能直接推导股票涨跌。

| 标签 | 定义 | 关键词 | 可能影响的行业/板块 |
| --- | --- | --- | --- |
| `macro_policy` 宏观政策 | 稳增长、扩大内需、高质量发展、经济运行等综合政策 | 宏观政策、稳增长、扩大内需、高质量发展、新质生产力、经济运行 | 大盘情绪、基建、消费、制造业、金融 |
| `fiscal_policy` 财政政策 | 财政支出、税费优惠、专项债、政府投资、转移支付 | 财政政策、专项债、减税降费、财政支出、政府投资、预算 | 基建、环保、公共服务、地方国企、建筑建材 |
| `monetary_policy` 货币政策 | 利率、流动性、信贷、降准降息、结构性工具 | 货币政策、降准、降息、流动性、信贷、利率、再贷款 | 银行、券商、地产、成长股、债券市场 |
| `industrial_policy` 产业政策 | 产业升级、制造业支持、设备更新、供应链韧性 | 产业政策、制造业、产业升级、设备更新、供应链、专精特新 | 高端制造、机械设备、工业母机、汽车、电子 |
| `capital_market_policy` 资本市场政策 | 监管、融资制度、并购重组、长期资金入市、投资者保护 | 资本市场、证监会、并购重组、IPO、再融资、长期资金、退市 | 券商、保险、上市公司、创投、金融科技 |
| `consumption_policy` 促消费政策 | 消费刺激、以旧换新、服务消费、文旅消费、汽车家电消费 | 促消费、以旧换新、服务消费、文旅消费、汽车消费、家电消费 | 零售、家电、汽车、旅游、食品饮料 |
| `real_estate_policy` 房地产政策 | 住房金融、购房限制、保障房、城中村改造、房地产融资 | 房地产、住房、房贷、保障房、城中村改造、去库存、保交楼 | 房地产、银行、建筑建材、家居、物业 |
| `foreign_trade_policy` 外贸政策 | 进出口、关税、跨境电商、服务贸易、稳外贸 | 外贸、进出口、关税、跨境电商、服务贸易、稳外贸 | 港口航运、跨境电商、出口制造、物流、纺织服装 |
| `employment_policy` 就业政策 | 稳就业、创业支持、职业培训、毕业生就业、社保 | 就业、稳就业、创业、职业培训、高校毕业生、社保 | 人力资源服务、教育培训、平台经济、消费、公共服务 |
| `technology_policy` 科技创新政策 | 科技创新、研发、半导体、人工智能、成果转化 | 科技创新、研发、关键核心技术、半导体、人工智能、成果转化 | 半导体、软件、人工智能、高端装备、通信 |
| `green_energy_policy` 绿色能源政策 | 新能源、绿色低碳、双碳、储能、电力体制、节能环保 | 新能源、绿色低碳、碳达峰、碳中和、储能、光伏、风电 | 新能源、电力设备、储能、环保、电网 |
| `data_ai_policy` 数据 / AI / 数字经济政策 | 数据要素、数字经济、AI、算力、数字基础设施、数据安全 | 数据要素、数字经济、人工智能、算力、数字基础设施、数据安全 | 云计算、数据中心、AI 应用、软件服务、网络安全 |

标签使用约束：

```text
只能用于政策影响解释
不能用于个股涨跌预测
不能输出买入/卖出建议
不能把政策新闻直接等同于股价结果
```

## 6. shadow query 测试集

本测试集只用于未来 shadow，不执行 enforce。

| query | expected_domain | expected_route_or_domain_marker | requires_evidence | requires_citation | financial_advice_guard |
| --- | --- | --- | --- | --- | --- |
| 最近有哪些高质量发展相关政策？ | `macro_policy` | `policy_macro_shadow` | true | true | true |
| 最近新质生产力相关政策有什么？ | `macro_policy` | `policy_macro_shadow` | true | true | true |
| 最近促消费政策有哪些？ | `consumption_policy` | `policy_macro_shadow` | true | true | true |
| 最近房地产政策有什么变化？ | `real_estate_policy` | `policy_macro_shadow` | true | true | true |
| 最近资本市场监管有什么新闻？ | `capital_market_policy` | `policy_macro_shadow` | true | true | true |
| 最近半导体产业政策有什么？ | `technology_policy` | `policy_macro_shadow` | true | true | true |
| 最近新能源产业政策有什么？ | `green_energy_policy` | `policy_macro_shadow` | true | true | true |
| 最近财政政策有什么变化？ | `fiscal_policy` | `policy_macro_shadow` | true | true | true |
| 最近货币政策有什么变化？ | `monetary_policy` | `policy_macro_shadow` | true | true | true |
| 最近哪些政策可能影响 A 股市场情绪？ | `capital_market_policy` | `policy_macro_shadow` | true | true | true |

补充建议：未来 shadow query 应加入无答案样本，例如不存在的政策名称、过期政策问询、要求明确股票涨跌的越界问询，用于验证拒答和安全边界。

## 7. shadow 评估指标

未来进入 shadow 时建议观察：

| 指标 | 含义 |
| --- | --- |
| `route_hit_rate` | policy_macro 问法被标记为 policy_macro shadow/domain 的比例 |
| `evidence_count` | 每个 query 的证据数量 |
| `citation_accuracy` | 引用是否来自实际召回证据 |
| `invalid_ref_rate` | 无法解析或不在证据中的引用比例 |
| `would_rewrite_rate` | shadow 下如果 enforce 会被 rewrite 的比例 |
| `hallucination_risk_distribution` | low / medium / high 风险分布 |
| `no_answer_ok_rate` | 证据不足时正确拒答比例 |
| `answer_len` | 最终展示给用户的回答长度 |
| `p95_latency` | 端到端 95 分位耗时 |
| `source_coverage` | 第一批来源覆盖度 |
| `time_coverage` | 发布时间覆盖度和近期覆盖度 |

进入 enforce 前至少还需要额外评估：

```text
policy_macro route 命中稳定性
官方 evidence detail 可解析性
citation 准确率
无答案拒答率
Validator shadow 失败原因
延迟和 rewrite 成本
用户是否会误解为投资建议
```

## 8. A 股板块影响解释边界

允许：

```text
基于政策/经济新闻解释可能影响哪些行业或板块
使用“可能”“倾向于”“需要结合行情和基本面判断”等保守表达
必须给 evidence
必须保留 [news:...] 或官方来源引用
必须说明政策影响只是影响因素之一
```

禁止：

```text
预测个股涨跌
给买入/卖出建议
说必涨、稳赚、确定利好
把政策新闻直接等同于股价结果
输出确定性投资结论
```

推荐回答边界：

```text
这类政策可能影响某些行业或板块的预期，但实际市场表现还要结合资金面、公司基本面、估值、行情数据和后续政策落地情况判断。
```

## 9. 是否建议进入小规模人工样本整理

```text
建议进入小规模人工样本整理
```

但只建议进入以下范围：

```text
小规模人工样本整理
官方 API / 下载入口确认
官方页面字段可用性确认
citation 和 evidence detail 可用性审计
标签体系适配性审计
```

不建议进入：

```text
爬虫
批量外部访问
新建 collection
policy_macro enforce
商业新闻全文抓取
股票涨跌预测
```

结论：

```text
建议进入小规模人工样本整理
```
