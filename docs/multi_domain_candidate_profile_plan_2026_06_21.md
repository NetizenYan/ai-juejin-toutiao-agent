# Multi-Domain Candidate Profile Plan

Generated at: `2026-06-21`

This plan turns the local 3G+ raw dataset profile into a route/domain roadmap. It does not crawl, download, build a collection, modify RAG, modify the frontend, or expand Validator enforce.

## 1. Current Evidence

The local raw profile shows:

```text
JJRB / 经济日报: 385,406 rows, 729 raw sections, 2010-01-01 to 2026-06-10
RMRB / 人民日报 recent profile: 32,709 rows, 311 page-section labels, 2025-01-01 to 2026-01-06
Existing econ candidate: 19,256 clean docs, active econ_finance_query enforce gray source
```

The original 3G+ data can continue to be used for internal profiling, candidate design, and RAG recall validation. It should not be uploaded to GitHub as raw CSV/XLSX, cleaned full-text JSONL, or Qdrant dumps.

## 2. Principles

```text
data volume high != enforce readiness
section count high != route quality
shadow stability != investment advice permission
profile first, sample second, shadow third, enforce last
```

Keep the existing production posture:

```text
econ_finance_query: keep current enforce
policy_macro: sample + shadow first
other domains: profile first
general_chat: no mandatory evidence
```

## 3. Candidate Domain Roadmap

| domain | recommendation | evidence | next action |
| --- | --- | --- | --- |
| `econ_finance_query` | Keep current enforce | Existing 19,256 clean docs and passed gray validation | Monitor only; no rebuild now |
| `policy_macro` | Manual sample then shadow | Macro/policy section hints are large, but not enforce-ready | Finish 30-60 manual samples, then shadow |
| `capital_market` | Profile recommended | 财金、财经、资本市场、证券、金融、银行、保险 | Local candidate profile with financial-advice guard |
| `industry_technology` | Profile recommended | 产经、产业、企业、公司、创新、新知、科技、数据 | Profile sections and sample content |
| `foreign_trade_global` | Profile recommended | 世界经济、环球、国际、国际财经、一带一路 | Profile by section and title keywords |
| `consumer_market` | Lower-volume profile | 消费、文旅、文化产业、服务 | Profile after higher-priority domains |
| `green_energy` | Specialized profile | 生态、绿色、能源、环保、碳 | Profile as policy/industry subdomain |
| `agriculture_rural` | Specialized profile | 乡村振兴、聚焦三农、现代农业、新农村 | Profile after macro/industry |
| `regional_local` | Later profile/facet | 地方、区域、地区、城市 | Prefer metadata/facet before standalone route |
| `real_estate` | Keyword profile required | Section names alone are weak | Use title/content keyword profile first |

## 4. Priority Order

Recommended execution order:

```text
1. policy_macro
2. capital_market
3. industry_technology
4. foreign_trade_global
5. consumer_market
6. green_energy
7. agriculture_rural
8. regional_local
9. real_estate
```

Why this order:

- `policy_macro` already has whitelist, sample pack, and safety boundaries.
- `capital_market` has product value but needs the strictest safety guard.
- `industry_technology` and `foreign_trade_global` have strong raw section signals.
- `consumer_market`, `green_energy`, and `agriculture_rural` are useful but should start as narrower profiles.
- `regional_local` may be better as a filter/facet than a route.
- `real_estate` needs content keyword profiling because section names alone are not enough.

## 5. Profile Fields

Each future domain profile should output at least:

```text
domain_id
source
source_doc_id
title
publish_time
section
domain_hint
topic_tags
industry_tags
content_length
source_url
risk_level
allowed_use
citation_id
evidence_detail_ready
```

Do not put long full text into reports. Use counts, titles only when needed, short snippets only when explicitly auditing evidence quality.

## 6. Shadow Entry Gates

A domain can enter shadow only after:

```text
profile report exists
30-60 reviewed or high-confidence local samples exist
source coverage is reported
time coverage is reported
citation_id can resolve to evidence detail
no-answer tests exist
financial advice guard exists if market-sensitive
Validator remains shadow unless explicitly approved
no raw/full-text corpus is included in GitHub demo
```

## 7. Domain Safety Boundaries

Capital market, real estate, industry, and policy answers must use conservative language:

```text
可能影响
倾向于
需要结合资金面、基本面、估值、行情数据和政策落地判断
```

Forbidden:

```text
预测个股涨跌
给买入/卖出建议
说必涨、稳赚、确定利好
把政策或新闻直接等同于股价结果
```

## 8. GitHub Demo Boundary

Allowed in GitHub:

```text
code
schema
docs
templates
fictional or desensitized examples
aggregate counts and profile reports without long full text
```

Not allowed in GitHub:

```text
经济日报2010-2026.6.csv
RMRB数据/*.xlsx
clean_merged_recent_econ.jsonl
Qdrant dumps
large full-text evidence metadata
commercial/news full-text corpus
```

## 9. Next Concrete Work

The next implementation step should be:

```text
capital_market_candidate_profile
```

Scope:

```text
local section/title profile only
no crawling
no indexing
no frontend change
no Validator change
no stock prediction
```

This pairs well with the already prepared `policy_macro_manual_sample_pack`: while policy_macro waits for manual samples, capital_market can be profiled locally from the 3G+ section signals.

## Final Decision

```text
继续使用本地 3G+ 数据做内部多类目候选画像；
下一步先做 policy_macro 人工样本和 capital_market / industry_technology / foreign_trade_global profile；
不直接新建 collection。
```
