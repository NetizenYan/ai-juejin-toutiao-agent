# Agent 架构说明

本文件描述 `ai-juejin-toutiao-agent` 的 Agent 运行时架构，内容均来自当前仓库代码（`harness/`、`mcp_servers/`、`routers/`、`config/`）。代码中尚未实现的能力会显式标注【设计中】或【待确认】，不臆造。

> 配套阅读：[OPEN_SOURCE_ARCHITECTURE](OPEN_SOURCE_ARCHITECTURE.md)、[上下文记忆设计](context_manager_memory_v1_2026_06_21.md)、[Answer Contract 校验](answer_contract_validation_2026_06_21.md)、[父子 RAG 索引](parent_child_rag_index.md)、[数据源风险门控](data_source_risk_gate_2026_06_21.md)。

## 1. Agent 总体架构

本项目是一个**单 Agent（single-agent）harness**，而非多 Agent 协作系统。模型只负责语言推理；检索、数据库访问、联网、OCR 与证据校验全部由后端受控代码完成。harness 在一个进程内把 Agent 的内部职责显式拆分为若干"角色（role）"，由 `harness/agent_orchestrator.py` 做确定性的角色规划，这样后续若要把某个角色替换为独立/委派实现（多 Agent 化），可以逐个替换而不破坏对用户的契约。

```text
Vue3 + Vant 前端
  -> FastAPI 路由 (routers/ai.py, SSE)
      -> Agent Harness (harness/agent.py)
          ├─ QueryUnderstanding   意图与锚点需求识别
          ├─ MemoryLedger         上下文/锚点/主题记忆装配
          ├─ AnchorResolver       模糊新闻锚点解析与候选确认
          ├─ Tool Layer           工具白名单校验 + MCP 执行
          ├─ EvidenceVerifier     站外证据与站内交叉核验
          ├─ AnswerPlanner        决定下一步动作（追问 / 取证 / 生成）
          └─ AnswerValidator      回答契约校验（引用 / 拒答 / 风险）
      -> MCP servers (business / rag / web)
      -> LLM / embedding / reranker providers
      -> MySQL / Redis / Qdrant
```

核心铁律（见 `harness/agent.py` 模块 docstring）：

- 模型只看到**最小化工具投影**（`list_tool_defs()` 给出的 OpenAI tools 描述）。
- 工具执行**只走 MCP**，模型不接触 DB 凭据 / ORM / SQL。
- `general_chat` 意图不放行任何涉库 / 隐私工具。

## 2. 角色与模块职责

下列角色为代码中**实际存在**的命名（`harness/agent_orchestrator.py` 中的 `AgentRoleStep.role`）与对应实现模块。

| 角色 / 模块 | 代码位置 | 职责 |
| --- | --- | --- |
| Harness 编排核心 | `harness/agent.py` | 串联整个闭环：意图路由 → 工具放行 → 模型规划 tool_calls → 校验 → MCP 执行 → 证据注入 → 流式生成 → 回答校验 |
| Orchestrator（角色规划） | `harness/agent_orchestrator.py` | 确定性地产出 `AgentOrchestrationPlan`：角色步骤、`next_action`、是否中断追问 |
| QueryUnderstanding | `harness/query_understanding.py`, `harness/intent.py`, `harness/query_intent.py` | 意图分类（news / recommend / web / general_chat 等）、是否需要锚点确认、投资边界关键词识别 |
| MemoryLedger（上下文记忆） | `harness/context_manager.py` | 短期会话形态、展示约束（字数 / 要点上限）、最近 evidence id、主题 ledger、新闻锚点 ledger；**记忆默认不充当事实证据** |
| AnchorResolver | `harness/anchor_resolver.py`, `harness/evidence_detail_resolver.py` | 模糊 B 类追问的新闻锚点解析：产出候选与检索线索，要求用户确认，而不替用户判定事实 |
| Tool Layer | `harness/tool_registry.py`, `harness/mcp_client.py`, `harness/rag_mcp_client.py`, `harness/web_mcp_client.py` | 工具白名单与参数校验（Pydantic, `extra="forbid"`、限额）+ 经 MCP stdio session 调用业务/RAG/Web 工具 |
| RAG 检索 | `harness/rag_search.py`, `harness/rag_search_v2.py`, `harness/rag_ranking.py`, `harness/rag_index.py`, `harness/rag_query_router.py`, `harness/reranker.py`, `harness/reranker_api.py`, `harness/chunking.py` | 站内 embedding 召回、hybrid ranking、reranker 精排、父子分块、外部文档入库 |
| EvidenceVerifier | `harness/external_evidence.py` | 站外证据（web/OCR）与站内新闻交叉核验，标注 `station_matched` / `unverified` / `low_signal` / `conflict` |
| Web / OCR 工具 | `harness/web_capture.py`, `harness/ocr_providers.py`, `harness/safe_http_client.py` | 受控网页抓取、截图 OCR（`PaddleOCRProvider`，`UnlimitedOCRProvider` 为预留）、SSRF 安全的 HTTP 客户端 |
| AnswerPlanner | `harness/agent_orchestrator.py` (`_next_action`) | 依据锚点状态与工具结果决定：追问确认 / 请求外部取证 / 运行工具层 / 直接生成 |
| AnswerValidator（回答契约） | `harness/answer_contract.py`, `harness/answer_validator.py` | 校验引用格式 `[news:ID]`、evidence-only、拒答策略、低可信提示、投资确定性措辞风险；支持 `off / shadow / enforce` 三种模式 |
| LLM 客户端 | `harness/llm_client.py` | 屏蔽供应商差异，仅输出最终 content，thinking/reasoning 字段不外泄 |
| MCP servers | `mcp_servers/business_server.py`, `mcp_servers/rag_server.py`, `mcp_servers/web_server.py` | 业务数据、RAG 证据、Web/OCR 的工具边界进程 |

> 关于 Planner / Executor / Memory / Review / Publish 的对应关系：本仓库中
> - **Planner** = `AnswerPlanner` + Orchestrator（角色规划），确定性而非由模型自由规划。
> - **Executor / Tool** = Tool Layer（`tool_registry` + 各 `*_mcp_client` + MCP servers）。
> - **Memory** = `MemoryLedger` / `context_manager`。
> - **Review** = `EvidenceVerifier` + `AnswerValidator`。
> - **Publish**：【待确认 / 未实现】当前仓库定位为新闻问答闭环，回答经 SSE 输出并落库（`crud/ai_agent`），**没有**面向掘金/头条的对外自动发布模块。如需发布编排，属于后续扩展点。

## 3. 数据流

```text
用户输入
  -> 意图识别 (QueryUnderstanding)
  -> 上下文/记忆装配 (MemoryLedger)
  -> 站内 RAG 检索 或 锚点候选确认 (AnchorResolver)
  -> 必要时调用 Web/OCR 工具，并做站内外交叉核验 (EvidenceVerifier)
  -> 形成 evidence pack（带 news:ID 引用）
  -> LLM 流式生成
  -> 回答契约校验 (AnswerValidator)
  -> SSE 输出并落库 (crud/ai_agent)
```

系统倾向"**先确认，再回答**"：当用户表达模糊（"我记得某年某报社发过一篇关于某主题的新闻"）时，`AnchorResolver` 优先返回候选让用户确认，而不是直接给出可能编造的答案。

## 4. 调用链路

1. `routers/ai.py` 接收请求，建立 SSE 流。
2. `harness/agent.py` 调 `detect_intent()` 做意图路由，按意图决定放行的工具集合（`allowed_tools`）。
3. `build_agent_orchestration_plan()` 产出角色计划与 `next_action`。
4. 若需工具：模型基于最小化工具投影规划 `tool_calls`；不稳定时走 `build_fallback_tool_calls()` 确定性兜底。
5. `validate_tool_arguments()` 校验工具名/参数/限额；通过后经 `business_session()` / `rag_session()` / `web_session()` 调用 MCP 工具。
6. 工具结果作为证据注入；`verify_external_evidence()` 标注站外证据可信状态。
7. `LLMClient` 流式生成最终答案；`validate_answer()` 按契约模式校验后输出并落库。

## 5. 配置方式

- 配置集中在 `config/`：`ai_conf.py`（模型 client / API_KEY / BASE_URL / MODEL、web/juhe key、校验模式）、`db_conf.py`（MySQL）、`cache_conf.py`（Redis）、`config/`（Qdrant/向量库）。
- 全部通过环境变量读取，`.env.example` 仅含占位模板，真实 `.env` 不入库。
- 关键开关示例：`LLM_API_KEY` / `EMBEDDING_API_KEY`（默认 `ollama` 本地）、`RERANKER_API_KEY`、`WEB_SEARCH_API_KEY`（缺省时联网工具优雅降级）、回答校验的 `enforce_routes` 与 `validation_mode`（`off/shadow/enforce`）。
- LLM 供应商可切换（Ollama 本地 / DeepSeek / SiliconFlow），见 `docs/adr/ADR-20260621-deepseek-provider.md`、`docs/SILICONFLOW_MODEL_STACK_20260623.md`。

## 6. 错误处理

- 工具违规：`ToolPolicyError`（未知工具 / 非法参数 / 越限）在执行前拦截，不会把非法调用送进 MCP。
- 模型规划不稳：意图层提供 `build_fallback_tool_calls()` 确定性兜底，避免空转或乱调工具。
- 联网工具未配置：`mcp_servers/web_server.py` 在缺 `WEB_SEARCH_API_KEY` 时**优雅降级**返回提示而非报错。
- 回答风险：`AnswerValidator` 在 `shadow` 模式下只标注、`enforce` 模式下可拦截不合契约的回答（缺引用、非证据措辞、投资确定性措辞等）。
- 全局异常：`utils/exception_handlers.register_exception_handlers(app)` 统一注册。
- 站外低可信来源：默认进入候选但回答需提示可信度低，并尽量与站内交叉验证。

## 7. 可扩展点

- **Publish / 发布编排**【设计中】：当前无对外发布模块，可在工具层之后追加受控发布角色。
- **多 Agent 化**：Orchestrator 已把角色显式化，可将单个角色替换为独立 Agent 或委派实现。
- **OCR provider**：`UnlimitedOCRProvider` 为高级 GPU/VLM OCR 预留位。
- **向量库迁移**：`docs/refactor_pg_qdrant_plan.md` 规划 PG + Qdrant 元数据同步。
- **新工具接入**：在对应 MCP server 注册工具 + 在 `tool_registry.py` 增加参数模型与放行规则即可。

## 8. 当前限制

- 仅为**单 Agent 学习项目**，非生产系统；不提供投资建议。
- 不内置真实 API key、不附带大规模新闻语料或数据库 dump。
- `AnswerValidator` 只能捕捉明显的引用/硬约束/风险措辞问题，**不能证明回答完全无幻觉**。
- 记忆 v1 保守设计：只保留会话形态与最近 evidence id，**不把历史对话变成事实证据**。
- 对外**自动发布**能力【未实现】。
- 生产化所需的数据授权、内容合规、限流、审计、风控、隐私保护需自行补充。
