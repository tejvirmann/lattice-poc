#!/usr/bin/env python3
"""
Lattice Manager — persona registry, marketplace browser, session configurator.

Runs at :5000.
- GET  /                         → 3-tab configurator UI
- GET  /api/marketplace          → list marketplace repos
- GET  /api/personas             → list registered personas
- POST /api/personas             → register a new persona
- GET  /api/personas/:id         → persona detail + modules
- DELETE /api/personas/:id       → unregister persona
- POST /api/personas/:id/sync    → trigger sync for one persona
- POST /api/launch               → write opencode.jsonc + restart OpenCode
- GET  /api/status               → OpenCode process status
- POST /api/stop                 → stop OpenCode
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "databases" / "context.db"
GENERATE = ROOT / "scripts" / "generate.py"
SYNC = ROOT / "scripts" / "sync_personas.py"
TEMPLATES = Path(__file__).parent / "templates"

app = FastAPI(title="Lattice Manager")
_opencode_proc: subprocess.Popen | None = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def _rows(conn, q, p=()):
    return [dict(r) for r in conn.execute(q, p).fetchall()]

def _one(conn, q, p=()):
    r = conn.execute(q, p).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------------------
# OpenCode process management
# ---------------------------------------------------------------------------

def start_opencode():
    global _opencode_proc
    stop_opencode()
    _opencode_proc = subprocess.Popen(
        ["opencode", "web"],
        cwd=ROOT,
        env={**os.environ, "OPENCODE_CONFIG": str(ROOT / "opencode.jsonc")},
    )
    print(f"  OpenCode started (pid {_opencode_proc.pid})")


def stop_opencode():
    global _opencode_proc
    if _opencode_proc and _opencode_proc.poll() is None:
        _opencode_proc.terminate()
        try:
            _opencode_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _opencode_proc.kill()
        print("  OpenCode stopped")
    _opencode_proc = None


def run_generate(skills=None, blueprints=None, mcps=None, model=None):
    cmd = [sys.executable, str(GENERATE)]
    if skills:     cmd += ["--skills",     ",".join(skills)]
    if blueprints: cmd += ["--blueprints", ",".join(blueprints)]
    if mcps:       cmd += ["--mcps",       ",".join(mcps)]
    if model:      cmd += ["--model",      model]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def ui():
    return (TEMPLATES / "index.html").read_text()


# ---------------------------------------------------------------------------
# Routes — Marketplace
# ---------------------------------------------------------------------------

@app.get("/api/mcps")
def api_mcps():
    mcps_file = ROOT / "registry" / "mcps.json"
    if not mcps_file.exists():
        return JSONResponse([])
    raw = json.loads(mcps_file.read_text())
    return JSONResponse([
        {"id": k, "description": v.get("description", ""), "systems": v.get("systems", [])}
        for k, v in raw.items()
    ])


@app.get("/api/marketplace")
def api_marketplace(search: str = "", scope: str = ""):
    conn = _conn()
    q = "SELECT * FROM marketplace_repos WHERE 1=1"
    params = []
    if search:
        q += " AND (name LIKE ? OR description LIKE ? OR owner LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if scope:
        q += " AND scope = ?"
        params.append(scope)
    q += " ORDER BY verified DESC, name"
    rows = _rows(conn, q, params)
    conn.close()

    # Mark which marketplace repos are already registered as personas
    conn2 = _conn()
    registered_urls = {r["repo_url"] for r in _rows(conn2, "SELECT repo_url FROM personas WHERE repo_url IS NOT NULL")}
    conn2.close()
    for r in rows:
        r["registered"] = r["repo_url"] in registered_urls

    return JSONResponse(rows)


# ---------------------------------------------------------------------------
# Routes — Personas
# ---------------------------------------------------------------------------

@app.get("/api/personas")
def api_personas(search: str = "", scope: str = ""):
    conn = _conn()
    q = "SELECT * FROM personas WHERE 1=1"
    params = []
    if search:
        q += " AND (name LIKE ? OR description LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if scope:
        q += " AND scope = ?"
        params.append(scope)
    q += " ORDER BY scope, name"
    personas = _rows(conn, q, params)
    conn.close()
    return JSONResponse(personas)


@app.get("/api/personas/{persona_id}")
def api_persona_detail(persona_id: str):
    conn = _conn()
    persona = _one(conn, "SELECT * FROM personas WHERE id = ?", (persona_id,))
    if not persona:
        raise HTTPException(404, f"Persona '{persona_id}' not found")
    modules = _rows(conn, "SELECT * FROM persona_modules WHERE persona_id = ? ORDER BY type, name", (persona_id,))
    last_sync = _one(conn, "SELECT * FROM sync_log WHERE persona_id = ? ORDER BY synced_at DESC LIMIT 1", (persona_id,))
    conn.close()
    return JSONResponse({"persona": persona, "modules": modules, "last_sync": last_sync})


class RegisterPersonaRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    repo_url: str = ""
    branch: str = "main"
    scope: str = "private"


@app.post("/api/personas")
def api_register_persona(req: RegisterPersonaRequest):
    conn = _conn()
    existing = _one(conn, "SELECT id FROM personas WHERE id = ?", (req.id,))
    if existing:
        conn.close()
        raise HTTPException(400, f"Persona '{req.id}' already registered")

    # For repo-backed personas, initial local_path is the cache dir (populated on first sync)
    # For local personas, point to registry/
    local_path = str(ROOT / ".personas" / "cache" / req.id) if req.repo_url else str(ROOT / "registry")

    conn.execute(
        "INSERT INTO personas(id, name, description, repo_url, branch, scope, owner, local_path, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (req.id, req.name, req.description, req.repo_url or None, req.branch,
         req.scope, "local", local_path, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    # If repo-backed, trigger an immediate sync
    if req.repo_url:
        conn.close()
        _trigger_sync(req.id)
    else:
        conn.close()

    return {"status": "registered", "id": req.id}


@app.delete("/api/personas/{persona_id}")
def api_delete_persona(persona_id: str):
    conn = _conn()
    persona = _one(conn, "SELECT * FROM personas WHERE id = ?", (persona_id,))
    if not persona:
        conn.close()
        raise HTTPException(404, f"Persona '{persona_id}' not found")
    conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.post("/api/personas/{persona_id}/sync")
def api_sync_persona(persona_id: str):
    conn = _conn()
    persona = _one(conn, "SELECT * FROM personas WHERE id = ?", (persona_id,))
    conn.close()
    if not persona:
        raise HTTPException(404, f"Persona '{persona_id}' not found")
    if not persona.get("repo_url"):
        return {"status": "skipped", "reason": "local-only persona"}
    _trigger_sync(persona_id)
    return {"status": "synced"}


def _trigger_sync(persona_id: str):
    """Run sync for one persona in a subprocess."""
    subprocess.Popen(
        [sys.executable, str(SYNC), persona_id],
        cwd=ROOT,
    )


# ---------------------------------------------------------------------------
# Routes — Session launch
# ---------------------------------------------------------------------------

class LaunchRequest(BaseModel):
    persona_id: str
    enabled_modules: list[str]   # list of module paths that are ON for this session
    mcps: list[str] = []
    model: str = ""


@app.post("/api/launch")
def api_launch(req: LaunchRequest):
    conn = _conn()
    persona = _one(conn, "SELECT * FROM personas WHERE id = ?", (req.persona_id,))
    if not persona:
        conn.close()
        raise HTTPException(404, f"Persona '{req.persona_id}' not found")

    local_path = Path(persona["local_path"])
    conn.close()

    # Resolve enabled module paths to absolute paths for generate.py instructions
    # generate.py accepts --skills / --blueprints as file slugs relative to registry/
    # For a persona pointing at registry/, we can extract slug from path directly.
    # For a cached repo persona, we pass full paths via a temp instruction override.
    #
    # For the POC: both personas point to registry/, so we use slug-based injection.
    skills = []
    blueprints = []
    for mod_path in req.enabled_modules:
        parts = Path(mod_path).parts
        if not parts:
            continue
        slug = Path(mod_path).stem
        if parts[0] == "skills":
            skills.append(slug)
        elif parts[0] == "blueprints":
            blueprints.append(slug)

    try:
        log = run_generate(
            skills=skills or None,
            blueprints=blueprints or None,
            mcps=req.mcps or None,
            model=req.model or None,
        )
        start_opencode()
        return {"status": "ok", "log": log, "redirect": "http://localhost:4000"}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Routes — Status
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    running = _opencode_proc is not None and _opencode_proc.poll() is None
    return {"opencode_running": running, "pid": _opencode_proc.pid if running else None}


@app.post("/api/stop")
def api_stop():
    stop_opencode()
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print("Lattice Manager → http://localhost:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")
