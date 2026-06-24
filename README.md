# AI 掘金头条

本地优先的新闻 Agent 学习项目：用 FastAPI、Vue、MCP、RAG、Qdrant、Ollama 和 OCR，构建一个可检索、可追溯、可评测的单 Agent 新闻问答系统。

> 项目用于学习 Agent 工程架构，不提供投资建议，不内置真实 API key，不附带大规模新闻语料或数据库 dump。

## 项目亮点

- **单 Agent 架构**：在一个 harness 内拆分 intent router、memory ledger、anchor resolver、tool executor、evidence reviewer、validator 等角色。
- **站内 RAG 优先**：用户问题先走站内新闻检索，embedding 召回、hybrid ranking、reranker 精排，再把 evidence pack 交给模型生成。
- **多轮上下文记忆**：支持短期记忆、会话摘要、主题 ledger、新闻锚点 ledger 和 evidence carry-over。
- **模糊新闻确认**：用户只记得大概时间、媒体或主题时，系统优先返回候选让用户确认，避免过度自信回答。
- **MCP 工具边界**：模型不能直接访问数据库或外网，只能通过受控 MCP 工具读取业务数据、RAG 证据和 Web/OCR 线索。
- **网页截图 OCR**：支持将站外网页截图识别为低可信线索，再与站内新闻做对照。
- **证据与回答校验**：回答需要遵循引用、拒答、低可信来源提示和幻觉风险控制。
- **测试驱动演进**：保留 Agent 合约测试、RAG 评测、上下文记忆测试和安全基线扫描。

## 架构文档

建议先读完整设计说明：

- [开源架构与实现说明](docs/OPEN_SOURCE_ARCHITECTURE.md)
- [项目概述](docs/项目概述.md)
- [父子 RAG 索引设计](docs/parent_child_rag_index.md)
- [上下文记忆设计](docs/context_manager_memory_v1_2026_06_21.md)
- [数据源风险门控](docs/data_source_risk_gate_2026_06_21.md)

## 总体架构

```text
Vue3 + Vant client
  -> FastAPI API / SSE
      -> Agent Harness
          -> MCP business tools
          -> MCP RAG tools
          -> guarded Web / OCR tools
          -> LLM / embedding / reranker providers
      -> MySQL / Redis / Qdrant
```

模型只负责语言推理。数据库、检索、联网、OCR 和证据校验都由后端受控工具完成。

## 目录结构

```text
apps/frontend/       Vue3 + Vant 前端客户端
cache/               Redis 缓存 helper
config/              数据库、缓存、模型、向量库配置
crud/                业务数据访问层
data/                示例数据模板
docs/                架构和设计文档
eval/                RAG / Agent 评测脚本与 gold 测试集
harness/             Agent 核心编排层
mcp_servers/         业务、RAG、Web/OCR MCP server
models/              SQLAlchemy ORM 模型
routers/             FastAPI 路由
schemas/             Pydantic schema
scripts/             索引、评测、审计、迁移辅助脚本
sql/                 数据库 schema
tests/               单元测试和 Agent 合约测试
utils/               鉴权、安全、通用工具
```

## 快速开始

### 1. 后端

```bash
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8030
```

健康检查：

```bash
curl http://127.0.0.1:8030/
```

API 文档：

```text
http://127.0.0.1:8030/docs
```

### 2. 前端

```bash
cd apps/frontend
npm install
copy .env.example .env
npm run dev
```

默认前端地址：

```text
http://localhost:5173
```

### 3. 可选本地服务

- MySQL：业务新闻、用户、收藏、历史、AI 会话记录。
- Redis：业务缓存。
- Qdrant：RAG 向量检索。
- Ollama：本地 LLM / embedding provider。
- PaddleOCR：本地 OCR provider。

`.env.example` 只提供模板。真实 `.env`、API key、数据库密码和本地日志不要提交到 Git。

## Agent 工作流

```text
用户输入
  -> 意图识别
  -> 上下文/记忆整理
  -> 站内 RAG 检索或候选确认
  -> 必要时调用 Web/OCR 工具
  -> evidence pack
  -> LLM 生成
  -> 回答契约校验
  -> SSE 输出并落库
```

系统倾向于“先确认，再回答”。当用户表达模糊时，例如“我记得某年某报社发过一篇关于某主题的新闻”，Agent 会尽量检索候选并让用户确认，而不是直接编造答案。

## OCR 与站外线索

站外内容默认是低可信线索：

- 站内能检索到，优先站内。
- 站内没有，再使用 Web/OCR 工具。
- OCR 文本需要去噪和来源标注。
- 低可信来源可以进入候选，但回答时必须提醒用户可信度较低。
- 站外线索最好与站内新闻或可信来源交叉验证。

当前 provider 抽象：

- `PaddleOCRProvider`：默认本地 OCR provider。
- `UnlimitedOCRProvider`：预留给未来高级 GPU/VLM OCR provider。

## 测试

```bash
python scripts/security_secret_scan.py
python -m pytest -q
```

当前清理后的本地验证结果：

```text
Secret hygiene check passed.
328 passed, 1 skipped
```

## 安全与开源边界

公开仓库不应包含：

- `.env` 或真实密钥。
- 数据库账号密码。
- 商业 API token。
- 私钥、证书、cookie、session。
- 原始新闻全文大规模语料。
- 数据库 dump 或 Qdrant dump。
- 本地日志、测试报告、截图、OCR 工作目录。

本项目已经把这些内容加入 `.gitignore`，并提供 `scripts/security_secret_scan.py` 做发布前检查。

## GitHub About 建议

Repository description:

```text
本地优先的新闻 Agent 学习项目：FastAPI + Vue + MCP + RAG + OCR，演示可检索、可追溯、可评测的单 Agent 架构。
```

Topics:

```text
agent, rag, mcp, fastapi, vue, qdrant, ollama, ocr, paddleocr, llm, news-agent, learning-project
```

## 项目声明

本项目仅用于 Agent 工程学习与研究。输出内容不构成投资建议。若用于真实产品，需要自行补充数据授权、内容合规、限流、审计、风控、隐私保护和生产级安全治理。

## License

MIT License. See [LICENSE](LICENSE).
