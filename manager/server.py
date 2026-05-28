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
  POST /api/launch                     → configure harness and return redirect URL
  GET  /api/status                     → harness process / service status
  POST /api/stop                       → stop managed processes

Misc:
  GET  /api/mcps                       → MCP list from registry/mcps.json
  GET  /api/marketplace                → marketplace catalog
  GET  /api/harness                    → which harness is active
  GET  /api/session                    → active session: persona, modules, MCPs loaded
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "databases" / "context.db"
SYNC = ROOT / "scripts" / "sync_personas.py"
TEMPLATES = Path(__file__).parent / "templates"

# "openwebui" (default) or "opencode"
HARNESS = os.getenv("HARNESS", "openwebui")

app = FastAPI(title="Lattice Manager")

# Allow Open WebUI (localhost:4000) to call /api/session for the sidebar panel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000", "http://127.0.0.1:4000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_proc: subprocess.Popen | None = None   # OpenCode web process (opencode harness only)
_mcpo_proc: subprocess.Popen | None = None
_active_session: dict | None = None    # Last successfully launched session


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
# MCPO process management (both harnesses)
# ---------------------------------------------------------------------------

def start_mcpo():
    global _mcpo_proc
    if _mcpo_proc and _mcpo_proc.poll() is None:
        return
    mcpo_port = os.getenv("MCPO_PORT", "8001")
    mcpo_cfg = ROOT / "mcpo.json"
    if not mcpo_cfg.exists():
        print("  mcpo.json not found — skipping MCPO start")
        return
    _mcpo_proc = subprocess.Popen(
        ["uvx", "mcpo", "--port", mcpo_port, "--config", str(mcpo_cfg)],
        cwd=ROOT,
    )
    print(f"  MCPO started (pid {_mcpo_proc.pid})")


def stop_mcpo():
    global _mcpo_proc
    if _mcpo_proc and _mcpo_proc.poll() is None:
        _mcpo_proc.terminate()
        try:
            _mcpo_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mcpo_proc.kill()
        print("  MCPO stopped")
    _mcpo_proc = None


# ---------------------------------------------------------------------------
# OpenCode harness helpers
# ---------------------------------------------------------------------------

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
    mcp_section = {}
    for k, v in all_mcps.items():
        if k in mcp_ids:
            cmd = v["command"]
            mcp_section[k] = {
                "type": "local",
                "command": cmd[0] if isinstance(cmd, list) else cmd,
                "args": cmd[1:] if isinstance(cmd, list) else [],
                "enabled": True,
            }
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "instructions": instruction_paths,
        "mcp": mcp_section,
        "server": {"hostname": "0.0.0.0", "port": int(os.getenv("OPENCODE_PORT", "4000"))},
    }
    (ROOT / "opencode.jsonc").write_text(json.dumps(config, indent=2))


def start_opencode():
    global _proc
    stop_opencode()
    _proc = subprocess.Popen(
        ["opencode", "web"],
        cwd=ROOT,
        env={**os.environ, "OPENCODE_CONFIG": str(ROOT / "opencode.jsonc")},
    )
    print(f"  OpenCode started (pid {_proc.pid})")


def stop_opencode():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        print("  OpenCode stopped")
    _proc = None


# ---------------------------------------------------------------------------
# Open WebUI harness helpers
# ---------------------------------------------------------------------------

def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


_webui_token_cache: str | None = None


def _get_webui_token(webui_url: str) -> str:
    global _webui_token_cache
    if _webui_token_cache:
        return _webui_token_cache
    email = os.getenv("OPENWEBUI_ADMIN_EMAIL", "admin@localhost")
    password = os.getenv("OPENWEBUI_ADMIN_PASSWORD", "admin")
    with httpx.Client(timeout=10) as client:
        r = client.post(
            f"{webui_url}/api/v1/auths/signin",
            json={"email": email, "password": password},
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"Open WebUI signin failed ({r.status_code}). "
                f"Set OPENWEBUI_API_KEY in .env (generate one in Open WebUI → Settings → Account → API Keys), "
                f"or set OPENWEBUI_ADMIN_EMAIL / OPENWEBUI_ADMIN_PASSWORD to match your Open WebUI login."
            )
        _webui_token_cache = r.json()["token"]
    return _webui_token_cache


def _webui_headers(webui_url: str = "") -> dict:
    """Return auth headers. Raises if auth cannot be established."""
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("OPENWEBUI_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif webui_url:
        headers["Authorization"] = f"Bearer {_get_webui_token(webui_url)}"
    return headers


def _register_mcp_servers(selected_mcp_ids: list[str], webui_url: str) -> bool:
    """Upsert selected MCPs as tool server connections in Open WebUI. Returns True on success."""
    if not selected_mcp_ids:
        return True

    # Open WebUI (Docker) reaches MCPO via host.docker.internal; local → localhost
    mcpo_base = os.getenv(
        "OPENWEBUI_MCPO_URL",
        f"http://host.docker.internal:{os.getenv('MCPO_PORT', '8001')}",
    )
    headers = _webui_headers(webui_url)
    with httpx.Client(timeout=10) as client:
        # Fetch existing connections — body is {"TOOL_SERVER_CONNECTIONS": [...]}
        r = client.get(f"{webui_url}/api/v1/configs/tool_servers", headers=headers)
        raw = r.json() if r.status_code == 200 else {}
        existing = raw.get("TOOL_SERVER_CONNECTIONS", []) if isinstance(raw, dict) else []

        # Drop any previously registered Lattice/MCPO entries, re-add selected ones
        kept = [s for s in existing if isinstance(s, dict) and not str(s.get("url", "")).startswith(mcpo_base)]
        new_connections = kept + [
            {
                "url": f"{mcpo_base}/{mid}",
                "path": "openapi.json",
                "auth_type": None,
                "key": None,
                "config": {"enable": True},
            }
            for mid in selected_mcp_ids
        ]

        r2 = client.post(
            f"{webui_url}/api/v1/configs/tool_servers",
            json={"TOOL_SERVER_CONNECTIONS": new_connections},
            headers=headers,
        )
        if r2.status_code not in (200, 201):
            # Non-fatal — context will still work; MCPs can be added manually in Open WebUI admin
            print(f"  Warning: MCP tool server registration returned {r2.status_code}: {r2.text[:200]}")
            return False
    return True


WEBUI_SUGGESTIONS = [
    {
        "title": ["What MCP tools", "do I have?"],
        "content": "List all the MCP servers and tools available in this session. For each one, describe what systems it connects to and what operations it can perform.",
    },
    {
        "title": ["What context", "is loaded?"],
        "content": "Summarize all the context modules loaded in your system prompt — what repos they're from, what each one covers, and the total token count.",
    },
    {
        "title": ["Query LIMS", "for recent samples"],
        "content": "Use the LIMS MCP tool to show me the most recently created samples or batches.",
    },
    {
        "title": ["Check QMS", "for open deviations"],
        "content": "Use the QMS MCP tool to list any open deviations or non-conformances.",
    },
]


def _set_webui_suggestions(webui_url: str, headers: dict) -> None:
    try:
        with httpx.Client(timeout=5) as client:
            r = client.post(
                f"{webui_url}/api/v1/configs/suggestions",
                json={"suggestions": WEBUI_SUGGESTIONS},
                headers=headers,
            )
            if r.status_code not in (200, 201):
                print(f"  Warning: suggestions update returned {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"  Warning: could not set suggestions: {e}")


def _set_webui_banner(webui_url: str, headers: dict, persona: dict, modules: list[dict], mcp_ids: list[str]) -> None:
    """Push a live banner to Open WebUI showing active context + MCPs."""
    repos: dict[str, list[str]] = {}
    for m in modules:
        rname = m.get("repo_name") or m.get("repo_id", "context")
        repos.setdefault(rname, []).append(m["name"])

    ctx_parts = [
        f"{rname}: {', '.join(mods[:3])}{'…' if len(mods) > 3 else ''}"
        for rname, mods in repos.items()
    ]
    content = "  |  ".join([
        f"**Context:** {' · '.join(ctx_parts) if ctx_parts else 'none'}",
        f"**MCP Tools:** {', '.join(mcp_ids) if mcp_ids else 'none'}",
    ])
    banner = [{
        "id": "lattice-session",
        "type": "info",
        "title": f"Lattice session: {persona['name']}",
        "content": content,
        "dismissible": True,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }]
    try:
        with httpx.Client(timeout=5) as client:
            r = client.post(f"{webui_url}/api/v1/configs/banners", json={"banners": banner}, headers=headers)
            if r.status_code not in (200, 201):
                print(f"  Warning: banner update returned {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  Warning: could not set banner: {e}")


def _push_to_openwebui(
    persona: dict, modules: list[dict], selected_mcp_ids: list[str], model_override: str
) -> tuple[str, dict]:
    """Compile system prompt, register MCPs, upsert model preset. Returns (redirect_url, summary)."""
    webui_url = os.getenv("OPENWEBUI_URL", "http://localhost:4000").rstrip("/")
    headers = _webui_headers(webui_url)

    # ── Session header prepended to the system prompt ─────────────────────────
    repos: dict[str, list[dict]] = {}
    for m in modules:
        rname = m.get("repo_name") or m.get("repo_id", "context")
        repos.setdefault(rname, []).append(m)

    header_lines = [
        "You are Lattice, an AI assistant for biologics manufacturing intelligence.",
        "You help scientists, analysts, and quality teams reason across complex multi-system data.",
        "Do not identify yourself as any specific AI model or disclose the underlying model provider. You are Lattice.",
        "",
        f"# Lattice Session: {persona['name']}", "", "## Context Loaded",
    ]
    for rname, mods in repos.items():
        header_lines.append(f"### {rname}")
        for m in mods:
            tok = f"  ({m['tokens']:,} tokens)" if m.get("tokens") else ""
            header_lines.append(f"- **{m['name']}**{tok}")

    if selected_mcp_ids:
        header_lines += ["", "## MCP Tools Available"]
        mcps_file = ROOT / "registry" / "mcps.json"
        all_mcps = json.loads(mcps_file.read_text()) if mcps_file.exists() else {}
        for mid in selected_mcp_ids:
            meta = all_mcps.get(mid, {})
            systems = " · ".join(meta.get("systems", []))
            desc = meta.get("description", "")
            detail = f" — {systems}" if systems else (f" — {desc}" if desc else "")
            header_lines.append(f"- **{mid}**{detail}")

    header = "\n".join(header_lines) + "\n\n---\n\n"

    # ── Content from module files ─────────────────────────────────────────────
    loaded_files, missing_files, content_parts = [], [], []
    for m in modules:
        full_path = Path(m["local_path"]) / m["path"]
        if full_path.exists():
            content_parts.append(_strip_frontmatter(full_path.read_text()).strip())
            loaded_files.append(m["path"])
        else:
            missing_files.append(m["path"])
    system_prompt = header + "\n\n---\n\n".join(content_parts)

    # ── Model description (shown in the model-selector tooltip) ──────────────
    desc_parts = []
    if persona.get("description"):
        desc_parts += [persona["description"], ""]
    desc_parts.append("**Context:** " + (", ".join(m["name"] for m in modules) or "none"))
    desc_parts.append("**Tools:** " + (", ".join(selected_mcp_ids) or "none"))
    model_description = "\n".join(desc_parts)

    # ── Base model ────────────────────────────────────────────────────────────
    base_model = os.getenv("OPENWEBUI_BASE_MODEL") or os.getenv("OLLAMA_MODEL", "qwen3:8b")
    if model_override:
        base_model = model_override

    model_id = f"lattice-{persona['id']}"
    payload = {
        "id": model_id,
        "name": persona["name"],
        "base_model_id": base_model,
        "params": {"system": system_prompt},
        "meta": {
            "description": model_description,
            "tags": [{"name": mid} for mid in selected_mcp_ids],
        },
    }

    # Register MCPs (non-fatal — context works regardless)
    if selected_mcp_ids:
        mcp_ok = _register_mcp_servers(selected_mcp_ids, webui_url)
        mcp_status = "registered" if mcp_ok else "failed (add manually: Open WebUI Admin → Tool Servers)"
    else:
        mcp_status = "none selected"
    _set_webui_suggestions(webui_url, headers)
    _set_webui_banner(webui_url, headers, persona, modules, selected_mcp_ids)

    with httpx.Client(timeout=10) as client:
        r = client.post(f"{webui_url}/api/v1/models/create", json=payload, headers=headers)
        if r.status_code not in (200, 201):
            r2 = client.post(f"{webui_url}/api/v1/models/model/update?id={model_id}", json=payload, headers=headers)
            if r2.status_code not in (200, 201):
                raise RuntimeError(
                    f"Open WebUI model create {r.status_code}, update {r2.status_code}: {r2.text[:300]}"
                )

    summary = {
        "persona": {"id": persona["id"], "name": persona["name"]},
        "modules": [
            {"name": m["name"], "repo": m.get("repo_name", m.get("repo_id")), "tokens": m.get("tokens")}
            for m in modules
        ],
        "mcps": selected_mcp_ids,
        "model": base_model,
        "model_id": model_id,
        "context_files_loaded": loaded_files,
        "context_files_missing": missing_files,
        "mcp_status": mcp_status,
        "launched_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"  Launched: model={model_id}, modules={len(loaded_files)}, mcps={selected_mcp_ids}")
    return f"{webui_url}/?models={model_id}", summary


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def ui():
    return (TEMPLATES / "index.html").read_text()


@app.get("/health")
def health():
    return {"status": "ok", "harness": HARNESS}


# ---------------------------------------------------------------------------
# Routes — Misc
# ---------------------------------------------------------------------------

@app.get("/api/harness")
def api_harness():
    return {"harness": HARNESS}


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
    path: str
    add_all: bool = False


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
    enabled_module_ids: list[int]
    enabled_mcps: list[str] = []
    model: str = ""


@app.post("/api/launch")
def api_launch(req: LaunchRequest):
    if not req.enabled_module_ids:
        raise HTTPException(400, "No modules selected for this session")

    conn = _conn()
    persona = _one(conn, "SELECT * FROM personas WHERE id = ?", (req.persona_id,))
    if not persona:
        conn.close()
        raise HTTPException(404, f"Persona '{req.persona_id}' not found")

    placeholders = ",".join("?" * len(req.enabled_module_ids))
    modules = _rows(conn, f"""
        SELECT pm.*, cr.local_path
        FROM persona_modules pm
        JOIN context_repos cr ON pm.repo_id = cr.id
        WHERE pm.id IN ({placeholders}) AND pm.persona_id = ?
    """, (*req.enabled_module_ids, req.persona_id))
    conn.close()

    global _active_session
    try:
        if HARNESS == "opencode":
            instruction_paths = [
                str(Path(m["local_path"]) / m["path"])
                for m in modules
                if (Path(m["local_path"]) / m["path"]).exists()
            ]
            model = _resolve_model(req.model)
            _write_opencode_config(instruction_paths, req.enabled_mcps, model)
            start_opencode()
            _active_session = {
                "persona": {"id": persona["id"], "name": persona["name"]},
                "modules": [{"name": m["name"], "repo": m.get("repo_name", m.get("repo_id"))} for m in modules],
                "mcps": req.enabled_mcps,
                "model": model,
                "launched_at": datetime.now(timezone.utc).isoformat(),
            }
            return {"status": "ok", "redirect": f"http://localhost:{os.getenv('OPENCODE_PORT', '4000')}"}
        else:
            redirect, summary = _push_to_openwebui(persona, modules, req.enabled_mcps, req.model)
            _active_session = summary
            return {"status": "ok", "redirect": redirect, "summary": summary}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Routes — Status / Stop / Session
# ---------------------------------------------------------------------------

@app.get("/api/session")
def api_session():
    """Return the last successfully launched session (persona, modules, MCPs, model)."""
    if _active_session is None:
        return JSONResponse({"active": False})
    return JSONResponse({"active": True, **_active_session})


@app.get("/api/status")
def api_status():
    if HARNESS == "opencode":
        running = _proc is not None and _proc.poll() is None
        mcpo_managed = _mcpo_proc is not None and _mcpo_proc.poll() is None
        return {
            "harness": "opencode",
            "opencode_running": running,
            "pid": _proc.pid if running else None,
            "mcpo_managed_pid": _mcpo_proc.pid if mcpo_managed else None,
        }

    webui_url = os.getenv("OPENWEBUI_URL", "http://localhost:4000").rstrip("/")
    mcpo_port = os.getenv("MCPO_PORT", "8001")
    webui_up = mcpo_up = False
    try:
        with httpx.Client(timeout=2) as client:
            webui_up = client.get(f"{webui_url}/health").status_code == 200
    except Exception:
        pass
    try:
        with httpx.Client(timeout=2) as client:
            mcpo_up = client.get(f"http://localhost:{mcpo_port}/lims/openapi.json").status_code < 500
    except Exception:
        pass
    managed = _mcpo_proc is not None and _mcpo_proc.poll() is None
    return {
        "harness": "openwebui",
        "webui_up": webui_up,
        "mcpo_up": mcpo_up,
        "mcpo_managed_pid": _mcpo_proc.pid if managed else None,
    }


@app.post("/api/stop")
def api_stop():
    stop_opencode()
    stop_mcpo()
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print(f"Lattice Manager → http://localhost:5000  (harness: {HARNESS})")
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")
