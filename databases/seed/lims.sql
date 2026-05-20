-- LIMS: Laboratory Information Management System
-- Tracks compounds, samples, assays, and analytical results

CREATE TABLE IF NOT EXISTS compounds (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cas_number TEXT,
    molecular_weight REAL,
    formula TEXT,
    drug_class TEXT,
    target TEXT
);

CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    model TEXT,
    serial TEXT,
    calibration_due TEXT,
    status TEXT DEFAULT 'Operational'
);

CREATE TABLE IF NOT EXISTS assays (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    method TEXT,
    unit TEXT,
    lod REAL,
    loq REAL,
    validated INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    compound_id INTEGER REFERENCES compounds(id),
    name TEXT NOT NULL,
    matrix TEXT,
    concentration_mg_ml REAL,
    storage_temp TEXT,
    analyst TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    sample_id INTEGER REFERENCES samples(id),
    assay_id INTEGER REFERENCES assays(id),
    instrument_id INTEGER REFERENCES instruments(id),
    value REAL,
    unit TEXT,
    pass_fail TEXT,
    analyst TEXT,
    run_date TEXT,
    notes TEXT
);
