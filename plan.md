# Lattice POC — Build Plan

> Agentic proof-of-concept of [Axio BioPharma's Lattice](https://axiobiopharma.com/lattice).
> Biologics manufacturing intelligence: federated, local-first, cross-system.
> Domain: Pharma / Biotech. Harness: OpenCode Web. Provider: Ollama (local) ↔ OpenRouter (dev).

---

## What Lattice Does (as Code)

| Lattice concept | What we build |
|---|---|
| **Node** | One Python MCP server per data system — connects to its SQLite DB, exposes read tools. Data never moves off the local server. |
| **Rosetta** | A `rosetta-mcp` server that standardizes terminology, units, and ontology across systems before the model sees the data. |
| **Blueprints** | YAML workflow templates in `registry/blueprints/` — pre-configured multi-step runs for specific use cases (tech transfer, investigations, batch release). |
| **Signal** | Cross-system queries where the model calls multiple MCP servers in one session, Rosetta normalizes the results, and the model synthesizes a unified view. |

---

## Data Stays Local

This is the core principle. The architecture is federated:

- Each company runs its own Lattice instance on its own server
- MCP servers run locally — they talk directly to local databases
- The model runs locally via Ollama — query + data never leaves the network
- Only synthesized **insights** travel (e.g. a summary report shared across sites)

```
Company A                          Company B
┌─────────────────────────┐        ┌─────────────────────────┐
│  Lattice (Open WebUI)   │        │  Lattice (Open WebUI)   │
│  Ollama (local model)   │        │  Ollama (local model)   │
│  MCP servers (local)    │        │  MCP servers (local)    │
│  SQLite DBs (local)     │        │  SQLite DBs (local)     │
└─────────────────────────┘        └─────────────────────────┘
         │ insight                          │ insight
         └──────────────┬───────────────────┘
                 shared summary / report
```

OpenRouter is available as a **dev/test fallback only** — when you don't have Ollama set up yet. In production, Ollama keeps everything local.

---

## Use Cases

These are the reasons Lattice exists — what users actually do with it:

1. **Tech Transfer** — Compare lab-scale assay results (LIMS) against manufacturing batch performance (MES). Identify scale-up gaps, yield deltas, and process parameter drift when a drug moves from R&D to manufacturing.

2. **Deviation Investigation** — A batch deviation in QMS triggers a cross-system query: which LIMS samples were affected, what ELN experiments were running at that time, what does the MES process log show? Correlate automatically instead of manually.

3. **Batch Release Decision Support** — Aggregate release testing (LIMS) + process parameters (MES) + specification checks (QMS) into a single go/no-go summary with flagged OOS items.

4. **Clinical Safety Signal Detection** — Link adverse event trends in CTMS to batch quality data in QMS and PK assay results in LIMS. Surface whether a safety signal correlates with a specific lot, site, or manufacturing parameter.

5. **Cross-Site Process Comparison** — Compare yield, purity, and critical process parameters for the same product manufactured at two sites. Rosetta normalizes terminology and units so the comparison is apples-to-apples.

6. **CAPA Tracking** — Surface all open corrective and preventive actions in QMS tied to a specific compound, product family, or equipment ID. Identify overdue CAPAs and their associated deviation severity.

7. **Regulatory Readiness** — Pull together process characterization data across LIMS, MES, and ELN for a BLA or IND submission package. Summarize what's complete, what's missing, what has deviations.

8. **Process Trend Monitoring** — Detect drift in a key process parameter (pH, temperature, yield, endotoxin level) across multiple batches before it becomes an OOS event. Early warning from MES + LIMS combined.

---

## Architecture

```
  ./lattice
      │
      ├── default ──────────────────────────────────────────────────────┐
      │   writes opencode.jsonc (all enabled skills + all MCPs)         │
      │   starts opencode web                                            │
      │                                                                  │
      └── web ──────────────────────────────┐                           │
          starts opencode web + manager     │                           │
          user visits :5000 to configure    │                           │
                                            ▼                           │
                        ┌─── :5000 ─────────────────────┐              │
                        │  Lattice Manager (FastAPI)      │              │
                        │  · Shows registry checklist     │              │
                        │    (skills, blueprints, MCPs)   │              │
                        │  · Shows token budget per item  │              │
                        │  · On Launch:                   │              │
                        │    - writes opencode.jsonc      │              │
                        │      with only selected items   │              │
                        │    - restarts opencode web      │              │
                        │    - redirects to :4000         │              │
                        └───────────────────────────────┬─┘              │
                                                        │                │
                                          ┌─────────────┘                │
                                          │                               │
                                          ▼                               ▼
                        ┌─── :4000 ──────────────────────────────────────┐
                        │  Lattice Harness  (OpenCode Web)                │
                        │  · Markdown, tables, code blocks                │
                        │  · Tool call trace, session history             │
                        │  · Password auth, network-accessible            │
                        └────────────────────┬───────────────────────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                  ┌─────────────────┐           ┌──────────────────┐
                  │ Ollama (local)  │   ←env→   │ OpenRouter (dev) │
                  │ qwen3-30b-a3b   │           │ any model        │
                  └─────────────────┘           └──────────────────┘
                              │
                              │  MCP tools (native OpenCode)
                              ▼
         ┌──────────────────────────────────────────────────┐
         │  MCP Servers  (local Python stdio processes)      │
         │  lims · eln · qms · mes · ctms · rosetta         │
         └──────────────────────────────────────────────────┘
              │        │        │        │        │
              ▼        ▼        ▼        ▼        ▼
         lims.db  eln.db   qms.db   mes.db  ctms.db  (SQLite, local)
```

---

## Harness — OpenCode Web

**OpenCode Web** (`opencode web`) is the browser-based version of OpenCode — the same harness you already use in manager-v2, but accessible over the network.

| Feature | Detail |
|---|---|
| Deploy | `opencode web --hostname 0.0.0.0 --port 4000` on any VPS |
| Access | Browser at `http://your-server:4000` |
| Auth | Password via `OPENCODE_WEB_PASSWORD` env var |
| Model providers | Ollama, OpenRouter, any OpenAI-compatible API |
| Output | Full markdown: tables, code blocks, tool call trace |
| MCP support | Native — same `opencode.jsonc` config you already know |
| Registry | Identical to manager-v2: `registry/skills/`, `mcps.json`, `context.md` |
| TUI + Web | Share the same sessions — use either interface |
| Open WebUI | Also viable as an alternative UI skin, but requires a separate configurator wrapper to replicate the registry. OpenCode Web is the simpler path given the hard registry requirement. |

### Registry pattern (identical to manager-v2)

```
registry/
  context.md              ← Lattice base persona + pharma domain context, always loaded
  skills/
    tech-transfer.md      ← enabled: true/false in frontmatter
    deviation-investigation.md
    batch-release.md
    clinical-signal.md
  blueprints/             ← step-by-step workflow instructions (injected as skills)
    tech-transfer.md
    deviation-investigation.md
  mcps.json               ← canonical MCP list
```

`scripts/generate.py` reads frontmatter, filters `enabled: true`, writes `opencode.jsonc` with only the selected items. Same pattern as manager-v2's `generate.py`, extended with pharma skills and MCP servers.

### Provider toggle

```env
# .env

# Option A — Ollama (production, data stays local)
PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-30b-a3b

# Option B — OpenRouter (dev/test)
PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=qwen/qwen-2.5-72b-instruct
```

`./lattice` script reads `PROVIDER` and writes it into `opencode.jsonc` before starting `opencode web`. No code change to switch.

---

## File Structure

```
lattice-poc/
├── databases/
│   ├── seed/
│   │   ├── lims.sql          # LIMS schema + realistic seed data
│   │   ├── eln.sql           # ELN schema + seed data
│   │   ├── qms.sql           # QMS schema + seed data
│   │   ├── mes.sql           # MES schema + seed data
│   │   ├── ctms.sql          # CTMS schema + seed data
│   │   └── rosetta.sql       # Terminology/unit mapping tables
│   └── *.db                  # gitignored, generated by seed script
│
├── mcp-servers/
│   ├── lims_mcp.py
│   ├── eln_mcp.py
│   ├── qms_mcp.py
│   ├── mes_mcp.py
│   ├── ctms_mcp.py
│   ├── rosetta_mcp.py        # Cross-system standardization
│   └── requirements.txt
│
├── registry/
│   ├── context.md            # Base Lattice persona, always loaded
│   ├── mcps.json             # MCP server definitions (name, command, args, description)
│   ├── skills/
│   │   ├── tech-transfer.md         # frontmatter: enabled: true/false
│   │   ├── deviation-investigation.md
│   │   ├── batch-release.md
│   │   └── clinical-signal.md
│   └── blueprints/                  # Injected as skills when selected
│       ├── tech-transfer.md
│       ├── deviation-investigation.md
│       ├── batch-release.md
│       └── clinical-signal.md
│
├── manager/
│   ├── server.py             # FastAPI: serves configurator UI, handles /launch
│   ├── templates/
│   │   └── index.html        # Configurator UI (checklist + token budget + launch)
│   └── requirements.txt
│
├── scripts/
│   ├── generate.py           # Reads registry + selection → builds OPENCODE_CONFIG_CONTENT
│   └── seed_databases.py     # Creates all .db files from seed SQL
│
├── opencode.jsonc            # Static fallback config (used if opencode run directly)
├── lattice                   # Shell script: start manager server + opencode web
├── docker-compose.yml        # Ollama + MCP servers + manager + opencode as containers
├── .env.example
└── plan.md
```

---

## Phase 1 — Data Layer

### The Five Systems

**LIMS — Lab Information Management**
```sql
compounds(id, name, cas_number, molecular_weight, formula, drug_class, target)
samples(id, compound_id, name, matrix, concentration_mg_ml, storage_temp, analyst, created_at)
assays(id, name, method, unit, lod, loq, validated)
results(id, sample_id, assay_id, value, unit, pass_fail, analyst, instrument_id, run_date)
instruments(id, name, type, serial, calibration_due, status)
```

**ELN — Electronic Lab Notebook**
```sql
protocols(id, title, version, department, author, effective_date, status)
experiments(id, protocol_id, title, researcher, start_date, end_date, status, objective)
observations(id, experiment_id, step_number, type, description, value, unit, timestamp)
deviations_noted(id, experiment_id, description, severity, action_taken)
```

**QMS — Quality Management System**
```sql
batches(id, product_id, lot_number, manufacture_date, expiry_date, status, batch_size_kg)
specifications(id, product_id, parameter, min_value, max_value, unit, test_method)
deviations(id, batch_id, deviation_number, description, severity, root_cause, status, opened_date)
capas(id, deviation_id, capa_number, action_description, owner, due_date, status, effectiveness_check)
audits(id, type, auditor, date, department, findings_count, critical_count, status)
```

**MES — Manufacturing Execution System**
```sql
products(id, name, formulation_type, strength, route_of_admin, target_indication)
batches(id, product_id, lot_number, start_time, end_time, yield_kg, yield_target_kg, status)
equipment(id, name, type, location, last_maintenance, next_maintenance, status)
process_steps(id, batch_id, step_name, equipment_id, parameter, value, uom, timestamp, operator)
materials(id, name, supplier, grade, lot_number, quantity_kg, expiry, status)
```

**CTMS — Clinical Trial Management**
```sql
trials(id, name, phase, indication, sponsor, status, start_date, primary_endpoint, sites_count)
sites(id, trial_id, site_name, principal_investigator, country, status, enrolled_count, target_count)
subjects(id, site_id, subject_code, status, enrollment_date, randomization_arm, age, sex)
visits(id, subject_id, visit_name, scheduled_date, actual_date, status, protocol_deviation)
adverse_events(id, subject_id, visit_id, ae_term, severity, seriousness, relatedness, outcome, onset_date)
pk_samples(id, subject_id, visit_id, time_point_h, compound_conc_ng_ml, matrix)
```

**Rosetta (`rosetta.db`)**
```sql
term_map(id, source_system, source_term, canonical_term, ontology_code, confidence)
unit_conversions(id, from_unit, to_unit, factor, offset)
compound_aliases(id, canonical_name, alias, source_system)
```

### Seed Data Quality
Each DB gets ~200–500 rows of realistic data:
- Compound names drawn from real drug classes: kinase inhibitors, mAbs, ADCs, bispecifics
- Realistic assay names: HPLC purity, SEC-HPLC aggregate, endotoxin LAL, bioassay potency, osmolality, sub-visible particles
- QMS deviations: temperature excursion, yield OOS, container closure integrity failure, particulate matter
- CTMS: Phase 1/2 oncology and autoimmune trials, AE terms from MedDRA, realistic dropout rates

---

## Phase 2 — MCP Servers

Each is a Python process using the `mcp` library. Exposes read-only tools against its SQLite DB. Registered in `registry/mcps.json`.

### Tool examples

**`lims_mcp.py`**
```
get_sample(sample_id)
search_samples(compound_name, matrix, date_from, date_to)
get_assay_results(sample_id, assay_name)
get_oos_results(date_from, date_to)
get_instrument_status()
compare_results_across_batches(compound_name, assay_name)
```

**`qms_mcp.py`**
```
get_batch(lot_number)
get_deviations(batch_id, severity, status)
get_open_capas(department, overdue_only)
get_audit_findings(date_from, date_to)
check_batch_release_status(lot_number)
```

**`rosetta_mcp.py`**
```
normalize_term(term, source_system)           → canonical term + ontology code
convert_units(value, from_unit, to_unit)      → converted value
resolve_compound(alias, source_system)        → canonical compound name
standardize_result_set(results: list)         → normalized list for cross-system merge
```

`registry/mcps.json`:
```json
{
  "lims":    { "command": "python", "args": ["mcp-servers/lims_mcp.py"],    "description": "LIMS — samples and assay results" },
  "eln":     { "command": "python", "args": ["mcp-servers/eln_mcp.py"],     "description": "ELN — experiments and protocols" },
  "qms":     { "command": "python", "args": ["mcp-servers/qms_mcp.py"],     "description": "QMS — batch records, deviations, CAPAs" },
  "mes":     { "command": "python", "args": ["mcp-servers/mes_mcp.py"],     "description": "MES — manufacturing process data" },
  "ctms":    { "command": "python", "args": ["mcp-servers/ctms_mcp.py"],    "description": "CTMS — clinical trial and subject data" },
  "rosetta": { "command": "python", "args": ["mcp-servers/rosetta_mcp.py"], "description": "Rosetta — cross-system standardization" }
}
```

---

## Phase 3 — Lattice Manager + OpenCode Web

### Lattice Manager (`manager/server.py`)

A small FastAPI server (~100 lines). Two responsibilities:

**1. Configurator UI** (`GET /`)
Serves an HTML page that reads `registry/` and renders:
- **Skills** checklist (each `registry/skills/*.md` file, name + description from frontmatter, token cost estimate)
- **Blueprints** checklist (each `registry/blueprints/*.md`)
- **MCPs** checklist (each entry in `registry/mcps.json`)
- **Model** dropdown (Ollama models available, or OpenRouter model string)
- **Launch** button

**2. Session launch** (`POST /launch`)
Accepts the selection JSON, then:
1. Calls `scripts/generate.py --select skill1,skill2 --blueprints bp1 --mcps lims,qms,rosetta`
2. Writes a fresh `opencode.jsonc` with only the selected skills, blueprints, and MCPs
3. Kills the current OpenCode process (if running)
4. Restarts `opencode web --hostname 0.0.0.0 --port 4000`
5. Returns `{"redirect": "http://localhost:4000"}`

This is the mechanism that makes token-efficient context injection work: you choose exactly what goes into the context window before the session starts, not after.

### `opencode.jsonc`

The static fallback config. Defines the base model connection and a glob fallback for skills:

```jsonc
{
  "model": "ollama/qwen3-30b-a3b",  // overridden by OPENCODE_CONFIG_CONTENT
  "instructions": "registry/context.md",
  "mcp": {
    // all MCPs listed here; generate.py selects which to include at runtime
  }
}
```

`OPENCODE_CONFIG_CONTENT` (produced by `generate.py`) takes priority over this file. If you run `opencode` directly without `./lattice`, the static config is the fallback.

### Token cost column in the configurator

Each skill file's frontmatter includes an estimated token count:
```markdown
---
name: Tech Transfer
description: Lab vs manufacturing comparison workflow
enabled: true
tokens: ~800
---
```

The configurator UI shows a running total as you check/uncheck items, so you can see the context budget before launching.

---

## Phase 5 — Blueprints (Pre-built Workflows)

YAML configs in `registry/blueprints/`. The model is prompted to follow the workflow steps in sequence. Each blueprint's content is injected as part of the system prompt by the configurator.

**`tech-transfer.yaml`** (example)
```yaml
name: Tech Transfer Assessment
description: Compare lab-scale assay results with manufacturing batch performance
systems_required: [lims, mes, rosetta]
instructions: |
  You are running a tech transfer assessment. Follow these steps:
  1. Use LIMS tools to retrieve assay results for the compound across all lab-scale batches
  2. Use MES tools to retrieve yield and process parameters for manufacturing batches of the same compound
  3. Use Rosetta tools to normalize units and terminology before comparing
  4. Produce a comparison table: lab vs manufacturing, per parameter
  5. Identify scale-up gaps, yield deltas, and any process parameter drift
  6. Flag any values outside the lab-established ranges
```

**Four initial blueprints:**
- `tech-transfer.yaml` — Use cases 1, 5 (LIMS + MES)
- `deviation-investigation.yaml` — Use case 2 (QMS + LIMS + ELN)
- `batch-release.yaml` — Use case 3 (QMS + MES + LIMS)
- `clinical-signal.yaml` — Use case 4 (CTMS + LIMS + QMS)

---

## Phase 6 — Local Model

**Recommended: Qwen3-30B-A3B** (MoE architecture)
- 30B total params, ~3B active at inference — high quality, small compute footprint
- Fits comfortably in 20GB RAM (Q4_K_M via Ollama or llama.cpp)
- Strong tool use, instruction following, structured output

**Alternative: Qwen2.5-32B-Q4** (~20GB VRAM, dense, very capable for pharma reasoning)

Deployment is handled by the `docker-compose.yml` Ollama service — just set `OLLAMA_MODEL=qwen3-30b-a3b` in `.env` and the model pulls on first start. No code changes.

---

## Build Order

| Phase | What | Done when |
|---|---|---|
| 1 | Seed databases | 5 SQLite DBs created by `seed_databases.py`, data looks realistic |
| 2 | MCP servers | Each server starts, tools callable via `mcp dev` |
| 3 | OpenCode Web up | `opencode web` running, connected to Ollama or OpenRouter, one MCP tool works |
| 4 | Lattice Manager | Configurator page loads registry, selection POSTs to `/launch`, OpenCode restarts with new context, token budget visible |
| 5 | Blueprints | At least one blueprint runs multi-step correctly after being selected in configurator |
| 6 | Cross-system Signal | Query spans 2+ systems, Rosetta normalizes, model produces a comparison table |
| 7 | Local model | Ollama running with Qwen3, same functionality, data never leaves server |

---

## Tech Decisions

| Decision | Choice | Why |
|---|---|---|
| Databases | SQLite | Zero infrastructure, seed scripts trivial, realistic for POC |
| MCP library | Python `mcp` (official SDK) | First-class stdio support, native OpenCode integration |
| Harness | OpenCode Web | Already known, native registry + MCP support, browser-accessible when deployed with `--hostname 0.0.0.0`, no build required |
| Registry | Identical to manager-v2 | Frontmatter-gated skills, `generate.py`, `OPENCODE_CONFIG_CONTENT` — zero new concepts |
| Primary provider | Ollama (local) | Data never leaves the server; production default |
| Dev fallback | OpenRouter | API key only, same OpenAI-compatible interface, swap via env var |
| Local model | Qwen3-30B-A3B via Ollama | MoE, fits in 20GB, strong tool use |
| Alternative UI | Open WebUI | Viable if richer UI is needed later; requires a configurator wrapper to replicate registry injection |

---

## What This Is NOT

- A replacement for real LIMS/QMS/MES systems
- Production-ready (no auth, no RBAC, no audit log)
- A full reimplementation of Lattice — it's a POC to explore the architecture and demonstrate the concept

---

## Key Insight

Lattice = **MCP servers as data interfaces + registry-driven context injection + a deployable AI harness**.

The model doesn't need pharma training data. It needs:
1. MCP tools that know where each system's data lives
2. A Rosetta pass to normalize before cross-system comparison
3. Blueprint prompts that guide it through the correct workflow for a given use case

Everything runs locally. Raw data never leaves. The insight — a table, a summary, a go/no-go recommendation — is what travels.
