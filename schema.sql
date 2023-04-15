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

CREATE TABLE IF NOT EXISTS addbot (
    owner_id bigint NOT NULL,
    bot_id bigint NOT NULL UNIQUE,
    added boolean DEFAULT false NOT NULL,
    pending boolean DEFAULT true NOT NULL,
    reason text,
    PRIMARY KEY (owner_id, bot_id)
);

-- Thanks chai :) and Laggy
DO $$
BEGIN
        CREATE TYPE blacklist_type AS ENUM ('guild', 'channel', 'user');
    EXCEPTION
        WHEN duplicate_object THEN null;
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

CREATE TABLE IF NOT EXISTS message_info (
    author_id BIGINT,
    message_id BIGINT,
    channel_id BIGINT,
    embed_count INT,
    attachment_count INT,
    created_at TIMESTAMP WITH TIME ZONE,
    edited_at TIMESTAMP WITH TIME ZONE,
    deleted BOOLEAN DEFAULT FALSE,
    is_bot BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (message_id, channel_id)
);

CREATE TABLE IF NOT EXISTS status_history(
    user_id BIGINT, 
    status TEXT, 
    changed_at TIMESTAMP WITH TIME ZONE
);

DO $$
BEGIN
        CREATE TYPE archive_mode AS ENUM ('leave', 'inactive', 'manual');
    EXCEPTION
        WHEN duplicate_object THEN null;
END$$;

CREATE TABLE IF NOT EXISTS pits (
    pit_id BIGINT UNIQUE,
    pit_owner BIGINT UNIQUE,
    archive_mode archive_mode
);

CREATE TABLE IF NOT EXISTS user_settings(
    user_id BIGINT PRIMARY KEY,
    timezone TEXT
);