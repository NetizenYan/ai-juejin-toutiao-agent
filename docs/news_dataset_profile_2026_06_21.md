# News Dataset Profile Report

Generated at: `2026-06-21T23:44:36`

## Technical Summary

- 当前业务库 parent 新闻表为 MySQL `news_app.news`，本次画像统计 `clean_count = 7319`。这是站内业务库口径，不是 Qdrant point 数，也不是经济候选 collection 的 19,256 条口径。
- 原始 `category/type` 可用但粒度偏粗，`头条` 占比极高，不能直接支撑细粒度 route/enforce 决策。
- 本报告区分“数据占比高”和“可以 enforce”：占比高只说明值得 shadow 观察；enforce 仍需要灰度指标、引用准确率、拒答质量和稳定性验证。
- 当前结论保持：`econ_finance_query` 继续 enforce；`policy_macro` / `politics_governance` 最多进入 shadow；其他 `news_qa` 继续 shadow；`general_chat` 不强制 evidence。

## 1. 数据源和字段映射

数据源：

```text
database = news_app
primary_parent_table = news
category_table = news_category
```

本报告读取 MySQL parent 新闻表和既有实验日志，不读取 Qdrant。Qdrant 是 chunk/point 级索引，不能代表 parent 新闻数量。

| logical_field | actual_field |
| --- | --- |
| news_id | news.id |
| title | news.title |
| description | news.description |
| content | news.content |
| source | news.author |
| category_id | news.category_id |
| category_name | news_category.name |
| publish_time | news.publish_time |
| created_at | news.created_at |
| updated_at | news.updated_at |

## 2. raw / clean 数量

当前生产业务库口径：

| metric | value |
| --- | --- |
| raw_count_from_current_business_table | 7319 |
| clean_count | 7319 |
| duplicate_title_groups_in_clean_table | 50 |
| duplicate_title_rows_in_clean_table | 108 |
| noise_removed_in_current_business_table | unknown: no raw import log for current MySQL table |
| duplicate_removed_before_current_business_table | unknown: no raw import log for current MySQL table |

补充经济候选集清洗日志口径，不与当前 MySQL `news` 混算：

| metric | value |
| --- | --- |
| clean_report_path | C:\Users\yanyi\OneDrive\Desktop\toutiao_agent_unified\work\econ_rag_experiment\clean_merged_recent_econ_report.json |
| index_report_path | C:\Users\yanyi\OneDrive\Desktop\toutiao_agent_unified\work\econ_rag_experiment\econ_candidate_chunk_index_report.json |
| scanned_total | 418328 |
| date_window_total | 35781 |
| relevant_before_dedupe | 21870 |
| raw_kept_before_dedupe | 21870 |
| deduped_count | 19256 |
| duplicates_removed | 2629 |
| duplicate_removed_rate_of_kept | 12.02% |
| noise_dropped | 3883 |
| too_short | 3049 |
| index_collection | toutiao_econ_chunks_candidate_20260621 |
| index_doc_count |  |
| qdrant_points_count | 89753 |
| index_elapsed_seconds | 6150.79 |

## 3. 原始 category/type 分布

| category_id | category | count | percentage |
| --- | --- | --- | --- |
| 1 | 头条 | 6928 | 94.66% |
| 6 | 体育 | 73 | 1.0% |
| 7 | 科技 | 59 | 0.81% |
| 4 | 国际 | 57 | 0.78% |
| 8 | 财经 | 54 | 0.74% |
| 2 | 社会 | 51 | 0.7% |
| 3 | 国内 | 51 | 0.7% |
| 5 | 娱乐 | 46 | 0.63% |

局限：`category_id -> news_category.name` 是前端新闻分类，不是面向 RAG route 的专业标签；`头条` 是宽泛类别，会吞掉经济、政策、产业等更细主题。

## 4. heuristic multi_label 分布

multi_label 允许一条新闻命中多个标签，因此百分比相加可以超过 100%。

| label | matched_count | matched_percentage_of_total |
| --- | --- | --- |
| stock_market_related | 1752 | 23.94% |
| real_estate | 2379 | 32.5% |
| foreign_trade | 5726 | 78.23% |
| energy_new_energy | 5544 | 75.75% |
| consumer_market | 5797 | 79.2% |
| technology_industry | 6838 | 93.43% |
| industry_policy | 6504 | 88.86% |
| policy_macro | 6842 | 93.48% |
| economy_finance | 6854 | 93.65% |
| politics_governance | 6851 | 93.61% |
| general_news | 151 | 2.06% |

## 5. heuristic primary_label 分布

primary_label 每条新闻只归入一个主标签，使用“具体标签优先，宽泛标签靠后”的优先级：

```text
stock_market_related > real_estate > foreign_trade > energy_new_energy > consumer_market > technology_industry > industry_policy > policy_macro > economy_finance > politics_governance > general_news > unknown
```

| primary_label | count | percentage |
| --- | --- | --- |
| stock_market_related | 1752 | 23.94% |
| real_estate | 1668 | 22.79% |
| foreign_trade | 2876 | 39.29% |
| energy_new_energy | 389 | 5.31% |
| consumer_market | 172 | 2.35% |
| technology_industry | 250 | 3.42% |
| industry_policy | 15 | 0.2% |
| policy_macro | 30 | 0.41% |
| economy_finance | 9 | 0.12% |
| politics_governance | 7 | 0.1% |
| general_news | 151 | 2.06% |

## 6. 来源分布

source 使用 `news.author` 归一化。

归一化规则：

| normalized_source | rule |
| --- | --- |
| 经济日报 / jjrb | 经济日报 OR jjrb |
| 央视 / cctv / 新闻联播 | 新闻联播 OR 央视 OR cctv OR CCTV |
| 聚合数据 | 聚合数据 OR juhe OR Juhe |
| 人民日报 / rmrb | 人民日报 OR rmrb |
| 新华社 | 新华社 OR 新华每日电讯 |
| 课程原始数据 | English personal-name style author, admin/test/tester |
| 其他来源 | non-empty author not matched by known source rules |
| unknown | empty author |

分布：

| source | count | percentage |
| --- | --- | --- |
| 央视 / cctv / 新闻联播 | 6813 | 93.09% |
| 其他来源 | 283 | 3.87% |
| 课程原始数据 | 212 | 2.9% |
| 新华社 | 7 | 0.1% |
| 人民日报 / rmrb | 2 | 0.03% |
| 经济日报 / jjrb | 2 | 0.03% |

## 7. 时间分布

| year | count | percentage |
| --- | --- | --- |
| 2006 | 122 | 1.67% |
| 2007 | 365 | 4.99% |
| 2008 | 366 | 5.0% |
| 2009 | 365 | 4.99% |
| 2010 | 365 | 4.99% |
| 2011 | 365 | 4.99% |
| 2012 | 366 | 5.0% |
| 2013 | 365 | 4.99% |
| 2014 | 365 | 4.99% |
| 2015 | 365 | 4.99% |
| 2016 | 366 | 5.0% |
| 2017 | 365 | 4.99% |
| 2018 | 365 | 4.99% |
| 2019 | 365 | 4.99% |
| 2020 | 366 | 5.0% |
| 2021 | 365 | 4.99% |
| 2022 | 365 | 4.99% |
| 2023 | 616 | 8.42% |
| 2024 | 416 | 5.68% |
| 2025 | 210 | 2.87% |
| 2026 | 111 | 1.52% |

| metric | value |
| --- | --- |
| min_publish_time | 2006-09-01 19:00:00 |
| max_publish_time | 2026-06-21 06:54:37 |
| recent_30d | 111 |
| recent_90d | 111 |
| recent_180d | 111 |
| recent_365d | 213 |
| recent_730d | 515 |

如果 source/time 分布偏旧，“最近/最新”类 query 必须继续依赖 time-aware 排序、时间过滤或显式时效提示。

## 8. 内容质量分布

| metric | value |
| --- | --- |
| empty_title_count | 0 |
| empty_content_count | 0 |
| short_content_count (<100 chars) | 119 |
| medium_content_count (100-1000 chars) | 401 |
| long_content_count (1000-5000 chars) | 250 |
| very_long_content_count (>5000 chars) | 6549 |
| avg_content_length | 6871.45 |
| median_content_length | 7139 |
| p90_content_length | 9137 |
| max_content_length | 20000 |

内容长度会影响是否需要 body chunk、父子切分和回答摘要策略。短内容更适合 summary-first；长内容更依赖 body evidence。

## 9. 每类样本

### stock_market_related

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 357 | A股科技板块集体上涨 | 课程原始数据 | 2023-08-08 15:05:00 | 120 | A股、创业板指、北向资金、券商、科技、AI、芯片、云计算、财经 |
| 360 | 全球加密货币市值突破1万亿美元 | 其他来源 | 2023-08-11 17:20:00 | 115 | ETF、监管、财经、货币、投资 |
| 368 | 日本央行结束负利率政策 | 其他来源 | 2023-08-19 09:30:00 | 119 | 股市、出口、政策、央行、经济、财经、货币、汇率、政府 |
| 372 | 全球大宗商品价格分化 | 其他来源 | 2023-08-23 08:15:00 | 119 | ETF、进口、能源、天然气、财经、投资 |
| 373 | 中国养老金投资规模扩大 | 其他来源 | 2023-08-24 13:30:00 | 121 | 公募基金、财经、投资 |

### real_estate

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 26 | 全国城市更新试点工作取得阶段性成效 | 其他来源 | 2024-02-15 13:50:00 | 130 | 住房、政策 |
| 49 | 全国住房公积金缴存额超3万亿 | 其他来源 | 2024-03-08 14:55:00 | 126 | 住房、房贷、财政部、财政、人民银行、贷款 |
| 85 | 社区宠物管理公约出台 | 其他来源 | 2025-08-20 09:45:00 | 54 | 物业 |
| 118 | 全国住房公积金异地转移接续平台优化升级 | 其他来源 | 2025-09-11 16:00:00 | 95 | 住房 |
| 129 | 全国住房公积金缴存额超3万亿 | 其他来源 | 2025-08-31 14:55:00 | 126 | 住房、房贷、财政部、财政、人民银行、贷款 |

### foreign_trade

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 12 | 2024年前两月外贸进出口实现开门红 | 其他来源 | 2024-03-15 13:25:00 | 143 | 外贸、进出口、出口、进口 |
| 45 | 2024博鳌亚洲论坛年会举行 | 其他来源 | 2024-03-30 16:20:00 | 126 | 一带一路、科技、经济、治理 |
| 125 | 2025博鳌亚洲论坛年会举行 | 其他来源 | 2025-09-04 16:20:00 | 126 | 一带一路、科技、经济、治理 |
| 148 | 2025博鳌亚洲论坛年会举行 | 其他来源 | 2025-08-12 16:20:00 | 126 | 一带一路、科技、经济、治理 |
| 162 | 非洲联盟启动首个区域疫苗中心 | 课程原始数据 | 2023-08-19 12:05:00 | 64 | 进口 |

### energy_new_energy

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 10 | “十四五”规划实施中期评估报告发布 | 其他来源 | 2024-03-10 15:50:00 | 122 | 能源、科技、发改委、规划 |
| 14 | 我国首口万米深地科探井开钻 | 其他来源 | 2024-03-25 11:05:00 | 125 | 石油、技术 |
| 40 | 中国—中亚机制升级为元首峰会 | 其他来源 | 2024-03-21 12:25:00 | 128 | 能源 |
| 103 | 长庆油田第二采油厂原油日产量突破万吨 | 央视 / cctv / 新闻联播 | 2025-09-20 09:46:00 | 120 | 能源、技术 |
| 105 | 全国首座500千伏全自主可控变电站投运 | 央视 / cctv / 新闻联播 | 2025-09-20 09:46:00 | 123 | 能源、新能源、风电、电力、技术、芯片、操作系统 |

### consumer_market

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 4 | 2023年我国GDP同比增长5.2% | 经济日报 / jjrb | 2024-01-17 10:00:00 | 140 | 消费、零售、技术、高质量发展、经济、投资、GDP |
| 7 | 春节假期国内旅游出游4.74亿人次 | 其他来源 | 2024-02-25 14:30:00 | 136 | 文旅、旅游、假期、数据中心 |
| 15 | 《政府工作报告》明确2024年发展预期目标 | 新华社 | 2024-03-28 14:50:00 | 146 | 消费、政策、宏观、政府工作报告、经济、全国人大、政府、会议 |
| 29 | 2024年“消费促进年”活动启动 | 其他来源 | 2024-02-27 14:40:00 | 130 | 消费、汽车、促消费、经济 |
| 47 | 中国戏曲像音像工程录制剧目超500部 | 其他来源 | 2024-01-18 15:15:00 | 132 | 文旅、科技 |

### technology_industry

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 1 | 国家主席发表2024年新年贺词 | 新华社 | 2024-01-01 08:00:00 | 146 | 科技、互联网、高质量发展、改革、开放、经济、中央 |
| 3 | 我国成功发射通信技术试验卫星十一号 | 央视 / cctv / 新闻联播 | 2024-01-10 18:20:00 | 125 | 技术、卫星 |
| 5 | 央行宣布降准0.5个百分点 | 其他来源 | 2024-01-20 16:45:00 | 133 | 科技、央行、经济、金融、人民银行、实体经济 |
| 8 | 我国科学家在量子计算领域取得新突破 | 其他来源 | 2024-03-01 11:20:00 | 128 | 技术、量子 |
| 11 | 我国成功发射遥感四十一号卫星 | 央视 / cctv / 新闻联播 | 2024-03-13 20:10:00 | 124 | 卫星、规划、治理 |

### industry_policy

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 24 | 我国科学家发现新的耐碱基因 | 其他来源 | 2024-02-08 15:20:00 | 133 | 农业 |
| 42 | 全国累计建成高标准农田超10亿亩 | 其他来源 | 2024-03-26 10:50:00 | 125 | 农业 |
| 66 | “爱心驿站”为户外工作者送温暖 | 其他来源 | 2025-09-08 12:10:00 | 60 | 医药 |
| 78 | 农民画作品荣获全国大奖 | 其他来源 | 2025-08-27 15:55:00 | 57 | 农业 |
| 122 | 全国累计建成高标准农田超10亿亩 | 其他来源 | 2025-09-07 10:50:00 | 127 | 农业 |

### policy_macro

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 2 | 全国两会将于3月初在京召开 | 人民日报 / rmrb | 2024-01-05 09:30:00 | 120 | 政策、国务院、政府工作报告、两会、经济、全国人大、政协、政府、会议 |
| 19 | 2024年全国教育工作会议部署重点任务 | 其他来源 | 2024-01-22 11:45:00 | 124 | 高质量发展、会议 |
| 21 | 全国生态环境保护大会召开 | 其他来源 | 2024-01-30 09:05:00 | 128 | 高质量发展、会议 |
| 23 | 2024年中央一号文件发布 | 人民日报 / rmrb | 2024-02-05 08:50:00 | 144 | 国务院、中央、治理 |
| 32 | 十四届全国人大二次会议开幕 | 新华社 | 2024-03-05 09:00:00 | 129 | 政策、国务院、政府工作报告、经济、全国人大、政府、会议 |

### economy_finance

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 20 | 我国水利建设投资首次突破1.2万亿元 | 其他来源 | 2024-01-25 14:15:00 | 126 | 投资 |
| 31 | 全国政协十四届二次会议开幕 | 其他来源 | 2024-03-04 15:00:00 | 118 | 经济、政协、会议 |
| 134 | 全国政协十四届二次会议开幕 | 其他来源 | 2025-08-26 15:00:00 | 118 | 经济、政协、会议 |
| 352 | 特斯拉Q2财报超预期 | 其他来源 | 2023-08-03 11:40:00 | 133 | 财经、投资、营收、利润 |
| 358 | 美联储官员暗示暂停加息 | 其他来源 | 2023-08-09 12:30:00 | 128 | 经济、财经、CPI |

### politics_governance

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 25 | 我国注册志愿者超2.3亿人 | 其他来源 | 2024-02-12 10:35:00 | 129 | 治理 |
| 38 | 《中华人民共和国宪法》最新修正版发布 | 其他来源 | 2024-03-16 13:10:00 | 126 | 全国人大、会议、人大常委会 |
| 55 | 老旧小区加装电梯工程竣工 | 其他来源 | 2025-09-19 16:45:00 | 81 | 政府 |
| 110 | 秦代石刻“尕日塘秦刻石”获文物部门认定 | 其他来源 | 2025-09-17 16:45:00 | 96 | 治理 |
| 141 | 《中华人民共和国宪法》最新修正版发布 | 其他来源 | 2025-08-19 13:10:00 | 126 | 全国人大、会议、人大常委会 |

### general_news

| news_id | title | source | publish_time | content_length | matched_keywords |
| --- | --- | --- | --- | --- | --- |
| 6 | C919国产大飞机开启东南亚演示飞行 | 新华社 | 2024-02-18 12:15:00 | 125 |  |
| 9 | 2024年春运圆满结束 | 其他来源 | 2024-03-05 17:00:00 | 135 |  |
| 13 | 国家医保局公布2023年医保基金运行情况 | 其他来源 | 2024-03-20 09:40:00 | 126 |  |
| 17 | 全国耕地面积连续三年实现净增加 | 其他来源 | 2024-01-12 15:55:00 | 133 |  |
| 18 | 我国发明专利有效量已突破500万件 | 其他来源 | 2024-01-15 16:30:00 | 130 |  |

## 10. heuristic 分类关键词规则

### stock_market_related

```text
A股、股市、股票、上市公司、证券、证监会、交易所、上交所、深交所、北交所、IPO、并购、回购、分红、沪指、深成指、创业板指、上证指数、股票指数、股指、股票板块、行业板块、个股、北向资金、公募基金、私募基金、证券投资基金、股票型基金、ETF、券商、资本市场
```

### real_estate

```text
房地产、楼市、房价、住房、商品房、二手房、租赁、房贷、按揭、土地出让、保障房、城中村、保交楼、物业、开发商
```

### foreign_trade

```text
外贸、进出口、出口、进口、全球贸易、贸易、关税、海关、跨境电商、一带一路、自贸区、外资、外商投资、国际市场、RCEP
```

### energy_new_energy

```text
能源、新能源、光伏、风电、储能、锂电、电池、充电桩、煤炭、石油、天然气、电力、绿电、氢能、碳市场、碳排放、节能、核电
```

### consumer_market

```text
消费、零售、餐饮、文旅、旅游、假期、票房、商场、电商、购物、家电、汽车消费、以旧换新、服务消费、夜经济、居民收入
```

### technology_industry

```text
科技、技术、人工智能、AI、大模型、算力、芯片、半导体、机器人、数字化、云计算、数据中心、互联网、软件、操作系统、量子、卫星、低空经济、智能制造、新质生产力
```

### industry_policy

```text
半导体、芯片、人工智能、算力、新能源汽车、汽车、医药、军工、能源、钢铁、农业、低空经济、数字经济、机器人、光伏、储能、工业互联网、制造业、产业链、供应链、专精特新、现代化产业体系
```

### policy_macro

```text
政策、宏观、国务院、发改委、财政部、央行、证监会、工信部、政府工作报告、两会、高质量发展、新质生产力、改革、开放、监管、产业政策、促消费、扩大内需、稳就业、稳增长、十五五、规划
```

### economy_finance

```text
经济、财经、金融、财政、货币、投资、GDP、CPI、PPI、PMI、汇率、债券、人民银行、商业银行、银行业、银行贷款、银行信贷、银行间、信贷、融资、贷款、税收、营收、利润、经济增长、稳增长、资本市场、民营经济、实体经济、高质量发展、新质生产力
```

### politics_governance

```text
习近平、中央、政治局、全国人大、政协、政府、治理、党员、会议、外交、国家安全、地方政府、省委、市委、国务院常务会议、人大常委会、纪检、监察、法治
```

## 11. 数据画像结论

1. `economy_finance` 当前业务库 primary count = 9。继续经济 enforce 的依据是前序经济灰度通过，而不是本次画像单独证明。
2. `policy_macro` primary count = 30，`politics_governance` primary count = 7。即使占比较高，也只能说明值得进入 shadow 观察，不代表可以直接 enforce。
3. `stock_market_related` primary count = 1752。A 股相关方向当前只能支持“政策/经济新闻对行业或板块的可能影响解释”，不能做个股涨跌预测、买卖建议或确定性投资结论。
4. 当前 MySQL 业务库和经济候选集是两套口径：业务库用于前端新闻/通用站内画像；经济候选集用于 `econ_finance_query` 灰度 RAG。

## 12. 对经济/政策灰度路线的建议

```text
econ_finance_query：继续 enforce
policy_macro / politics_governance：最多建议进入 shadow，不建议直接 enforce
其他 news_qa：继续 shadow
general_chat：不强制 evidence
```

建议逻辑：

- 数据占比高 -> 说明值得进入 shadow 观察。
- 可以 enforce -> 需要通过 Answer Validator shadow 指标、引用准确率、拒答质量、SSE/落库稳定性和灰度测试。
- 经济 enforce 已通过灰度，因此可继续；政策宏观还需要先 shadow 采集失败类型。

## 13. 是否建议新增 policy_macro_query

可以进入需求讨论和 shadow 方案设计，但不建议本阶段直接实现或 enforce。

建议先做：

1. 设计 `policy_macro_query` 的触发词和语句回归测试集。
2. 在 shadow 中记录 citation accuracy、no-answer、wouldRewrite、hallucination_risk。
3. 与 `econ_finance_query` 分开看指标，不混合判断。

## 14. 是否建议进入 A 股板块影响解释模块

暂不建议做个股涨跌预测或投资建议。

可以考虑的边界是：

```text
政策/经济新闻对行业或板块的可能影响解释
```

回答必须使用保守表达：

```text
可能影响
可能利好/利空
仍需结合市场资金、公司基本面和行情数据判断
```

## Final Recommendation

```text
继续经济为主 / 加入政策宏观 shadow / 不建议 policy_macro enforce / 暂不建议股票涨跌预测
```
