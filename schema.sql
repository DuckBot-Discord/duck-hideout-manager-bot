-- noinspection SpellCheckingInspectionForFile

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS timers (
    id BIGSERIAL PRIMARY KEY,
    precise BOOLEAN DEFAULT TRUE,
    event TEXT,
    extra JSONB,
    created TIMESTAMP,
    expires TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blocks (
    guild_id BIGINT,
    channel_id BIGINT,
    user_id BIGINT,
    PRIMARY KEY (guild_id, channel_id, user_id)
);

-- Thanks chai :)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'blacklist_type') THEN
        CREATE TYPE blacklist_type AS ENUM ('guild', 'channel', 'user');
    END IF;
END$$;


CREATE TABLE IF NOT EXISTS blacklist (
    blacklist_type blacklist_type,
    entity_id bigint,
    guild_id bigint NOT NULL default 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reason TEXT,
    PRIMARY KEY (blacklist_type, entity_id, guild_id)
);

-- For tags.
CREATE TABLE IF NOT EXISTS tags (
    id BIGSERIAL,
    name VARCHAR(200),
    content VARCHAR(2000),
    owner_id BIGINT,
    guild_id BIGINT,
    uses INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE
        NOT NULL DEFAULT NOW(),
    points_to BIGINT
        REFERENCES tags(id)
            ON DELETE CASCADE,
    embed JSONB,
    PRIMARY KEY (id),
    UNIQUE (name, guild_id),
    CONSTRAINT tags_mutually_excl_cnt_p_to CHECK (
            ((content IS NOT NULL OR embed IS NOT NULL) and points_to IS NULL)
            OR (points_to IS NOT NULL and (content IS NULL AND embed IS NULL))
        )
);

CREATE INDEX IF NOT EXISTS tags_name_ind ON tags (name);
CREATE INDEX IF NOT EXISTS tags_location_id_ind ON tags (guild_id);
-- noinspection SqlResolve
CREATE INDEX IF NOT EXISTS tags_name_trgm_ind ON tags USING GIN (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS tags_name_lower_ind ON tags (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS tags_uniq_ind ON tags (LOWER(name), guild_id);

CREATE TABLE commands (
    user_id BIGINT NOT NULL,
    guild_id  BIGINT,
    command   TEXT NOT NULL ,
    timestamp TIMESTAMP WITH TIME ZONE
        NOT NULL DEFAULT NOW()
);
