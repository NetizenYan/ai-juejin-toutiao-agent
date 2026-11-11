CREATE TABLE IF NOT EXISTS news_unified (
  id BIGSERIAL PRIMARY KEY,
  evidence_id TEXT UNIQUE NOT NULL,
  doc_id TEXT,
  source_code TEXT,
  source_doc_id TEXT,
  title TEXT,
  publish_time TIMESTAMPTZ,
  publish_ts BIGINT DEFAULT 0,
  section TEXT DEFAULT '',
  category TEXT DEFAULT '',
  url TEXT DEFAULT '',
  content TEXT,
  content_length INTEGER DEFAULT 0,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_news_unified_source_ts
  ON news_unified (source_code, publish_ts DESC);

CREATE INDEX IF NOT EXISTS idx_news_unified_doc_id
  ON news_unified (doc_id);

CREATE TABLE IF NOT EXISTS news_chunks_meta (
  id BIGSERIAL PRIMARY KEY,
  evidence_id TEXT NOT NULL REFERENCES news_unified(evidence_id) ON DELETE CASCADE,
  chunk_id TEXT UNIQUE NOT NULL,
  chunk_type TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT,
  collection_name TEXT NOT NULL,
  vector_model TEXT NOT NULL,
  vector_dim INTEGER NOT NULL,
  qdrant_point_id BIGINT NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_news_chunks_meta_evidence_id
  ON news_chunks_meta (evidence_id);

CREATE INDEX IF NOT EXISTS idx_news_chunks_meta_collection_model
  ON news_chunks_meta (collection_name, vector_model, vector_dim);

CREATE INDEX IF NOT EXISTS idx_news_chunks_meta_point_id
  ON news_chunks_meta (qdrant_point_id);
