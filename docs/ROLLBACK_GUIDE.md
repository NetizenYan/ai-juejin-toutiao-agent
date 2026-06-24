# Rollback Guide

## Immediate Rollback

Set:

```env
RAG_SEARCH_VERSION=v1
```

Restart backend.

## 立即回滚方式

将运行环境切回 v1：

```env
RAG_SEARCH_VERSION=v1
```

然后重启后端服务。

## 说明

- Restores v1 search path.
- Uses old MySQL.
- Uses old Qdrant collection.
- Does not delete PostgreSQL v2.
- Does not delete `news_chunks_v2`.
- Does not rebuild embeddings.
- Does not affect MySQL data.
- 回滚只切回 v1 检索路径。
- 不删除 PG v2。
- 不删除 `news_chunks_v2`。
- 不重建 embedding。
- 不影响 MySQL。
- 不影响旧 Qdrant。
- 不需要重建 clean corpus。
- 不需要重新清洗数据。

## 注意

- 不要把真实 `.env` 提交。
- 不要提交 `env_snapshots/*.local`。
- 不要为了回滚删除 `backups/*.sql` 或 `backups/*.json`。
