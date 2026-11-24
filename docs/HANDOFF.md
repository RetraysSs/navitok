# Handoff

## Last sprint: v0.5 (Schedule engine + update tiers), done

- **Commit:** `43a96a3 feat(schedule): live schedule with tiered updates (v0.5.0)`.
- **Tests:** 108/108 pass (32 new, `tests/test_schedule.py`).
- **Acceptance:** a synthetic project in the scratchpad (non-ASCII path), driven through `sh hooks/run.sh prompt` with UTF-8 stdin and a statusline-format `usage_snapshot.json`. With session % going 66 → 66 → 81 → 81 → 81 → 2 → 2, the output was nothing, nothing, one "v0.1 no longer fits" line, nothing, nothing, one "fits again" line, nothing. `ROADMAP.md` followed each step. There were no model calls.
- **Not yet verified live:** that the line actually reaches Claude's context in a real session (`/reload-plugins` in a project with `.navitok/plan.json`). The docs say plain stdout on exit 0 does (quoted verbatim in `docs/data-sources.md`).

### What v0.5 built

- `scripts/schedule.py`: `recompute` (Tier 0 + 1 + 2 detection, `--session-pct/--weekly-pct` override), `show`, `hook` (`UserPromptSubmit` entry point). Pure `compute()` + `notice()` for tests.
- Packing is greedy and in order. A release joins the open session if its remaining upper estimate fits what is left of it, otherwise it opens the next one. The weekly cost is `session hi × 0.15` (cold start, from the dogfood ledger, `weekly_per_session` in config). In strict mode a week overflow moves the release to the next week in a fresh session. In flex mode it is marked `extra`.
- The Tier-1 state is `status_key` (`<release>:fits|no-fit`) in `schedule.json`. A line is printed on a change to no-fit, or on a return from no-fit to fits for the same release. A release finishing, or usage being unknown, is silent.
- Tier 2: `replan` list + `replan_key`, which is announced once per new trigger set. The baseline for the slip trigger (`baseline.final_week_ends_at`) resets when the plan's fingerprint changes (plan, mode, release and task ids). So a Claude replan does not trigger "slipped".
- `hooks/run.sh prompt` passes stdout through (stderr dropped). The other modes stay fully silent.
- `plan.py render/price` keep the last schedule section (a lazy import of `schedule`).

### Decisions to review

- **The release fit uses the threshold only, without the §10.2 buffer.** The per-task check with `buffer = max(2, max_step)` belongs to v0.6.
- **The 0.15 weekly/session ratio** comes from one maintainer's Pro data (≈34 session-% moved weekly by ≈5). The ROADMAP has no ratio. v0.7 should calibrate it.
- **"Scope changed" (§10.4, 4th trigger)** is detected only as a config plan/mode mismatch with `plan.json`. Scope changes arrive through the user asking, and then Claude replans directly.
- **External reserve** is `null` and 0 in packing until v0.7.
- **Placement ignores calendar time**, that is, how many 5-hour sessions fit before the weekly reset. Only the % capacity is modelled.

### Known issue (v0.2 recorder, not fixed: out of scope)

- When `/navitok:plan` creates `.navitok/` partway through a session, `SessionStart` was skipped (no folder yet), so the first snapshot comes from `Stop`, after the work. The record then shows **0 local tokens**. Seen in the sample project's `history.jsonl`. A fix fits v0.5 or v0.6: take the start snapshot from the transcript's first message instead.

### Lessons (v0.2–v0.5) (keep in mind)

- **Hook stdin is UTF-8.** Python on Windows decodes stdin with the ANSI code page (cp1254 here), so always read `sys.stdin.buffer`. Test with non-ASCII paths: this machine's home is `C:\Users\ÜNSAL`.
- To check whether a hook ran, look at the `system` / `stop_hook_summary` record in the transcript. Silent successful hooks leave no other trace.
- **The usage cache (`~/.claude.json`) is effectively frozen.** Neither `/usage` nor a new session refreshed it. The account-wide % in automatic records is unreliable until the statusline snapshot exists (v0.8). Manual `/usage` stays ground truth for the dogfood ledger.
- CLI output must be UTF-8 (`sys.stdout.reconfigure`), or the Bash tool and tests get garbled text on Windows (v0.4).
- Because the usage cache is frozen, the `UserPromptSubmit` hook in a real session will usually see a **stale** reading (`usage_stale: true`) until v0.8's statusline snapshot exists. `schedule.py recompute --session-pct N --weekly-pct N` feeds a manual `/usage` reading (v0.5).

## Next sprint: v0.6 (Handoff and safe stopping, `S`): not started, needs approval

See ROADMAP §7 v0.6 and §10.2. Use `schedule.json` for the per-task fit check (`remaining ≥ task upper + buffer`). Re-verify the `SessionStart` context-output fields first. The known issue above (a start snapshot of 0 tokens) fits here too, but only if it stays in scope.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
