-- Discovery catalog: repos users can browse and add to their Lattice
CREATE TABLE marketplace_repos (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  repo_url    TEXT,
  owner       TEXT,
  scope       TEXT DEFAULT 'public',
  verified    INTEGER DEFAULT 0,
  created_at  TEXT
);

-- Repos cloned/registered locally — browsable, syncable, independent of personas
CREATE TABLE context_repos (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  repo_url    TEXT,             -- NULL for the local built-in registry
  branch      TEXT DEFAULT 'main',
  local_path  TEXT NOT NULL,
  last_hash   TEXT,
  last_synced TEXT,
  created_at  TEXT
);

-- All modules available within a context_repo (rescanned on sync)
CREATE TABLE repo_modules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id     TEXT NOT NULL REFERENCES context_repos(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,   -- relative to local_path
  type        TEXT,            -- skill | blueprint | agent | command
  name        TEXT,
  description TEXT,
  tokens      INTEGER DEFAULT 0
);

-- Named persona bundles: composed from any mix of repos and individual files
CREATE TABLE personas (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  scope       TEXT DEFAULT 'private',
  owner       TEXT,
  created_at  TEXT
);

-- Individual files added to a persona — one row per file, from any repo
-- enabled = default checked state in session view (session can override without saving)
CREATE TABLE persona_modules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  persona_id  TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
  repo_id     TEXT NOT NULL REFERENCES context_repos(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,   -- relative to repo local_path
  type        TEXT,
  name        TEXT,
  description TEXT,
  tokens      INTEGER DEFAULT 0,
  enabled     INTEGER DEFAULT 1
);

-- Sync history for context_repos
CREATE TABLE sync_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id     TEXT,
  synced_at   TEXT,
  status      TEXT,
  message     TEXT
);
