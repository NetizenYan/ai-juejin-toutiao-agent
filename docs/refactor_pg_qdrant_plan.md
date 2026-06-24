# PG+Qdrant 重构执行手册

> 交给 Codex / Claude 逐步执行。每个阶段完成后停下来确认再继续。

## 架构目标

```
PostgreSQL (元数据中心 + 全文检索)
  ├── news_unified        新闻主表
  ├── news_chunks_meta    chunk 元数据 + tsvector
  └── ACID 保证一致性

Qdrant (纯向量检索)
  ├── news_chunks_v2      新 collection
  └── payload 只存 news_id + 过滤字段

检索流程:
  Qdrant 向量召回 top30 → news_id 回 PG 查元数据 + 全文分 → SQL diversity → top5
```

## 约束

- 不删除旧 MySQL news 表
- 不删除旧 Qdrant collection
- 不新增 Redis / Milvus / NGINX
- 不扩大 Validator enforce
- session summary / memory 不作 factual evidence
- 前端 API 路径不变，内部实现切换
- 无图片的新闻 image_url = NULL，前端不渲染图片块

---

## 阶段 0：环境检查

### 0.1 检查 PostgreSQL 版本和扩展

```bash
psql -U postgres -c "SELECT version();"
psql -U postgres -c "SELECT * FROM pg_available_extensions WHERE name IN ('pg_trgm', 'vector', 'pg_jieba');"
```

要求：
- PostgreSQL >= 12
- pg_trgm 内置可用
- 如果有 pgvector 最好（本方案不依赖但后续可加）
- pg_jieba 可选，装不了用 simple 配置

### 0.2 创建数据库

```sql
CREATE DATABASE toutiao_agent
  WITH ENCODING 'UTF8'
  LC_COLLATE 'C'
  LC_CTYPE 'C'
  TEMPLATE template0;

\c toutiao_agent
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- 如果可用:
-- CREATE EXTENSION IF NOT EXISTS pg_jieba;
```

### 0.3 检查 Qdrant 可用

```bash
curl http://localhost:6333/collections
```

### 0.4 检查 Embedding 服务

```bash
curl http://localhost:11434/v1/models
```

确认当前 embedding 模型名称和维度。

### 0.5 确认数据源文件存在

```bash
ls -la "D:/Files/BaiDu/经济日报2010-2026.6.csv"
ls -la "D:/Files/BaiDu/RMRB数据"
```

---

## 阶段 1：PG 建表

### 1.1 执行建表 SQL

文件: `sql/pg_rebuild.sql`

```sql
-- ============================================================
-- toutiao_agent PG schema
-- ============================================================

-- 扩展
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 新闻主表
-- ============================================================
CREATE TABLE news_unified (
  id              BIGSERIAL PRIMARY KEY,
  source_code     VARCHAR(16)  NOT NULL,
  source_name     VARCHAR(32)  NOT NULL,
  title           VARCHAR(256) NOT NULL,
  summary         TEXT,
  body            TEXT,
  publish_time    TIMESTAMPTZ  NOT NULL,
  publish_ts      BIGINT       NOT NULL,
  url             VARCHAR(512),
  image_url       VARCHAR(512),
  has_image       BOOLEAN      DEFAULT FALSE,
  content_type    VARCHAR(32)  NOT NULL DEFAULT 'general_news',
  quality_score   REAL         DEFAULT 0.8,
  entity_tags     TEXT[],
  dedup_hash      VARCHAR(64)  UNIQUE,
  created_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- Chunk 元数据表 (Qdrant 存向量, PG 存元数据 + 全文)
-- ============================================================
CREATE TABLE news_chunks_meta (
  id              BIGSERIAL PRIMARY KEY,
  news_id         BIGINT       NOT NULL REFERENCES news_unified(id) ON DELETE CASCADE,
  chunk_type      VARCHAR(16)  NOT NULL,
  chunk_index     INT          DEFAULT 0,
  chunk_text      TEXT         NOT NULL,
  qdrant_point_id VARCHAR(64),
  tsv             tsvector,
  created_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- 索引
-- ============================================================
CREATE INDEX idx_chunks_tsv      ON news_chunks_meta USING gin(tsv);
CREATE INDEX idx_chunks_news     ON news_chunks_meta(news_id);
CREATE INDEX idx_news_source     ON news_unified(source_code);
CREATE INDEX idx_news_type       ON news_unified(content_type);
CREATE INDEX idx_news_publish    ON news_unified(publish_ts DESC);
CREATE INDEX idx_news_entities   ON news_unified USING gin(entity_tags);
CREATE INDEX idx_news_title_trgm ON news_unified USING gin(title gin_trgm_ops);
CREATE INDEX idx_news_dedup      ON news_unified(dedup_hash);

-- ============================================================
-- 全文检索 trigger
-- 如果装了 pg_jieba, 把 'simple' 改成 'jieba'
-- ============================================================
CREATE OR REPLACE FUNCTION update_chunk_tsv() RETURNS trigger AS $$
BEGIN
  NEW.tsv := to_tsvector('simple', NEW.chunk_text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chunk_tsv
  BEFORE INSERT OR UPDATE ON news_chunks_meta
  FOR EACH ROW EXECUTE FUNCTION update_chunk_tsv();

-- ============================================================
-- 辅助函数: 构造 evidence_id
-- ============================================================
CREATE OR REPLACE FUNCTION news_evidence_id(news_id BIGINT, source_code TEXT)
RETURNS TEXT AS $$
BEGIN
  RETURN 'news:' || source_code || ':' || news_id;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

执行:

```bash
psql -U postgres -d toutiao_agent -f sql/pg_rebuild.sql
```

### 1.2 添加 PG 配置

文件: `config/pg_conf.py`

```python
"""PostgreSQL configuration for unified news metadata."""
from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DATABASE = os.getenv("PG_DATABASE", "toutiao_agent")

PG_DSN = os.getenv(
    "PG_DSN",
    f"postgresql+asyncpg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}",
)

pg_engine = create_async_engine(PG_DSN, echo=False, pool_size=10, max_overflow=20)
PgSessionLocal = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)


async def get_pg_session() -> AsyncSession:
    async with PgSessionLocal() as session:
        yield session
```

### 1.3 更新 .env 和 .env.example

在 `.env` 末尾追加:

```
# PostgreSQL (unified metadata)
PG_HOST=127.0.0.1
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=
PG_DATABASE=toutiao_agent

# New Qdrant collection
QDRANT_UNIFIED_COLLECTION=news_chunks_v2

# Embedding (可选换 bge-m3, 不换保持原值)
EMBEDDING_MODEL=qwen3-embedding:4b
```

在 `.env.example` 追加同样的键但值留空或默认。

### 1.4 安装 Python 依赖

```bash
pip install asyncpg sqlalchemy[asyncio]
```

### 1.5 验证 PG 连接

```python
# scripts/verify_pg.py
import asyncio
from config.pg_conf import pg_engine
from sqlalchemy import text

async def main():
    async with pg_engine.connect() as conn:
        result = await conn.execute(text("SELECT count(*) FROM news_unified"))
        print(f"news_unified rows: {result.scalar()}")

asyncio.run(main())
```

```bash
python scripts/verify_pg.py
```

---

## 阶段 2：数据清洗管道

### 2.1 创建清洗脚本

文件: `scripts/rebuild_pipeline.py`

```python
"""
Data cleaning and migration pipeline.
Reads all data sources → cleans → writes PG news_unified → chunks → embeds → writes Qdrant.

Usage:
  python scripts/rebuild_pipeline.py --dry-run          # 只清洗不写入, 输出统计
  python scripts/rebuild_pipeline.py --pg-only           # 只写 PG
  python scripts/rebuild_pipeline.py --full              # PG + Qdrant 全量
  python scripts/rebuild_pipeline.py --full --limit 100  # 只跑前100条测试
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from config.pg_conf import PgSessionLocal


# ============================================================
# 数据源读取
# ============================================================

ECON_CSV = "D:/Files/BaiDu/经济日报2010-2026.6.csv"
RMRB_DIR = "D:/Files/BaiDu/RMRB数据"


def read_econ_csv(path: str) -> list[dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            items.append({
                "source_code": "jjrb",
                "source_name": "经济日报",
                "title": (row.get("title") or row.get("标题") or "").strip(),
                "summary": (row.get("summary") or row.get("摘要") or row.get("导语") or "").strip(),
                "body": (row.get("content") or row.get("正文") or row.get("body") or "").strip(),
                "publish_time_str": (row.get("publish_time") or row.get("date") or row.get("发布时间") or "").strip(),
                "url": (row.get("url") or row.get("链接") or "").strip(),
                "image_url": (row.get("image_url") or row.get("图片") or "").strip(),
            })
    return items


def read_rmrb_dir(path: str) -> list[dict[str, Any]]:
    items = []
    p = Path(path)
    if not p.exists():
        return items
    for csv_file in p.glob("*.csv"):
        with open(csv_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append({
                    "source_code": "rmrb",
                    "source_name": "人民日报",
                    "title": (row.get("title") or row.get("标题") or "").strip(),
                    "summary": (row.get("summary") or row.get("摘要") or "").strip(),
                    "body": (row.get("content") or row.get("正文") or row.get("body") or "").strip(),
                    "publish_time_str": (row.get("publish_time") or row.get("date") or row.get("发布时间") or "").strip(),
                    "url": (row.get("url") or row.get("链接") or "").strip(),
                    "image_url": (row.get("image_url") or row.get("图片") or "").strip(),
                })
    return items


async def read_mysql_legacy() -> list[dict[str, Any]]:
    """Read 7319 records from old MySQL news table."""
    from config.db_conf import AsyncSessionLocal as MysqlSession
    items = []
    async with MysqlSession() as session:
        result = await session.execute(text("SELECT id, title, content, summary, source, author, publish_time, url, image_url FROM news ORDER BY id"))
        for row in result:
            items.append({
                "source_code": classify_source_code(str(row.source or row.author or "")),
                "source_name": str(row.source or row.author or ""),
                "title": str(row.title or "").strip(),
                "summary": str(row.summary or "").strip(),
                "body": str(row.content or "").strip(),
                "publish_time_str": str(row.publish_time or "") if row.publish_time else "",
                "url": str(row.url or "").strip(),
                "image_url": str(row.image_url or "").strip(),
            })
    return items


def classify_source_code(source_name: str) -> str:
    name = source_name.lower()
    if "经济日报" in name or "jjrb" in name:
        return "jjrb"
    if "人民日报" in name or "rmrb" in name:
        return "rmrb"
    if "新闻联播" in name or "央视" in name or "cctv" in name:
        return "cctv"
    if "新华社" in name or "xhw" in name:
        return "xhw"
    return "other"


# ============================================================
# 清洗
# ============================================================

ARTIFACT_PATTERNS = [
    "nannann", "｜nan", "|nan", "nan政协", "nan国家",
    "NaN", "null", "undefined",
]

CLICKBAIT_PATTERNS = [
    "吵翻", "掀桌", "傻乎乎", "无人问津", "震惊", "崩了",
    "特大级消息", "变盘行情", "周六上午传来",
]

ENTITY_KEYWORDS = [
    "新质生产力", "高质量发展", "科技创新", "产业升级", "产业链",
    "制造业", "高技术制造业", "现代化产业体系", "先进制造",
    "半导体", "新能源", "数字经济", "人工智能",
    "财政政策", "货币政策", "宏观政策", "A股",
    "促消费", "外贸", "就业", "房地产",
]

CONTENT_TYPE_SIGNALS = {
    "economic_analysis": [
        "制造业", "产业链", "PMI", "增加值", "投资", "出口",
        "消费数据", "同比增长", "环比", "工业", "产业",
    ],
    "policy_statement": [
        "重要讲话", "强调", "指出", "要求", "会议强调",
        "部署", "总书记", "总理",
    ],
    "theory_interpretation": [
        "理论", "硬道理", "认识", "深刻理解", "实践价值",
        "理论贡献", "思想",
    ],
    "data_report": [
        "数据显示", "统计", "调查", "报告显示",
    ],
}


def clean_title(title: str) -> str:
    t = (title or "").strip()
    # 去 nan
    for p in ARTIFACT_PATTERNS:
        t = t.replace(p, "")
    # 去前缀日期
    t = re.sub(r"^\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}[日]?\s*[|｜]\s*", "", t)
    # 去来源前缀
    t = re.sub(r"^(经济日报|人民日报|新闻联播|央视|新华社)\s*[|｜]\s*", "", t)
    return t.strip()


def clean_body(body: str) -> str:
    b = (body or "").strip()
    # 去 HTML 标签
    b = re.sub(r"<[^>]+>", "", b)
    # 去多余空白
    b = re.sub(r"\s{3,}", "\n", b)
    # 去 artifact
    for p in ARTIFACT_PATTERNS:
        b = b.replace(p, "")
    # 截断超长
    if len(b) > 8000:
        b = b[:8000]
    return b.strip()


def handle_image(image_url: str) -> dict:
    url = (image_url or "").strip()
    if not url or url.lower() in ("nan", "null", "undefined", "none", ""):
        return {"image_url": None, "has_image": False}
    if not url.startswith("http"):
        return {"image_url": None, "has_image": False}
    # 检查是否是占位图
    if any(x in url.lower() for x in ["placeholder", "default", "no-image", "blank"]):
        return {"image_url": None, "has_image": False}
    return {"image_url": url, "has_image": True}


def parse_publish_time(time_str: str) -> tuple[datetime | None, int]:
    if not time_str:
        return None, 0
    # 尝试多种格式
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
        "%Y.%m.%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str[:19] if len(time_str) > 19 else time_str, fmt)
            return dt, int(dt.timestamp())
        except ValueError:
            continue
    # 尝试从字符串中提取日期
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", time_str)
    if match:
        try:
            dt = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return dt, int(dt.timestamp())
        except ValueError:
            pass
    return None, 0


def classify_content_type(title: str, body: str) -> str:
    text = (title + " " + body[:500]).lower()
    scores = {}
    for ctype, signals in CONTENT_TYPE_SIGNALS.items():
        score = sum(1 for s in signals if s in text)
        if score > 0:
            scores[ctype] = score
    if not scores:
        return "general_news"
    return max(scores, key=scores.get)


def extract_entities(title: str, body: str) -> list[str]:
    text = title + " " + body[:1000]
    return list({kw for kw in ENTITY_KEYWORDS if kw in text})


def compute_quality_score(title: str, body: str, source_code: str) -> float:
    score = 1.0
    if not title.strip() or len(title.strip()) < 4:
        score -= 0.55
    if not body.strip() or len(body.strip()) < 50:
        score -= 0.40
    joined = (title + " " + body[:200]).lower()
    if any(p in joined for p in ARTIFACT_PATTERNS):
        score -= 0.85
    if any(p in title for p in CLICKBAIT_PATTERNS):
        score -= 0.50
    if source_code == "other" and not any(kw in joined for kw in ENTITY_KEYWORDS):
        score -= 0.30
    return max(0.05, min(1.0, score))


def dedup_hash(title: str, body: str) -> str:
    raw = (title[:80] + body[:200]).strip()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ============================================================
# Chunk 策略
# ============================================================

def smart_chunk(item: dict) -> list[dict]:
    chunks = []
    # title chunk
    if item["title"]:
        chunks.append({
            "chunk_type": "title",
            "chunk_index": 0,
            "chunk_text": item["title"],
        })
    # summary chunk
    if item["summary"] and len(item["summary"]) > 10:
        chunks.append({
            "chunk_type": "summary",
            "chunk_index": 1,
            "chunk_text": item["summary"],
        })
    # body chunks (按段落切, 每段 200-400 字)
    body = item["body"]
    if body:
        paragraphs = re.split(r"\n{2,}", body)
        chunk_idx = 2
        for para in paragraphs:
            para = para.strip()
            if len(para) < 20:
                continue
            if len(para) > 400:
                # 长段落按句号切
                sentences = re.split(r"([。！？])", para)
                current = ""
                for i in range(0, len(sentences), 2):
                    s = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
                    if len(current) + len(s) > 400 and current:
                        chunks.append({
                            "chunk_type": "body",
                            "chunk_index": chunk_idx,
                            "chunk_text": current.strip(),
                        })
                        chunk_idx += 1
                        current = s
                    else:
                        current += s
                if current.strip():
                    chunks.append({
                        "chunk_type": "body",
                        "chunk_index": chunk_idx,
                        "chunk_text": current.strip(),
                    })
                    chunk_idx += 1
            else:
                chunks.append({
                    "chunk_type": "body",
                    "chunk_index": chunk_idx,
                    "chunk_text": para,
                })
                chunk_idx += 1
    return chunks


# ============================================================
# 主流程
# ============================================================

async def run_pipeline(dry_run: bool = False, pg_only: bool = False, full: bool = False, limit: int = 0):
    print("=" * 60)
    print("PG+Qdrant Rebuild Pipeline")
    print("=" * 60)

    # 1. 汇聚数据
    print("\n[1/6] Reading data sources...")
    raw = []
    econ = read_econ_csv(ECON_CSV)
    print(f"  经济日报 CSV: {len(econ)} rows")
    raw += econ

    rmrb = read_rmrb_dir(RMRB_DIR)
    print(f"  人民日报 CSV: {len(rmrb)} rows")
    raw += rmrb

    mysql = await read_mysql_legacy()
    print(f"  MySQL 旧库: {len(mysql)} rows")
    raw += mysql

    print(f"  Total raw: {len(raw)}")

    if limit:
        raw = raw[:limit]
        print(f"  Limited to: {limit}")

    # 2. 去重
    print("\n[2/6] Deduplicating...")
    seen_hashes = set()
    deduped = []
    for item in raw:
        h = dedup_hash(item["title"], item["body"])
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        item["dedup_hash"] = h
        deduped.append(item)
    print(f"  After dedup: {len(deduped)} (removed {len(raw) - len(deduped)})")

    # 3. 清洗
    print("\n[3/6] Cleaning...")
    cleaned = []
    stats = {"no_title": 0, "low_quality": 0, "ok": 0, "by_source": {}, "by_type": {}}
    for item in deduped:
        title = clean_title(item["title"])
        body = clean_body(item["body"])
        summary = (item.get("summary") or "").strip()

        if not title or len(title) < 4:
            stats["no_title"] += 1
            continue

        img = handle_image(item.get("image_url", ""))
        dt, ts = parse_publish_time(item.get("publish_time_str", ""))
        if not ts:
            stats["low_quality"] += 1
            continue

        ctype = classify_content_type(title, body)
        entities = extract_entities(title, body)
        qscore = compute_quality_score(title, body, item["source_code"])

        if qscore <= 0.3:
            stats["low_quality"] += 1
            continue

        cleaned.append({
            "source_code": item["source_code"],
            "source_name": item["source_name"],
            "title": title,
            "summary": summary,
            "body": body,
            "publish_time": dt,
            "publish_ts": ts,
            "url": item.get("url", ""),
            "image_url": img["image_url"],
            "has_image": img["has_image"],
            "content_type": ctype,
            "entity_tags": entities,
            "quality_score": qscore,
            "dedup_hash": item["dedup_hash"],
        })
        stats["ok"] += 1
        stats["by_source"][item["source_code"]] = stats["by_source"].get(item["source_code"], 0) + 1
        stats["by_type"][ctype] = stats["by_type"].get(ctype, 0) + 1

    print(f"  Cleaned: {stats['ok']}")
    print(f"  No title: {stats['no_title']}")
    print(f"  Low quality: {stats['low_quality']}")
    print(f"  By source: {json.dumps(stats['by_source'], ensure_ascii=False)}")
    print(f"  By content_type: {json.dumps(stats['by_type'], ensure_ascii=False)}")

    if dry_run:
        print("\n[DRY RUN] Not writing to PG or Qdrant.")
        return

    if not cleaned:
        print("\n[ERROR] No data to write.")
        return

    # 4. 写 PG news_unified
    if pg_only or full:
        print(f"\n[4/6] Writing {len(cleaned)} records to PG news_unified...")
        async with PgSessionLocal() as session:
            # 批量插入
            values = []
            for item in cleaned:
                values.append({
                    "source_code": item["source_code"],
                    "source_name": item["source_name"],
                    "title": item["title"],
                    "summary": item["summary"],
                    "body": item["body"],
                    "publish_time": item["publish_time"],
                    "publish_ts": item["publish_ts"],
                    "url": item["url"],
                    "image_url": item["image_url"],
                    "has_image": item["has_image"],
                    "content_type": item["content_type"],
                    "quality_score": item["quality_score"],
                    "entity_tags": item["entity_tags"],
                    "dedup_hash": item["dedup_hash"],
                })

            # 分批插入, 每批 500
            batch_size = 500
            inserted_ids = []
            for i in range(0, len(values), batch_size):
                batch = values[i:i + batch_size]
                cols = ", ".join(batch[0].keys())
                placeholders = ", ".join(f":{k}" for k in batch[0].keys())
                sql = text(f"""
                    INSERT INTO news_unified ({cols})
                    VALUES ({placeholders})
                    RETURNING id
                """)
                for row in batch:
                    result = await session.execute(sql, row)
                    inserted_ids.append(result.scalar())
                print(f"  Inserted batch {i // batch_size + 1}/{(len(values) + batch_size - 1) // batch_size}")
            await session.commit()
        print(f"  PG news_unified: {len(inserted_ids)} rows inserted")

    if not full:
        print("\n[PG-ONLY] Done. Run --full to also chunk + embed + write Qdrant.")
        return

    # 5. Chunk + 写 PG news_chunks_meta
    print(f"\n[5/6] Chunking and writing news_chunks_meta...")
    total_chunks = 0
    chunk_records = []
    for news_id, item in zip(inserted_ids, cleaned):
        chunks = smart_chunk(item)
        for chunk in chunks:
            chunk_records.append({
                "news_id": news_id,
                "chunk_type": chunk["chunk_type"],
                "chunk_index": chunk["chunk_index"],
                "chunk_text": chunk["chunk_text"],
            })
            total_chunks += 1
    print(f"  Total chunks: {total_chunks}")

    # 批量写 chunk 元数据
    chunk_meta_ids = []
    async with PgSessionLocal() as session:
        for i in range(0, len(chunk_records), 500):
            batch = chunk_records[i:i + 500]
            for row in batch:
                result = await session.execute(text("""
                    INSERT INTO news_chunks_meta (news_id, chunk_type, chunk_index, chunk_text)
                    VALUES (:news_id, :chunk_type, :chunk_index, :chunk_text)
                    RETURNING id
                """), row)
                chunk_meta_ids.append(result.scalar())
            print(f"  Chunk batch {i // 500 + 1}")
        await session.commit()
    print(f"  PG news_chunks_meta: {len(chunk_meta_ids)} rows")

    # 6. Embed + 写 Qdrant
    print(f"\n[6/6] Embedding and writing Qdrant...")
    from config.ai_conf import get_embedding_client, settings
    from config.vector_conf import get_qdrant
    import uuid

    collection_name = os.getenv("QDRANT_UNIFIED_COLLECTION", "news_chunks_v2")

    qdrant = get_qdrant()
    # 创建 collection (如果不存在)
    try:
        await qdrant.create_collection(
            collection_name=collection_name,
            vectors_config={"size": 2560, "distance": "Cosine"},  # 根据实际 embedding 维度调整
        )
        print(f"  Created Qdrant collection: {collection_name}")
    except Exception:
        print(f"  Collection {collection_name} already exists or creation skipped")

    client = get_embedding_client()
    batch_size = 32
    embedded = 0
    for i in range(0, len(chunk_records), batch_size):
        batch = chunk_records[i:i + batch_size]
        batch_ids = chunk_meta_ids[i:i + batch_size]
        texts = [c["chunk_text"] for c in batch]
        response = await client.embeddings.create(model=settings.embedding_model, input=texts)
        points = []
        for j, (chunk, meta_id) in enumerate(zip(batch, batch_ids)):
            vec = response.data[j].embedding
            # 找对应的 news_unified 记录
            news_idx = inserted_ids.index(chunk["news_id"]) if chunk["news_id"] in inserted_ids else 0
            item = cleaned[news_idx]
            point_id = str(uuid.uuid4())
            points.append({
                "id": point_id,
                "vector": vec,
                "payload": {
                    "news_id": chunk["news_id"],
                    "chunk_meta_id": meta_id,
                    "source_code": item["source_code"],
                    "chunk_type": chunk["chunk_type"],
                    "content_type": item["content_type"],
                    "publish_ts": item["publish_ts"],
                }
            })
            # 回写 qdrant_point_id 到 PG
        await qdrant.upsert(collection_name=collection_name, points=points)
        embedded += len(points)
        if embedded % 320 == 0 or embedded == len(chunk_records):
            print(f"  Embedded: {embedded}/{len(chunk_records)}")

    # 回写 qdrant_point_id (可选, 批量更新)
    print(f"  Qdrant points written: {embedded}")

    # 验证
    print("\n" + "=" * 60)
    print("Verification:")
    async with PgSessionLocal() as session:
        news_count = (await session.execute(text("SELECT count(*) FROM news_unified"))).scalar()
        chunk_count = (await session.execute(text("SELECT count(*) FROM news_chunks_meta"))).scalar()
        with_img = (await session.execute(text("SELECT count(*) FROM news_unified WHERE has_image = true"))).scalar()
        print(f"  PG news_unified: {news_count}")
        print(f"  PG news_chunks_meta: {chunk_count}")
        print(f"  News with image: {with_img}")
        print(f"  News without image: {news_count - with_img}")
    print(f"  Qdrant {collection_name}: {embedded} points")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PG+Qdrant rebuild pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Clean only, no writes")
    parser.add_argument("--pg-only", action="store_true", help="Write PG only, no Qdrant")
    parser.add_argument("--full", action="store_true", help="Full: PG + Qdrant")
    parser.add_argument("--limit", type=int, default=0, help="Limit records for testing")
    args = parser.parse_args()

    asyncio.run(run_pipeline(
        dry_run=args.dry_run,
        pg_only=args.pg_only,
        full=args.full,
        limit=args.limit,
    ))
```

### 2.2 运行步骤

```bash
# 第一步: dry-run 看清洗统计
python scripts/rebuild_pipeline.py --dry-run

# 第二步: 先跑 100 条验证
python scripts/rebuild_pipeline.py --full --limit 100

# 第三步: 全量
python scripts/rebuild_pipeline.py --full
```

---

## 阶段 3：检索层 v2

### 3.1 创建新检索模块

文件: `harness/rag_search_v2.py`

```python
"""
PG+Qdrant hybrid search v2.
Qdrant 向量召回 → PG 元数据 + 全文分 → SQL diversity → top5.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from config.pg_conf import PgSessionLocal
from config.vector_conf import get_qdrant
from config.ai_conf import get_embedding_client, settings


UNIFIED_COLLECTION = os.getenv("QDRANT_UNIFIED_COLLECTION", "news_chunks_v2")


QUERY_TYPE_SIGNALS = {
    "economic_analysis": ["影响", "制造业", "产业链", "出口", "投资", "数据", "增长", "PMI", "工业"],
    "theory_interpretation": ["理论", "认识", "硬道理", "理解", "实践", "贡献", "思想"],
    "policy_statement": ["讲话", "强调", "指出", "要求", "会议", "部署"],
    "data_report": ["数据显示", "统计", "调查", "报告"],
}

SOURCE_ALIASES = {
    "经济日报": "jjrb",
    "人民日报": "rmrb",
    "新闻联播": "cctv",
    "央视": "cctv",
    "新华社": "xhw",
}


def infer_content_types(query: str) -> list[str]:
    matched = []
    for ctype, signals in QUERY_TYPE_SIGNALS.items():
        if any(s in query for s in signals):
            matched.append(ctype)
    return matched or ["general_news"]


def build_tsquery(query: str) -> str:
    """Build a simple tsquery from query text."""
    # 提取中文词组 (2字以上)
    words = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    if not words:
        return ""
    return " & ".join(words[:6])


async def search_news_v2(
    query: str,
    top_k: int = 5,
    recall_limit: int = 30,
    *,
    source_filter: str | None = None,
    time_floor: float = 0.0,
) -> dict[str, Any]:
    """PG+Qdrant hybrid search."""

    # 1. Embed query
    client = get_embedding_client()
    response = await client.embeddings.create(model=settings.embedding_model, input=[query])
    query_vector = list(response.data[0].embedding)

    # 2. Qdrant 向量召回
    qdrant = get_qdrant()
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    must_conditions = []
    if source_filter:
        must_conditions.append(FieldCondition(key="source_code", match=MatchValue(value=source_filter)))
    if time_floor:
        must_conditions.append(FieldCondition(key="publish_ts", match=MatchValue(value=int(time_floor))))

    query_filter = Filter(must=must_conditions) if must_conditions else None

    kwargs = {
        "collection_name": UNIFIED_COLLECTION,
        "query": query_vector,
        "limit": recall_limit,
        "with_payload": True,
    }
    if query_filter:
        kwargs["query_filter"] = query_filter

    result = await qdrant.query_points(**kwargs)
    points = list(result.points or [])

    if not points:
        return {"items": [], "evidence_ids": [], "query": query, "recall_count": 0}

    # 3. 准备 PG 查询参数
    chunk_meta_ids = [p.payload.get("chunk_meta_id") for p in points if p.payload.get("chunk_meta_id")]
    vector_scores = {p.payload.get("chunk_meta_id"): float(p.score or 0.0) for p in points}
    preferred_types = infer_content_types(query)
    tsquery_str = build_tsquery(query)

    if not chunk_meta_ids:
        return {"items": [], "evidence_ids": [], "query": query, "recall_count": 0}

    # 4. PG 一条 SQL: 元数据 + 全文分 + diversity + content_type 偏好
    async with PgSessionLocal() as session:
        # 构造临时表
        sql = text("""
            WITH vector_hits AS (
                SELECT
                    unnest(:chunk_meta_ids::bigint[]) AS chunk_meta_id,
                    unnest(:vector_scores::float[]) AS vec_score
            ),
            enriched AS (
                SELECT
                    c.id AS chunk_meta_id,
                    c.news_id,
                    c.chunk_type,
                    c.chunk_text,
                    n.source_code,
                    n.source_name,
                    n.title,
                    n.summary,
                    n.content_type,
                    n.entity_tags,
                    n.quality_score,
                    n.publish_ts,
                    n.image_url,
                    n.has_image,
                    v.vec_score,
                    CASE WHEN :tsquery_str != '' THEN ts_rank(c.tsv, to_tsquery('simple', :tsquery_str)) ELSE 0 END AS text_score,
                    CASE
                        WHEN n.content_type = ANY(:preferred_types::text[]) THEN 0.15
                        ELSE 0.0
                    END AS type_bonus,
                    CASE c.chunk_type
                        WHEN 'title' THEN 1.2
                        WHEN 'summary' THEN 1.0
                        WHEN 'body' THEN 0.85
                        ELSE 1.0
                    END AS chunk_weight,
                    ROW_NUMBER() OVER (
                        PARTITION BY n.source_code
                        ORDER BY v.vec_score DESC
                    ) AS source_rank
                FROM vector_hits v
                JOIN news_chunks_meta c ON c.id = v.chunk_meta_id
                JOIN news_unified n ON n.id = c.news_id
            )
            SELECT *, (
                0.45 * vec_score +
                0.25 * text_score +
                0.15 * quality_score +
                0.15 * type_bonus
            ) * chunk_weight AS hybrid_score
            FROM enriched
            ORDER BY
                CASE WHEN source_rank <= 3 THEN 0 ELSE 1 END,
                hybrid_score DESC
            LIMIT :limit
        """)

        result = await session.execute(sql, {
            "chunk_meta_ids": chunk_meta_ids,
            "vector_scores": [vector_scores.get(cid, 0.0) for cid in chunk_meta_ids],
            "tsquery_str": tsquery_str,
            "preferred_types": preferred_types,
            "limit": top_k * 3,  # 多取一些用于聚合
        })
        rows = result.fetchall()

    # 5. 聚合同一新闻的多个 chunk → 取最高分
    best_by_news: dict[int, dict] = {}
    for row in rows:
        nid = row.news_id
        if nid not in best_by_news or row.hybrid_score > best_by_news[nid]["hybrid_score"]:
            best_by_news[nid] = {
                "id": nid,
                "source_code": row.source_code,
                "source_name": row.source_name,
                "title": row.title,
                "summary": row.summary,
                "chunk_text": row.chunk_text,
                "content_type": row.content_type,
                "entity_tags": row.entity_tags,
                "quality_score": float(row.quality_score),
                "publish_ts": int(row.publish_ts),
                "image_url": row.image_url,
                "has_image": row.has_image,
                "hybrid_score": float(row.hybrid_score),
                "vec_score": float(row.vec_score),
                "text_score": float(row.text_score),
                "chunk_type": row.chunk_type,
            }

    parents = sorted(best_by_news.values(), key=lambda x: x["hybrid_score"], reverse=True)[:top_k]

    # 6. 构造 evidence_id
    for p in parents:
        p["evidence_id"] = f"news:{p['source_code']}:{p['id']}"
        p["score"] = round(p["hybrid_score"], 4)

    return {
        "items": parents,
        "evidence_ids": [p["evidence_id"] for p in parents],
        "query": query,
        "recall_count": len(points),
        "preferred_types": preferred_types,
    }
```

### 3.2 更新 eval 支持 v2

文件: `eval/eval_context_rag.py` 追加 v2 路径

在 `_retrieve_once` 函数中添加 v2 分支:

```python
# 在 _retrieve_once 函数开头添加 use_v2 参数
async def _retrieve_once(
    query: str,
    limit: int,
    top_k: int,
    *,
    use_light_rerank: bool = False,
    use_fusion_rerank: bool = False,
    case_type: str = "",
    use_multi_query: bool = False,
    use_v2: bool = False,          # <-- 新增
) -> dict[str, Any]:
    if use_v2:
        from harness.rag_search_v2 import search_news_v2
        start = time.perf_counter()
        result = await search_news_v2(query, top_k=top_k, recall_limit=limit)
        latency_ms = (time.perf_counter() - start) * 1000
        evidence_ids = [p["evidence_id"] for p in result["items"]]
        return {
            "route": "econ_finance_query",
            "rag_route": None,
            "retrieved_evidence_ids": evidence_ids,
            "raw_evidence_ids": evidence_ids,
            "latency_ms": round(latency_ms, 2),
            "collection": "news_chunks_v2",
            "items_count": result["recall_count"],
        }
    # ... 原有 v1 逻辑不变
```

在 `parse_args` 添加:

```python
parser.add_argument("--use-v2", action="store_true", help="Use PG+Qdrant v2 search")
```

在 `evaluate_retrieve_only` 传入:

```python
use_v2=args.use_v2,
```

在 `async_main` 传入:

```python
use_v2=args.use_v2,
```

### 3.3 v2 eval 命令

```bash
python -X utf8 -m eval.eval_context_rag \
  --mode retrieve-only \
  --top-k 20 --metric-k 5 --limit 50 \
  --use-v2 \
  --gold-existence-check \
  --report eval/reports/context_rag_v2_report.md \
  --json-report eval/reports/context_rag_v2_report.json \
  --diagnosis-report eval/reports/context_rag_v2_diagnosis.md \
  --diagnosis-json eval/reports/context_rag_v2_diagnosis.json \
  --failure-report eval/reports/context_rag_v2_failure.md \
  --gold-existence-report eval/reports/context_rag_v2_gold_existence.md \
  --gold-existence-json eval/reports/context_rag_v2_gold_existence.json
```

---

## 阶段 4：Evidence Detail Resolver 更新

### 4.1 修改 resolver 支持 PG

文件: `harness/evidence_detail_resolver.py` 追加 PG 查询路径

```python
async def resolve_evidence_detail_pg(evidence_id: str) -> dict | None:
    """Resolve evidence from PG news_unified table."""
    from config.pg_conf import PgSessionLocal
    from sqlalchemy import text

    # 解析 evidence_id: news:jjrb:12345
    core = evidence_id
    if core.startswith("news:"):
        core = core[5:]
    parts = core.split(":", 1)
    if len(parts) == 2:
        source_code, news_id_str = parts
    else:
        news_id_str = parts[0]
        source_code = None

    try:
        news_id = int(news_id_str)
    except ValueError:
        return None

    async with PgSessionLocal() as session:
        result = await session.execute(text("""
            SELECT id, source_code, source_name, title, summary, body,
                   publish_time, image_url, has_image, content_type, entity_tags
            FROM news_unified
            WHERE id = :news_id
            LIMIT 1
        """), {"news_id": news_id})
        row = result.first()
        if not row:
            return None
        return {
            "evidence_id": f"news:{row.source_code}:{row.id}",
            "news_id": row.id,
            "source_code": row.source_code,
            "source_name": row.source_name,
            "title": row.title,
            "summary": row.summary,
            "content": row.body,
            "publish_time": str(row.publish_time) if row.publish_time else None,
            "image_url": row.image_url,
            "has_image": row.has_image,
            "content_type": row.content_type,
            "entity_tags": row.entity_tags or [],
            "source": "pg_news_unified",
        }
```

在现有 `resolve_evidence_detail` 函数中，将 PG 查询作为优先路径（在 Qdrant 和 JSONL 之前）。

---

## 阶段 5：前端适配

### 5.1 后端 evidence-detail API

在现有 `/api/ai/evidence-detail` 路由中添加 PG 优先查询:

```python
# 在 api/ai_routes.py 或对应路由文件中
@router.get("/api/ai/evidence-detail")
async def evidence_detail(evidence_id: str):
    # 优先查 PG
    result = await resolve_evidence_detail_pg(evidence_id)
    if result:
        return {"status": "ok", "data": result}
    # 回退到旧 resolver
    result = await resolve_evidence_detail(evidence_id)
    if result:
        return {"status": "ok", "data": result}
    return {"status": "not_found", "data": None}
```

### 5.2 前端图片渲染

在 `apps/frontend` 的新闻卡片组件中:

```vue
<!-- 有图才渲染 -->
<img
  v-if="item.has_image && item.image_url"
  :src="item.image_url"
  class="news-image"
/>
<!-- 无图不渲染任何占位图, 不留空白 -->
```

CSS 中确保无图时布局不塌陷:

```css
.news-card {
  display: flex;
  flex-direction: column;
}
.news-card:not(:has(.news-image)) .news-content {
  /* 无图时内容区占满 */
  flex: 1;
}
```

---

## 阶段 6：验证和灰度切换

### 6.1 数据一致性验证

```python
# scripts/verify_v2.py
import asyncio
from config.pg_conf import PgSessionLocal
from config.vector_conf import get_qdrant
from sqlalchemy import text

async def main():
    # PG 计数
    async with PgSessionLocal() as session:
        news_count = (await session.execute(text("SELECT count(*) FROM news_unified"))).scalar()
        chunk_count = (await session.execute(text("SELECT count(*) FROM news_chunks_meta"))).scalar()
        with_img = (await session.execute(text("SELECT count(*) FROM news_unified WHERE has_image"))).scalar()
        by_source = (await session.execute(text("SELECT source_code, count(*) FROM news_unified GROUP BY source_code"))).fetchall()
        by_type = (await session.execute(text("SELECT content_type, count(*) FROM news_unified GROUP BY content_type ORDER BY count DESC"))).fetchall()
        null_hash = (await session.execute(text("SELECT count(*) FROM news_unified WHERE dedup_hash IS NULL"))).scalar()

    print(f"news_unified: {news_count}")
    print(f"news_chunks_meta: {chunk_count}")
    print(f"with_image: {with_img}")
    print(f"without_image: {news_count - with_img}")
    print(f"null_dedup_hash: {null_hash}")
    print(f"\nBy source:")
    for row in by_source:
        print(f"  {row[0]}: {row[1]}")
    print(f"\nBy content_type:")
    for row in by_type:
        print(f"  {row[0]}: {row[1]}")

    # Qdrant 计数
    qdrant = get_qdrant()
    collection = os.getenv("QDRANT_UNIFIED_COLLECTION", "news_chunks_v2")
    info = await qdrant.get_collection(collection_name=collection)
    print(f"\nQdrant {collection}: {info.points_count} points")

    # 一致性检查
    assert info.points_count == chunk_count, f"Mismatch: Qdrant={info.points_count} PG={chunk_count}"
    print("\n[OK] PG and Qdrant counts match")

asyncio.run(main())
```

```bash
python scripts/verify_v2.py
```

### 6.2 Eval 对比 v1 vs v2

```bash
# v1 (当前)
python -X utf8 -m eval.eval_context_rag --mode retrieve-only --top-k 20 --metric-k 5 --limit 50 --light-rerank --report eval/reports/context_rag_v1_final.md --json-report eval/reports/context_rag_v1_final.json

# v2 (新)
python -X utf8 -m eval.eval_context_rag --mode retrieve-only --top-k 20 --metric-k 5 --limit 50 --use-v2 --report eval/reports/context_rag_v2_final.md --json-report eval/reports/context_rag_v2_final.json
```

### 6.3 灰度切换条件

v2 通过以下条件后切换:

```
v2 Recall@5 >= v1 Recall@5
v2 EvidenceRecall@5 >= v1 EvidenceRecall@5
v2 gold_not_in_top20 <= v1 gold_not_in_top20
v2 LatencyP95 <= 1500ms
```

切换方式: 在 `.env` 中设置 `RAG_SEARCH_VERSION=v2`，在 `rag_search.py` 中根据此值选择 v1 或 v2 路径。

---

## 阶段 7：回滚方案

如果 v2 指标不达标:

```bash
# 1. 切回 v1 (改 .env)
RAG_SEARCH_VERSION=v1

# 2. 删除新 collection (可选)
curl -X DELETE http://localhost:6333/collections/news_chunks_v2

# 3. 旧数据完全不受影响 (MySQL + 旧 Qdrant collection 均未改动)

# 4. PG 表保留，分析失败原因后重跑清洗管道
```

---

## 文件清单

### 新建文件

| 文件 | 用途 |
|---|---|
| `sql/pg_rebuild.sql` | PG 建表 |
| `config/pg_conf.py` | PG 连接配置 |
| `scripts/rebuild_pipeline.py` | 数据清洗+迁移管道 |
| `scripts/verify_pg.py` | PG 连接验证 |
| `scripts/verify_v2.py` | 数据一致性验证 |
| `harness/rag_search_v2.py` | PG+Qdrant 检索层 v2 |
| `docs/refactor_pg_qdrant_plan.md` | 本文档 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `.env` / `.env.example` | 追加 PG 和 collection 配置 |
| `eval/eval_context_rag.py` | 添加 --use-v2 路径 |
| `harness/evidence_detail_resolver.py` | 添加 PG 优先查询 |
| `harness/rag_search.py` | 根据 RAG_SEARCH_VERSION 选择 v1/v2 |
| 前端新闻组件 | has_image 条件渲染 |

### 不改动文件

| 文件 | 原因 |
|---|---|
| `harness/reranker.py` | v2 不依赖 cross-encoder |
| `harness/context_manager.py` | query rewrite 逻辑不变 |
| `harness/answer_validator.py` | 不扩大 enforce |
| 旧 MySQL news 表 | 保留不动 |
| 旧 Qdrant collection | 保留不动 |

---

## 执行顺序总览

```
阶段0  环境检查              ← 确认 PG 版本 + 扩展 + 数据源
  ↓
阶段1  PG 建表 + 配置         ← sql/pg_rebuild.sql + config/pg_conf.py
  ↓
阶段2  数据清洗管道            ← 先 dry-run 再 full
  ↓
阶段3  检索层 v2              ← harness/rag_search_v2.py
  ↓
阶段4  Evidence Detail 更新   ← PG 优先查询
  ↓
阶段5  前端适配               ← has_image 条件渲染
  ↓
阶段6  验证 + Eval 对比       ← v1 vs v2 50条 gold
  ↓
  通过 → 灰度切换
  不通过 → 回滚, 分析, 重跑管道
```

## 注意事项

1. Embedding 维度: 建表时 Qdrant collection 的 vector size 必须和实际 embedding 模型维度一致。qwen3-embedding:4b 是 2560 维，bge-m3 是 1024 维。确认后再创建 collection。
2. 磡分词: 如果能装 pg_jieba，把 `sql/pg_rebuild.sql` 里的 `to_tsvector('simple', ...)` 全部改成 `to_tsvector('jieba', ...)`，中文全文检索效果更好。
3. 批量插入: 清洗管道中 PG 批量插入用 500 条/批，Qdrant embedding 用 32 条/批，避免内存溢出。
4. 时间字段: CSV 数据的 publish_time 格式可能不统一，`parse_publish_time` 尝试多种格式，解析失败的条目跳过。
5. 图片处理: 只存 http 开头的 URL，nan/null/占位图一律设为 NULL + has_image=false。
6. 旧数据: 全程不碰旧 MySQL news 表和旧 Qdrant collection，保证可回滚。
