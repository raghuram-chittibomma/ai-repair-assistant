-- Phase 3 schema: documents + chunks with pgvector embeddings.
-- Applied by repair-corpus db-migrate (idempotent where practical).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    publication_number TEXT,
    revision TEXT,
    source_filename TEXT,
    extractor TEXT,
    corpus_sha256 TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    content_fingerprint TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    kind TEXT,
    error_codes TEXT[] NOT NULL DEFAULT '{}',
    language TEXT,
    publication_number TEXT,
    revision TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768),
    embedding_model TEXT,
    UNIQUE (doc_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS chunks_content_hash_idx ON chunks (content_hash);
CREATE INDEX IF NOT EXISTS chunks_error_codes_gin ON chunks USING gin (error_codes);
CREATE INDEX IF NOT EXISTS chunks_kind_idx ON chunks (kind);

-- NULL embeddings are omitted from the HNSW index by pgvector.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
