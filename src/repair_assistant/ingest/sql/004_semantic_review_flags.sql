-- Persist LLM rationale and review-board signals on semantic units (ADR-0048).
-- rationale was already produced by the segmenter but never stored; review_flag
-- / review_note let the model mark ambiguous boundaries for human priority.

ALTER TABLE semantic_units
    ADD COLUMN IF NOT EXISTS rationale TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS review_flag TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS review_note TEXT NOT NULL DEFAULT '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'semantic_units_review_flag_chk'
    ) THEN
        ALTER TABLE semantic_units
            ADD CONSTRAINT semantic_units_review_flag_chk
            CHECK (review_flag IN (
                'none',
                'ambiguous_boundary',
                'cross_page_dependency',
                'table_relationship',
                'figure_relationship',
                'warning_scope',
                'diagnostic_dependency',
                'other'
            ));
    END IF;
END $$;
