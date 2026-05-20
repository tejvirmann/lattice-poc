-- Rosetta: terminology and unit mapping across systems

CREATE TABLE IF NOT EXISTS term_map (
    id INTEGER PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_term TEXT NOT NULL,
    canonical_term TEXT NOT NULL,
    ontology_code TEXT,
    confidence REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS unit_conversions (
    id INTEGER PRIMARY KEY,
    from_unit TEXT NOT NULL,
    to_unit TEXT NOT NULL,
    factor REAL NOT NULL,
    offset REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS compound_aliases (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    alias TEXT NOT NULL,
    source_system TEXT
);
