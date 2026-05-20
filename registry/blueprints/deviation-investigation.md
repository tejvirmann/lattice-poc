---
name: Deviation Investigation
description: Cross-system investigation linking QMS deviation to LIMS analytical data
enabled: true
tokens: ~600
systems: [qms, lims, rosetta]
---

Follow these steps when the user asks to investigate a deviation, OOS result, or batch quality event:

**Step 1 — Find the deviation in QMS**
Use `get_deviations` to retrieve the full deviation record including description, severity, root cause, and status.

**Step 2 — Identify affected batches and products**
Note the lot number, product, and manufacture date from the deviation record.

**Step 3 — Pull LIMS results for affected samples**
Use `search_samples` to find samples corresponding to the affected lot, then `get_assay_results` to retrieve all analytical results. Flag any failures.

**Step 4 — Normalize terminology via Rosetta**
Use `normalize_term` to map QMS deviation terms and LIMS result statuses to canonical forms. Use `standardize_status` to align pass/fail designations across systems.

**Step 5 — Check open CAPAs**
Use `get_open_capas` to surface any corrective actions linked to this deviation. Flag overdue CAPAs.

**Step 6 — Synthesize**
Present a structured investigation summary:
- Deviation number, severity, description, root cause
- Affected lot(s) and product
- Analytical results table (all assays, pass/fail highlighted)
- Open CAPAs with owner and due date
- Risk assessment: is this batch releasable? Are there systemic patterns?
