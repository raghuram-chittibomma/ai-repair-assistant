-- Trigram GIN so code_fetch / connector_fetch `text ~*` can use an index
-- (review R15). ADR-0020 rejected FTS ranking; this is recall only.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS chunks_text_trgm_gin
    ON chunks USING gin (text gin_trgm_ops);
