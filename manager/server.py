#!/usr/bin/env python3
"""
Lattice Manager — pre-session context configurator.

Runs at :5000. Serves the configurator UI, reads the registry,
accepts a skill/blueprint/MCP selection, writes opencode.jsonc,
and restarts OpenCode Web.

Start with: python3 manager/server.py
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
REGISTRY = ROOT / "registry"
GENERATE = ROOT / "scripts" / "generate.py"
TEMPLATES = Path(__file__).parent / "templates"

app = FastAPI(title="Lattice Manager")
_opencode_proc: subprocess.Popen | None = None


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def parse_frontmatter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---"):
        return {"name": path.stem, "description": "", "enabled": "true", "tokens": "0"}
    end = text.index("---", 3)
    fm = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    fm.setdefault("name", path.stem)
    fm.setdefault("description", "")
    fm.setdefault("enabled", "true")
    fm.setdefault("tokens", "0")
    return fm


def get_registry() -> dict:
    skills = []
    for p in sorted((REGISTRY / "skills").glob("*.md")):
        fm = parse_frontmatter(p)
        skills.append({
            "slug": p.stem,
            "name": fm["name"],
            "description": fm["description"],
            "enabled": fm["enabled"].lower() == "true",
            "tokens": int(fm["tokens"].replace("~", "").replace(",", "")) if fm["tokens"].replace("~","").replace(",","").isdigit() else 400,
            "systems": fm.get("systems", ""),
        })

    blueprints = []
    for p in sorted((REGISTRY / "blueprints").glob("*.md")):
        fm = parse_frontmatter(p)
        blueprints.append({
            "slug": p.stem,
            "name": fm["name"],
            "description": fm["description"],
            "enabled": fm["enabled"].lower() == "true",
            "tokens": int(fm["tokens"].replace("~", "").replace(",", "")) if fm["tokens"].replace("~","").replace(",","").isdigit() else 500,
            "systems": fm.get("systems", ""),
        })

    mcps = json.loads((REGISTRY / "mcps.json").read_text())
    mcp_list = [{"slug": k, **v} for k, v in mcps.items()]

    return {"skills": skills, "blueprints": blueprints, "mcps": mcp_list}


# ---------------------------------------------------------------------------
# OpenCode process management
# ---------------------------------------------------------------------------

def start_opencode():
    global _opencode_proc
    stop_opencode()
    cmd = ["opencode", "web"]
    env = {**os.environ, "OPENCODE_CONFIG": str(ROOT / "opencode.jsonc")}
    _opencode_proc = subprocess.Popen(cmd, cwd=ROOT, env=env)
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
    if skills:
        cmd += ["--skills", ",".join(skills)]
    if blueprints:
        cmd += ["--blueprints", ",".join(blueprints)]
    if mcps:
        cmd += ["--mcps", ",".join(mcps)]
    if model:
        cmd += ["--model", model]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def configurator():
    return (TEMPLATES / "index.html").read_text()


@app.get("/api/registry")
def api_registry():
    return JSONResponse(get_registry())


class LaunchRequest(BaseModel):
    skills: list[str] = []
    blueprints: list[str] = []
    mcps: list[str] = []
    model: str = ""


@app.post("/api/launch")
def api_launch(req: LaunchRequest):
    try:
        log = run_generate(
            skills=req.skills or None,
            blueprints=req.blueprints or None,
            mcps=req.mcps or None,
            model=req.model or None,
        )
        start_opencode()
        return {"status": "ok", "log": log, "redirect": "http://localhost:4000"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    print("Lattice Manager starting on http://localhost:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")
