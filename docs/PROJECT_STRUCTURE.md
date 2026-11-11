# 项目目录结构

仓库分成三块，各管各的：

| 目录 | 内容 |
|---|---|
| `frontend/` | Vue3 + Vant 前端 |
| `backend/` | 新闻站的 Web 后端（FastAPI），以及新闻数据、数据库 schema、数据导入脚本 |
| `agent/` | Agent 的代码：编排层、MCP server、模型与检索配置、评测 |

所有 Python 命令都在仓库根目录执行，包名从根目录算起（`backend.app.…`、`agent.…`）。

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030   # 启动后端
python -m pytest backend/tests agent/tests -q                         # 跑测试
python -m agent.eval.drift_eval run --help                             # Agent 评测
```

## backend/

按 FastAPI 常见的分层组织，上层只调用下层：

```text
backend/
  app/
    main.py            应用入口：创建 app、注册异常处理、CORS、挂载路由
    api/
      router.py        汇总全部路由
      deps.py          依赖注入：当前登录用户
      routes/          news、users、favorite、history、ai
    services/          业务服务：带缓存的新闻查询（先读缓存，未命中再查库并回填）
    crud/              数据访问：每张表的增删改查
    cache/             新闻缓存的键和读写
    models/            SQLAlchemy ORM 模型
    schemas/           Pydantic 请求/响应模型
    db/                数据库引擎与会话（get_db）
    core/              应用配置、环境变量加载、Redis 连接、密码加密、统一响应与异常
  data/                新闻数据
    raw/               原始数据（不入库，体积大）
    processed/         由脚本加工出的语料（可重建，不入库）
    policy_macro_manual_samples/   示例数据模板
  sql/                 MySQL / PostgreSQL schema 与初始化数据
  scripts/             数据导入、语料构建、数据集画像、密钥扫描
  tests/               接口与数据层测试
```

调用方向：`api/routes` → `services` → `crud` / `cache` → `db` / `models`。

以后新增的数据放到 `backend/data/` 下；新增的表在 `backend/sql/` 加 schema，在 `models/`、`schemas/`、`crud/` 各加一个文件，路由放 `api/routes/` 并在 `api/router.py` 里挂上。

## agent/

```text
agent/
  harness/             Agent 核心：意图、记忆、锚点、工具调用、证据、回答校验、规则类请求处理
  mcp_servers/         业务、RAG、Web/OCR 三个 MCP server（由 harness 以子进程启动）
  config/              模型、检索、向量库配置（ai_conf.py、vector_conf.py、rag_meta.json）
  eval/                评测脚本、gold 测试集、评委工具（eval/judge/）
  evals/               早期的问答评测集与检索评测
  scripts/             索引构建、评测运行、gold 标注流程
  tests/               单元测试与 Agent 合约测试
```

## 两边怎么衔接

依赖只有两个方向，各自只经过几处入口：

| 方向 | 入口 | 用途 |
|---|---|---|
| backend → agent | `backend/app/api/routes/ai.py` | 聊天接口调用 `agent.harness.agent.run_chat`，并用到意图识别、长期记忆提取、证据详情解析 |
| backend → agent | `backend/app/schemas/ai.py` | 读取 Agent 配置里的消息长度上限 |
| backend → agent | `backend/app/main.py` | 应用关闭时回收 MCP 子进程 |
| agent → backend | `backend.app.db.session` | 数据库会话 |
| agent → backend | `backend.app.models`、`backend.app.crud` | 读新闻、站外资讯，读写对话记录和浏览历史 |
| agent → backend | `backend.app.core.env` | 加载环境变量文件 |

Agent 不依赖后端的路由层；后端除聊天相关的几个文件外不依赖 Agent。

## 旧路径对照

2026-11-11 之前，所有目录平铺在仓库根目录。`docs/` 里带日期的报告和计划仍按当时的路径书写，对照如下：

| 旧路径 | 新路径 |
|---|---|
| `main.py` | `backend/app/main.py` |
| `routers/` | `backend/app/api/routes/` |
| `crud/` | `backend/app/crud/`（`crud/news_cache.py` → `backend/app/services/news_service.py`） |
| `models/`、`schemas/` | `backend/app/models/`、`backend/app/schemas/` |
| `utils/` | `backend/app/core/`（`utils/auth.py` → `backend/app/api/deps.py`） |
| `cache/` | `backend/app/cache/` |
| `config/db_conf.py` | `backend/app/db/session.py` |
| `config/cache_conf.py` | `backend/app/core/cache.py` |
| `config/env_loader.py` | `backend/app/core/env.py` |
| `config/ai_conf.py`、`config/vector_conf.py`、`config/rag_meta.json` | `agent/config/` |
| `sql/`、`scripts/ai_tables.sql` | `backend/sql/` |
| `data/` | `backend/data/` |
| `harness/`、`mcp_servers/` | `agent/harness/`、`agent/mcp_servers/` |
| `eval/`、`evals/` | `agent/eval/`、`agent/evals/` |
| `scripts/` | 数据类在 `backend/scripts/`，索引、评测、标注类在 `agent/scripts/` |
| `tests/` | 后端的在 `backend/tests/`，其余在 `agent/tests/`；`tests/conftest.py` → 根目录 `conftest.py` |
| `apps/frontend/` | `frontend/` |

运行时产生的 `reports/` 和 `work/` 仍在仓库根目录，不入库。
