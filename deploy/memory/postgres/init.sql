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

-- Raw chat image attachments (disk path + metadata only). Separate from
-- the memory tables above: the agent/LOCOMO worker never read this, it
-- exists purely so a user can view an image they sent again later.
CREATE TABLE IF NOT EXISTS image_attachments (
    id              UUID PRIMARY KEY,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    width           INTEGER,
    height          INTEGER,
    byte_size       INTEGER NOT NULL,
    source_turn_ts  DOUBLE PRECISION NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_image_attachments_user_ts
    ON image_attachments(user_id, source_turn_ts DESC);
