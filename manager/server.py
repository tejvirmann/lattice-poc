#!/usr/bin/env python3
"""
Lattice Manager — context repo registry, persona builder, session configurator.

Runs at :5000.

Repos (context_repos):
  GET  /api/repos                      → list registered repos with module count
  POST /api/repos                      → register a repo (triggers sync if remote)
  GET  /api/repos/:id                  → repo detail + all available modules
  DELETE /api/repos/:id                → remove repo (blocks 'local')
  POST /api/repos/:id/sync             → trigger sync

Personas:
  GET  /api/personas                   → list personas with module count
  POST /api/personas                   → create a persona
  GET  /api/personas/:id               → persona detail + modules (with repo info)
  DELETE /api/personas/:id             → delete persona
  POST /api/personas/:id/modules       → add a module (or all modules from a repo)
  DELETE /api/personas/:id/modules/:mid → remove a module
  PATCH /api/personas/:id/modules/:mid  → toggle enabled default

Session:
  POST /api/launch                     → write opencode.jsonc + restart OpenCode
  GET  /api/status                     → OpenCode process status
  POST /api/stop                       → stop OpenCode

Misc:
  GET  /api/mcps                       → MCP list from registry/mcps.json
  GET  /api/marketplace                → marketplace catalog
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "databases" / "context.db"
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


def _resolve_model(override: str = "") -> str:
    if override:
        return override
    env_path = ROOT / ".env"
    provider, model = "ollama", "qwen3:8b"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "PROVIDER":
                provider = v
            elif k == "OLLAMA_MODEL" and provider == "ollama":
                model = v
            elif k == "OPENROUTER_MODEL" and provider == "openrouter":
                model = v
    return f"{provider}/{model}"


def _write_opencode_config(instruction_paths: list[str], mcp_ids: list[str], model: str) -> None:
    mcps_file = ROOT / "registry" / "mcps.json"
    all_mcps = json.loads(mcps_file.read_text()) if mcps_file.exists() else {}
    mcp_section = {
        k: {"type": "local", "command": v["command"], "enabled": True}
        for k, v in all_mcps.items()
        if k in mcp_ids
    }
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "instructions": [str(ROOT / "registry" / "context.md")] + instruction_paths,
        "mcp": mcp_section,
        "server": {"hostname": "0.0.0.0", "port": 4000},
    }
    (ROOT / "opencode.jsonc").write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def ui():
    return (TEMPLATES / "index.html").read_text()


# ---------------------------------------------------------------------------
# Routes — Misc
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

    # Mark repos already added to context_repos
    added_urls = {r["repo_url"] for r in _rows(conn, "SELECT repo_url FROM context_repos WHERE repo_url IS NOT NULL")}
    conn.close()
    for r in rows:
        r["added"] = r["repo_url"] in added_urls
    return JSONResponse(rows)


# ---------------------------------------------------------------------------
# Routes — Context Repos
# ---------------------------------------------------------------------------

@app.get("/api/repos")
def api_repos():
    conn = _conn()
    repos = _rows(conn, "SELECT * FROM context_repos ORDER BY id = 'local' DESC, name")
    for r in repos:
        r["module_count"] = conn.execute(
            "SELECT COUNT(*) FROM repo_modules WHERE repo_id = ?", (r["id"],)
        ).fetchone()[0]
        r["last_sync"] = _one(conn, "SELECT * FROM sync_log WHERE repo_id = ? ORDER BY synced_at DESC LIMIT 1", (r["id"],))
    conn.close()
    return JSONResponse(repos)


class CreateRepoRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    repo_url: str = ""
    branch: str = "main"


@app.post("/api/repos")
def api_create_repo(req: CreateRepoRequest):
    conn = _conn()
    if _one(conn, "SELECT id FROM context_repos WHERE id = ?", (req.id,)):
        conn.close()
        raise HTTPException(400, f"Repo '{req.id}' already registered")

    local_path = str(ROOT / ".personas" / "cache" / req.id) if req.repo_url else str(ROOT / "registry")
    conn.execute(
        "INSERT INTO context_repos(id, name, description, repo_url, branch, local_path, created_at) VALUES (?,?,?,?,?,?,?)",
        (req.id, req.name, req.description, req.repo_url or None, req.branch,
         local_path, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    if req.repo_url:
        subprocess.Popen([sys.executable, str(SYNC), req.id], cwd=ROOT)

    return {"status": "registered", "id": req.id}


@app.get("/api/repos/{repo_id}")
def api_repo_detail(repo_id: str):
    conn = _conn()
    repo = _one(conn, "SELECT * FROM context_repos WHERE id = ?", (repo_id,))
    if not repo:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    modules = _rows(conn, "SELECT * FROM repo_modules WHERE repo_id = ? ORDER BY type, name", (repo_id,))
    last_sync = _one(conn, "SELECT * FROM sync_log WHERE repo_id = ? ORDER BY synced_at DESC LIMIT 1", (repo_id,))
    conn.close()
    return JSONResponse({"repo": repo, "modules": modules, "last_sync": last_sync})


@app.delete("/api/repos/{repo_id}")
def api_delete_repo(repo_id: str):
    if repo_id == "local":
        raise HTTPException(400, "Cannot remove the built-in local registry")
    conn = _conn()
    if not _one(conn, "SELECT id FROM context_repos WHERE id = ?", (repo_id,)):
        conn.close()
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    conn.execute("DELETE FROM context_repos WHERE id = ?", (repo_id,))
    conn.commit()
    conn.close()
    return {"status": "removed"}


@app.post("/api/repos/{repo_id}/sync")
def api_sync_repo(repo_id: str):
    conn = _conn()
    repo = _one(conn, "SELECT * FROM context_repos WHERE id = ?", (repo_id,))
    conn.close()
    if not repo:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    if not repo.get("repo_url"):
        return {"status": "skipped", "reason": "local-only repo"}
    subprocess.Popen([sys.executable, str(SYNC), repo_id], cwd=ROOT)
    return {"status": "syncing"}


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
    q += " ORDER BY name"
    personas = _rows(conn, q, params)
    for p in personas:
        p["module_count"] = conn.execute(
            "SELECT COUNT(*) FROM persona_modules WHERE persona_id = ?", (p["id"],)
        ).fetchone()[0]
    conn.close()
    return JSONResponse(personas)


class CreatePersonaRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    scope: str = "private"


@app.post("/api/personas")
def api_create_persona(req: CreatePersonaRequest):
    conn = _conn()
    if _one(conn, "SELECT id FROM personas WHERE id = ?", (req.id,)):
        conn.close()
        raise HTTPException(400, f"Persona '{req.id}' already exists")
    conn.execute(
        "INSERT INTO personas(id, name, description, scope, owner, created_at) VALUES (?,?,?,?,?,?)",
        (req.id, req.name, req.description, req.scope, "local",
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return {"status": "created", "id": req.id}


@app.get("/api/personas/{persona_id}")
def api_persona_detail(persona_id: str):
    conn = _conn()
    persona = _one(conn, "SELECT * FROM personas WHERE id = ?", (persona_id,))
    if not persona:
        raise HTTPException(404, f"Persona '{persona_id}' not found")
    # Join with context_repos to include repo name in each module
    modules = _rows(conn, """
        SELECT pm.*, cr.name AS repo_name, cr.repo_url AS repo_url
        FROM persona_modules pm
        JOIN context_repos cr ON pm.repo_id = cr.id
        WHERE pm.persona_id = ?
        ORDER BY cr.name, pm.type, pm.name
    """, (persona_id,))
    conn.close()
    return JSONResponse({"persona": persona, "modules": modules})


@app.delete("/api/personas/{persona_id}")
def api_delete_persona(persona_id: str):
    conn = _conn()
    if not _one(conn, "SELECT id FROM personas WHERE id = ?", (persona_id,)):
        conn.close()
        raise HTTPException(404, f"Persona '{persona_id}' not found")
    conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


class AddModuleRequest(BaseModel):
    repo_id: str
    path: str           # relative path within the repo
    add_all: bool = False   # if True, add all modules from repo_id (path ignored)


@app.post("/api/personas/{persona_id}/modules")
def api_add_module(persona_id: str, req: AddModuleRequest):
    conn = _conn()
    if not _one(conn, "SELECT id FROM personas WHERE id = ?", (persona_id,)):
        conn.close()
        raise HTTPException(404, f"Persona '{persona_id}' not found")
    if not _one(conn, "SELECT id FROM context_repos WHERE id = ?", (req.repo_id,)):
        conn.close()
        raise HTTPException(404, f"Repo '{req.repo_id}' not found")

    if req.add_all:
        # Add every module in the repo that isn't already in the persona
        repo_mods = _rows(conn, "SELECT * FROM repo_modules WHERE repo_id = ?", (req.repo_id,))
        existing = {(r["repo_id"], r["path"]) for r in
                    _rows(conn, "SELECT repo_id, path FROM persona_modules WHERE persona_id = ?", (persona_id,))}
        added = []
        for m in repo_mods:
            if (req.repo_id, m["path"]) not in existing:
                conn.execute(
                    "INSERT INTO persona_modules(persona_id, repo_id, path, type, name, description, tokens, enabled) VALUES (?,?,?,?,?,?,?,1)",
                    (persona_id, req.repo_id, m["path"], m["type"], m["name"], m["description"], m["tokens"]),
                )
                added.append(m["path"])
        conn.commit()
        conn.close()
        return {"status": "added", "count": len(added), "paths": added}

    # Add a single module
    mod = _one(conn, "SELECT * FROM repo_modules WHERE repo_id = ? AND path = ?", (req.repo_id, req.path))
    if not mod:
        conn.close()
        raise HTTPException(404, f"Module '{req.path}' not found in repo '{req.repo_id}'")
    if _one(conn, "SELECT id FROM persona_modules WHERE persona_id = ? AND repo_id = ? AND path = ?",
            (persona_id, req.repo_id, req.path)):
        conn.close()
        raise HTTPException(400, "Module already in persona")

    conn.execute(
        "INSERT INTO persona_modules(persona_id, repo_id, path, type, name, description, tokens, enabled) VALUES (?,?,?,?,?,?,?,1)",
        (persona_id, req.repo_id, mod["path"], mod["type"], mod["name"], mod["description"], mod["tokens"]),
    )
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"status": "added", "id": new_id}


@app.delete("/api/personas/{persona_id}/modules/{mod_id}")
def api_remove_module(persona_id: str, mod_id: int):
    conn = _conn()
    if not _one(conn, "SELECT id FROM persona_modules WHERE id = ? AND persona_id = ?", (mod_id, persona_id)):
        conn.close()
        raise HTTPException(404, "Module not found in persona")
    conn.execute("DELETE FROM persona_modules WHERE id = ?", (mod_id,))
    conn.commit()
    conn.close()
    return {"status": "removed"}


class ToggleModuleRequest(BaseModel):
    enabled: bool


@app.patch("/api/personas/{persona_id}/modules/{mod_id}")
def api_toggle_module(persona_id: str, mod_id: int, req: ToggleModuleRequest):
    conn = _conn()
    if not _one(conn, "SELECT id FROM persona_modules WHERE id = ? AND persona_id = ?", (mod_id, persona_id)):
        conn.close()
        raise HTTPException(404, "Module not found in persona")
    conn.execute("UPDATE persona_modules SET enabled = ? WHERE id = ?", (1 if req.enabled else 0, mod_id))
    conn.commit()
    conn.close()
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Routes — Session launch
# ---------------------------------------------------------------------------

class LaunchRequest(BaseModel):
    persona_id: str
    enabled_module_ids: list[int]   # IDs from persona_modules (session selection)
    enabled_mcps: list[str] = []
    model: str = ""


@app.post("/api/launch")
def api_launch(req: LaunchRequest):
    if not req.enabled_module_ids:
        raise HTTPException(400, "No modules selected for this session")

    conn = _conn()
    placeholders = ",".join("?" * len(req.enabled_module_ids))
    modules = _rows(conn, f"""
        SELECT pm.*, cr.local_path
        FROM persona_modules pm
        JOIN context_repos cr ON pm.repo_id = cr.id
        WHERE pm.id IN ({placeholders}) AND pm.persona_id = ?
    """, (*req.enabled_module_ids, req.persona_id))
    conn.close()

    instruction_paths = []
    for m in modules:
        full_path = Path(m["local_path"]) / m["path"]
        if full_path.exists():
            instruction_paths.append(str(full_path))

    model = _resolve_model(req.model)

    try:
        _write_opencode_config(instruction_paths, req.enabled_mcps, model)
        start_opencode()
        return {"status": "ok", "redirect": "http://localhost:4000"}
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
