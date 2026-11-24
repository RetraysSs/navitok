# Dogfood report

The real cost of building navitok with navitok's own approach (ROADMAP §6). Raw records are in [`ledger.jsonl`](ledger.jsonl), schema in ROADMAP §10.5.

All numbers are % of one 5-hour session on the maintainer's plan, read manually from `/usage` unless noted otherwise.
- **Actual** is the account-wide session % change. It includes any claude.ai or other-machine use during the sprint.
- **Error** is actual minus the midpoint of the estimate. It is not adjusted for external usage, so check the notes.
- `null` means the number was not reported.

> One maintainer, one plan, one project. This data improves the cold start; it does not replace per-user calibration.

| Sprint | Date | Plan | Estimate | Actual | Error | Session % (start→end) | Weekly % (start→end) | Notes |
|---|---|---|---|---|---|---|---|---|
| v0.0 | 2026-11-24 | Pro | 8–17% | 1% | −11.5 | 27→28 | 11→11 | Pure scaffolding, overestimated ~10×. `/usage` has integer resolution (true delta 0–2%). Main cost: one docs fetch through a subagent (~62k subagent tokens). claude.ai open but idle. Wrap-up (t5) happened after the end reading. |
| v0.1 | 2026-11-24 | Pro | 7.5–19.5% | 4% (±2) | −9.5 | 30→31, reset, 0→3 | 11→12 | Two parts (5-hour window reset mid-sprint), each ±1. Overestimated ~3×. Local tokens: 34k output, 2.13M cache read. Main drivers: a docs fetch through a subagent, then code + tests with large context re-reads. Wrap-up included. Pre-sprint 28→30 (chores, claude.ai, plugin test) excluded. |
