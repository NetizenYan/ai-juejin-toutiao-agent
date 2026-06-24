# AI 掘金头条 —— AI 模块「Agent 化」改造技术文档

> 版本：v1.0　|　编写日期：2026-06-20　|　适用项目：toutiao_backend（day06_AI掘金头条-缓存和调用模型）
>
> 本文目的：在把现有「AI 问答」改造成 **Agent** 之前，沉淀一份现状基线（数据库 / 技术栈 / 代码位置 / 运行方式 / 代码规范），并给出改造的落地点与注意事项，作为后续开发的统一依据。

---

## 1. 背景与改造目标

### 1.1 现状（AS-IS）
当前的「AI 问答」是**纯前端直连大模型**，后端完全没有参与：

```
浏览器 (AIChat.vue)  ──HTTPS+SSE──►  阿里云 DashScope (通义千问 qwen3-max-preview)
        │
        └─ API Key 明文写死在前端 src/config/api.js  ⚠️ 安全隐患
```

- 前端直接 `fetch` 阿里云 OpenAI 兼容接口，流式（SSE）接收并用 Markdown 渲染。
- 后端 `main.py` 只注册了 news / users / favorite / history 四个路由，**无任何 AI 接口**。
- 数据库里已预留 `ai_chat` 表，但目前**没有任何代码读写它**（聊天记录未落库）。

### 1.2 目标（TO-BE）
将「单轮问答」升级为 **后端驱动的 Agent**：

1. **调用大模型的逻辑下沉到后端**：前端只调自己的后端（`/api/ai/...`），API Key 收归后端环境变量，杜绝泄露。
2. **Agent 能力**：多轮对话上下文、工具调用（Function Calling，如查新闻/查收藏）、可选的记忆/检索（RAG）。
3. **流式输出**：后端以 SSE 把模型增量结果转发给前端，保持现有打字机体验。
4. **聊天记录落库**：利用已有 `ai_chat` 表持久化对话。

> 改造范围：**新增** AI 相关后端代码 + **改造** 前端 `AIChat.vue` / `config/api.js`；其余 news/user/favorite/history 模块不动。

---

## 2. 技术栈

### 2.1 后端（实际运行环境 = 唯一事实来源）
| 类别 | 选型 | 版本 | 备注 |
|------|------|------|------|
| 语言 | Python | **3.11.15** | miniconda `agent` 环境 |
| Web 框架 | FastAPI | 0.125.0 | |
| ASGI 服务器 | uvicorn | 0.38.0 | |
| ORM | SQLAlchemy | 2.0.45 | **异步**（`async_sessionmaker` + `create_async_engine`）|
| MySQL 异步驱动 | aiomysql | 0.3.2 | 连接串 `mysql+aiomysql://...` |
| MySQL 同步驱动 | PyMySQL | 1.x | |
| 缓存 | redis（redis-py） | 7.x+ | 用 `redis.asyncio` 异步客户端 |
| 数据校验 | pydantic | 2.x | |
| 密码哈希 | passlib + **bcrypt 4.0.1** | — | ⚠️ bcrypt 必须 4.0.x，5.x 与 passlib 1.7.4 不兼容 |
| 配置 | python-dotenv | 1.x | 改造后用它管理模型 API Key |

> 注：`requirements.txt` 里的 pin（如 redis==7.1.0、bcrypt==3.2.2、aioredis、uvloop）与实际 `agent` 环境存在漂移；`aioredis` 多余（代码用 `redis.asyncio`），`uvloop` 在 Windows 上装不了。改造时建议同步整理 `requirements.txt`。

### 2.2 前端
| 类别 | 选型 | 版本 |
|------|------|------|
| 框架 | Vue 3（`<script setup>`） | 3.x |
| 构建工具 | Vite | 7.x（`@vitejs/plugin-vue` 6） |
| UI 组件库 | Vant | 4.9.x（移动端） |
| 状态管理 | Pinia + pinia-plugin-persistedstate | 3.x / 4.x |
| 路由 | vue-router | 4.x |
| HTTP | axios（业务接口）+ 原生 `fetch`（AI SSE） | 1.x |
| Markdown | marked + dompurify | AI 回复渲染 + XSS 清理 |
| 国际化 | vue-i18n | 9.x |
| 运行时 | Node.js 24 / npm 11 | |

### 2.3 当前 AI 模型（现状）
| 项 | 值 |
|----|----|
| 服务商 | 阿里云 DashScope（OpenAI 兼容模式） |
| Endpoint | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |
| 模型 | `qwen3-max-preview` |
| 协议 | OpenAI Chat Completions（`messages` + `stream:true`），SSE 头 `X-DashScope-SSE: enable` |

> Agent 化后仍可沿用 DashScope OpenAI 兼容接口（支持 function calling / tool_calls），无需更换 SDK；后端用任意 OpenAI 兼容 client 即可。

---

## 3. 代码位置

### 3.1 后端（完整路径）
```
D:\Developer\Code\Python Web开发：FastAPI从入门到实战\day06_AI掘金头条-缓存和调用模型\代码\toutiao_backend
```

完整结构（已排除 `__pycache__` / `.venv` / `.idea`）：
```
toutiao_backend/
├── main.py                      # 应用入口：注册路由 + CORS + 异常处理器
├── requirements.txt
├── test_main.http
├── config/
│   ├── db_conf.py               # MySQL 异步引擎 + get_db 依赖
│   └── cache_conf.py            # Redis 异步客户端 + get/set 缓存封装（已配密码 0813）
├── routers/                     # 路由层（接口定义）
│   ├── news.py                  #   /api/news/*
│   ├── users.py                 #   /api/user/*
│   ├── favorite.py              #   /api/favorite/*
│   └── history.py               #   /api/history/*
├── crud/                        # 数据访问层（封装 DB 操作）
│   ├── news.py
│   ├── news_cache.py            #   带 Redis 缓存的新闻查询
│   ├── users.py                 #   含 create_token（单用户单 token）/ 密码哈希
│   ├── favorite.py
│   └── history.py
├── cache/
│   └── news_cache.py            # 新闻相关缓存键的读写
├── models/                      # ORM 模型（SQLAlchemy DeclarativeBase）
│   ├── news.py                  #   News / Category / RelatedNews
│   ├── users.py                 #   User / UserToken
│   ├── favorite.py              #   Favorite
│   └── history.py               #   History
├── schemas/                     # Pydantic 请求/响应模型
│   ├── base.py                  #   NewsItemBase 等公共基类
│   ├── news.py / users.py / favorite.py / history.py
└── utils/
    ├── auth.py                  # get_current_user（Bearer Token 鉴权依赖）
    ├── security.py              # passlib 密码 hash / verify
    ├── response.py              # success_response 统一响应封装
    ├── exception.py             # 各类异常处理函数
    └── exception_handlers.py    # register_exception_handlers
```

> ⚠️ 数据库里已有 `ai_chat` 表，但 `models/`、`crud/`、`routers/`、`schemas/` 中**都没有对应文件** —— 这正是改造要新增的部分（见 §6）。

### 3.2 前端（完整路径）
```
D:\Developer\Code\Python Web开发：FastAPI从入门到实战\day03-AI掘金头条-新闻模块\项目物料\03-前端项目代码\xwzx-news
```
> 注意：前端**不在 day06 里**，整个课程共用 day03 项目物料中的这一份。

AI 改造相关的关键前端文件：
| 文件 | 作用 |
|------|------|
| `src/views/AIChat.vue` | AI 问答页（351 行）：输入框、消息列表、SSE 流式接收、Markdown 渲染 |
| `src/config/api.js` | `apiConfig.baseURL`（后端地址）+ `aiChatConfig`（⚠️ 含明文 API Key、endpoint、model） |
| `src/router/index.js` | 路由 `/aichat` → `AIChat.vue` |
| `src/components/TabBar.vue` | 底部「AI问答」入口 |
| `src/store/user.js` | 用户/Token（改造后 AI 接口需带 Token 鉴权时复用） |

### 3.3 课程其他物料
| 物料 | 路径 |
|------|------|
| 数据库 SQL | `day03-AI掘金头条-新闻模块\项目物料\02-数据库sql文件\database.sql` |
| 本章讲义 | `day06_AI掘金头条-缓存和调用模型\讲义\第六章_AI掘金头条-缓存和调用模型.pdf` |

---

## 4. 数据库

### 4.1 连接信息
| 项 | 值 |
|----|----|
| 引擎 | MySQL 8.0（Docker 容器 `toutiao-mysql`） |
| 连接串 | `ASYNC_DATABASE_URL` 或 `MYSQL_*` 环境变量注入；不要在源码中写 root 密码 |
| 库名 | `news_app`（utf8mb4 / utf8mb4_unicode_ci） |
| 配置位置 | `config/db_conf.py`（`ASYNC_DATABASE_URL`） |
| 缓存 | Redis（Docker 容器 `redis`）`localhost:6379`，**密码 `0813`**，`config/cache_conf.py` |

### 4.2 表清单（共 8 张）
| 表 | 说明 | 是否已被代码使用 |
|----|------|------------------|
| `user` | 用户信息 | ✅ |
| `user_token` | 登录令牌（单用户单 token） | ✅ |
| `news` | 新闻（约 403 条数据） | ✅ |
| `news_category` | 新闻分类（8 个） | ✅ |
| `related_news` | 相关新闻关联 | ✅ |
| `favorite` | 收藏 | ✅ |
| `history` | 浏览历史 | ✅ |
| **`ai_chat`** | **AI 聊天记录** | ❌ **预留未用 —— 改造目标表** |

### 4.3 `ai_chat` 表结构（改造核心表）
```sql
CREATE TABLE IF NOT EXISTS `ai_chat` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '聊天记录ID',
  `user_id`    INT UNSIGNED NOT NULL                COMMENT '用户ID',
  `message`    TEXT         NOT NULL                COMMENT '用户消息',
  `response`   TEXT         NOT NULL                COMMENT 'AI回复',
  `created_at` TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  INDEX `fk_ai_chat_user_idx` (`user_id` ASC),
  INDEX `idx_created_at` (`created_at` DESC),
  CONSTRAINT `fk_ai_chat_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI聊天记录表';
```
> Agent 化后若需要保存「多轮会话 / 工具调用轨迹」，现有 `message`+`response` 单轮结构可能不够，建议评估是否新增 `conversation_id`、`role`、`tool_calls`(JSON) 等字段或新增 `ai_conversation` 表（见 §6.4）。

---

## 5. 运行环境与启动方式

| 组件 | 地址 / 命令 |
|------|-------------|
| 后端 | `http://127.0.0.1:8000` ｜ `<agent-python> -m uvicorn main:app --host 127.0.0.1 --port 8000` |
| 后端解释器 | `D:\Developer\Soft\Miniconda3\envs\agent\python.exe`（Python 3.11） |
| API 文档 | `http://127.0.0.1:8000/docs` |
| 前端 | `http://localhost:5173` ｜ 在 `xwzx-news` 下 `npm run dev` |
| MySQL | `docker start toutiao-mysql`（容器，3306） |
| Redis | 容器 `redis`，开机自启（6379，密码 0813） |

> 端口说明：8000 曾被另一应用占用，已腾出给本后端；前端 `baseURL` 指向 8000，两者匹配。

---

## 6. 改造落地点（开发指引）

> 遵循现有**分层约定**：`routers`（接口）→ `crud`（DB 操作）→ `models`（ORM）/`schemas`（校验），鉴权用 `utils/auth.get_current_user`，响应用 `utils/response.success_response`。

### 6.1 新增后端文件（建议）
```
config/ai_conf.py        # 模型 client 配置：从 .env 读 API_KEY / BASE_URL / MODEL
.env                     # DASHSCOPE_API_KEY=...（加入 .gitignore，禁止入库）
models/ai_chat.py        # AiChat ORM 模型，映射 ai_chat 表
schemas/ai.py            # ChatRequest / ChatMessage / ChatHistoryResponse 等
crud/ai_chat.py          # 保存对话、查询历史
routers/ai.py            # APIRouter(prefix="/api/ai")，下挂 chat / history 接口
utils/agent/             # Agent 核心：模型调用、工具注册、多轮编排（可拆多文件）
```
并在 `main.py` 增加：`app.include_router(ai.router)`。

### 6.2 建议接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ai/chat` | 发起对话，**SSE 流式**返回；后端代理调用模型 |
| GET | `/api/ai/history` | 分页查询当前用户聊天记录（鉴权） |
| DELETE | `/api/ai/history/clear` | 清空聊天记录 |

- **流式实现**：用 FastAPI `StreamingResponse`（`media_type="text/event-stream"`），把模型 SSE 增量转发给前端。
- **鉴权**：复用 `get_current_user`（前端请求头带 `Authorization: Bearer <token>`）。

### 6.3 Agent 能力设计要点
- **多轮上下文**：维护 `messages` 列表（system/user/assistant/tool），按 `conversation_id` 组织。
- **工具调用（Function Calling）**：把站内能力暴露为工具，例如：
  - `search_news(keyword)` → 调 `crud/news` 查新闻
  - `get_user_favorites()` → 调 `crud/favorite`
  - 工具结果回灌模型，形成「思考→调用→观测→回答」闭环。
- **DashScope 兼容**：qwen 的 OpenAI 兼容接口支持 `tools` / `tool_calls`，沿用即可；后端可用任意 OpenAI 兼容 SDK。
- **可选 RAG**：若要让 Agent「读新闻库回答」，可对 `news` 内容做向量检索后注入上下文。

### 6.4 数据模型演进（按需）
单轮 `ai_chat(message, response)` 难以表达 Agent 的多轮 + 工具轨迹，二选一：
- **方案 A（轻量）**：保留 `ai_chat`，每轮一行，靠 `created_at` 排序还原会话。
- **方案 B（完整）**：新增 `ai_conversation(id, user_id, title, created_at)` + `ai_message(id, conversation_id, role, content, tool_calls JSON, created_at)`，`ai_chat` 退役或保留兼容。

### 6.5 前端改造
- `src/config/api.js`：**删除 `aiChatConfig` 中的 apiKey/endpoint**，AI 改为请求 `apiConfig.baseURL + '/api/ai/chat'`。
- `src/views/AIChat.vue`：`fetch` 目标改为后端接口，请求头改带用户 Token；SSE 解析逻辑基本可复用（注意后端转发后的事件格式与现有 `data:`/`[DONE]` 对齐）。

---

## 7. 安全与注意事项

1. **🔴 立即处理：API Key 泄露**。`src/config/api.js` 明文硬编码了 DashScope key（`sk-…`），任何访问前端的人都能看到。改造第一步应：① 在阿里云控制台**重置/吊销该 key**；② 新 key 只放后端 `.env`，`.env` 加入 `.gitignore`。
2. **bcrypt 版本锁定**：保持 `bcrypt==4.0.1`，勿升级到 5.x（与 passlib 1.7.4 不兼容，会导致注册 500）。
3. **CORS**：`main.py` 当前通过 `CORS_ALLOWED_ORIGINS` 显式配置来源；上线需收敛到正式前端域名。
4. **超时与重试**：模型调用要设超时、错误兜底（DashScope 限流/失败时给前端友好提示）。
5. **`requirements.txt` 整理**：移除 `aioredis`、给 `uvloop` 加 `; sys_platform != 'win32'`，并把 pin 对齐 `agent` 环境实际版本。

---

## 8. 现状基线一句话总结
> 项目是**前后端分离的移动端新闻 App**：后端 FastAPI（异步 SQLAlchemy + MySQL + Redis，分层清晰），前端 Vue3+Vant。新闻/用户/收藏/历史四大模块已完整且接口全部测试通过；**AI 问答目前是前端直连通义千问、后端零参与、`ai_chat` 表空置**——这就是本次 Agent 化改造的起点。
