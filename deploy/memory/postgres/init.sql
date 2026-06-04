-- Phase 2 schema for Shore Assistant hybrid memory.
-- Executed by the postgres:16-alpine entrypoint exactly once, when the data
-- volume is empty. Schema changes after first init must be applied manually
-- or via a future migration tool (Phase 4 may add Alembic).

CREATE TABLE IF NOT EXISTS profile (
    id          SMALLINT PRIMARY KEY DEFAULT 1
                CHECK (id = 1),
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS profile_history (
    id              BIGSERIAL PRIMARY KEY,
    key_path        TEXT NOT NULL,
    old_value       JSONB,
    new_value       JSONB,
    source_turn_ts  DOUBLE PRECISION,
    confidence      REAL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profile_history_key
    ON profile_history(key_path, created_at DESC);

INSERT INTO profile (id, data) VALUES (1, '{}'::jsonb)
    ON CONFLICT (id) DO NOTHING;
