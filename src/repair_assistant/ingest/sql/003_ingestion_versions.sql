-- Per-document ingestion strategy over versioned derived data (ADR-0047).
-- Every chunk row belongs to exactly one ingestion version. Retrieval reads
-- the active_chunks view, so invalidation is one fact in one place.

CREATE TABLE IF NOT EXISTS ingestion_versions (
    id BIGSERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    status TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL DEFAULT '',
    segmenter_model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,
    superseded_by BIGINT REFERENCES ingestion_versions (id) ON DELETE SET NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (doc_id, version),
    CONSTRAINT ingestion_versions_strategy_chk
        CHECK (strategy IN ('structured', 'semantic_llm')),
    CONSTRAINT ingestion_versions_status_chk
        CHECK (status IN ('candidate', 'ready', 'active', 'superseded', 'abandoned'))
);

-- The guardrail that makes a duplicate active representation unrepresentable
-- rather than merely unlikely (ADR-0047 decision 2).
CREATE UNIQUE INDEX IF NOT EXISTS ingestion_versions_one_active
    ON ingestion_versions (doc_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ingestion_versions_doc_status_idx
    ON ingestion_versions (doc_id, status);

-- A semantic knowledge unit: the authoritative source content that reaches the
-- answer-generation LLM. source_text is assembled from parsed chunk bodies, so
-- it is never model prose.
CREATE TABLE IF NOT EXISTS semantic_units (
    id BIGSERIAL PRIMARY KEY,
    ingestion_version_id BIGINT NOT NULL
        REFERENCES ingestion_versions (id) ON DELETE CASCADE,
    unit_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    unit_type TEXT,
    page_start INTEGER,
    page_end INTEGER,
    section_path JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_text TEXT NOT NULL,
    source_span JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'proposed',
    origin TEXT NOT NULL DEFAULT 'llm',
    edits JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ingestion_version_id, unit_key),
    CONSTRAINT semantic_units_review_chk
        CHECK (review_status IN ('proposed', 'edited', 'approved')),
    CONSTRAINT semantic_units_origin_chk
        CHECK (origin IN ('llm', 'llm_edited', 'human'))
);

CREATE INDEX IF NOT EXISTS semantic_units_version_idx
    ON semantic_units (ingestion_version_id, ordinal);

-- One row per segmentation run: the exact context handed to the model and the
-- raw structured output. With semantic_units.origin / .edits this is what makes
-- human corrections reconstructable as training data later.
CREATE TABLE IF NOT EXISTS semantic_proposals (
    id BIGSERIAL PRIMARY KEY,
    ingestion_version_id BIGINT NOT NULL
        REFERENCES ingestion_versions (id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL DEFAULT 1,
    model TEXT,
    prompt_version TEXT,
    prompt_sha256 TEXT,
    llm_input JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_output TEXT NOT NULL DEFAULT '',
    validation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS semantic_proposals_version_idx
    ON semantic_proposals (ingestion_version_id, attempt);

-- Legacy rows keep unit_id / rep_kind NULL. That is what makes the semantic
-- path additive rather than a rewrite.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS ingestion_version_id BIGINT
        REFERENCES ingestion_versions (id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS unit_id BIGINT
        REFERENCES semantic_units (id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS rep_kind TEXT;

-- Backfill: one structured/active version per existing document, so retrieval
-- behaviour is unchanged the moment this migration lands.
INSERT INTO ingestion_versions (
    doc_id, version, strategy, status, source_fingerprint, activated_at
)
SELECT d.doc_id, 1, 'structured', 'active', d.content_fingerprint, d.ingested_at
FROM documents d
WHERE NOT EXISTS (
    SELECT 1 FROM ingestion_versions v WHERE v.doc_id = d.doc_id
);

UPDATE chunks c
SET ingestion_version_id = v.id
FROM ingestion_versions v
WHERE v.doc_id = c.doc_id
  AND v.strategy = 'structured'
  AND v.status = 'active'
  AND c.ingestion_version_id IS NULL;

-- Total by construction: chunks.doc_id has an FK to documents, and the insert
-- above gave every document a version.
ALTER TABLE chunks
    ALTER COLUMN ingestion_version_id SET NOT NULL;

-- (doc_id, chunk_id) is no longer unique: a promoted document holds both its
-- structured rows and its semantic representation rows, and re-segmenting may
-- reuse unit keys across versions.
DO $$
DECLARE
    target_constraint TEXT;
BEGIN
    SELECT c.conname INTO target_constraint
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'chunks'
      AND c.contype = 'u'
      AND array_length(c.conkey, 1) = 2
      AND EXISTS (
          SELECT 1 FROM pg_attribute a
          WHERE a.attrelid = c.conrelid
            AND a.attname = 'doc_id'
            AND a.attnum = ANY (c.conkey)
      )
      AND EXISTS (
          SELECT 1 FROM pg_attribute a
          WHERE a.attrelid = c.conrelid
            AND a.attname = 'chunk_id'
            AND a.attnum = ANY (c.conkey)
      )
    LIMIT 1;

    IF target_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE chunks DROP CONSTRAINT %I', target_constraint);
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS chunks_version_chunk_id_key
    ON chunks (doc_id, ingestion_version_id, chunk_id);

CREATE INDEX IF NOT EXISTS chunks_ingestion_version_idx
    ON chunks (ingestion_version_id);

CREATE INDEX IF NOT EXISTS chunks_unit_id_idx
    ON chunks (unit_id)
    WHERE unit_id IS NOT NULL;

-- Retrieval reads this, never `chunks` (ADR-0047 decision 3). Superseded rows
-- stay stored for audit and comparison; they are simply not in the view.
CREATE OR REPLACE VIEW active_chunks AS
SELECT
    c.id,
    c.doc_id,
    c.chunk_id,
    c.content_hash,
    c.text,
    c.page,
    c.kind,
    c.error_codes,
    c.language,
    c.publication_number,
    c.revision,
    c.metadata,
    c.embedding,
    c.embedding_model,
    c.ingestion_version_id,
    c.unit_id,
    c.rep_kind,
    v.strategy
FROM chunks c
JOIN ingestion_versions v ON v.id = c.ingestion_version_id
WHERE v.status = 'active';
