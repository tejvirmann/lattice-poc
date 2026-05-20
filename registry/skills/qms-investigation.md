---
name: QMS Investigation
description: Deviation tracking, CAPA status, batch release, and audit findings
enabled: true
tokens: ~450
systems: [qms, rosetta]
---

When asked about deviations, batch status, or quality events:

1. Use `get_deviations` filtered by severity and status. Distinguish open vs closed.
2. Use `get_open_capas` to surface any overdue corrective actions. Flag anything past due date.
3. Use `check_batch_release_status` when the user wants to know if a batch can be released.
4. Use `get_specifications` to show acceptance limits alongside actual results.
5. Use Rosetta's `standardize_status` to normalize QMS status terms when comparing against LIMS results.

Severity hierarchy: Critical > Major > Minor. Escalate Critical deviations prominently.

When listing CAPAs, always show: owner, due date, days until due (or overdue by X days), and effectiveness check status.
