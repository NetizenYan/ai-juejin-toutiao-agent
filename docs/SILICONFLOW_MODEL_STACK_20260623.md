# SiliconFlow Model Stack 2026-06-23

## 固定规则

本项目 3.2E.1 之后的 SiliconFlow API 测试栈固定为：

| 角色 | 模型 | 用途 |
|---|---|---|
| Embedding | `Pro/BAAI/bge-m3` | query 向量化，必须与 Qdrant 向量索引维度/模型一致 |
| Reranker | `Pro/BAAI/bge-reranker-v2-m3` | 对召回候选做二次重排序 |
| Inference | `zai-org/GLM-5.2` | 基于召回证据生成最终回答 |

## 禁止混用

- `zai-org/GLM-5.2` 只用于问答生成，不用于 embedding。
- `Pro/BAAI/bge-m3` 只用于 embedding，不用于最终回答生成。
- `Pro/BAAI/bge-reranker-v2-m3` 只用于 rerank，不替代向量召回或问答生成。

## 配置入口

`.env` 中统一使用：

```env
SILICONFLOW_API_KEY=

EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Pro/BAAI/bge-m3

RERANKER_PROVIDER=api
RERANKER_API_BASE_URL=https://api.siliconflow.cn/v1
RERANKER_API_MODEL=Pro/BAAI/bge-reranker-v2-m3

LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=zai-org/GLM-5.2
```

不要把真实 API key 写入报告或提交记录。运行测试时通过 `SILICONFLOW_API_KEY` 注入；如 reranker 使用单独 key，可只覆盖 `RERANKER_API_KEY`。

## Collection 对应

当前 API BGE 候选 collection：

```env
QDRANT_UNIFIED_COLLECTION=news_chunks_v32e_api_bge_m3_test
RAG_SEARCH_VERSION=v2
EMBEDDING_V2_MODEL=Pro/BAAI/bge-m3
EMBEDDING_V2_DIM=1024
```

如果 query embedding 改成 SiliconFlow `Pro/BAAI/bge-m3`，就应使用上述 API BGE collection；不要混到旧的本地 embedding collection。
