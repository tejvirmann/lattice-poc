#!/usr/bin/env python3
"""
QMS MCP Server
Provides read-only access to Quality Management System data.
Exposes: batches, specifications, deviations, CAPAs, audits.
"""

import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent.parent / "databases" / "qms.db"
mcp = FastMCP("qms", instructions="QMS — batch records, deviations, CAPAs, specifications, audits")


@mcp.tool()
def health() -> dict:
    """Return server health status."""
    return {"status": "ok", "server": "qms", "db": str(DB_PATH)}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(conn, query, params=()):
    return [dict(r) for r in conn.execute(query, params).fetchall()]


@mcp.tool()
def list_products() -> str:
    """List all products in the QMS with formulation and indication."""
    conn = _conn()
    rows = _rows(conn, "SELECT * FROM products ORDER BY name")
    conn.close()
    return json.dumps(rows)


@mcp.tool()
def get_batch(lot_number: str) -> str:
    """
    Retrieve a batch record by lot number.
    Returns batch details, linked product, and current status.
    """
    conn = _conn()
    rows = _rows(conn, """
        SELECT b.*, p.name AS product_name, p.formulation_type, p.strength
        FROM batches b
        JOIN products p ON b.product_id = p.id
        WHERE b.lot_number LIKE ?
    """, (f"%{lot_number}%",))
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def list_batches(
    product_name: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """
    List batches with optional filters.
    - product_name: partial match (e.g. "Nexivab")
    - status: "Released", "In Review", "On Hold"
    - date_from / date_to: manufacture date range (YYYY-MM-DD)
    """
    conn = _conn()
    q = """
        SELECT b.id, p.name AS product, b.lot_number,
               b.manufacture_date, b.expiry_date,
               b.batch_size_kg, b.status
        FROM batches b
        JOIN products p ON b.product_id = p.id
        WHERE 1=1
    """
    params = []
    if product_name:
        q += " AND p.name LIKE ?"
        params.append(f"%{product_name}%")
    if status:
        q += " AND b.status = ?"
        params.append(status)
    if date_from:
        q += " AND b.manufacture_date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND b.manufacture_date <= ?"
        params.append(date_to)
    q += " ORDER BY b.manufacture_date DESC"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def get_deviations(
    batch_lot: str = "",
    severity: str = "",
    status: str = "",
) -> str:
    """
    Retrieve deviations from QMS.
    - batch_lot: filter by lot number (partial match)
    - severity: "Minor", "Major", "Critical"
    - status: "Open", "Closed"
    Returns deviation details with root cause and associated batch.
    """
    conn = _conn()
    q = """
        SELECT d.*, b.lot_number, p.name AS product
        FROM deviations d
        JOIN batches  b ON d.batch_id   = b.id
        JOIN products p ON b.product_id = p.id
        WHERE 1=1
    """
    params = []
    if batch_lot:
        q += " AND b.lot_number LIKE ?"
        params.append(f"%{batch_lot}%")
    if severity:
        q += " AND d.severity = ?"
        params.append(severity)
    if status:
        q += " AND d.status = ?"
        params.append(status)
    q += " ORDER BY d.opened_date DESC"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def get_open_capas(overdue_only: bool = False) -> str:
    """
    List open CAPAs. Set overdue_only=true to see only past-due actions.
    Returns CAPA details, owner, due date, and linked deviation.
    """
    conn = _conn()
    from datetime import date
    today = date.today().isoformat()
    q = """
        SELECT ca.*, d.deviation_number, d.severity, d.description AS deviation_desc,
               b.lot_number, p.name AS product
        FROM capas ca
        JOIN deviations d ON ca.deviation_id = d.id
        JOIN batches b    ON d.batch_id = b.id
        JOIN products p   ON b.product_id = p.id
        WHERE ca.status = 'Open'
    """
    params = []
    if overdue_only:
        q += " AND ca.due_date < ?"
        params.append(today)
    q += " ORDER BY ca.due_date"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def get_specifications(product_name: str) -> str:
    """
    Retrieve quality specifications for a product.
    Returns all parameters with acceptance limits and test methods.
    """
    conn = _conn()
    rows = _rows(conn, """
        SELECT s.*, p.name AS product_name
        FROM specifications s
        JOIN products p ON s.product_id = p.id
        WHERE p.name LIKE ?
        ORDER BY s.parameter
    """, (f"%{product_name}%",))
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def check_batch_release_status(lot_number: str) -> str:
    """
    Check if a batch is ready for release.
    Returns batch status, any open deviations, and open CAPAs.
    Use this for batch release decision support.
    """
    conn = _conn()
    batch = _rows(conn, """
        SELECT b.*, p.name AS product_name
        FROM batches b JOIN products p ON b.product_id = p.id
        WHERE b.lot_number LIKE ?
    """, (f"%{lot_number}%",))

    if not batch:
        conn.close()
        return json.dumps({"error": f"No batch found for lot {lot_number}"})

    batch_id = batch[0]["id"]
    open_devs = _rows(conn, """
        SELECT deviation_number, severity, description, status
        FROM deviations WHERE batch_id = ? AND status = 'Open'
    """, (batch_id,))
    open_capas = _rows(conn, """
        SELECT ca.capa_number, ca.action_description, ca.owner, ca.due_date
        FROM capas ca JOIN deviations d ON ca.deviation_id = d.id
        WHERE d.batch_id = ? AND ca.status = 'Open'
    """, (batch_id,))

    result = {
        "batch": batch[0],
        "release_status": batch[0]["status"],
        "open_deviations": open_devs,
        "open_capas": open_capas,
        "release_blocked": len(open_devs) > 0 or batch[0]["status"] == "On Hold",
    }
    conn.close()
    return json.dumps(result, default=str)


@mcp.tool()
def get_audit_findings(date_from: str = "", date_to: str = "") -> str:
    """
    List audit findings, optionally filtered by date range.
    Returns audit type, department, finding counts, and status.
    """
    conn = _conn()
    q = "SELECT * FROM audits WHERE 1=1"
    params = []
    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)
    q += " ORDER BY date DESC"
    rows = _rows(conn, q, params)
    conn.close()
    return json.dumps(rows, default=str)


if __name__ == "__main__":
    mcp.run()
