# 工程与 Agent 流程提升点

本文件总结 `ai-juejin-toutiao-agent` 相比"普通脚本 / 手工内容流程"的提升。所有结论均基于当前仓库的代码结构（`harness/`、`mcp_servers/`、`tests/`、`eval/`、`scripts/`），不使用未经测量的百分比指标。需要真实数据支撑的项统一归入第 6 节"仍待补充的指标"。

> 配套阅读：[agent-architecture](agent-architecture.md)、[OPEN_SOURCE_ARCHITECTURE](OPEN_SOURCE_ARCHITECTURE.md)。

## 1. 相比普通脚本 / 手工内容发布流程的提升

普通做法通常是：一段脚本直接拼 prompt 调模型，或人工检索后手工整理。本项目相比之下：

- **检索可追溯**：回答必须带 `[news:ID]` 引用，证据来自站内 RAG / 受控工具，而非模型"凭记忆"作答。
- **先确认再回答**：模糊问题先由 `AnchorResolver` 给候选让用户确认，降低自信幻觉。
- **工具边界清晰**：模型不直接碰 DB / 外网，只能经 MCP 受控工具，避免脚本式"模型直连数据库"的风险。
- **站外内容降级**：Web/OCR 线索默认低可信，需与站内交叉核验（`EvidenceVerifier`），而非直接采信。
- **可评测**：`eval/` 下有 RAG / Agent gold 测试集与评测脚本，效果变化可回归，而非靠人工主观判断。

## 2. 工程结构提升

- **分层清晰**：`harness/`（Agent 编排）、`mcp_servers/`（工具边界进程）、`routers/` + `crud/` + `models/`（Web/数据访问）、`config/`（配置集中）、`eval/` + `tests/`（评测与测试）边界分明。
- **配置与密钥分离**：全部走环境变量，`.env.example` 只含占位，`scripts/security_secret_scan.py` 做发布前密钥扫描。
- **供应商可切换**：`llm_client` + `config/ai_conf.py` 屏蔽 LLM/embedding/reranker 供应商差异，可在 Ollama 本地与云端 provider 间切换（见 ADR 文档）。
- **安全 HTTP**：`safe_http_client.py` 处理对外抓取，降低 SSRF 类风险。

## 3. Agent 流程提升

- **角色显式化**：`agent_orchestrator.py` 把单 Agent 的内部职责拆成 QueryUnderstanding / MemoryLedger / AnchorResolver / EvidenceVerifier / AnswerPlanner 等显式角色，调度链路完整、可逐角色替换。
- **确定性兜底**：意图与工具规划在模型不稳时有 `build_fallback_tool_calls()` 确定性 fallback，链路不至于空转。
- **记忆受控**：`context_manager` 区分"会话形态/约束记忆"与"事实证据"，避免把历史对话当事实。
- **意图驱动放行**：不同意图放行不同工具集合，`general_chat` 不放行涉库/隐私工具。

## 4. 质量控制提升

- **回答契约校验**：`answer_contract.py` + `answer_validator.py` 校验引用、evidence-only、拒答策略、低可信提示、投资确定性措辞风险；支持 `off / shadow / enforce` 渐进式启用。
- **工具参数硬校验**：`tool_registry.py` 用 Pydantic（`extra="forbid"` + 限额）拦截非法工具调用。
- **证据交叉核验**：站外证据标注 `station_matched / unverified / low_signal / conflict`。
- **测试驱动**：`tests/` 含 Agent 合约测试、上下文记忆测试、安全基线测试；README 记录的本地验证为 `328 passed, 1 skipped`、`Secret hygiene check passed`（以实际运行为准）。

## 5. 可维护性提升

- **职责单一的模块**：harness 每个文件聚焦一个角色/能力，便于定位与替换。
- **可回归的评测集**：`eval/gold/` 提供 gold 数据与 split，改动后能跑评测对比。
- **审计/迁移脚本化**：`scripts/` 下的标签提升、回滚、索引重建、PG/Qdrant 同步等都有确定性确认 token（如 `COPY_REVIEWED_LABELS_*` / `ROLLBACK_*`）保护，降低误操作。
- **文档沉淀**：`docs/` + `docs/adr/` 记录架构决策与设计演进，新成员可顺链路理解系统。

## 6. 仍待补充的指标

以下需要真实运行数据，当前**未测量**，不写成具体百分比：

- RAG 检索质量：recall@k、命中率、reranker 前后对比。
- 回答质量：引用正确率、拒答恰当率、幻觉率（人工或自动评测）。
- 端到端延迟：意图 / 检索 / 生成各阶段耗时分布。
- 工具调用成功率与 fallback 触发频率。
- `enforce` 模式下回答拦截率与误拦率。
- 站外证据交叉核验的命中分布（`station_matched` 等占比）。

> 这些指标依赖运行环境与真实语料，应在配置好本地服务（MySQL/Redis/Qdrant/Ollama）并跑通 `eval/` 后补充。
