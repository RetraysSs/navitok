# Handoff

## Last sprint: v0.7 (Learning, external usage, adaptive threshold), done

- **Commit:** `ccb3b74 feat(learn): calibration, external usage and adaptive threshold (v0.7.0)`.
- **Tests:** 160/160 pass (22 new, `tests/test_calibrate.py`), including the real dogfood ledger.
- **Acceptance:** synthetic history through the real `run.sh start` hook in a scratchpad project:
  - 20 low-variance sessions: threshold **96.5**, confidence 98.
  - The same history with 10% web usage in 4 sessions: threshold and error spread unchanged (96.5, ±0.2), external ≈10% per web session, 3.9% reserved.
  - High variance: threshold **90**, confidence 60.
  - The cap holds at 98.
  - `price` used the learned ranges, `/navitok:status` printed, and `fit` used the learned 2.1% buffer.
- **Real dogfood ledger:** n=6 (v0.0 has no tokens, so "missing data"). sigma_err 3.5, max_step 2.27, threshold 90, confidence 20. %-per-weighted-token ≈8.0e-6. Learned weekly ratio 0.097 (cold start was 0.15). Learned per-type means are 2–3× below the cold-start table.

### What v0.7 built

- `scripts/calibrate.py` (`update`, `report --history`, `status`, `hook`) → `.navitok/calibration.json` (script-owned).
- `scripts/external.py`: token weights, %-per-token fit (P25 of ratios, ≥5 sessions), external per session, weekday/weekly P80 profile, reserve.
- `plan.load_config` attaches the calibration under `cfg["calibration"]`. `write_config` strips it. `threshold_for`, `learned_types`, `price(..., learned)` and `estimate(..., learned)` use it.
- `schedule.compute`: `week_cap = threshold − reserve` and the learned weekly ratio. `handoff.fit_check`: buffer from the learned `max_step`.
- `hook_session`: `plan_tasks` snapshot at start, `finished_tasks` diff at end → `tasks` + `release` in the history record.
- `/navitok:status` → `calibrate.py status`.

### Decisions to review

- **Small scope addition:** the recorder now attaches finished plan tasks. Without it, automatic history has `tasks: []` and calibration never learns for real users.
- **sigma_err** is the weighted std of signed (local − estimate midpoint), not literally of |error|. A consistent bias is corrected by the learned per-type means and should not lower the threshold.
- **Apportioning:** session local % is split by estimate midpoint. So per-type differences come only from the task mix, until per-task actuals exist (v0.12 or a per-task snapshot could add them).
- **The token weights (1/5/0.1/1.25) are an assumption**, marked unstable in `docs/data-sources.md`.
- **The weekly profile uses ISO weeks** and counts weekly-% gaps between records as external. In the dogfood ledger those gaps include unrecorded local chores.
- **`ROADMAP.md` has uncommitted checkbox ticks** that I did not make. They are left as found for the maintainer.

### Known issue (v0.5 schedule, found in v0.6, still open)

- **A manual `/usage` reading does not survive the next prompt.** `schedule.py recompute --session-pct N` writes it to `schedule.json`, but the `UserPromptSubmit` hook then recomputes from the (stale) usage cache and overwrites it. The fit check then reads the stale number again. Fix in v0.7 or v0.8: persist the manual reading (e.g. a `manual` snapshot in `.navitok/` with a timestamp) and let `account_usage` prefer it while it is fresher than the cache.

### Known issue (v0.2 recorder, not fixed: out of scope)

- When `/navitok:plan` creates `.navitok/` partway through a session, `SessionStart` was skipped (no folder yet), so the first snapshot comes from `Stop`, after the work. The record then shows **0 local tokens**. Seen in the sample project's `history.jsonl`. A fix fits v0.5 or v0.6: take the start snapshot from the transcript's first message instead.

### Lessons (v0.2–v0.5) (keep in mind)

- **Hook stdin is UTF-8.** Python on Windows decodes stdin with the ANSI code page (cp1254 here), so always read `sys.stdin.buffer`. Test with non-ASCII paths: this machine's home is `C:\Users\ÜNSAL`.
- To check whether a hook ran, look at the `system` / `stop_hook_summary` record in the transcript. Silent successful hooks leave no other trace.
- **The usage cache (`~/.claude.json`) is effectively frozen.** Neither `/usage` nor a new session refreshed it. The account-wide % in automatic records is unreliable until the statusline snapshot exists (v0.8). Manual `/usage` stays ground truth for the dogfood ledger.
- CLI output must be UTF-8 (`sys.stdout.reconfigure`), or the Bash tool and tests get garbled text on Windows (v0.4).
- Because the usage cache is frozen, the `UserPromptSubmit` hook in a real session will usually see a **stale** reading (`usage_stale: true`) until v0.8's statusline snapshot exists. `schedule.py recompute --session-pct N --weekly-pct N` feeds a manual `/usage` reading (v0.5).

## Next sprint: v0.8 (Statusline, `S`): not started, needs approval

See ROADMAP §7 v0.8. Re-verify the statusline docs first (stdin JSON, `rate_limits`, `refreshInterval`). The statusline snapshot (`.navitok/usage_snapshot.json`) is what finally gives fresh account-wide %, so it should also resolve the manual-reading issue above. Never replace an existing user statusline: wrap it, and only with explicit approval. The v0.2 0-token start snapshot is still open.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
