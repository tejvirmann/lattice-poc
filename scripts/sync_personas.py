#!/usr/bin/env python3
"""
sync_personas.py — Pull updates for all registered context repos.

Usage:
  python3 scripts/sync_personas.py              # sync all repos with a repo_url
  python3 scripts/sync_personas.py qc-analyst-bundle  # sync one repo by ID
  python3 scripts/sync_personas.py --check      # check for updates, don't pull

Called by: ./lattice sync
Can also be scheduled as a cron job for automatic updates.

Git auth:
  GitHub.com / GitHub Enterprise: set GITHUB_PAT in .env
  GitLab self-hosted:             set GITLAB_PAT in .env
  SSH repos (git@...):            uses system SSH key, no token needed
"""

import argparse
import os
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
        return repo_url

    parsed = urlparse(repo_url)
    host = parsed.netloc

    github_pat = os.environ.get("GITHUB_PAT", "")
    gitlab_pat = os.environ.get("GITLAB_PAT", "")
    gitlab_host = os.environ.get("GITLAB_HOST", "")
    is_gitlab = gitlab_pat and ("gitlab" in host or (gitlab_host and gitlab_host in host))

    token = gitlab_pat if is_gitlab else github_pat
    if not token:
        return repo_url

    authed = parsed._replace(netloc=f"oauth2:{token}@{host}" if is_gitlab else f"{token}@{host}")
    return authed.geturl()


def git_remote_hash(repo_url: str, branch: str) -> str | None:
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
    authed_url = git_url_with_auth(repo_url)
    local_path.mkdir(parents=True, exist_ok=True)

    if (local_path / ".git").exists():
        subprocess.run(["git", "fetch", "origin", branch],
                       cwd=local_path, check=True, capture_output=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{branch}"],
                       cwd=local_path, check=True, capture_output=True)
    else:
        subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch", authed_url, str(local_path)],
            check=True, capture_output=True,
        )

    result = subprocess.run(["git", "rev-parse", "HEAD"],
                            cwd=local_path, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def scan_modules(local_path: Path) -> list[dict]:
    """Scan a repo directory for .md files with frontmatter."""
    modules = []
    type_map = {"skills": "skill", "blueprints": "blueprint",
                "agents": "agent", "commands": "command"}

    for md_file in sorted(local_path.rglob("*.md")):
        rel = md_file.relative_to(local_path)
        parts = rel.parts
        file_type = type_map.get(parts[0], "skill") if len(parts) > 1 else "skill"

        text = md_file.read_text()
        name = md_file.stem
        description = ""
        tokens = 0

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
            except (ValueError, AttributeError):
                pass

        modules.append({
            "path": str(rel),
            "type": file_type,
            "name": name,
            "description": description,
            "tokens": tokens,
        })
    return modules


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_repo(conn: sqlite3.Connection, repo: dict, check_only: bool = False) -> str:
    """Sync one context_repo. Returns status: 'ok' | 'no-change' | 'error'."""
    rid = repo["id"]
    repo_url = repo["repo_url"]
    branch = repo.get("branch") or "main"

    print(f"  [{rid}] Checking {repo_url} ({branch})...")

    remote_hash = git_remote_hash(repo_url, branch)
    if remote_hash is None:
        msg = f"Could not reach {repo_url}"
        print(f"    ✗ {msg}")
        conn.execute(
            "INSERT INTO sync_log(repo_id, synced_at, status, message) VALUES (?,?,?,?)",
            (rid, now_iso(), "error", msg),
        )
        return "error"

    stored_hash = repo.get("last_hash")
    if check_only:
        if remote_hash != stored_hash:
            print(f"    Update available: {stored_hash[:8] if stored_hash else 'never'} → {remote_hash[:8]}")
        else:
            print(f"    Up to date ({remote_hash[:8]})")
        return "ok" if remote_hash != stored_hash else "no-change"

    if remote_hash == stored_hash:
        print(f"    Up to date ({remote_hash[:8]})")
        conn.execute(
            "INSERT INTO sync_log(repo_id, synced_at, status, message) VALUES (?,?,?,?)",
            (rid, now_iso(), "no-change", f"already at {remote_hash[:8]}"),
        )
        return "no-change"

    local_path = CACHE_DIR / rid
    try:
        print(f"    Pulling {stored_hash[:8] if stored_hash else 'fresh'} → {remote_hash[:8]}...")
        actual_hash = git_clone_or_pull(repo_url, branch, local_path)

        modules = scan_modules(local_path)
        conn.execute("DELETE FROM repo_modules WHERE repo_id = ?", (rid,))
        conn.executemany(
            "INSERT INTO repo_modules(repo_id, path, type, name, description, tokens) VALUES (?,?,?,?,?,?)",
            [(rid, m["path"], m["type"], m["name"], m["description"], m["tokens"]) for m in modules],
        )

        conn.execute(
            "UPDATE context_repos SET last_hash=?, last_synced=?, local_path=? WHERE id=?",
            (actual_hash, now_iso(), str(local_path), rid),
        )
        conn.execute(
            "INSERT INTO sync_log(repo_id, synced_at, status, message) VALUES (?,?,?,?)",
            (rid, now_iso(), "ok", f"{len(modules)} modules at {actual_hash[:8]}"),
        )
        print(f"    ✓ {len(modules)} modules synced")
        return "ok"

    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode() if e.stderr else str(e)
        print(f"    ✗ Git error: {msg[:120]}")
        conn.execute(
            "INSERT INTO sync_log(repo_id, synced_at, status, message) VALUES (?,?,?,?)",
            (rid, now_iso(), "error", msg[:500]),
        )
        return "error"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync Lattice context repos")
    parser.add_argument("repo_id", nargs="?", help="Sync a specific repo by ID")
    parser.add_argument("--check", action="store_true", help="Check for updates without pulling")
    args = parser.parse_args()

    load_env()

    if not DB_PATH.exists():
        print("context.db not found. Run: python3 scripts/seed_databases.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Only sync repos with a repo_url (skip local built-in)
    query = "SELECT * FROM context_repos WHERE repo_url IS NOT NULL"
    params = []
    if args.repo_id:
        query += " AND id = ?"
        params.append(args.repo_id)

    repos = [dict(r) for r in conn.execute(query, params).fetchall()]
    if not repos:
        print("No remote context repos found.")
        conn.close()
        return

    action = "Checking" if args.check else "Syncing"
    print(f"{action} {len(repos)} repo(s)...")

    results = {"ok": 0, "no-change": 0, "error": 0}
    for repo in repos:
        status = sync_repo(conn, repo, check_only=args.check)
        results[status] = results.get(status, 0) + 1

    if not args.check:
        conn.commit()

    conn.close()
    print(f"\nDone: {results['ok']} updated, {results['no-change']} up to date, {results['error']} errors")


if __name__ == "__main__":
    main()
