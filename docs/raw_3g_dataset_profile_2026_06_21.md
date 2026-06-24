# Raw 3G+ Dataset Profile Report

Generated at: `2026-06-22T01:41:42`

This is a local-only profile of the 3G+ raw datasets. It does not crawl, download, build Qdrant collections, write MySQL, or copy large full text into the report.

## 1. Scope

The profile covers:

- JJRB / 经济日报 CSV: `D:\Files\BaiDu\经济日报2010-2026.6.csv`
- RMRB / 人民日报 Excel files: `2` files, years filter `['2025', '2026']`
- Existing cleaned economic candidate report, if present

## 2. Raw Source Inventory

| source | rows/profiled rows | size | date_min | date_max | section_unique_count |
| --- | --- | --- | --- | --- | --- |
| jjrb | 385406 | 1294.8 MB | 2010-01-01 | 2026-06-10 | 729 |
| rmrb | 32709 | 56.29 MB | 2025-01-01 | 2026-01-06 | 311 |

## 3. JJRB Raw Section Top 30

| section | count | percentage |
| --- | --- | --- |
| 要闻 | 92925 | 24.11% |
| 综合 | 23712 | 6.15% |
| 时评 | 23700 | 6.15% |
| 关注 | 12702 | 3.3% |
| 特别报道 | 10374 | 2.69% |
| 产经 | 10075 | 2.61% |
| 综合新闻 | 9008 | 2.34% |
| 宏观资讯 | 8496 | 2.2% |
| 世界经济 | 6744 | 1.75% |
| 财金 | 6676 | 1.73% |
| 区域 | 6587 | 1.71% |
| 环球 | 5785 | 1.5% |
| 地方 | 5495 | 1.43% |
| 经济要闻 | 5110 | 1.33% |
| 财经 | 5090 | 1.32% |
| 资本市场 | 4686 | 1.22% |
| 理论 | 4408 | 1.14% |
| 企业 | 4333 | 1.12% |
| 国际 | 4208 | 1.09% |
| 地区新闻 | 3373 | 0.88% |
| 要 闻 | 3349 | 0.87% |
| 两会特刊 | 3269 | 0.85% |
| 国际财经 | 2839 | 0.74% |
| 今日财经 | 2723 | 0.71% |
| 理论周刊 | 2614 | 0.68% |
| 环球经济 | 2383 | 0.62% |
| 环球财经 | 2286 | 0.59% |
| 读者 | 2236 | 0.58% |
| 周末 | 2209 | 0.57% |
| 区域经济 | 2197 | 0.57% |

## 4. RMRB Section Top 30

| section | count | percentage |
| --- | --- | --- |
| 第01版：要闻 | 3181 | 9.73% |
| 第03版：要闻 | 2934 | 8.97% |
| 第04版：要闻 | 2677 | 8.18% |
| 第02版：要闻 | 2504 | 7.66% |
| 第20版：副刊 | 1576 | 4.82% |
| 第05版：评论 | 1527 | 4.67% |
| 第06版：要闻 | 1491 | 4.56% |
| 第07版：要闻 | 933 | 2.85% |
| 第17版：国际 | 676 | 2.07% |
| 第08版：副刊 | 656 | 2.01% |
| 第09版：理论 | 548 | 1.68% |
| 第11版：政治 | 474 | 1.45% |
| 第10版：经济 | 453 | 1.38% |
| 第10版：各地传真 | 441 | 1.35% |
| 第15版：国际 | 387 | 1.18% |
| 第15版：体育 | 376 | 1.15% |
| 第13版：社会 | 362 | 1.11% |
| 第14版：生态 | 358 | 1.09% |
| 第10版：政治 | 337 | 1.03% |
| 第11版：经济 | 274 | 0.84% |
| 第11版：文化 | 263 | 0.8% |
| 第16版：国际 | 261 | 0.8% |
| 第07版：读者来信 | 246 | 0.75% |
| 第05版：要闻 | 245 | 0.75% |
| 第14版：社会 | 236 | 0.72% |
| 第12版：文化 | 230 | 0.7% |
| 第13版：文化 | 201 | 0.61% |
| 第19版：党建 | 199 | 0.61% |
| 第19版：法治 | 192 | 0.59% |
| 第18版：新农村 | 187 | 0.57% |

## 5. Domain Hints From Section Names

These are only profile hints for future internal RAG candidate design. They do not change Router, Validator, or collection config.

| source | domain_hint | count | percentage |
| --- | --- | --- | --- |
| jjrb | macro_policy | 160736 | 41.71% |
| jjrb | other | 111513 | 28.93% |
| jjrb | capital_market | 28994 | 7.52% |
| jjrb | industry_technology | 26807 | 6.96% |
| jjrb | foreign_trade_global | 24746 | 6.42% |
| jjrb | regional_local | 21557 | 5.59% |
| jjrb | consumer_market | 4535 | 1.18% |
| jjrb | agriculture_rural | 3622 | 0.94% |
| jjrb | green_energy | 2896 | 0.75% |
| rmrb | macro_policy | 16634 | 50.85% |
| rmrb | other | 11928 | 36.47% |
| rmrb | foreign_trade_global | 2004 | 6.13% |
| rmrb | green_energy | 904 | 2.76% |
| rmrb | industry_technology | 657 | 2.01% |
| rmrb | agriculture_rural | 197 | 0.6% |
| rmrb | capital_market | 193 | 0.59% |
| rmrb | consumer_market | 192 | 0.59% |

## 6. Existing Econ Candidate Link

Existing cleaned economic candidate is available: `True`.

```json
{
  "source_counts": {
    "old": 33,
    "jjrb": 14274,
    "rmrb": 4949
  },
  "dedupe": {
    "duplicates_removed": 2629,
    "duplicates_by_source": {
      "old": 1,
      "jjrb": 1843,
      "rmrb": 785
    }
  },
  "recent_windows": {
    "last_7_days": {
      "count": 21,
      "by_source": {
        "old": 21
      },
      "title_econ_keyword": 1
    },
    "last_30_days": {
      "count": 884,
      "by_source": {
        "old": 21,
        "jjrb": 863
      },
      "title_econ_keyword": 236
    },
    "last_90_days": {
      "count": 3251,
      "by_source": {
        "old": 21,
        "jjrb": 3230
      },
      "title_econ_keyword": 902
    },
    "last_180_days": {
      "count": 7056,
      "by_source": {
        "old": 21,
        "jjrb": 6697,
        "rmrb": 338
      },
      "title_econ_keyword": 1981
    },
    "last_365_days": {
      "count": 19256,
      "by_source": {
        "old": 33,
        "jjrb": 14274,
        "rmrb": 4949
      },
      "title_econ_keyword": 5747
    }
  }
}
```

## 7. Recommended Next Step

Start with local-only candidate profiles rather than indexing:

1. `econ_finance_query`: keep current enforce setup and current collection.
2. `policy_macro`: use the manual sample pack first, then shadow only.
3. `capital_market`, `consumer_market`, `industry_technology`, `foreign_trade_global`: create profile-only candidate plans from raw section/domain hints before building any collection.
4. Do not upload raw CSV/XLSX, cleaned full-text JSONL, or Qdrant dumps to GitHub.

## Final Decision

```text
可以继续用本地 3G+ 数据做内部画像、候选集设计和 RAG 召回验证；
下一步先做多类目 candidate profile，不直接新建 collection。
```
