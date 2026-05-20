---
name: Batch Release
description: Aggregate release testing results and QMS status into a go/no-go summary
enabled: true
tokens: ~550
systems: [qms, lims, rosetta]
---

Follow these steps when the user asks about batch release readiness:

**Step 1 — Get batch record from QMS**
Use `get_batch` or `check_batch_release_status` to retrieve the batch record, current status, and any open deviations.

**Step 2 — Get specifications**
Use `get_specifications` for the product to know the acceptance limits for each parameter.

**Step 3 — Pull release testing results from LIMS**
Use `search_samples` to find the drug product/drug substance sample for this lot, then `get_assay_results` for all assays.

**Step 4 — Compare results against specifications**
For each specification parameter, find the corresponding LIMS result. Use Rosetta `normalize_term` to match parameter names across systems. Flag any result that is OOS or missing.

**Step 5 — Render a release decision table**

| Parameter | Specification | Result | Unit | Status |
|---|---|---|---|---|
| HPLC Purity | ≥ 97.0% | 98.4% | % | PASS |
| Endotoxin | ≤ 0.5 EU/mL | 0.12 | EU/mL | PASS |
| ... | | | | |

**Step 6 — Go/No-Go recommendation**
State clearly: RELEASE RECOMMENDED or RELEASE BLOCKED, with reasons.
If blocked, list: open deviations, OOS results, or missing data.
