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
| v0.2 | 2026-11-24 | Pro | 5–13% | 8% (±1) | −1.0 | 6→14 | 12→13 | First estimate inside its range. Includes two short test sessions. Drivers: an unplanned debugging loop (Windows cp1254 stdin garbled the non-ASCII path; a flawed revert check had to be redone), a large docs fetch, growing context (7.3M cache read). Pre-sprint 3→6 (history rewrite, CLAUDE.md removal) excluded. |
| v0.3 | 2026-11-24 | Pro | 5.5–10.5% | 2% (±1) | −6.0 | 16→18 | 14→14 | Fresh session. Overestimated ~4×. No subagents, no docs fetch, no debugging; tests passed on the first run. Local tokens: 16k output, 0.75M cache read. One extra commit restored handoff text dropped by mistake. Wrap-up included. Pre-sprint 15→16 excluded. |
| v0.4 | 2026-11-24 | Pro | 8–21% | 6% (±1) | −8.5 | 23→29 | 15→15 | Below the low end, ~2.4× over. Same session as v0.3 (warm context). Includes two `/navitok:plan` acceptance sessions (~0.48M tokens). Little skill iteration: one wording fix. Drivers: a docs check through a subagent, a Windows UTF-8 stdout bug. Pre-sprint 18→23 (light claude.ai) excluded. |
| v0.5 | 2026-11-24 | Pro | 6.5–16% | 6% (±1) | −5.25 | 30→36 | 16→16 | Just below the low end, ~1.9× over (closest ratio so far). Fresh session, no external use. Drivers: a docs check through a subagent that needed a second verbatim pass (~158k subagent tokens), one large script + test file written in one go, one failed scripted edit redone, acceptance rerun once (first jump did not cross the threshold). Wrap-up included. |
| v0.6 | 2026-11-25 | Pro | 5–12.5% | 4% (±1) | −4.75 | 5→9 | 17→18 | Just below the low end, ~2.2× over. Fresh session; claude.ai use (~5%) was before the start reading and is excluded. Drivers: one narrow docs check through a lighter-model subagent (~27k tokens), one script + test file written in one go (tests passed first time), one live `claude -p` acceptance session (~22k tokens), one CLI argument retry. Wrap-up included. |
| v0.7 | 2026-11-25 | Pro | 6–15.5% | 6% (±1) | −4.75 | 10→16 | 18→19 | At the low end, ~1.8× over. Same session as v0.6 (warm context), no external use. No subagents or docs fetch. Drivers: two new modules + a large test file in one go (tests passed first time), growing context (3.48M cache read), one failed scripted edit redone. The sprint's own token model predicts ~5.2% for it (measured 6). Wrap-up included. |
| v0.8 | 2026-11-25 | Pro | 3.5–10% | 3% (±1) | −3.75 | 17→20 | 19→19 | Below the low end, ~2.3× over. Same session as v0.6–v0.7, no external use. Drivers: one docs check through a lighter-model subagent (~45k tokens), one script + test file in one go, one Windows shell bug caught by tests (wrapped command ran via cmd.exe). The v0.7 token model predicts ~3.6% (measured 3). Wrap-up included. |
