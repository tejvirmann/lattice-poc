# Lattice

**Federated intelligence for biologics manufacturing.**

Lattice connects process data across sites and partners — without moving the data.
Each organization keeps full custody of their systems. Lattice coordinates the insight.

---

## The problem

Biologics manufacturing generates data across dozens of systems: lab results, batch records, deviation logs, clinical outcomes, manufacturing parameters. When something goes wrong — or needs to scale — that data lives in silos across sites, partners, and software vendors.

Getting a cross-system answer today means manual exports, spreadsheet merges, and email chains. By the time you have the picture, it's already stale.

---

## How Lattice works

```
  Partner A                        Partner B                       Partner C
  ─────────────────────            ─────────────────────           ─────────────────────
  LIMS  QMS  MES  ELN              LIMS  QMS  CTMS                 MES  QMS  ELN
    │    │    │    │                 │    │    │                      │    │    │
    └────┴────┴────┘                 └────┴────┘                      └────┴────┘
           │                               │                                │
      [ MCP Server ]                 [ MCP Server ]                  [ MCP Server ]
      data stays here                data stays here                 data stays here
           │                               │                                │
           └───────────────┬───────────────┘                                │
                           │                         ┌──────────────────────┘
                           ▼                         ▼
                    ┌─────────────────────────────────────┐
                    │              Lattice                  │
                    │                                       │
                    │   query  →  MCP tools  →  synthesis  │
                    │                                       │
                    │   "Compare yield across all three     │
                    │    sites for Compound XB-441"         │
                    └─────────────────────────────────────┘
                                     │
                              insight travels
                                     │
                                     ▼
                           comparison table, gaps
                           flagged, ready to act on
```

**Data stays at the source.** MCP (Model Context Protocol) servers run inside each partner's own environment — on their server, behind their firewall. Lattice never pulls raw data into a central store. It issues queries through the MCP interface and synthesizes the responses locally.

**Insight travels, not data.** What crosses boundaries is the model's output: a table, a summary, a go/no-go recommendation. Never raw records.

---

## The four layers

| Layer | What it does |
|---|---|
| **Node** | An MCP server for each data system — LIMS, ELN, QMS, MES, CTMS. Runs inside the partner's environment. Exposes read-only query tools. Raw data never leaves. |
| **Rosetta** | A standardization layer that normalizes terminology, units, and compound names across systems before the model sees them. "Yield (%)" in one system and "Process yield (g/g)" in another become comparable. |
| **Blueprints** | Pre-built workflow templates for common use cases. Select one before your session and the model follows a structured, repeatable process — not a free-form conversation. |
| **Signal** | Cross-system pattern detection. The model queries multiple MCP servers in parallel, Rosetta normalizes the results, and Signal surfaces comparisons, trends, and anomalies that no single system could show. |

---

## Use cases

**Tech Transfer**
Compare lab-scale assay results against manufacturing batch performance. Identify yield deltas, scale-up gaps, and process parameter drift when a compound moves from R&D to manufacturing.

**Deviation Investigation**
A batch deviation in QMS triggers a cross-system query: which LIMS samples were affected, what ELN experiments were running at that time, what does the MES process log show? Correlated automatically.

**Batch Release Decision Support**
Aggregate release testing (LIMS) + process parameters (MES) + specification checks (QMS) into a single go/no-go summary with flagged out-of-spec items.

**Clinical Safety Signal Detection**
Link adverse event trends in CTMS to batch quality data in QMS and PK assay results in LIMS. Surface whether a safety signal correlates with a specific lot, site, or manufacturing parameter.

**Cross-Site Process Comparison**
Compare yield, purity, and critical process parameters for the same product across manufacturing sites. Rosetta normalizes terminology and units so the comparison is apples-to-apples.

**CAPA Tracking**
Surface all open corrective and preventive actions tied to a specific compound, product family, or equipment ID. Identify overdue CAPAs and their associated deviation severity.

**Regulatory Readiness**
Pull together process characterization data across LIMS, MES, and ELN for a BLA or IND submission package. Summarize what's complete, what's missing, what has open deviations.

**Process Trend Monitoring**
Detect drift in a key process parameter — pH, temperature, yield, endotoxin — across multiple batches before it becomes an OOS event. Early warning from MES and LIMS combined.

---

## Security model

Lattice is designed for environments where data sovereignty is non-negotiable.

- **MCP servers run inside the partner's environment.** They are not external services. They are processes running on the partner's own infrastructure, talking to their own databases.
- **The model runs locally.** In production, Lattice uses a locally-hosted model via Ollama. Queries and data never leave the network. OpenRouter is available as a development fallback only.
- **No central data store.** There is no Lattice cloud database. Each organization's data lives in their own systems, queried on demand through the MCP interface.
- **Read-only by default.** MCP servers expose read-only tools. Lattice does not write to partner systems.

```
  Partner's network boundary
  ╔══════════════════════════════════════════════╗
  ║                                              ║
  ║   LIMS DB ──► lims_mcp.py                   ║
  ║   QMS DB  ──► qms_mcp.py    ◄── Lattice     ║
  ║   MES DB  ──► mes_mcp.py         (queries)  ║
  ║                                              ║
  ║   Data never crosses this boundary           ║
  ╚══════════════════════════════════════════════╝
```

---

## Architecture (POC)

```
  ./lattice
      │
      ├── (default) writes opencode.jsonc with full registry
      │             starts OpenCode Web at :4000
      │
      └── (web)     also starts Lattice Manager at :5000
                    for pre-session context selection

  :5000  Lattice Manager
         Select which skills, blueprints, and MCP servers
         to include in the session. See estimated token cost
         per item. Launch when ready.
                │
                │ writes opencode.jsonc with selected items only
                │ restarts OpenCode Web
                ▼
  :4000  OpenCode Web  (the harness)
         Markdown · Tables · Tool call trace · Session history
                │
         ┌──────┴──────┐
         ▼             ▼
      Ollama        OpenRouter
      (local)       (dev only)
         │
         │  MCP tools
         ▼
  lims_mcp · eln_mcp · qms_mcp · mes_mcp · ctms_mcp · rosetta_mcp
         │
         ▼
  lims.db · eln.db · qms.db · mes.db · ctms.db  (SQLite, local)
```

---

## Registry

Context is controlled through a registry of files. Before each session, you choose what gets injected — only what you need, keeping the context window lean.

```
registry/
  context.md                    ← base Lattice persona, always loaded
  skills/
    tech-transfer.md            ← enabled: true/false in frontmatter
    deviation-investigation.md
    batch-release.md
    clinical-signal.md
  blueprints/
    tech-transfer.md            ← step-by-step workflow instructions
    deviation-investigation.md
    batch-release.md
    clinical-signal.md
  mcps.json                     ← MCP server definitions
```

Each skill and blueprint declares its name, description, and estimated token cost in frontmatter. The configurator shows the running total as you build your session.

---

## Data systems (POC seed data)

| System | What it holds |
|---|---|
| **LIMS** | Compounds, samples, assay methods, analytical results, instruments |
| **ELN** | Experiment protocols, researcher observations, lab deviations |
| **QMS** | Batch records, OOS deviations, CAPAs, audit findings, specifications |
| **MES** | Manufacturing batches, process parameters, equipment logs, material lots |
| **CTMS** | Clinical trials, sites, enrolled subjects, adverse events, PK samples |
| **Rosetta** | Terminology mappings, unit conversions, compound alias resolution |

Seed data covers realistic biologics scenarios: mAbs, ADCs, kinase inhibitors. Assays include HPLC purity, SEC aggregate, bioassay potency, endotoxin, osmolality. QMS deviations include temperature excursions, yield OOS, container closure failures.

---

## Provider

| Mode | Provider | Notes |
|---|---|---|
| Production | Ollama (local) | Model runs on the same server as Lattice. Nothing leaves the network. |
| Development | OpenRouter | Cloud-hosted. Data is part of the prompt — use only for dev/test with non-sensitive data. |

Switch via `.env`:

```env
# Local (production)
PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-30b-a3b

# Cloud (dev only)
PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=qwen/qwen-2.5-72b-instruct
```

Recommended local model: **Qwen3-30B-A3B** — mixture-of-experts architecture, ~3B parameters active at inference, fits in 20GB RAM, strong tool use and structured output.

---

## Getting started

```bash
# 1. Install prerequisites
brew install opencode
pip install -r mcp-servers/requirements.txt
pip install -r manager/requirements.txt

# 2. Seed the databases
python scripts/seed_databases.py

# 3. Configure
cp .env.example .env
# edit .env — set PROVIDER and API key or Ollama URL

# 4. Launch
./lattice           # default: full registry, straight to OpenCode Web
./lattice web       # with configurator UI for session-level context control
```

---

## What this is not

- A replacement for LIMS, QMS, MES, or any existing system
- A central data warehouse or ETL pipeline
- A write interface — Lattice reads, it does not modify partner data
- Production-ready — this is a proof of concept (no auth, no RBAC, no audit log)

---

*Lattice POC — modeling [Axio BioPharma's Lattice](https://axiobiopharma.com/lattice) as an agentic, MCP-native, local-first intelligence layer for biologics manufacturing.*
