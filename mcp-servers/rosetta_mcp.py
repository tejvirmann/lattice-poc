#!/usr/bin/env python3
"""
Rosetta MCP Server
Cross-system terminology standardization, unit conversion, and compound alias resolution.
Call Rosetta before merging data from multiple systems to ensure consistent terminology.
"""

import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent.parent / "databases" / "rosetta.db"
mcp = FastMCP("rosetta", description="Rosetta — normalize terms, units, and compound names across systems")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, query, params=()):
    return [dict(r) for r in conn.execute(query, params).fetchall()]


@mcp.tool()
def normalize_term(term: str, source_system: str = "") -> str:
    """
    Normalize a term from any system to its canonical form.
    - term: the term as it appears in the source system (e.g. "HPLC Purity", "Released")
    - source_system: optional filter (e.g. "LIMS", "QMS")
    Returns canonical term, ontology code, and confidence.
    """
    conn = _conn()
    q = "SELECT * FROM term_map WHERE source_term LIKE ?"
    params = [f"%{term}%"]
    if source_system:
        q += " AND source_system = ?"
        params.append(source_system)
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """
    Convert a numeric value between units.
    - value: the number to convert
    - from_unit: source unit (e.g. "mg/mL", "EU/mL")
    - to_unit: target unit (e.g. "g/L", "IU/mL")
    Returns converted value, or an error if the conversion is not defined.
    """
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM unit_conversions WHERE from_unit = ? AND to_unit = ?",
        (from_unit, to_unit)
    ).fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"No conversion defined from {from_unit} to {to_unit}"})
    converted = value * row["factor"] + row["offset"]
    return json.dumps({
        "input_value": value,
        "input_unit": from_unit,
        "output_value": round(converted, 6),
        "output_unit": to_unit,
        "factor": row["factor"],
    })


@mcp.tool()
def resolve_compound(alias: str, source_system: str = "") -> str:
    """
    Resolve a compound alias to its canonical name.
    - alias: the name as used in a source system (e.g. "Nexivab", "anti-PD-L1", "XB441")
    - source_system: optional filter (e.g. "QMS", "CTMS")
    Returns the canonical compound name used in LIMS.
    """
    conn = _conn()
    q = "SELECT * FROM compound_aliases WHERE alias LIKE ?"
    params = [f"%{alias}%"]
    if source_system:
        q += " AND source_system = ?"
        params.append(source_system)
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def list_term_mappings(source_system: str = "") -> str:
    """
    List all term mappings, optionally filtered by source system.
    Useful for understanding what terminology a system uses and how it maps to canonical terms.
    """
    conn = _conn()
    q = "SELECT * FROM term_map"
    params = []
    if source_system:
        q += " WHERE source_system = ?"
        params.append(source_system)
    q += " ORDER BY source_system, canonical_term"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def standardize_status(status: str, source_system: str) -> str:
    """
    Convert a system-specific status value to its canonical meaning.
    Example: QMS "Released" → "Conforming", LIMS "Pass" → "Conforming".
    Essential when comparing pass/fail or status values across systems.
    """
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM term_map WHERE source_term = ? AND source_system = ?",
        (status, source_system)
    ).fetchone()
    conn.close()
    if not row:
        return json.dumps({"input": status, "system": source_system, "canonical": status, "note": "No mapping found — using original"})
    return json.dumps(dict(row))


if __name__ == "__main__":
    mcp.run()
