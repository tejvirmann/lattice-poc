-- QMS: Quality Management System
-- Tracks batch records, deviations, CAPAs, specifications, and audits

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    formulation_type TEXT,
    strength TEXT,
    route_of_admin TEXT,
    target_indication TEXT
);

CREATE TABLE IF NOT EXISTS specifications (
    id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    parameter TEXT NOT NULL,
    min_value REAL,
    max_value REAL,
    unit TEXT,
    test_method TEXT
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    lot_number TEXT UNIQUE NOT NULL,
    manufacture_date TEXT,
    expiry_date TEXT,
    batch_size_kg REAL,
    status TEXT DEFAULT 'In Review'
);

CREATE TABLE IF NOT EXISTS deviations (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER REFERENCES batches(id),
    deviation_number TEXT UNIQUE NOT NULL,
    description TEXT,
    severity TEXT,
    root_cause TEXT,
    status TEXT DEFAULT 'Open',
    opened_date TEXT,
    closed_date TEXT
);

CREATE TABLE IF NOT EXISTS capas (
    id INTEGER PRIMARY KEY,
    deviation_id INTEGER REFERENCES deviations(id),
    capa_number TEXT UNIQUE NOT NULL,
    action_description TEXT,
    owner TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'Open',
    effectiveness_check TEXT
);

CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY,
    type TEXT,
    auditor TEXT,
    date TEXT,
    department TEXT,
    findings_count INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Open'
);
