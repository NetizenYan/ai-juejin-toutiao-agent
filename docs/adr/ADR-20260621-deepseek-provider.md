# ADR-20260621: DeepSeek v4-pro Provider for 3.0 Gray Regression

## Status

Accepted for 3.0 gray validation.

## Usage Boundary

This ADR accepts DeepSeek v4-pro for gray validation only. It does not replace the normal test provider.

```text
DeepSeek gray validation -> DeepSeek API / deepseek-v4-pro
normal development test  -> Ollama / local OpenAI-compatible endpoint
```

Rules:

- DeepSeek API is used for Provider regression, gray validation, and explicitly named DeepSeek comparison tests.
- Normal unit tests, normal backend smoke tests, and non-gray AI checks continue to use Ollama as the baseline.
- Dataset profiling does not require model generation and should not call DeepSeek API.
- Reports that compare model behavior must label provider, model, reasoning configuration, and latency separately.
- After DeepSeek gray validation, local default runtime config should return to Ollama. The DeepSeek key may remain in local `.env`, but normal tests must not default to DeepSeek API.

Recommended normal-test defaults:

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=gpt-oss:20b
LLM_REASONING_EFFORT=
LLM_THINKING_ENABLED=false
```

## Context

`toutiao_agent_unified` 已进入 3.0 生成质量灰度阶段。经济 RAG 链路已经验证：

- Query Router 可将经济类问题路由到 `econ_finance_query`。
- 经济候选 collection 为 `toutiao_econ_chunks_candidate_20260621`。
- Answer Contract 和 Validator v1 已启用。
- 全局 Validator 为 `shadow`，仅 `econ_finance_query` enforce。
- 前端统一调用后端 `/api/ai/chat`，不直接调用模型供应商。

下一阶段需要验证更强的生成模型是否能改善回答质量、引用遵循和拒答表现，同时不得破坏现有 Harness、MCP、RAG、SSE、落库和前端边界。

## Decision

采用 DeepSeek v4-pro 作为后续灰度模型，接入方式保持 OpenAI-compatible。常规测试默认仍使用 Ollama，不因本 ADR 改为 DeepSeek。

配置层：

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
DEEPSEEK_API_KEY=<local .env only>
LLM_REASONING_EFFORT=high
LLM_THINKING_ENABLED=true
```

实现层：

- `config/ai_conf.py` 读取 DeepSeek 相关配置。
- `harness/llm_client.py` 统一构造 OpenAI-compatible Chat Completions 请求。
- 业务代码不直接依赖 DeepSeek SDK 或 DeepSeek 私有接口。
- 前端 API 不变，仍调用 `http://127.0.0.1:8030/api/ai/chat`。

## Reasoning / Thinking Boundary

DeepSeek thinking 模式 raw stream 会返回大量 `reasoning_content`。本次实测：

```text
raw stream chunks = 117
reasoning_content chunks = 113
final content chunks = 2
```

这些内容属于模型内部推理过程，不是最终用户回答。

因此固定规则为：

```text
Only delta.content may enter SSE delta and final answer.
reasoning_content / reasoning / thinking must be filtered.
```

具体边界：

- reasoning 不进入前端 SSE `delta`。
- reasoning 不进入最终 answer。
- reasoning 不进入 `ai_message.content`。
- reasoning 不进入 evidence metadata。
- reasoning 不作为 Answer Validator 的校验输入。

当前通过 `harness/llm_client.py::extract_stream_content(delta)` 显式只提取 `delta.content`，并通过 `tests/test_llm_client.py` 锁定该行为。

## Validation Evidence

### Key Safety

通过。

- 真实 key 只保存在本机 `.env`。
- 代码、测试、`.env.example`、前端源码、前端 `.env` 均未发现真实 key。
- 前端无 `dashscope / aliyuncs / openai / ollama / 11434 / api.deepseek.com` 直连。

### Econ Enforce Query

Query：

```text
最近高质量发展和新质生产力有什么新闻？请用不超过120字回答，并保留新闻证据引用。
```

结果：

```text
sessionId = 196
answer_len = 112
mode = enforce
validation.passed = true
hallucinationRisk = low
rewriteCount = 1
collection = toutiao_econ_chunks_candidate_20260621
route = econ_finance_query
total latency = 40.36s
```

### No-answer Query

Query：

```text
站内有没有关于虚构政策“蓝鲸计划2029”的新闻？
```

结果：

```text
sessionId = 197
route = default
mode = shadow
validation.passed = true
hallucinationRisk = low
evidence_count = 5
```

低相关旧 evidence 被召回，但最终正确拒答，没有强行回答或编造。

### Shadow Routes

测试 5 条非经济新闻 query：

```text
mode = shadow
SSE 未崩
最终答案不被 shadow Validator 拦截
详细诊断进入后端 metadata / log
done.validation 只返回 summary
```

其中 1 条约束探针出现：

```text
passed=false
wouldRewrite=true
rewriteCount=0
```

符合 shadow 策略。

### Test Suite

```text
py_compile = passed
tests.test_llm_client = 3 tests OK
python -m unittest discover -s tests = 74 tests OK
```

## Consequences

优点：

- DeepSeek v4-pro 可通过现有 OpenAI-compatible Client 接入，供应商切换成本低。
- 不改变前端 API、RAG collection、MCP 工具边界或 Validator 灰度范围。
- 经济 enforce query 在 DeepSeek 下通过回归。
- 无答案 query 能拒答，不因低相关 evidence 强答。
- reasoning 过滤规则已显式实现并测试覆盖。

风险：

- thinking 模式会产生大量 reasoning tokens。
- enforce + rewrite 会显著增加延迟。
- 经济 enforce 后端耗时可到 40s 级。
- 若未来改动 LLM Client，必须避免 reasoning 字段回流到 SSE、DB 或 Validator。

## Non-decisions

本 ADR 不决定：

- 是否长期使用 DeepSeek v4-pro 作为唯一生产模型。
- 是否重建或修改 RAG collection。
- 是否扩大 Validator enforce 到其他 route。
- 是否实现 Context Manager。
- 是否改变前端 API。
- 是否改变股票预测或财经投资建议能力边界。

## Follow-up

后续建议：

- 继续使用 DeepSeek v4-pro 做 3.0 灰度。
- 常规开发验证和普通自动化测试继续使用 Ollama。
- 增加 `LLM_THINKING_ENABLED=false` 对照测试。
- 比较 `LLM_REASONING_EFFORT=medium/low` 的质量和延迟。
- 对 enforce + rewrite 场景记录 P50 / P95 latency。
- 保持 reasoning 内容只在 Provider 内部消费，不进入用户可见或持久化回答正文。

## Rollback

如出现延迟、成本或稳定性问题，可按以下方式回退：

```env
# Disable thinking first.
LLM_THINKING_ENABLED=false

# Lower reasoning effort.
LLM_REASONING_EFFORT=medium
# or
LLM_REASONING_EFFORT=low

# Reduce extra model calls in enforce mode.
ANSWER_REWRITE_ON_FAIL=false

# Switch back to the previous provider.
LLM_BASE_URL=<original-provider-base-url>
LLM_MODEL=<original-model>
LLM_API_KEY=<original-provider-key>
```

回退不需要修改前端 API，也不需要修改 RAG collection。
