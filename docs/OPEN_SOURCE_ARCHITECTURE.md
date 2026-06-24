# AI 掘金头条：开源架构与实现说明

> 本项目是一个用于学习和验证 Agent 工程架构的本地优先新闻智能体项目。它不是商业资讯产品，不提供投资建议，也不包含可直接上线运营所需的数据授权、风控、审计和合规体系。

## 1. 项目定位

AI 掘金头条的目标，是把一个普通的新闻 App 改造成一个可检索、可追溯、可评测的新闻 Agent。

它主要用于学习这些工程问题：

- 如何把大模型从“直接聊天”改造成“受控 Agent”。
- 如何让模型通过工具读取站内新闻，而不是直接访问数据库。
- 如何做 RAG 召回、rerank、证据引用、回答校验和幻觉风险控制。
- 如何处理多轮追问、上下文压缩、短期记忆和证据 carry-over。
- 如何把网页工具、OCR、MCP 工具层接进同一个 Agent harness。
- 如何用测试集和指标驱动 Agent 改造，而不是只靠主观体验。

项目的核心思路是：**前端只是客户端，后端负责 Agent 编排，模型只负责语言推理，所有真实能力都通过受控工具暴露。**

## 2. 使用边界

### 适合用途

- 个人本地学习 Agent / RAG / MCP / OCR 工程。
- 学习如何拆分 harness、tools、memory、retrieval、validation。
- 作为新闻类 Agent 的实验模板。
- 作为本地评测、回归测试、架构演进练习项目。

### 不适合用途

- 直接部署成生产级资讯 App。
- 直接用于金融交易、股票预测或投资建议。
- 批量采集、转载、再分发未经授权的新闻全文。
- 把站外低可信度信息当作事实来源。
- 把模型回答当作权威事实结论。

## 3. 本地优先 / 纯客户端学习模式

这里的“纯客户端/学习使用”不是指所有逻辑都放在浏览器里，而是指：

- 不依赖托管云服务才能理解项目结构。
- 前端不保存任何模型 API key、数据库密码或搜索服务密钥。
- 运行者可以在本地启动前端、FastAPI 后端、MySQL、Redis、Qdrant、Ollama。
- 模型服务、embedding、reranker、OCR provider 都通过配置切换。
- `.env` 只存在于本机，不进入 Git 仓库。
- 仓库只保留源码、测试、schema、模板和说明文档。

前端是纯客户端 UI，默认只请求本机后端：

```text
Vue/Vite 客户端
  -> FastAPI 后端
      -> Agent Harness
          -> MCP 工具 / RAG / OCR / 数据库
          -> OpenAI-compatible LLM / Embedding / Reranker
```

## 4. 总体架构

```text
┌────────────────────────────┐
│ Vue3 + Vant 前端客户端      │
│ - 新闻浏览                  │
│ - 登录/收藏/历史            │
│ - AI 问答界面               │
└──────────────┬─────────────┘
               │ HTTP / SSE
┌──────────────▼─────────────┐
│ FastAPI 后端                │
│ - 用户/新闻业务 API         │
│ - AI chat API               │
│ - 会话与工具调用落库        │
└──────────────┬─────────────┘
               │
┌──────────────▼─────────────┐
│ Agent Harness               │
│ - 意图路由                  │
│ - 工具规划                  │
│ - 上下文管理                │
│ - 证据 carry-over           │
│ - 回答契约与校验            │
│ - SSE 流式输出              │
└───────┬───────────┬────────┘
        │           │
        │           │
┌───────▼──────┐ ┌──▼─────────────────┐
│ MCP 工具层   │ │ RAG / Evidence 层    │
│ - 业务工具   │ │ - Qdrant 向量召回    │
│ - Web 工具   │ │ - hybrid ranking     │
│ - OCR 工具   │ │ - reranker 精排       │
│ - 安全抓取   │ │ - evidence resolver  │
└───────┬──────┘ └──┬─────────────────┘
        │           │
┌───────▼───────────▼────────┐
│ MySQL / Redis / Qdrant      │
│ - 业务数据                  │
│ - 会话与工具调用记录        │
│ - 向量索引与证据 payload    │
└────────────────────────────┘
```

## 5. 代码目录说明

```text
apps/frontend/       Vue3 + Vant 前端客户端
cache/               Redis 缓存 helper 源码
config/              数据库、缓存、模型、向量库配置
crud/                业务数据访问层
data/                示例数据模板，不包含真实大规模语料
docs/                架构、设计和开源说明
eval/                RAG / Agent 评测脚本与 gold 测试集
evals/               评测辅助逻辑
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

## 6. Agent Harness 实现思路

Agent 不直接等于模型。项目里更重要的是 harness。

Harness 的职责：

- 接收用户输入和会话历史。
- 判断用户意图，例如新闻问答、推荐、联网研究、普通闲聊。
- 根据意图选择允许使用的工具集合。
- 管理短期上下文、会话摘要和已确认新闻锚点。
- 在追问时携带上一轮证据，让“它是什么意思”“继续分析”这类问题不丢上下文。
- 决定什么时候直接回答、什么时候召回新闻、什么时候让用户确认候选。
- 把工具结果整理成 evidence pack，再交给模型生成。
- 对模型回答做格式、引用、证据一致性检查。
- 将最终回答、引用证据和工具轨迹落库。

模型在这个架构里不直接访问数据库、不直接执行 SQL、不直接决定任意外部请求。它只看到 harness 暴露的工具 schema 和被整理过的证据。

## 7. 单 Agent 角色拆分

当前项目不是多进程多 Agent 框架，而是**单 Agent 内部角色拆分**：

- Intent Router：判断用户请求类型。
- Anchor Resolver：处理模糊新闻锚点，例如“我记得某年某月某报社发过一篇关于某主题的新闻”。
- Retrieval Planner：决定站内检索、追问改写和 carry-over。
- Memory Ledger：记录用户确认过的主题、约束和新闻锚点。
- Tool Executor：统一执行 MCP 工具。
- Evidence Reviewer：判断站内证据、站外线索、OCR 线索的可信状态。
- Answer Composer：让 LLM 基于 evidence pack 生成答案。
- Validator：检查引用、证据使用、拒答策略和幻觉风险。

这样做的好处是：不用一开始就引入复杂多 Agent 框架，也能把职责边界讲清楚，便于测试。

## 8. RAG 检索策略

站内新闻优先走 RAG：

1. 用户问题进入 intent/router。
2. 根据时间、来源、主题和上下文生成检索 query。
3. embedding 模型生成 query 向量。
4. Qdrant 召回候选 chunk。
5. hybrid ranking 结合向量分、关键词、时间、来源等信号。
6. reranker 对候选进行精排。
7. chunk 聚合回父级新闻。
8. top evidence 进入回答上下文。
9. 模型必须基于 evidence 回答，并带引用。

对模糊问题，系统倾向于先给候选确认，而不是过度自信回答。例如：

> “我记得 2024 年某月某报社发过一篇关于新质生产力的新闻。”

系统应该先找出可能匹配的新闻候选，并让用户确认是哪一篇，再继续解释或分析。

## 9. 多轮上下文与记忆

项目实现了面向新闻问答的短期记忆和长上下文压缩思路：

- recent turns：保留最近若干轮对话。
- session summary：当上下文变长时压缩历史摘要。
- topic ledger：记录用户持续讨论的主题。
- anchor ledger：记录用户确认过的新闻锚点。
- evidence carry-over：追问时携带上一轮证据 ID。
- memory-only fast path：当用户只问“最开始聊了什么”时，可以从 ledger 回答，不触发 RAG 和 LLM。

需要注意：记忆不是事实证据。新闻事实仍必须来自站内 RAG、明确的站外来源或用户确认过的候选。

## 10. 站外工具与 OCR

站外信息不是默认事实来源，而是低信任线索。

设计原则：

- 站内能检索到，优先站内。
- 站内没有，再考虑 Web/OCR 工具层。
- 站外网页抓取必须经过 safe HTTP 防护。
- 如果网页无法直接解析，可通过截图 + OCR 获取文本。
- OCR 结果必须去噪、打来源标签、记录可信度。
- 低可信度内容可以作为候选线索，但生成时必须提示用户“来源可信度较低”。
- 站外新闻最好与站内新闻或可信来源做对照后再进入高置信回答。

当前 OCR provider 抽象：

- PaddleOCRProvider：本地 CPU/GPU OCR provider，适合作为默认实现。
- UnlimitedOCRProvider：预留高级 GPU/VLM OCR provider。

MCP web 工具层会复用 provider 实例，避免每次 OCR 调用都重新加载重模型。

## 11. 回答契约与拒答策略

新闻 Agent 的回答不能只追求“像人说话”，还要满足证据边界：

- 有新闻事实主张时，应给出引用。
- 没有证据时，应拒绝确定性回答，并提示如何补充信息。
- 对低可信度站外/OCR线索，应明确标注来源和可信度。
- 对股票涨跌、投资建议、确定性预测，应降级为“政策/信息影响解释”，避免给出买卖建议。
- 对用户模糊请求，应优先澄清或给候选，而不是编造。

项目里的评测指标包括：

- Recall@5：正确证据是否进入前 5 个候选。
- MRR：正确证据排得是否靠前。
- EvidenceRecall@5：回答使用的证据是否覆盖 gold evidence。
- ValidationPassRate：回答是否通过契约校验。
- HallucinationRisk：是否出现无证据支撑或过度推断。
- RouteAccuracy：是否走了正确路线，例如候选确认、站内检索、拒答或工具调用。

## 12. MCP 工具边界

工具层通过 MCP server 暴露，harness 通过 MCP client 调用。

主要工具类型：

- 业务工具：新闻列表、新闻详情、收藏、历史、推荐等。
- RAG 工具：站内语义检索和 evidence detail。
- Web 工具：安全 URL 抓取、联网搜索降级提示、网页截图 OCR。
- OCR 工具：图片文本抽取和低信任 evidence staging。

这种设计把模型和真实系统隔开：

- 模型不能随意读数据库。
- 模型不能自己拼 SQL。
- 模型不能绕过 safe HTTP 访问内网。
- 工具参数由 registry 校验。
- 每轮工具调用有数量和超时上限。

## 13. 数据与合规边界

公开仓库不应包含：

- `.env` 或任何真实 API key。
- 数据库账号密码。
- 商业 API token。
- 私钥、证书、cookie、session。
- 原始新闻全文大规模语料。
- 数据库 dump。
- Qdrant dump。
- 本地日志、测试报告、截图、OCR 工作目录。

仓库只保留：

- 源码。
- 配置模板。
- 示例数据模板。
- schema。
- 单元测试。
- 小型 gold 测试集。
- 架构和实现文档。

## 14. 本地运行方式概览

后端：

```bash
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8030
```

前端：

```bash
cd apps/frontend
npm install
copy .env.example .env
npm run dev
```

可选依赖：

- MySQL：业务数据。
- Redis：缓存。
- Qdrant：向量检索。
- Ollama：本地 LLM / embedding。
- PaddleOCR：网页截图 OCR。

## 15. 测试与验证

推荐在公开前至少运行：

```bash
python scripts/security_secret_scan.py
python -m pytest -q
```

本项目倾向于用测试约束 Agent 行为，包括：

- 工具 schema 不泄露内部参数。
- RAG carry-over 行为正确。
- 模糊新闻锚点走候选确认。
- 记忆 fast path 不误触发工具和 LLM。
- OCR 线索按低可信 evidence 处理。
- safe HTTP 防护不被绕过。
- 回答契约和引用校验稳定。

## 16. 开源说明

建议开源时保持以下声明：

- 本项目仅用于学习和研究 Agent 工程。
- 默认本地运行，不附带真实新闻数据和真实密钥。
- 用户自行负责数据来源授权和 API 使用成本。
- 输出内容不构成投资建议。
- 站外/OCR内容只作为低信任线索，不能直接当作事实。
- 如果用于生产，需要补充鉴权、审计、限流、合规、版权和数据治理。

## 17. 后续演进方向

可以继续优化：

- 更稳的 anchor resolver。
- 更完整的低可信站外来源交叉验证。
- OCR 去噪和版面结构恢复。
- 更细的 source credibility policy。
- 长上下文第 100 轮记忆评测。
- 更系统的 RAG dataset registry。
- 多 Agent 框架或任务队列化工具执行。
- 前端 citation detail 与证据确认交互。
- 本地一键启动脚本和 Docker Compose。
