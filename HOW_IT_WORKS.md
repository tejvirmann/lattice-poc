# How Lattice Works

A quick reference for understanding and extending the POC.

---

## What happens when you run `./lattice web`

```
./lattice web
  │
  ├─ 1. Load .env (provider, model, ports)
  ├─ 2. Check databases exist → seed if missing
  ├─ 3. Run scripts/generate.py
  │       reads registry/ → writes opencode.jsonc
  │       (all enabled skills + blueprints + all MCPs)
  │
  ├─ 4. Start Lattice Manager at :5000
  │       3-tab UI: Marketplace / My Personas / Session
  │       POST /api/launch → re-runs generate.py → restarts OpenCode
  │
  └─ 5. Start OpenCode Web at :4000
          reads opencode.jsonc
          connects to Ollama (or OpenRouter)
          starts MCP servers as subprocesses (lims, qms, rosetta)
```

---

## Two-layer context management

### Layer 1 — Personas

A persona is a named bundle of context modules (skills + blueprints) stored in a git repo. Personas are versioned, scoped, and synced automatically.

```
Persona: "QC Analyst"
  repo_url: https://github.com/org/qc-analyst-bundle.git
  branch: main
  scope: team
  modules:
    skills/lims-analysis.md
    skills/qms-investigation.md
    blueprints/batch-release.md
```

Personas are registered from the **Marketplace tab** (public/team repos) or manually.
The sync job (`./lattice sync`) pulls updates and rescans modules whenever the upstream repo changes.

Persona data lives in `databases/context.db`:

| Table | What |
|---|---|
| `marketplace_repos` | Approved context repos available to all users |
| `personas` | Registered personas with git metadata |
| `persona_modules` | .md files scanned from each persona's repo |
| `sync_log` | History of sync runs |

### Layer 2 — Session toggles

Within a persona, you can temporarily enable or disable individual modules before launching a session. This controls token usage without changing the persona definition.

```
Session for "QC Analyst":
  ✓ skills/lims-analysis.md       (400 tokens)
  ✓ blueprints/batch-release.md   (550 tokens)
  ✗ skills/qms-investigation.md   (skipped — not needed today)

  Token budget: 950 / 2000
```

The persona in the database is never mutated. The toggle selection is used only for this session's `generate.py` call.

---

## The registry — what you edit locally

```
registry/
  context.md              ← base Lattice persona, always injected
  skills/
    lims-analysis.md      ← frontmatter: enabled: true/false, tokens: ~400
    qms-investigation.md
  blueprints/
    deviation-investigation.md   ← step-by-step workflow instructions
    batch-release.md
  mcps.json               ← MCP server command definitions
```

### Adding a new skill

1. Create `registry/skills/my-skill.md`
2. Add frontmatter:
   ```markdown
   ---
   name: My Skill
   description: What this skill does
   enabled: true
   tokens: ~300
   systems: [lims]
   ---

   Skill instructions here...
   ```
3. Run `./lattice` — it's picked up automatically.

### Adding a new blueprint

Same as a skill but in `registry/blueprints/`. Blueprints are step-by-step workflow instructions the model follows for a specific use case.

---

## The MCP servers — what you edit

```
mcp-servers/
  lims_mcp.py       ← tools for querying LIMS data
  qms_mcp.py        ← tools for querying QMS data
  rosetta_mcp.py    ← cross-system normalization tools
  requirements.txt
```

Each MCP server is a Python process using the `mcp` library. OpenCode starts and manages them as subprocesses. The model calls their tools during conversation.

### Adding a new MCP server

1. Create `mcp-servers/mydb_mcp.py`:
   ```python
   from mcp.server.fastmcp import FastMCP
   mcp = FastMCP("mydb", description="My system description")

   @mcp.tool()
   def my_tool(param: str) -> str:
       """Tool description shown to the model."""
       # query your database here
       return json.dumps(result)

   if __name__ == "__main__":
       mcp.run()
   ```

2. Add to `registry/mcps.json`:
   ```json
   "mydb": {
     "command": [".venv/bin/python3", "mcp-servers/mydb_mcp.py"],
     "description": "My system — what it provides"
   }
   ```

3. Run `./lattice` — it appears in the Session tab and gets injected into `opencode.jsonc`.

### Adding a new database

1. Add schema to `databases/seed/mydb.sql`
2. Add a `seed_mydb()` function in `scripts/seed_databases.py`
3. Call it from `__main__`
4. Run `./lattice seed` to regenerate

---

## generate.py — how context injection works

`scripts/generate.py` is the bridge between the registry and OpenCode.

```
registry/
  ├─ context.md         ← always included
  ├─ skills/*.md        ← included if enabled: true (or explicitly selected)
  ├─ blueprints/*.md    ← included if enabled: true (or explicitly selected)
  └─ mcps.json          ← all included by default, or filtered by --mcps

        ↓  python3 scripts/generate.py

opencode.jsonc
  ├─ model: ollama/qwen3:8b
  ├─ instructions: [context.md, skill1.md, blueprint1.md, ...]
  └─ mcp: { lims: {...}, qms: {...}, rosetta: {...} }
```

CLI options:
```bash
python3 scripts/generate.py                           # all enabled
python3 scripts/generate.py --skills lims-analysis    # only this skill
python3 scripts/generate.py --blueprints deviation-investigation
python3 scripts/generate.py --mcps lims,rosetta       # skip qms
python3 scripts/generate.py --model ollama/qwen3:30b-a3b
python3 scripts/generate.py --dry-run                 # print without writing
```

---

## sync_personas.py — keeping persona repos up to date

```bash
./lattice sync                  # sync all repo-backed personas
./lattice sync qc-analyst       # sync one persona
./lattice sync --check          # check for updates, don't pull
```

The sync job:
1. Runs `git ls-remote` to check the upstream HEAD hash (no clone needed)
2. Skips if already at that hash
3. Clones or pulls into `.personas/cache/<persona_id>/`
4. Rescans all `.md` files and updates `persona_modules` in context.db
5. Logs each run in `sync_log`

Git auth:
- GitHub.com / GitHub Enterprise: set `GITHUB_PAT` in `.env`
- GitLab self-hosted: set `GITLAB_PAT` in `.env` (and optionally `GITLAB_HOST`)
- SSH repos (`git@...`): uses system SSH key, no token needed

---

## Provider switching

In `.env`:
```env
# Local Ollama (production — data stays local)
PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b

# OpenRouter (dev only — data leaves the server)
PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=qwen/qwen-2.5-72b-instruct
```

Or in the Session tab: pick provider from the model dropdown before launching.
`generate.py` reads `.env` if `--model` is not specified.

---

## Lattice Manager — what it does

`manager/server.py` is a FastAPI server at `:5000`.

| Route | What |
|---|---|
| `GET /` | Serves the 3-tab configurator UI |
| `GET /api/mcps` | Returns MCP list from registry/mcps.json |
| `GET /api/marketplace` | Returns marketplace repos (with registered flag) |
| `POST /api/personas` | Register a persona (repo-backed triggers immediate sync) |
| `GET /api/personas` | List registered personas |
| `GET /api/personas/:id` | Persona detail + modules + last sync |
| `DELETE /api/personas/:id` | Unregister a persona |
| `POST /api/personas/:id/sync` | Trigger sync for one persona |
| `POST /api/launch` | Run generate.py with session selection → restart OpenCode |
| `GET /api/status` | Whether OpenCode is running |
| `POST /api/stop` | Kill OpenCode |

The Manager owns the OpenCode process lifecycle. When you click "Launch Session":
1. Manager resolves the module selections to skill/blueprint slugs
2. Manager calls `generate.py` with your selection
3. Manager kills the current OpenCode process (if running)
4. Manager starts a fresh OpenCode Web process with the new `opencode.jsonc`
5. Browser redirects to `:4000`

---

## Data stays local

```
  Your server
  ┌────────────────────────────────────────────────────────┐
  │                                                        │
  │  lims.db ──► lims_mcp.py  ┐                          │
  │  qms.db  ──► qms_mcp.py   ├──► OpenCode ──► Ollama   │
  │  rosetta.db ► rosetta_mcp ┘     (tool calls)  (local) │
  │                                                        │
  │  Nothing crosses this boundary                        │
  └────────────────────────────────────────────────────────┘
```

With Ollama: the model runs on your server. Data never leaves.
With OpenRouter: the query (including data in tool responses) goes to the cloud. Dev only.

---

## Adding more systems (roadmap)

The POC ships with LIMS + QMS. Adding the remaining systems is mechanical:

| System | DB file | MCP server | Skill file |
|---|---|---|---|
| ELN | `databases/seed/eln.sql` | `mcp-servers/eln_mcp.py` | `registry/skills/eln-research.md` |
| MES | `databases/seed/mes.sql` | `mcp-servers/mes_mcp.py` | `registry/skills/mes-manufacturing.md` |
| CTMS | `databases/seed/ctms.sql` | `mcp-servers/ctms_mcp.py` | `registry/skills/ctms-clinical.md` |

Follow the pattern in the existing servers. Each new system shows up in the Session tab automatically.
