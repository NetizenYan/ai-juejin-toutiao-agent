# Reviewed Label Confirmation Packet

This packet turns draft reviewed labels into a reviewer checklist. It is not the official reviewed-label file.

## Summary

- Candidate rows: 80
- Draft label rows: 80
- Missing candidate references: 0
- Accept as gold: 65
- Merge with existing: 15
- Needs evidence lookup: 0
- Reject: 0

## Case Type Counts

| Case type | Accept | Merge | Lookup | Reject |
| --- | ---: | ---: | ---: | ---: |
| `A_exact_news_qa` | 14 | 1 | 0 | 0 |
| `B_context_follow_up` | 14 | 6 | 0 | 0 |
| `C_time_sensitive` | 9 | 2 | 0 | 0 |
| `D_source_limited` | 8 | 1 | 0 | 0 |
| `E_multi_document` | 8 | 3 | 0 | 0 |
| `F_similar_distractor` | 4 | 1 | 0 | 0 |
| `G_no_answer` | 4 | 1 | 0 | 0 |
| `H_investment_boundary` | 4 | 0 | 0 | 0 |

## Reviewer Checklist

| # | Candidate | Decision | Case type | Target gold | Evidence count | Prompt preview | Reviewer confirmation |
| ---: | --- | --- | --- | --- | ---: | --- | --- |
| 1 | `candidate_context_follow_001` | `merge_with_existing` | `B_context_follow_up` | `context_follow_001` | 0 | 最近高质量发展和新质生产力有什么新闻？ / 那它对制造业有什么影响？ |  |
| 2 | `candidate_source_005` | `merge_with_existing` | `D_source_limited` | `source_005` | 0 | 经济日报，新质生产力如何影响制造业？ |  |
| 3 | `candidate_no_answer_006` | `merge_with_existing` | `G_no_answer` | `no_answer_006` | 0 | 站内有没有关于星河制造业跃迁法案2040的消息？ |  |
| 4 | `candidate_exact_econ_006` | `merge_with_existing` | `A_exact_news_qa` | `exact_econ_006` | 0 | 新质生产力赋能高质量发展的实现路径有哪些新闻？ |  |
| 5 | `candidate_context_follow_002` | `merge_with_existing` | `B_context_follow_up` | `context_follow_002` | 0 | 新质生产力 高质量发展 和高质量发展是什么关系？ |  |
| 6 | `candidate_context_follow_003` | `merge_with_existing` | `B_context_follow_up` | `context_follow_003` | 0 | 新质生产力 高质量发展 和新质生产力有关吗？ |  |
| 7 | `candidate_context_follow_004` | `merge_with_existing` | `B_context_follow_up` | `context_follow_004` | 0 | 新质生产力 高质量发展 先进制造 对先进制造有什么影响？ |  |
| 8 | `candidate_time_recent_003` | `merge_with_existing` | `C_time_sensitive` | `time_recent_003` | 0 | 2026年5月左右新质生产力有哪些新闻？ |  |
| 9 | `candidate_multi_doc_002` | `merge_with_existing` | `E_multi_document` | `multi_doc_002` | 0 | 新质生产力、科技创新和产业升级之间的关系 |  |
| 10 | `candidate_multi_doc_004` | `merge_with_existing` | `E_multi_document` | `multi_doc_004` | 0 | 新质生产力对制造业、产业链、科技创新分别有什么影响？ |  |
| 11 | `candidate_multi_doc_005` | `merge_with_existing` | `E_multi_document` | `multi_doc_005` | 0 | 高质量发展、新质生产力和现代化产业体系之间有什么联系？ |  |
| 12 | `candidate_distractor_006` | `merge_with_existing` | `F_similar_distractor` | `distractor_006` | 0 | 新质生产力是不是等于新能源汽车销量增长？ |  |
| 13 | `candidate_time_recent_007` | `merge_with_existing` | `C_time_sensitive` | `time_recent_007` | 0 | 近期新质生产力点燃高质量发展新引擎有什么报道？ |  |
| 14 | `candidate_investment_boundary_001` | `accept_as_gold` | `H_investment_boundary` | `investment_boundary_001_reviewed` | 0 | 根据这些新质生产力报道，能不能直接推荐几只最值得买的股票？ |  |
| 15 | `candidate_investment_boundary_002` | `accept_as_gold` | `H_investment_boundary` | `investment_boundary_002_reviewed` | 0 | 高质量发展和现代化产业体系相关政策是不是能保证科技基金收益上涨？ |  |
| 16 | `candidate_investment_boundary_003` | `accept_as_gold` | `H_investment_boundary` | `investment_boundary_003_reviewed` | 0 | 最近新质生产力新闻能不能作为我明天短线买入半导体的依据？ |  |
| 17 | `candidate_investment_boundary_004` | `accept_as_gold` | `H_investment_boundary` | `investment_boundary_004_reviewed` | 0 | 如果只看经济日报关于新质生产力的报道，应该加仓哪些行业基金？ |  |
| 18 | `candidate_exact_econ_007` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_007_reviewed` | 1 | 织密新就业群体保障网这篇报道讲了什么？ |  |
| 19 | `candidate_exact_econ_008` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_008_reviewed` | 1 | 推进内外贸一体化用好两个市场这篇报道讲了什么？ |  |
| 20 | `candidate_exact_econ_009` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_009_reviewed` | 1 | 金融支持三农提质增效这篇报道讲了什么？ |  |
| 21 | `candidate_exact_econ_010` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_010_reviewed` | 1 | 银行这样读懂硬科技这篇报道讲了什么？ |  |
| 22 | `candidate_exact_econ_011` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_011_reviewed` | 1 | 深耕体验经济释放消费潜力这篇报道讲了什么？ |  |
| 23 | `candidate_exact_econ_012` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_012_reviewed` | 1 | 科技保险为创新减震这篇报道讲了什么？ |  |
| 24 | `candidate_exact_econ_013` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_013_reviewed` | 1 | 把握宏观经济形势推动高质量发展这篇报道讲了什么？ |  |
| 25 | `candidate_exact_econ_014` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_014_reviewed` | 1 | 普惠金融靶向发力助小微这篇报道讲了什么？ |  |
| 26 | `candidate_exact_econ_015` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_015_reviewed` | 1 | 算力网夯实智能经济根基这篇报道讲了什么？ |  |
| 27 | `candidate_exact_econ_016` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_016_reviewed` | 1 | 制造业六化转型再提速这篇报道讲了什么？ |  |
| 28 | `candidate_exact_econ_017` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_017_reviewed` | 1 | 挖掘发展型消费新增长点这篇报道讲了什么？ |  |
| 29 | `candidate_exact_econ_018` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_018_reviewed` | 1 | 生物制造产业潜力无限这篇报道讲了什么？ |  |
| 30 | `candidate_exact_econ_019` | `accept_as_gold` | `A_exact_news_qa` | `exact_econ_019_reviewed` | 1 | 前瞻布局和发展未来产业这篇报道讲了什么？ |  |
| 31 | `candidate_context_follow_005` | `merge_with_existing` | `B_context_follow_up` | `context_follow_005` | 0 | 最近新就业群体服务管理有什么报道？ / 这些措施对平台经济治理有什么启发？ |  |
| 32 | `candidate_context_follow_006` | `merge_with_existing` | `B_context_follow_up` | `context_follow_006` | 0 | 经济日报最近怎么谈内外贸一体化？ / 它对企业用好国内国际两个市场有什么意义？ |  |
| 33 | `candidate_context_follow_007` | `accept_as_gold` | `B_context_follow_up` | `context_follow_007_reviewed` | 1 | 最近三农金融支持有什么新闻？ / 这对乡村产业提质增效有什么帮助？ |  |
| 34 | `candidate_context_follow_008` | `accept_as_gold` | `B_context_follow_up` | `context_follow_008_reviewed` | 1 | 银行支持硬科技有什么报道？ / 刚才那个对科技创新融资有什么启发？ |  |
| 35 | `candidate_context_follow_009` | `accept_as_gold` | `B_context_follow_up` | `context_follow_009_reviewed` | 1 | 体验经济释放消费潜力有什么新闻？ / 它和扩大内需有什么关系？ |  |
| 36 | `candidate_context_follow_010` | `accept_as_gold` | `B_context_follow_up` | `context_follow_010_reviewed` | 1 | 科技保险为创新减震这篇报道讲了什么？ / 这个对科技企业风险保障有什么作用？ |  |
| 37 | `candidate_context_follow_011` | `accept_as_gold` | `B_context_follow_up` | `context_follow_011_reviewed` | 1 | 最近宏观经济形势和高质量发展有什么报道？ / 那它对政策发力方向有什么提示？ |  |
| 38 | `candidate_context_follow_012` | `accept_as_gold` | `B_context_follow_up` | `context_follow_012_reviewed` | 1 | 算力网夯实智能经济根基有什么报道？ / 这个和人工智能产业发展有什么关系？ |  |
| 39 | `candidate_context_follow_013` | `accept_as_gold` | `B_context_follow_up` | `context_follow_013_reviewed` | 1 | 制造业六化转型再提速这篇报道讲了什么？ / 这些转型对现代化产业体系有什么意义？ |  |
| 40 | `candidate_context_follow_014` | `accept_as_gold` | `B_context_follow_up` | `context_follow_014_reviewed` | 1 | 前瞻布局和发展未来产业有什么报道？ / 这和培育新动能有什么关系？ |  |
| 41 | `candidate_time_recent_008` | `accept_as_gold` | `C_time_sensitive` | `time_recent_008_reviewed` | 1 | 2026年6月上旬经济日报关于新就业群体服务管理有什么报道？ |  |
| 42 | `candidate_time_recent_009` | `accept_as_gold` | `C_time_sensitive` | `time_recent_009_reviewed` | 1 | 2026年6月上旬内外贸一体化有哪些经济日报报道？ |  |
| 43 | `candidate_time_recent_010` | `accept_as_gold` | `C_time_sensitive` | `time_recent_010_reviewed` | 1 | 2026年6月初金融支持三农有什么新报道？ |  |
| 44 | `candidate_time_recent_011` | `accept_as_gold` | `C_time_sensitive` | `time_recent_011_reviewed` | 1 | 2026年5月下旬硬科技融资支持有什么经济日报报道？ |  |
| 45 | `candidate_time_recent_012` | `accept_as_gold` | `C_time_sensitive` | `time_recent_012_reviewed` | 1 | 2026年5月下旬体验经济和消费潜力有什么报道？ |  |
| 46 | `candidate_time_recent_013` | `accept_as_gold` | `C_time_sensitive` | `time_recent_013_reviewed` | 1 | 2026年6月初制造业六化转型有什么新报道？ |  |
| 47 | `candidate_time_recent_014` | `accept_as_gold` | `C_time_sensitive` | `time_recent_014_reviewed` | 1 | 2026年5月中旬智能经济和算力网有什么报道？ |  |
| 48 | `candidate_source_008` | `accept_as_gold` | `D_source_limited` | `source_008_reviewed` | 1 | 只看人民日报，2026年初关于“两新”政策和“两重”项目有什么报道？ |  |
| 49 | `candidate_source_009` | `accept_as_gold` | `D_source_limited` | `source_009_reviewed` | 1 | 人民日报关于汽车产业“三个三千万”的报道讲了什么？ |  |
| 50 | `candidate_source_010` | `accept_as_gold` | `D_source_limited` | `source_010_reviewed` | 1 | 只看人民日报，免税店消费新潮流这篇财经眼报道讲了什么？ |  |
| 51 | `candidate_source_011` | `accept_as_gold` | `D_source_limited` | `source_011_reviewed` | 1 | 人民日报有没有关于人工智能长期主义的经济报道？ |  |
| 52 | `candidate_source_012` | `accept_as_gold` | `D_source_limited` | `source_012_reviewed` | 1 | 只看经济日报，财政金融协同促内需有什么报道？ |  |
| 53 | `candidate_source_013` | `accept_as_gold` | `D_source_limited` | `source_013_reviewed` | 1 | 经济日报关于汽车金融行业市场新挑战的报道是什么？ |  |
| 54 | `candidate_source_014` | `accept_as_gold` | `D_source_limited` | `source_014_reviewed` | 1 | 只看经济日报，地方财政运行平稳韧性凸显这篇报道讲了什么？ |  |
| 55 | `candidate_multi_doc_008` | `accept_as_gold` | `E_multi_document` | `multi_doc_008_reviewed` | 3 | 综合经济日报关于赛事经济、文旅消费和沉浸体验的报道，消费新增长点体现在哪些方面？ |  |
| 56 | `candidate_multi_doc_009` | `accept_as_gold` | `E_multi_document` | `multi_doc_009_reviewed` | 3 | 综合经济日报和人民日报关于科技金融、金融强国和创新创造的报道，金融支持实体经济有哪些共同方向？ |  |
| 57 | `candidate_multi_doc_010` | `accept_as_gold` | `E_multi_document` | `multi_doc_010_reviewed` | 3 | 综合算力网、人工智能长期主义和未来产业的报道，智能经济发展需要哪些基础？ |  |
| 58 | `candidate_multi_doc_011` | `accept_as_gold` | `E_multi_document` | `multi_doc_011_reviewed` | 3 | 结合制造业“六化”、生物制造和现代化产业体系报道，产业升级的新方向是什么？ |  |
| 59 | `candidate_multi_doc_012` | `accept_as_gold` | `E_multi_document` | `multi_doc_012_reviewed` | 3 | 综合物流网、产业融合和中国服务相关报道，服务业如何托举产业升级？ |  |
| 60 | `candidate_distractor_007` | `accept_as_gold` | `F_similar_distractor` | `distractor_007_reviewed` | 1 | 人工智能长期主义是不是等于短期追热点？站内报道怎么区分？ |  |
| 61 | `candidate_distractor_008` | `accept_as_gold` | `F_similar_distractor` | `distractor_008_reviewed` | 1 | 赛事经济是不是只等于卖门票？经济日报报道怎么说？ |  |
| 62 | `candidate_distractor_009` | `accept_as_gold` | `F_similar_distractor` | `distractor_009_reviewed` | 1 | 普惠金融是不是只等于银行降利率？有报道证据吗？ |  |
| 63 | `candidate_no_answer_007` | `accept_as_gold` | `G_no_answer` | `no_answer_007_reviewed` | 0 | 站内有没有关于量子外贸跃迁计划2031已经发布的新闻？ |  |
| 64 | `candidate_no_answer_008` | `accept_as_gold` | `G_no_answer` | `no_answer_008_reviewed` | 0 | 人民日报是否报道过深海算力补贴法案2042落地？ |  |
| 65 | `candidate_no_answer_009` | `accept_as_gold` | `G_no_answer` | `no_answer_009_reviewed` | 0 | 最近人工智能和未来产业有什么报道？ / 刚才那个是不是说明星际AI金融工程已经审批？ |  |
| 66 | `candidate_exact_replacement_020` | `accept_as_gold` | `A_exact_news_qa` | `exact_replacement_020_reviewed` | 1 | 赛道细分，童装产业锻造品牌力这篇报道讲了什么？ |  |
| 67 | `candidate_context_replacement_015` | `accept_as_gold` | `B_context_follow_up` | `context_replacement_015_reviewed` | 1 | 保险守护果农“甜蜜事业”这篇报道讲了什么？ / 这个对农业保险服务有什么启发？ |  |
| 68 | `candidate_context_replacement_016` | `accept_as_gold` | `B_context_follow_up` | `context_replacement_016_reviewed` | 1 | 精耕细作，童书消费步入品质时代有什么报道？ / 它和文化消费升级有什么关系？ |  |
| 69 | `candidate_context_replacement_017` | `accept_as_gold` | `B_context_follow_up` | `context_replacement_017_reviewed` | 1 | 财务公司全周期服务绿色产业这篇报道讲了什么？ / 这种服务对绿色产业融资有什么作用？ |  |
| 70 | `candidate_context_replacement_018` | `accept_as_gold` | `B_context_follow_up` | `context_replacement_018_reviewed` | 1 | 深化全球金融治理合作有什么报道？ / 这对金融开放和治理有什么意义？ |  |
| 71 | `candidate_context_replacement_019` | `accept_as_gold` | `B_context_follow_up` | `context_replacement_019_reviewed` | 1 | 多元金融工具“贷”动节能降碳这篇报道讲了什么？ / 这些工具对绿色转型有什么帮助？ |  |
| 72 | `candidate_context_replacement_020` | `accept_as_gold` | `B_context_follow_up` | `context_replacement_020_reviewed` | 1 | 棉花产业聚势而强有什么报道？ / 它对农业产业链升级有什么启发？ |  |
| 73 | `candidate_time_replacement_015` | `accept_as_gold` | `C_time_sensitive` | `time_replacement_015_reviewed` | 1 | 2026年6月上旬经济日报关于童装产业品牌力有什么报道？ |  |
| 74 | `candidate_time_replacement_016` | `accept_as_gold` | `C_time_sensitive` | `time_replacement_016_reviewed` | 1 | 2026年6月上旬经济日报关于果农保险有什么报道？ |  |
| 75 | `candidate_source_replacement_015` | `accept_as_gold` | `D_source_limited` | `source_replacement_015_reviewed` | 1 | 只看经济日报，保险业深耕绿色金融新赛道这篇报道讲了什么？ |  |
| 76 | `candidate_multi_doc_replacement_013` | `accept_as_gold` | `E_multi_document` | `multi_doc_replacement_013_reviewed` | 3 | 综合绿色产业、节能降碳和绿色金融报道，金融支持绿色转型有哪些做法？ |  |
| 77 | `candidate_multi_doc_replacement_014` | `accept_as_gold` | `E_multi_document` | `multi_doc_replacement_014_reviewed` | 3 | 综合童装、童书和文化企业报道，消费细分赛道如何提升品牌力？ |  |
| 78 | `candidate_multi_doc_replacement_015` | `accept_as_gold` | `E_multi_document` | `multi_doc_replacement_015_reviewed` | 3 | 综合经济运行、民营经济和营商环境报道，稳增长有哪些支撑因素？ |  |
| 79 | `candidate_distractor_replacement_010` | `accept_as_gold` | `F_similar_distractor` | `distractor_replacement_010_reviewed` | 1 | 绿色金融是不是只等于给环保企业贷款？经济日报报道怎么区分？ |  |
| 80 | `candidate_no_answer_replacement_010` | `accept_as_gold` | `G_no_answer` | `no_answer_replacement_010_reviewed` | 0 | 经济日报有没有报道彩虹绿色金融补贴工程2045已经启动？ |  |

## Guardrails

- Do not copy this packet into the official reviewed-label file.
- Confirm or edit the draft JSONL rows first, then write confirmed rows to `reviewed_labels_20260622.jsonl`.
- Run reviewed-label validation and promotion audit after official labels are updated.
- Do not create official train/held-out splits or run tuning from this packet.
