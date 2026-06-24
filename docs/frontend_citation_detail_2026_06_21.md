# 前端 Citation 点击详情 — 灰度实施文档

日期：2026-06-22

## 1. Citation 渲染规则

AI Chat 回答中出现的 `[news:...]` 模式被识别为可点击的证据引用。

**正则表达式：**

```js
/\[news:[A-Za-z0-9:_-]+\]/g
```

**支持的格式：**

| 格式 | 示例 |
|------|------|
| 数字 ID | `[news:2726]` |
| jjrb hash | `[news:jjrb:8dcc9e6349959132]` |
| 带日期编号 | `[news:cctv-20200101-3]` |
| 含下划线 | `[news:cctv_special-2026]` |

**渲染流程（基于 DOM 文本节点，安全实现）：**

1. `marked.parse(content)` 解析 Markdown
2. `DOMPurify.sanitize(html)` 净化 HTML
3. 把净化后的 HTML 装进一个**游离的 `<div>`**，用 `TreeWalker` 只遍历**文本节点**
4. 对命中 citation 的文本节点，用 `document.createElement('span')` + `textContent` / `setAttribute('data-evidence-id', ...)` 包裹（绝不拼接 HTML 字符串）
5. 跳过位于 `<code>` / `<pre>` / `<a>` 内的文本节点（代码块/行内代码/链接内部不渲染 citation）
6. 读取 `div.innerHTML` 交给 `v-html` 渲染

> **为什么不是「正则替换序列化后的 HTML 字符串」？**
> 早期实现 `marked → DOMPurify → 正则替换字符串 → v-html` 存在两个风险：
> (1) 正则在序列化 HTML 上替换，会把 `<span>` 注入到 `href` / `title` 等**属性值**里，破坏 HTML 结构；
> (2) 代码块里的 `[news:...]` 会被误渲染成可点击元素。
> 改为「只处理已净化 DOM 的文本节点」后，两类问题都从根上消除。

**XSS 防护（双重）：**
- 内容先经 `DOMPurify.sanitize` 去除 `<script>`、`onerror` 等危险内容；
- citation 仅在文本节点上、通过 DOM API（`textContent` / `setAttribute`）包裹，不做任何 HTML 字符串拼接；
- evidence_id 字符集 `[A-Za-z0-9:_-]` 不含 `"`、`<`、`>`、`&`、空格，天然不可越界。

## 2. Evidence Detail API 调用

**端点：**

```
GET /api/ai/evidence-detail?evidence_id={id}
```

**调用方式：**

- 使用 `fetch` 直接请求
- `baseURL` 取自 `apiConfig.baseURL`（即 `VITE_API_BASE_URL` 环境变量）
- `evidence_id` 通过 `encodeURIComponent()` 编码后放入 query string
- 不硬编码端口号

**鉴权：**

```js
headers: { 'Authorization': userStore.token }
```

与现有 AI Chat 请求一致，复用登录 token。

**响应结构：**

```json
{
  "code": 200,
  "message": "获取证据详情成功",
  "data": {
    "evidence_id": "news:jjrb:...",
    "found": true,
    "source": "经济日报",
    "title": "...",
    "publish_time": "...",
    "snippet": "...",
    "content_excerpt": "...",
    "collection": "...",
    "parent_id": "...",
    "chunk_index": 0,
    "detail_available": true
  }
}
```

## 3. UI 展示方式

使用 Vant `van-popup` 底部弹出面板（position="bottom", round）：

- **标题**：大字展示 `title`
- **来源与时间**：图标 + `source` + `publish_time`
- **证据 ID**：小字灰色展示
- **摘要**：`snippet` 独立段落
- **正文片段**：`content_excerpt` 独立段落

**样式特点：**

- citation 标签：蓝色文字、浅蓝背景、虚线下划线、hover 加深
- 弹窗最大高度 70vh，可滚动
- 右上角关闭按钮

## 4. 错误处理

| 场景 | 展示 |
|------|------|
| 加载中 | `van-loading` + "正在查询证据详情..." |
| `found=false` | 图标 + "未找到该证据详情" |
| 401 / 未登录 | "登录已过期，请重新登录" / "请先登录后查看证据详情" |
| 网络错误 | "网络错误，请检查连接后重试" |
| HTTP 非 200 | "网络请求失败，请稍后重试" |
| `code != 200` | 展示后端返回的 `message` |

所有错误场景都不会导致页面崩溃，统一在弹窗内展示友好提示。

## 5. 修改文件清单

| 文件 | 变更 |
|------|------|
| `apps/frontend/src/views/AIChat.vue` | citation 渲染（DOM 文本节点）、事件委托、弹窗集成 |
| `apps/frontend/src/components/EvidenceDetailPopup.vue` | 新增：证据详情弹窗组件 |
| `apps/frontend/src/main.js` | 新增 Vant `Loading` 组件全局注册 |
| `harness/evidence_detail_resolver.py` | **Bug 修复**：`_row_matches` 误匹配（见第 6 节） |
| `tests/test_evidence_detail_resolver.py` | 新增 JSONL 误匹配回归用例 |

未修改：前端 `api.js` / baseURL 机制、RAG collection、Answer Validator、
DeepSeek/Ollama 配置、Qdrant、MySQL 同步。后端仅修了 resolver 的匹配判定这一个 bug。

## 6. 测试结果

### 自动验证

| 测试项 | 结果 |
|--------|------|
| `[news:jjrb:hash]` 替换为可点击 span | PASS |
| `[news:2726]` 数字 ID | PASS |
| `[news:cctv-20200101-3]` 带连字符 | PASS |
| 多个 citation 连续出现 | PASS |
| 无 citation 的普通文本不受影响 | PASS |
| XSS `"><script>` 注入 | SAFE（不匹配） |
| XSS `onclick=alert(1)` 注入 | SAFE（不匹配） |
| Vite build 成功 | PASS |

### 端到端验证（2026-06-22，真实浏览器 Headless Chromium + 真实后端 8030）

驱动方式：Playwright 启动 Chromium，登录测试账号 `u1`，加载 `http://127.0.0.1:5174/aichat`，
真实调用后端 `/api/ai/chat` 与 `/api/ai/evidence-detail`。共 **23 项断言全部通过**。

**Test A — 真实链路（真问真答 → 点击 → 弹窗）：**

| 断言 | 结果 |
|------|------|
| 经济问题返回 `[news:jjrb:139aa3760c02aada]` 并渲染为可点击 | PASS |
| citation 带 `data-evidence-id` | PASS |
| 弹窗展示 title（织密新就业群体保障网）/ source（经济日报）/ publish_time / 摘要 / 正文片段 / evidence_id | PASS |
| 点击触发 `GET /api/ai/evidence-detail`，URL 含 `evidence_id=` | PASS |
| 请求携带 `Authorization` token | PASS |
| 浏览器**无**模型供应商直连（无 :11434 / deepseek / openai 等） | PASS |
| 全部 `/api/` 请求指向后端 `127.0.0.1:8030` | PASS |

**Test B — 受控输入（mock `/api/ai/chat` 注入对抗内容，evidence-detail 走真实后端）：**

| 断言 | 结果 |
|------|------|
| 普通文本中的 citation 可点击 | PASS |
| 代码块内 `[news:...]` 不渲染为按钮（留在 `<code>/<pre>`） | PASS |
| 行内代码内 `[news:...]` 不渲染 | PASS |
| 链接内 `[news:...]`（位于 href）不注入 span、不破坏 HTML | PASS |
| `<script>` / `onerror` XSS 被净化（`window.__xss` 未被置位） | PASS |
| 不存在的 `[news:jjrb:fake000ZZZ]` → 弹窗显示「未找到该证据详情」 | PASS |
| not-found 后页面不崩溃、输入框仍可用 | PASS |

截图见 `reports/citation_e2e_found_true.png`、`reports/citation_e2e_found_false.png`。

### 发现并修复的后端 Bug（resolver JSONL fallback 误匹配）

E2E 过程中发现 `harness/evidence_detail_resolver.py::_row_matches` 存在逻辑错误：
它把**查询派生**的 id（`core`、`news:source:doc`）混入了本应只装**行字段**的 `candidates`
集合，再对该集合自身做成员判断，导致 `core in candidates` 恒为真 —— 只要 Qdrant 未命中、
JSONL 文件存在，**任意** `news:<source>:<x>` 都会返回 JSONL 的第一行（伪造命中）。

- 影响：`found=false` 路径在有 JSONL 兜底时失效；生产中一旦 Qdrant 漏召回，会给用户**错配文章**。
- 修复：把「行标识集合」与「查询标识集合」分开，仅当两者有交集才判定命中（最小改动，见该函数注释）。
- 回归：新增 `tests/test_evidence_detail_resolver.py::test_jsonl_fallback_does_not_match_unrelated_row`；
  全量 7 个用例通过（旧 buggy 代码下新用例会失败）。
- 该修复**仅**触及 resolver 的匹配判定，未改 RAG、Validator、模型配置或 Qdrant/MySQL。

## 7. 后续优化方向

- 右侧抽屉替代底部弹窗（桌面端体验更好）
- citation 编号化展示（如 [1] [2]），鼠标悬停预览
- 来源详情页跳转
- citation 高亮联动（点击时高亮对应引用文本）
- （非本期）前端 `store/user.js` 的 `persist` 仍是 v3 写法（`enabled`/`strategies`/`key:'user-store'`），
  而依赖是 pinia-plugin-persistedstate v4，实际持久化键回落为 store id `user`；持久化能用但配置项是死代码，建议后续清理。
