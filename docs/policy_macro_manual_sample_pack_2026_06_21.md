# Policy Macro Manual Sample Pack Report

Generated at: `2026-06-21`

本阶段创建 `policy_macro_manual_sample_pack`，只为后续人工整理 30-60 条政策/宏观样本做准备。

本阶段不采集数据，不访问外部站点，不自动下载，不新建 Qdrant collection，不修改 RAG collection，不改前端，不改 Validator enforce，不实现 `policy_macro_query`，不做股票涨跌预测。

## 1. 样本包目标

目标是给 `policy_macro` 后续 shadow 测试准备一个可审计的人工样本入口：

- 统一样本目录。
- 统一字段 schema。
- 统一 `policy_domain` 标签。
- 统一 `industry_tags` 标签。
- 提供 2-3 条虚构/脱敏示例。
- 提供本地校验脚本。
- 输出可复用的校验报告格式。

这个样本包不是知识库，不是索引，不是训练集，也不是可公开分发的全文数据集。

## 2. 第一批来源

第一批来源仍然固定为 6 个官方来源：

| sample source_id | 白名单来源 | 来源名称 |
| --- | --- | --- |
| `gov_policy_documents` | `gov_policy_library` | 国务院政策文件库 |
| `ndrc` | `ndrc_policy` | 国家发改委 |
| `mof` | `mof_policy_fiscal` | 财政部 |
| `pbc` | `pbc_policy_statistics` | 人民银行 |
| `stats_gov` | `stats_gov_data` | 国家统计局 |
| `stats_data` | `national_data_stats` | 国家数据 |

本阶段只允许围绕这些来源做人工样本准备。证监会、工信部、商务部、交易所公告、巨潮资讯等仍作为第二批观察对象，不进入本轮人工样本包的第一批门槛。

## 3. 样本字段说明

每条样本必须包含：

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

字段约定：

| 字段 | 说明 |
| --- | --- |
| `source_id` | 样本包内的 6 个第一批来源短 ID |
| `source_name` | 来源名称 |
| `document_id` | 人工整理时记录的文档 ID，建议按日期和序号确定 |
| `title` | 文档标题 |
| `publish_time` | 发布时间 |
| `publisher` | 发布机构 |
| `document_type` | `policy_document` / `notice` / `announcement` / `statistics_release` / `press_release` / `interpretation` / `other` |
| `topic_tags` | 可多选的 policy macro 标签 |
| `policy_domain` | 主标签，只能是 12 类之一 |
| `industry_tags` | 行业/板块标签，只用于影响解释 |
| `summary` | 人工短摘要，不替代原文 |
| `content_excerpt` | 短片段，不复制大段全文 |
| `content_length` | `content_excerpt` 或保留短文本的字符长度 |
| `source_url` | 官方来源 URL，校验脚本只检查是否填写，不访问网络 |
| `license_or_terms_status` | `checked` / `unknown` / `restricted` / `blocked` |
| `risk_level` | `low` / `medium` / `high` / `blocked` |
| `allowed_use` | 如 `internal_profile`、`citation`、`summary`、`shadow_eval` |
| `citation_id` | 建议格式 `policy:<source_id>:<document_id>` |

示例：

```text
policy:gov_policy_documents:20260621-001
policy:ndrc:20260621-001
policy:pbc:20260621-001
```

## 4. policy_domain 标签说明

允许值：

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

标签用途：

- 用于政策/宏观文档画像。
- 用于未来 shadow query 的期望 domain。
- 用于判断证据是否支持用户问题。
- 不用于股票涨跌预测。
- 不用于买卖建议。

## 5. industry_tags 标签说明

允许值：

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

这些标签只支持未来的“板块影响解释”：

```text
可能影响哪些行业或板块
可能通过哪些政策路径影响预期
仍需结合行情、资金面、基本面和政策落地判断
```

禁止把这些标签用于：

```text
个股涨跌预测
买入/卖出建议
必涨、稳赚、确定利好等确定性表达
```

## 6. 人工整理流程

人工整理必须遵守：

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

示例文件 `samples.example.jsonl` 只放虚构或脱敏示例，不能当作真实政策证据。

## 7. 校验脚本使用方式

脚本：

```text
scripts/validate_policy_macro_samples.py
```

默认用法：

```powershell
python scripts/validate_policy_macro_samples.py
```

输出到报告文件：

```powershell
python scripts/validate_policy_macro_samples.py --output reports/policy_macro_manual_sample_validation.json
```

脚本能力：

- 读取 `data/policy_macro_manual_samples/*.jsonl`。
- 读取 `data/policy_macro_manual_samples/*.csv`。
- 跳过 `_template=true` 的模板行。
- 校验必填字段。
- 校验 `source_id` 是否属于第一批 6 个来源。
- 校验 `policy_domain` 和 `topic_tags` 是否属于 12 类标签。
- 校验 `industry_tags` 是否属于允许值。
- 校验 `source_url` 是否填写且形态是 HTTP(S)，不访问外部网络。
- 校验 `content_length` 是否与 `content_excerpt/summary` 大致一致。
- 校验 `risk_level` 和 `allowed_use` 是否填写。
- 校验 `citation_id` 是否符合 `policy:<source_id>:<document_id>`。
- 输出字段完整率、标签分布、来源分布、错误列表和 shadow 入门门槛。

脚本不会：

```text
访问外部网站
下载数据
连接数据库
访问 Qdrant
修改 RAG collection
调用 LLM
```

## 8. 合格样本标准

单条样本合格标准：

- 必填字段完整。
- `source_id` 属于第一批 6 个来源。
- `policy_domain` 属于 12 类标签。
- `industry_tags` 至少有一个可判定标签。
- `source_url` 已填写。
- `content_excerpt` 只保留短片段。
- `risk_level` 不是 `blocked`。
- `allowed_use` 明确。
- `citation_id` 可稳定引用。
- 不含商业新闻全文。
- 不含个人敏感信息。

样本包合格标准：

```text
样本数 >= 30
第一批 6 个来源中至少 4 个来源有样本
必填字段完整率 >= 95%
source_url 完整率 >= 95%
policy_domain 可判定率 >= 90%
industry_tags 可判定率 >= 70%
无 blocked 来源
无商业新闻全文
无个人敏感信息
```

## 9. 后续进入 policy_macro shadow 的条件

只有满足以下条件，才建议进入 `policy_macro shadow`：

```text
样本数 >= 30
第一批 6 个来源中至少 4 个来源有样本
必填字段完整率 >= 95%
source_url 完整率 >= 95%
policy_domain 可判定率 >= 90%
industry_tags 可判定率 >= 70%
无 blocked 来源
无商业新闻全文
无个人敏感信息
```

进入 shadow 后仍然不代表可以 enforce。`policy_macro enforce` 需要另行评估 route 命中、证据数量、citation 准确率、invalid ref、would rewrite、no-answer、延迟和投资建议安全边界。

## Example Validation Result

示例校验报告：

```text
reports/policy_macro_manual_sample_validation_example_2026_06_21.json
```

当前示例数据结果：

```text
sample_count = 3
required field completeness = 100%
source_url completeness = 100%
policy_domain determinable rate = 100%
industry_tags determinable rate = 100%
errors = 0
warnings = 0
shadow_entry_ready = false
```

`shadow_entry_ready=false` 是预期结果，因为示例数据只有 3 条，未达到真实 shadow 的 30 条样本和 4 个来源覆盖门槛。

## Final Decision

```text
可以开始人工整理 30-60 条样本
```

但只能采用：

```text
人工小规模整理
官方 API / 下载入口确认
官方页面字段可用性确认
```

不能采用：

```text
爬虫
批量外部访问
自动下载
商业新闻全文抓取
股票涨跌预测
```
