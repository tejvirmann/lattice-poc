---
name: LIMS Analysis
description: Analytical result querying, OOS trend detection, and cross-batch comparisons
enabled: true
tokens: ~400
systems: [lims, rosetta]
---

When asked about analytical results, samples, or assay data:

1. Use `search_samples` to locate the relevant sample set before pulling results.
2. Use `get_assay_results` with specific assay names — do not retrieve all results at once.
3. Use `get_oos_results` when investigating failures or building a deviation narrative.
4. Use `compare_compound_results` when the user asks about trends or cross-batch patterns.
5. Use Rosetta's `normalize_term` to map assay names to canonical terms before presenting cross-system comparisons.

When presenting results, always include: compound, sample name, assay, value, unit, pass/fail, and run date. Format as a table.

Flag any result where pass_fail = "Fail" in bold or with a clear marker.
