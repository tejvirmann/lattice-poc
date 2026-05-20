#!/usr/bin/env python3
"""
sync_personas.py — Pull updates for all registered repo-backed personas.

Usage:
  python3 scripts/sync_personas.py           # sync all personas with a repo_url
  python3 scripts/sync_personas.py qc-analyst  # sync one persona by ID
  python3 scripts/sync_personas.py --check   # check for updates, don't pull

Called by: ./lattice sync
Can also be scheduled as a cron job for automatic updates.

Git auth:
  GitHub.com / GitHub Enterprise: set GITHUB_PAT in .env
  GitLab self-hosted:             set GITLAB_PAT in .env
  SSH repos (git@...):            uses system SSH key, no token needed
"""

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "databases" / "context.db"
CACHE_DIR = ROOT / ".personas" / "cache"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def git_url_with_auth(repo_url: str) -> str:
    """Inject PAT into HTTPS URLs. SSH URLs pass through unchanged."""
    if repo_url.startswith("git@"):
        return repo_url  # SSH — no token needed

    parsed = urlparse(repo_url)
    host = parsed.netloc

    # Detect provider and pick the right token
    github_pat = os.environ.get("GITHUB_PAT", "")
    gitlab_pat = os.environ.get("GITLAB_PAT", "")

    gitlab_host = os.environ.get("GITHUB_HOST", "")  # can be gitlab host too
    is_gitlab = gitlab_pat and (
        "gitlab" in host or (gitlab_host and gitlab_host in host)
    )

    token = gitlab_pat if is_gitlab else github_pat
    if not token:
        return repo_url  # public repo or SSH — proceed without token

    # Insert token as basic auth: https://token@host/path
    authed = parsed._replace(netloc=f"oauth2:{token}@{host}" if is_gitlab else f"{token}@{host}")
    return authed.geturl()


def git_remote_hash(repo_url: str, branch: str) -> str | None:
    """Get the current remote HEAD hash without cloning."""
    authed_url = git_url_with_auth(repo_url)
    try:
        result = subprocess.run(
            ["git", "ls-remote", authed_url, f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.split()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def git_clone_or_pull(repo_url: str, branch: str, local_path: Path) -> str:
    """Clone if missing, pull if exists. Returns new HEAD hash."""
    authed_url = git_url_with_auth(repo_url)
    local_path.mkdir(parents=True, exist_ok=True)

    if (local_path / ".git").exists():
        subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=local_path, check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{branch}"],
            cwd=local_path, check=True,
            capture_output=True,
        )
    else:
        subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch",
             authed_url, str(local_path)],
            check=True, capture_output=True,
        )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=local_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def scan_modules(local_path: Path) -> list[dict]:
    """
    Scan a persona directory for .md files with frontmatter.
    Returns a list of module dicts.
    """
    modules = []
    for md_file in sorted(local_path.rglob("*.md")):
        rel = md_file.relative_to(local_path)
        parts = rel.parts

        # Determine type from directory name
        type_map = {"skills": "skill", "blueprints": "blueprint",
                    "agents": "agent", "commands": "command"}
        file_type = type_map.get(parts[0], "skill") if len(parts) > 1 else "skill"

        # Parse frontmatter
        text = md_file.read_text()
        name = md_file.stem
        description = ""
        tokens = 0
        enabled = True

        if text.startswith("---"):
            try:
                end = text.index("---", 3)
                for line in text[3:end].strip().splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k == "name":
                            name = v
                        elif k == "description":
                            description = v
                        elif k == "tokens":
                            tokens = int(v.replace("~", "").replace(",", "")) if v.replace("~", "").replace(",", "").isdigit() else 0
                        elif k == "enabled":
                            enabled = v.lower() == "true"
            except (ValueError, AttributeError):
                pass

        modules.append({
            "path": str(rel),
            "type": file_type,
            "name": name,
            "description": description,
            "tokens": tokens,
            "enabled_by_default": 1 if enabled else 0,
        })
    return modules


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_persona(conn: sqlite3.Connection, persona: dict, check_only: bool = False) -> str:
    """Sync one persona. Returns status: 'ok' | 'no-change' | 'error'."""
    pid = persona["id"]
    repo_url = persona["repo_url"]
    branch = persona.get("branch") or "main"

    if not repo_url:
        return "no-change"  # local-only persona

    print(f"  [{pid}] Checking {repo_url} ({branch})...")

    # Check remote hash
    remote_hash = git_remote_hash(repo_url, branch)
    if remote_hash is None:
        msg = f"Could not reach {repo_url}"
        print(f"    ✗ {msg}")
        conn.execute(
            "INSERT INTO sync_log(persona_id, synced_at, status, message) VALUES (?,?,?,?)",
            (pid, now_iso(), "error", msg),
        )
        return "error"

    stored_hash = persona.get("last_hash")
    if check_only:
        if remote_hash != stored_hash:
            print(f"    Update available: {stored_hash[:8] if stored_hash else 'never'} → {remote_hash[:8]}")
            return "ok"
        else:
            print(f"    Up to date ({remote_hash[:8]})")
            return "no-change"

    if remote_hash == stored_hash:
        print(f"    Up to date ({remote_hash[:8]})")
        conn.execute(
            "INSERT INTO sync_log(persona_id, synced_at, status, message) VALUES (?,?,?,?)",
            (pid, now_iso(), "no-change", f"already at {remote_hash[:8]}"),
        )
        return "no-change"

    # Pull
    local_path = CACHE_DIR / pid
    try:
        print(f"    Pulling {stored_hash[:8] if stored_hash else 'fresh'} → {remote_hash[:8]}...")
        actual_hash = git_clone_or_pull(repo_url, branch, local_path)

        # Rescan modules
        modules = scan_modules(local_path)
        conn.execute("DELETE FROM persona_modules WHERE persona_id = ?", (pid,))
        conn.executemany(
            "INSERT INTO persona_modules(persona_id, path, type, name, description, tokens, enabled_by_default) VALUES (?,?,?,?,?,?,?)",
            [(pid, m["path"], m["type"], m["name"], m["description"], m["tokens"], m["enabled_by_default"]) for m in modules],
        )

        conn.execute(
            "UPDATE personas SET last_hash=?, last_synced=?, local_path=? WHERE id=?",
            (actual_hash, now_iso(), str(local_path), pid),
        )
        conn.execute(
            "INSERT INTO sync_log(persona_id, synced_at, status, message) VALUES (?,?,?,?)",
            (pid, now_iso(), "ok", f"{len(modules)} modules at {actual_hash[:8]}"),
        )
        print(f"    ✓ {len(modules)} modules synced")
        return "ok"

    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode() if e.stderr else str(e)
        print(f"    ✗ Git error: {msg[:120]}")
        conn.execute(
            "INSERT INTO sync_log(persona_id, synced_at, status, message) VALUES (?,?,?,?)",
            (pid, now_iso(), "error", msg[:500]),
        )
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync Lattice persona repos")
    parser.add_argument("persona_id", nargs="?", help="Sync a specific persona by ID")
    parser.add_argument("--check", action="store_true", help="Check for updates without pulling")
    args = parser.parse_args()

    load_env()

    if not DB_PATH.exists():
        print("context.db not found. Run: python3 scripts/seed_databases.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM personas WHERE repo_url IS NOT NULL"
    params = []
    if args.persona_id:
        query += " AND id = ?"
        params.append(args.persona_id)

    personas = [dict(r) for r in conn.execute(query, params).fetchall()]
    if not personas:
        print("No repo-backed personas found.")
        conn.close()
        return

    action = "Checking" if args.check else "Syncing"
    print(f"{action} {len(personas)} persona(s)...")

    results = {"ok": 0, "no-change": 0, "error": 0}
    for p in personas:
        status = sync_persona(conn, p, check_only=args.check)
        results[status] = results.get(status, 0) + 1

    if not args.check:
        conn.commit()

    conn.close()
    print(f"\nDone: {results['ok']} updated, {results['no-change']} up to date, {results['error']} errors")


if __name__ == "__main__":
    main()
