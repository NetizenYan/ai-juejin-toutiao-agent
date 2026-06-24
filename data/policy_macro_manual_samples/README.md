# Policy Macro Manual Samples

This folder is a manual sample pack for the `policy_macro` shadow-readiness phase.

It is intentionally small and local-only:

- Do not crawl data.
- Do not bulk-access external sites.
- Do not auto-download files.
- Do not store commercial news full text.
- Do not collect personal sensitive information.
- Do not use these samples for stock prediction or trading advice.

## Directory Structure

```text
data/policy_macro_manual_samples/
├─ README.md
├─ samples_template.csv
├─ samples_template.jsonl
├─ samples.example.jsonl
└─ sources/
   ├─ gov_policy_documents/
   ├─ ndrc/
   ├─ mof/
   ├─ pbc/
   ├─ stats_gov/
   └─ stats_data/
```

The `sources/` folders are staging folders for manually reviewed notes or source-side exports. Do not put large raw corpora here.

## First-Batch Source IDs

Manual sample `source_id` values are short local IDs mapped to the first-batch whitelist sources:

| source_id | Whitelist source | Source name |
| --- | --- | --- |
| `gov_policy_documents` | `gov_policy_library` | 国务院政策文件库 |
| `ndrc` | `ndrc_policy` | 国家发改委 |
| `mof` | `mof_policy_fiscal` | 财政部 |
| `pbc` | `pbc_policy_statistics` | 人民银行 |
| `stats_gov` | `stats_gov_data` | 国家统计局 |
| `stats_data` | `national_data_stats` | 国家数据 |

Recommended `citation_id` format:

```text
policy:<source_id>:<document_id>
```

Examples:

```text
policy:gov_policy_documents:20260621-001
policy:ndrc:20260621-001
policy:pbc:20260621-001
```

## Required Fields

Each real sample must include:

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
content_excerpt
content_length
source_url
license_or_terms_status
risk_level
allowed_use
citation_id
```

`topic_tags`, `industry_tags`, and `allowed_use` may be written as JSON arrays in JSONL, or semicolon/comma-separated strings in CSV.

## Allowed policy_domain Values

```text
macro_policy
fiscal_policy
monetary_policy
industrial_policy
capital_market_policy
consumption_policy
real_estate_policy
foreign_trade_policy
employment_policy
technology_policy
green_energy_policy
data_ai_policy
```

These labels are for policy/news impact explanation only. They must not be used to infer stock price direction.

## Allowed industry_tags Values

```text
broad_market
consumer
real_estate
banking
securities
insurance
semiconductor
ai_computing
new_energy
automobile
pharmaceutical
defense
infrastructure
foreign_trade
manufacturing
agriculture
digital_economy
green_energy
```

These tags support future A-share sector impact explanation, not stock price prediction.

## Manual Collection Flow

1. 人工打开官方来源页面。
2. 选择政策/宏观相关文档。
3. 只摘录标题、来源、发布时间、摘要、短片段、URL。
4. 不复制大段全文。
5. 不采集个人信息。
6. 不绕过登录、验证码、反爬。
7. 不录入商业新闻全文。
8. 每个来源先整理 5-10 条。
9. 总量控制在 30-60 条。
10. 先用于内部 shadow 测试，不对外发布全文。

## Validation

Run from the project root:

```powershell
python scripts/validate_policy_macro_samples.py
```

Optional JSON output:

```powershell
python scripts/validate_policy_macro_samples.py --output reports/policy_macro_manual_sample_validation.json
```

The validator only reads local files under this folder. It does not access external sites and does not download data.

## Minimum Gate for policy_macro Shadow

Only enter `policy_macro` shadow after the real manual sample pack satisfies:

```text
sample_count >= 30
at least 4 of the first-batch 6 sources have samples
required field completeness >= 95%
source_url completeness >= 95%
policy_domain determinable rate >= 90%
industry_tags determinable rate >= 70%
no blocked sources
no commercial news full text
no personal sensitive information
```

## Notes

`samples.example.jsonl` contains fictional or desensitized examples only. Do not treat it as real policy evidence.
