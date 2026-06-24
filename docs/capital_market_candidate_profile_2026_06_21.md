# Capital Market Candidate Profile Report

Generated at: `2026-06-22T01:46:58`

This is a local-only candidate profile for `capital_market`. It does not crawl, download, build a Qdrant collection, modify RAG, modify frontend, or expand Validator enforce.

## 1. Scope

Profile source:

```text
JJRB / 经济日报 local CSV
RMRB / 人民日报 local XLSX, years 2025 and 2026
```

The profile uses section, title, and short content-prefix keyword matches. It does not store long full text in the report.

## 2. Candidate Counts

| source | scanned | date_window | matched | section_matched | title_matched | content_prefix_matched |
| --- | --- | --- | --- | --- | --- | --- |
| jjrb | 385406 | 18036 | 1825 | 1025 | 905 | 841 |
| rmrb | 32709 | 17532 | 336 | 72 | 228 | 109 |
| combined | 418115 | 35568 | 2161 |  |  |  |

Matched rate of date window: `6.08%`.

## 3. Top Sections

| section | count | percentage |
| --- | --- | --- |
| 财金 | 1025 | 47.43% |
| 要闻 | 229 | 10.6% |
| 国际 | 111 | 5.14% |
| 时评 | 97 | 4.49% |
| 综合 | 88 | 4.07% |
| 关注 | 72 | 3.33% |
| 第18版：财经 | 61 | 2.82% |
| 产经 | 40 | 1.85% |
| 第02版：要闻 | 31 | 1.43% |
| 地方 | 27 | 1.25% |
| 理论 | 18 | 0.83% |
| 第03版：要闻 | 18 | 0.83% |
| 智库 | 17 | 0.79% |
| 港澳台 | 16 | 0.74% |
| 第06版：要闻 | 16 | 0.74% |
| 第01版：要闻 | 15 | 0.69% |
| 第04版：要闻 | 15 | 0.69% |
| 第10版：经济 | 15 | 0.69% |
| 两会特刊 | 14 | 0.65% |
| 企业 | 12 | 0.56% |
| 第08版：广告 | 12 | 0.56% |
| 国际副刊 | 11 | 0.51% |
| 副刊 | 11 | 0.51% |
| 特别报道 | 8 | 0.37% |
| 第16版：广告 | 8 | 0.37% |

## 4. Year Distribution

| year | count | percentage |
| --- | --- | --- |
| 2025 | 1318 | 60.99% |
| 2026 | 843 | 39.01% |

## 5. Industry Tag Hints

| tag | count | percentage |
| --- | --- | --- |
| banking | 1226 | 56.73% |
| broad_market | 951 | 44.01% |
| securities | 655 | 30.31% |
| insurance | 539 | 24.94% |

## 6. Sample Titles

JJRB examples:

| date | section | title | matched_keywords |
| --- | --- | --- | --- |
| 2025-06-21 | 要闻 | 强化资本市场枢纽功能服务科创 | 上市公司, 证监会, 资本市场 |
| 2025-06-21 | 综合 | 深化金融改革服务高质量发展 | 证监会, 资本市场, 金融 |
| 2025-06-21 | 企业 | 治理“零公里二手车”乱象 | 资本市场 |
| 2025-06-22 | 要闻 | 谱写金融善治福建新篇章 | 金融, 金融市场 |
| 2025-06-22 | 要闻 | 谱写金融善治福建新篇章 | 金融, 金融市场 |
| 2025-06-22 | 关注 | 设置“科创成长层”为哪般 | 投资者保护, 证监会, 资本市场 |
| 2025-06-22 | 港澳台 | 不攻自破的“香港玩完论” | 资本市场 |
| 2025-06-23 | 要闻 | 中国特色金融发展之路从这里出发 | 金融 |
| 2025-06-23 | 要闻 | 中国特色金融发展之路从这里出发 | 金融 |
| 2025-06-23 | 国际 | 德国推出大规模减税方案重振经济 | 资本市场 |

RMRB examples:

| date | section | title | matched_keywords |
| --- | --- | --- | --- |
| 2025-06-22 | 第02版：要闻 | “走出去有保险兜底，踏实！”（经济新方位·外贸一线见闻） | 保险 |
| 2025-06-23 | 第18版：财经 | 精准“画像”服务小微企业融资（财经故事） | 融资, 财经 |
| 2025-06-23 | 第18版：财经 | 让人与城的“双向奔赴”更美好（财经眼·为新型城镇化战略提供有力资金保障） | 财经 |
| 2025-06-23 | 第18版：财经 | 江苏银行“一企一策”稳外贸（财经短波） | 财经, 银行 |
| 2025-06-23 | 第18版：财经 | 助力新市民更好“落地生根”（财经观） | 财经 |
| 2025-06-24 | 第01版：要闻 | “走好中国特色金融发展之路” | 金融 |
| 2025-06-24 | 第04版：要闻 | “走好中国特色金融发展之路” | 金融 |
| 2025-06-24 | 第19版：党建 | 套取保险，“套”住自己（监督哨） | 保险 |
| 2025-06-25 | 第02版：要闻 | 十九项金融举措提振消费（政策解读） | 证监会, 金融 |
| 2025-06-25 | 第02版：要闻 | 李强将出席2025年亚洲基础设施投资银行第十届理事会年会开幕式 | 银行 |

## 7. Safety Boundary

Allowed:

```text
capital-market policy/regulation explanation
sector-level possible influence explanation
citation-backed news evidence
```

Forbidden:

```text
individual stock price prediction
buy/sell advice
guaranteed gain or deterministic market outcome
```

## 8. Shadow Readiness

```json
{
  "profile_exists": true,
  "candidate_count_at_least_30": true,
  "source_coverage_at_least_2": true,
  "manual_review_done": false,
  "citation_detail_gate_done": false,
  "no_answer_tests_done": false,
  "financial_advice_guard_required": true,
  "recommended_mode": "profile_only_now_then_shadow_after_manual_review"
}
```

## 9. Next Steps

```text
manual review 30-60 capital_market samples
split policy/regulation news from institution/company financial news
create shadow query set with no-answer and advice-boundary probes
do not build a collection until profile and shadow gates pass
```

## Final Decision

```text
capital_market has enough local signal for candidate profiling;
not ready for enforce;
not ready for a new collection.
```
