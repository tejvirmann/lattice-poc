#!/usr/bin/env python3
"""
Seed all Lattice databases with realistic biologics data.
Run once: python scripts/seed_databases.py
Re-run any time to reset to clean state.
"""

import sqlite3
from pathlib import Path
from datetime import date, timedelta
import random

ROOT = Path(__file__).parent.parent
SEED_DIR = ROOT / "databases" / "seed"
DB_DIR = ROOT / "databases"

random.seed(42)  # reproducible

def date_str(d): return d.isoformat()
def days_ago(n): return date_str(date.today() - timedelta(days=n))
def days_from_now(n): return date_str(date.today() + timedelta(days=n))


# ---------------------------------------------------------------------------
# LIMS
# ---------------------------------------------------------------------------

def seed_lims():
    db_path = DB_DIR / "lims.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((SEED_DIR / "lims.sql").read_text())

    conn.executemany("INSERT INTO compounds VALUES (?,?,?,?,?,?,?)", [
        (1, "XB-441",  "XB-441-MAB",  148200, "IgG1 mAb",       "Monoclonal Antibody",     "PD-L1"),
        (2, "KL-872",  "KL-872-ADC",  152400, "IgG1-DM1 ADC",   "Antibody-Drug Conjugate", "HER2"),
        (3, "ZM-103",  "1029384-75-2", 438.5, "C24H26N4O4S",    "Kinase Inhibitor",        "CDK4/6"),
        (4, "AB-290",  "AB-290-BSP",  195000, "Bispecific IgG",  "Bispecific Antibody",     "CD3xCD19"),
    ])

    conn.executemany("INSERT INTO instruments VALUES (?,?,?,?,?,?,?)", [
        (1, "HPLC-01",   "HPLC",            "Agilent 1290",         "AG1290-4471", days_from_now(87),  "Operational"),
        (2, "SEC-01",    "SEC-HPLC",        "Waters Alliance e2695", "WT-ALC-0023", days_from_now(52),  "Operational"),
        (3, "BCA-01",    "Spectrophotometer","BioTek Epoch 2",       "BT-EP-0091", days_from_now(41),  "Operational"),
        (4, "LAL-01",    "Endotoxin Reader", "Charles River PTS",    "CR-PTS-007", days_from_now(130), "Operational"),
        (5, "OSM-01",    "Osmometer",        "Wescor Vapro 5600",    "WV-5600-003", days_from_now(-5),  "Calibration Due"),
    ])

    conn.executemany("INSERT INTO assays VALUES (?,?,?,?,?,?,?)", [
        (1, "HPLC Purity",          "RP-HPLC",          "%",        0.05, 0.1,  1),
        (2, "SEC Aggregate",        "SEC-HPLC",          "%",        0.1,  0.2,  1),
        (3, "Protein Concentration","BCA Assay",         "mg/mL",    0.05, 0.1,  1),
        (4, "Endotoxin",            "LAL Kinetic",       "EU/mL",    0.01, 0.05, 1),
        (5, "Bioassay Potency",     "Cell-Based Assay",  "% Ref",    5.0,  10.0, 1),
        (6, "Osmolality",           "Vapor Pressure Osm","mOsm/kg",  None, None, 1),
        (7, "pH",                   "Potentiometric",    "pH units", None, None, 1),
        (8, "Sub-Visible Particles","MFI",               "particles/mL", None, None, 1),
    ])

    samples = []
    sid = 1
    analysts = ["R. Patel", "S. Kim", "M. Okonkwo", "A. Reyes", "L. Chen"]
    matrices = ["Drug Substance", "Drug Product", "In-Process", "Reference Standard"]
    for cid in range(1, 5):
        for batch_num in range(1, 7):
            conc = round(random.uniform(5.0, 25.0), 2)
            samples.append((
                sid, cid,
                f"LOT-{cid:02d}{batch_num:03d}",
                random.choice(matrices),
                conc,
                "-20°C" if cid in (1, 2, 4) else "25°C",
                random.choice(analysts),
                days_ago(random.randint(30, 365)),
            ))
            sid += 1
    conn.executemany("INSERT INTO samples VALUES (?,?,?,?,?,?,?,?)", samples)

    results = []
    rid = 1
    pass_ranges = {
        1: (97.0, 100.0),  # HPLC Purity ≥ 97%
        2: (0.0, 2.0),     # SEC Aggregate ≤ 2%
        3: (18.0, 22.0),   # Protein Conc 18-22 mg/mL
        4: (0.0, 0.5),     # Endotoxin ≤ 0.5 EU/mL
        5: (80.0, 120.0),  # Potency 80-120%
        6: (270, 310),     # Osmolality 270-310 mOsm/kg
        7: (6.5, 7.2),     # pH 6.5-7.2
        8: (0, 6000),      # Sub-Vis ≤ 6000/mL
    }
    for sample in samples:
        sample_id = sample[0]
        for assay_id in range(1, 9):
            lo, hi = pass_ranges[assay_id]
            # ~10% chance of OOS
            if random.random() < 0.10:
                value = round(random.choice([lo - abs(lo)*0.05, hi + abs(hi)*0.05]), 3)
                pf = "Fail"
            else:
                value = round(random.uniform(lo + (hi-lo)*0.1, hi - (hi-lo)*0.1), 3)
                pf = "Pass"
            instrument_id = random.choice([1, 2, 3, 4, 5])
            results.append((
                rid, sample_id, assay_id, instrument_id,
                value, list(pass_ranges.keys())[assay_id-1],
                pf, random.choice(analysts),
                days_ago(random.randint(1, 300)),
                None,
            ))
            rid += 1
    # Fix unit column — use correct unit strings
    unit_map = {1:"%", 2:"%", 3:"mg/mL", 4:"EU/mL", 5:"% Ref", 6:"mOsm/kg", 7:"pH units", 8:"particles/mL"}
    results = [(r[0],r[1],r[2],r[3],r[4],unit_map[r[2]],r[6],r[7],r[8],r[9]) for r in results]
    conn.executemany("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?)", results)

    conn.commit()
    conn.close()
    print(f"  LIMS: {len(samples)} samples, {len(results)} results")


# ---------------------------------------------------------------------------
# QMS
# ---------------------------------------------------------------------------

def seed_qms():
    db_path = DB_DIR / "qms.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((SEED_DIR / "qms.sql").read_text())

    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", [
        (1, "Nexivab",  "Liquid Concentrate", "25 mg/mL", "IV Infusion", "NSCLC, Melanoma"),
        (2, "Keltara",  "Lyophilized Powder",  "20 mg vial", "IV Infusion", "HER2+ Breast Cancer"),
        (3, "Zomaclib", "Film-coated Tablet",  "50 mg",     "Oral",        "HR+ Breast Cancer"),
    ])

    specs = []
    spec_id = 1
    spec_defs = {
        1: [  # Nexivab
            ("HPLC Purity",         97.0, 100.0, "%",       "RP-HPLC USP <621>"),
            ("SEC Aggregate",        0.0,   2.0,  "%",       "SEC-HPLC"),
            ("Protein Concentration",23.0,  27.0, "mg/mL",   "BCA Assay"),
            ("Endotoxin",            0.0,   0.5,  "EU/mL",   "LAL Kinetic"),
            ("Bioassay Potency",     80.0, 120.0, "% Ref",   "Cell-Based"),
            ("Osmolality",          270.0, 310.0, "mOsm/kg", "Vapro Osmometer"),
            ("pH",                    6.5,   7.2,  "pH",      "Potentiometric"),
        ],
        2: [  # Keltara
            ("HPLC Purity",         98.0, 100.0, "%",       "RP-HPLC"),
            ("Reconstitution Time",  0.0,   5.0,  "min",     "Visual Inspection"),
            ("Moisture Content",     0.0,   2.0,  "%",       "KF Coulometric"),
            ("Protein Concentration",19.0,  21.0, "mg/mL",   "UV Absorbance"),
            ("Bioassay Potency",     75.0, 125.0, "% Ref",   "ELISA"),
        ],
        3: [  # Zomaclib
            ("Assay",                98.0, 102.0, "%",       "RP-HPLC"),
            ("Dissolution (30 min)", 80.0, 100.0, "%",       "USP Apparatus II"),
            ("Related Substances",   0.0,   0.2,  "%",       "RP-HPLC"),
            ("Water Content",        0.0,   3.0,  "%",       "KF"),
        ],
    }
    for product_id, sdefs in spec_defs.items():
        for name, lo, hi, unit, method in sdefs:
            specs.append((spec_id, product_id, name, lo, hi, unit, method))
            spec_id += 1
    conn.executemany("INSERT INTO specifications VALUES (?,?,?,?,?,?,?)", specs)

    batches = []
    mfg_start = date.today() - timedelta(days=400)
    product_cycle = [1, 1, 2, 1, 3, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2, 1, 3, 2, 1, 1]
    statuses = ["Released", "Released", "Released", "In Review", "On Hold", "Released"]
    for i, pid in enumerate(product_cycle):
        mfg_date = mfg_start + timedelta(days=i*18)
        exp_date = mfg_date + timedelta(days=730)
        prefix = {1: "NXV", 2: "KLT", 3: "ZOM"}[pid]
        batches.append((
            i+1, pid,
            f"{prefix}-{2024 + i//12}-{(i%12)+1:03d}",
            date_str(mfg_date),
            date_str(exp_date),
            round(random.uniform(2.0, 8.0), 2),
            random.choice(statuses),
        ))
    conn.executemany("INSERT INTO batches VALUES (?,?,?,?,?,?,?)", batches)

    deviations = [
        (1,  3,  "DEV-2025-001", "Temperature excursion during cold chain transport. Unit refrigerator alarm triggered at +12°C for 4 hours.", "Major",   "Equipment failure — temperature logger malfunction",           "Closed", days_ago(310), days_ago(270)),
        (2,  5,  "DEV-2025-002", "HPLC purity result 96.2% against spec ≥97.0%. Single replicate, repeat analysis pending.",                "Major",   "Column degradation — mobile phase pH drift",                   "Closed", days_ago(290), days_ago(250)),
        (3,  8,  "DEV-2025-003", "Bioassay potency result 76% (spec 80-120%). Repeated; second result 118%. Assignable cause investigation.", "Critical","Cell passage number exceeded — cell bank refresh required",     "Open",   days_ago(240), None),
        (4,  10, "DEV-2025-004", "Batch yield 1.8 kg against target 4.0 kg. Process step 3 (diafiltration) membrane integrity failure.",     "Critical","Membrane defect — supplier quality issue (Lot TF-8821)",       "Open",   days_ago(180), None),
        (5,  12, "DEV-2025-005", "Endotoxin result 0.62 EU/mL (spec ≤0.5). Repeat in progress. Potential BET reagent sensitivity issue.",   "Major",   "Pending investigation",                                        "Open",   days_ago(45),  None),
        (6,  14, "DEV-2025-006", "Documentation error — batch record page 12 missing analyst signature. Administrative deviation.",           "Minor",   "Training gap — new analyst unfamiliar with SOP QA-112",        "Closed", days_ago(120), days_ago(110)),
        (7,  16, "DEV-2025-007", "Sub-visible particle count 8,200/mL (spec ≤6,000). Linked to vial washing equipment maintenance gap.",     "Major",   "Vial washer nozzle blockage — maintenance schedule overdue",    "Open",   days_ago(60),  None),
        (8,  18, "DEV-2025-008", "SEC aggregate 2.3% (spec ≤2.0%). Marginally OOS. Root cause: hold time extension during manufacturing.",   "Minor",   "Hold time exceeded SOP limit by 2 hours",                      "Closed", days_ago(95),  days_ago(80)),
    ]
    conn.executemany("INSERT INTO deviations VALUES (?,?,?,?,?,?,?,?,?)", deviations)

    capas = [
        (1, 1, "CAPA-2025-001", "Replace all cold chain temperature loggers with dual-redundant units. Update SOP QA-045 section 7.",  "J. Martinez",   days_from_now(-200), "Closed", "Effective — zero excursions in 6 months post-implementation"),
        (2, 2, "CAPA-2025-002", "Implement column lifetime tracking system. Add column wash step after every 50 injections.",           "S. Kim",         days_from_now(-150), "Closed", "Effective — HPLC purity trending improved"),
        (3, 3, "CAPA-2025-003", "Establish cell bank passage limits in SOP. Generate new working cell bank (WCB-2025-03).",             "M. Okonkwo",     days_from_now(30),   "Open",   None),
        (4, 4, "CAPA-2025-004", "Audit membrane supplier qualification. Add incoming QC test for membrane integrity before use.",       "R. Patel",       days_from_now(15),   "Open",   None),
        (5, 5, "CAPA-2025-005", "Requalify BET reagent lot. Run positive product control at 2x concentration.",                         "L. Chen",        days_from_now(7),    "Open",   None),
        (6, 6, "CAPA-2025-006", "GMP training refresh for all analysts. Add dual-verification step for batch record signatures.",       "A. Reyes",       days_from_now(-80),  "Closed", "Effective — zero documentation deviations in 90 days"),
        (7, 7, "CAPA-2025-007", "Revise vial washer PM schedule from quarterly to monthly. Add pre-batch nozzle integrity check.",      "J. Martinez",    days_from_now(21),   "Open",   None),
        (8, 8, "CAPA-2025-008", "Update hold time SOP to include 2-hour buffer with mandatory approval. Retrain manufacturing team.",   "S. Kim",         days_from_now(-55),  "Closed", "Effective"),
    ]
    conn.executemany("INSERT INTO capas VALUES (?,?,?,?,?,?,?,?)", capas)

    audits = [
        (1, "Internal GMP Audit",    "Quality Assurance Team",    days_ago(320), "Manufacturing",     8, 1, "Closed"),
        (2, "Partner Site Audit",    "External QA Consultant",    days_ago(210), "QC Laboratory",     5, 0, "Closed"),
        (3, "Regulatory Mock Audit", "Internal QA + Regulatory",  days_ago(150), "All Departments",   12, 2, "Closed"),
        (4, "Internal GMP Audit",    "Quality Assurance Team",    days_ago(60),  "Warehouse/Logistics",3, 0, "Open"),
    ]
    conn.executemany("INSERT INTO audits VALUES (?,?,?,?,?,?,?,?)", audits)

    conn.commit()
    conn.close()
    print(f"  QMS: {len(batches)} batches, {len(deviations)} deviations, {len(capas)} CAPAs")


# ---------------------------------------------------------------------------
# Rosetta
# ---------------------------------------------------------------------------

def seed_rosetta():
    db_path = DB_DIR / "rosetta.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((SEED_DIR / "rosetta.sql").read_text())

    terms = [
        (1,  "LIMS",  "HPLC Purity",           "Purity by RP-HPLC",     "CHEMINF:000455", 1.0),
        (2,  "QMS",   "HPLC Purity",            "Purity by RP-HPLC",     "CHEMINF:000455", 1.0),
        (3,  "LIMS",  "SEC Aggregate",           "Aggregation by SEC",     "MS:1001861",     1.0),
        (4,  "QMS",   "SEC Aggregate",           "Aggregation by SEC",     "MS:1001861",     1.0),
        (5,  "LIMS",  "Protein Concentration",   "Protein Content",        "BAO:0002624",    1.0),
        (6,  "QMS",   "Protein Concentration",   "Protein Content",        "BAO:0002624",    1.0),
        (7,  "LIMS",  "Endotoxin",               "Bacterial Endotoxin",    "NCIT:C71572",    1.0),
        (8,  "QMS",   "Endotoxin",               "Bacterial Endotoxin",    "NCIT:C71572",    1.0),
        (9,  "LIMS",  "Bioassay Potency",        "Relative Potency",       "NCIT:C41394",    1.0),
        (10, "QMS",   "Bioassay Potency",        "Relative Potency",       "NCIT:C41394",    1.0),
        (11, "LIMS",  "Sub-Visible Particles",   "Subvisible Particulates","NCIT:C134010",   1.0),
        (12, "LIMS",  "Osmolality",              "Osmolality",             "NCIT:C64547",    1.0),
        (13, "QMS",   "Osmolality",              "Osmolality",             "NCIT:C64547",    1.0),
        (14, "LIMS",  "Pass",                    "Conforming",             None,             1.0),
        (15, "QMS",   "Released",                "Conforming",             None,             1.0),
        (16, "QMS",   "On Hold",                 "Non-Conforming",         None,             0.9),
        (17, "LIMS",  "Fail",                    "Non-Conforming",         None,             1.0),
        (18, "QMS",   "In Review",               "Pending",                None,             1.0),
        (19, "LIMS",  "Drug Substance",          "Bulk Drug Substance",    "NCIT:C48817",    1.0),
        (20, "QMS",   "Major",                   "Major Deviation",        "GMP:DEV-MAJ",    1.0),
        (21, "QMS",   "Critical",                "Critical Deviation",     "GMP:DEV-CRIT",   1.0),
        (22, "QMS",   "Minor",                   "Minor Deviation",        "GMP:DEV-MIN",    1.0),
    ]
    conn.executemany("INSERT INTO term_map VALUES (?,?,?,?,?,?)", terms)

    units = [
        (1, "mg/mL",    "g/L",      1.0,    0),
        (2, "g/L",      "mg/mL",    1.0,    0),
        (3, "EU/mL",    "IU/mL",    10.0,   0),
        (4, "mOsm/kg",  "Osm/kg",   0.001,  0),
        (5, "% Ref",    "%",        1.0,    0),
        (6, "pH units", "pH",       1.0,    0),
        (7, "g",        "mg",       1000.0, 0),
        (8, "mg",       "g",        0.001,  0),
        (9, "kg",       "g",        1000.0, 0),
    ]
    conn.executemany("INSERT INTO unit_conversions VALUES (?,?,?,?,?)", units)

    aliases = [
        (1, "XB-441", "Nexivab",      "QMS"),
        (2, "XB-441", "XB441",        "ELN"),
        (3, "XB-441", "anti-PD-L1",   "CTMS"),
        (4, "KL-872", "Keltara",      "QMS"),
        (5, "KL-872", "KL872",        "ELN"),
        (6, "KL-872", "HER2-ADC",     "CTMS"),
        (7, "ZM-103", "Zomaclib",     "QMS"),
        (8, "ZM-103", "CDK4/6i",      "CTMS"),
        (9, "AB-290", "AB290",        "ELN"),
    ]
    conn.executemany("INSERT INTO compound_aliases VALUES (?,?,?,?)", aliases)

    conn.commit()
    conn.close()
    print(f"  Rosetta: {len(terms)} term mappings, {len(units)} unit conversions, {len(aliases)} aliases")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Seeding Lattice databases...")
    DB_DIR.mkdir(exist_ok=True)
    seed_lims()
    seed_qms()
    seed_rosetta()
    print("Done. Databases written to databases/")
