-- context.db: persona registry, marketplace catalog, sync log

CREATE TABLE IF NOT EXISTS marketplace_repos (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    repo_url    TEXT NOT NULL,
    owner       TEXT,
    scope       TEXT DEFAULT 'public',   -- public | team | private
    verified    INTEGER DEFAULT 0,       -- 1 = marketplace-approved
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS personas (
    id          TEXT PRIMARY KEY,        -- slug, e.g. "qc-analyst"
    name        TEXT NOT NULL,
    description TEXT,
    repo_url    TEXT,                    -- null for local-only personas
    branch      TEXT DEFAULT 'main',
    scope       TEXT DEFAULT 'private',  -- public | team | private
    owner       TEXT,
    last_synced TEXT,
    last_hash   TEXT,                    -- last git commit hash pulled
    local_path  TEXT NOT NULL,           -- where modules are cached / live
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS persona_modules (
    id                  INTEGER PRIMARY KEY,
    persona_id          TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    path                TEXT NOT NULL,   -- relative to persona local_path
    type                TEXT,            -- skill | blueprint | agent | command
    name                TEXT,
    description         TEXT,
    tokens              INTEGER DEFAULT 0,
    enabled_by_default  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY,
    persona_id  TEXT,
    synced_at   TEXT,
    status      TEXT,   -- ok | error | no-change
    message     TEXT
);
