#!/usr/bin/env python3
"""
LIMS MCP Server
Provides read-only access to Laboratory Information Management System data.
Exposes: compounds, samples, assay results, instruments.
"""

import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent.parent / "databases" / "lims.db"
mcp = FastMCP("lims", instructions="LIMS — samples, assay results, compounds, instruments")


@mcp.tool()
def health() -> dict:
    """Return server health status."""
    return {"status": "ok", "server": "lims", "db": str(DB_PATH)}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, query, params=()):
    return [dict(r) for r in conn.execute(query, params).fetchall()]

def _one(conn, query, params=()):
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


@mcp.tool()
def list_compounds() -> str:
    """List all compounds tracked in LIMS with drug class and target."""
    conn = _conn()
    rows = _rows(conn, "SELECT * FROM compounds ORDER BY name")
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def search_samples(
    compound_name: str = "",
    matrix: str = "",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """
    Search LIMS samples. All filters are optional.
    - compound_name: partial match against compound name (e.g. "XB-441")
    - matrix: partial match against matrix type (e.g. "Drug Substance")
    - date_from / date_to: ISO date strings (YYYY-MM-DD)
    Returns sample list with compound name joined.
    """
    conn = _conn()
    q = """
        SELECT s.id, c.name AS compound, s.name AS sample_name,
               s.matrix, s.concentration_mg_ml, s.storage_temp,
               s.analyst, s.created_at
        FROM samples s
        JOIN compounds c ON s.compound_id = c.id
        WHERE 1=1
    """
    params = []
    if compound_name:
        q += " AND c.name LIKE ?"
        params.append(f"%{compound_name}%")
    if matrix:
        q += " AND s.matrix LIKE ?"
        params.append(f"%{matrix}%")
    if date_from:
        q += " AND s.created_at >= ?"
        params.append(date_from)
    if date_to:
        q += " AND s.created_at <= ?"
        params.append(date_to)
    q += " ORDER BY s.created_at DESC"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def get_assay_results(
    sample_name: str = "",
    compound_name: str = "",
    assay_name: str = "",
    pass_fail: str = "",
) -> str:
    """
    Retrieve analytical results from LIMS.
    - sample_name: exact or partial sample/lot name
    - compound_name: filter by compound
    - assay_name: filter by assay (e.g. "HPLC Purity", "Endotoxin")
    - pass_fail: "Pass" or "Fail" to filter OOS results
    Returns results with sample, compound, assay, value, unit, and pass/fail status.
    """
    conn = _conn()
    q = """
        SELECT r.id, c.name AS compound, s.name AS sample_name,
               a.name AS assay, r.value, r.unit, r.pass_fail,
               r.analyst, r.run_date, r.notes,
               a.method,
               spec.lo, spec.hi
        FROM results r
        JOIN samples s   ON r.sample_id  = s.id
        JOIN compounds c ON s.compound_id = c.id
        JOIN assays a    ON r.assay_id   = a.id
        LEFT JOIN (
            SELECT name,
                   MIN(lod) AS lo,
                   MAX(loq)  AS hi
            FROM assays GROUP BY name
        ) spec ON spec.name = a.name
        WHERE 1=1
    """
    params = []
    if sample_name:
        q += " AND s.name LIKE ?"
        params.append(f"%{sample_name}%")
    if compound_name:
        q += " AND c.name LIKE ?"
        params.append(f"%{compound_name}%")
    if assay_name:
        q += " AND a.name LIKE ?"
        params.append(f"%{assay_name}%")
    if pass_fail:
        q += " AND r.pass_fail = ?"
        params.append(pass_fail)
    q += " ORDER BY r.run_date DESC"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def get_oos_results(date_from: str = "", date_to: str = "") -> str:
    """
    Get all out-of-spec (OOS) results — pass_fail = 'Fail'.
    Optionally filter by date range (YYYY-MM-DD).
    Useful for deviation investigations and trend analysis.
    """
    conn = _conn()
    q = """
        SELECT r.id, c.name AS compound, s.name AS sample_name,
               a.name AS assay, r.value, r.unit, r.analyst, r.run_date
        FROM results r
        JOIN samples s   ON r.sample_id  = s.id
        JOIN compounds c ON s.compound_id = c.id
        JOIN assays a    ON r.assay_id   = a.id
        WHERE r.pass_fail = 'Fail'
    """
    params = []
    if date_from:
        q += " AND r.run_date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND r.run_date <= ?"
        params.append(date_to)
    q += " ORDER BY r.run_date DESC"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def get_instrument_status() -> str:
    """
    List all analytical instruments with calibration status.
    Flags any instruments with overdue or imminent calibration.
    """
    conn = _conn()
    rows = _rows(conn, "SELECT * FROM instruments ORDER BY calibration_due")
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def compare_compound_results(compound_name: str, assay_name: str) -> str:
    """
    Compare assay results across all samples for a given compound.
    Returns a summary: min, max, mean, pass rate, and individual results.
    Useful for cross-batch trend analysis and tech transfer comparisons.
    """
    conn = _conn()
    rows = _rows(conn, """
        SELECT s.name AS sample_name, s.matrix, r.value, r.unit,
               r.pass_fail, r.run_date
        FROM results r
        JOIN samples s   ON r.sample_id  = s.id
        JOIN compounds c ON s.compound_id = c.id
        JOIN assays a    ON r.assay_id   = a.id
        WHERE c.name LIKE ? AND a.name LIKE ?
        ORDER BY r.run_date
    """, (f"%{compound_name}%", f"%{assay_name}%"))
    conn.close()

    if not rows:
        return json.dumps({"error": "No results found", "compound": compound_name, "assay": assay_name})

    values = [r["value"] for r in rows if r["value"] is not None]
    passes = sum(1 for r in rows if r["pass_fail"] == "Pass")
    summary = {
        "compound": compound_name,
        "assay": assay_name,
        "n": len(rows),
        "min": round(min(values), 4) if values else None,
        "max": round(max(values), 4) if values else None,
        "mean": round(sum(values)/len(values), 4) if values else None,
        "pass_rate_pct": round(passes / len(rows) * 100, 1),
        "results": rows,
    }
    return json.dumps(summary, default=str)


if __name__ == "__main__":
    mcp.run()
