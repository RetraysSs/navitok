# Handoff

## Last sprint: v0.6 (Handoff and safe stopping), done

- **Commit:** `f148ae4 feat(handoff): checkpoints and session resume (v0.6.0)`.
- **Tests:** 138/138 pass (30 new, `tests/test_handoff.py`).
- **Acceptance:** a synthetic git project in the scratchpad (non-ASCII path). `handoff.py fit` gave FITS at 40% and NO-FIT at 86% (`v0.1-t3`, 7.5% + 2% buffer). `handoff.py write` produced the handoff, and `run.sh start` printed one summary line, nothing on `resume`. **Live:** `claude -p --plugin-dir <repo> --model haiku` with file tools disabled answered "v0.1 (Core), task 3 of 4, Storage to JSON, in progress, `storage.py` uncommitted" from the SessionStart line alone (~22k tokens). This also closes v0.5's open point: plain hook stdout does reach Claude's context.

### What v0.6 built

- `scripts/handoff.py`:
  - `fit`: §10.2 per-task check from `schedule.json`. Exit 0 FITS, 1 NO-FIT, 3 UNKNOWN. A stale reading is flagged, not blocked.
  - `write`: `.navitok/HANDOFF.md` from plan statuses + git, with Claude's `--note` lines.
  - `summary` / `hook`: SessionStart summary, at most 600 characters.
  - Template: `skills/navitok/references/handoff-template.md`. Its `> Resume:` line is what the summary parses.
- `hooks/run.sh start` reads stdin once and feeds both the recorder (silent) and `handoff.py hook`.
- `/navitok:checkpoint` → SKILL.md "Checkpoint flow". SKILL.md now also has "Before every task: fit check" and "Resuming".

### Decisions to review

- **`max_step` is not learned yet**, so the buffer is `max(2, config.max_step_pct)`, i.e. 2% by default. v0.7 should write `max_step_pct` (or compute it from history).
- **Stale readings do not block**, because the usage cache is effectively frozen and blocking would make every task ask for `/usage`. FITS on a stale reading is said once per session.
- **No summary on `resume`** (the conversation is restored). It is printed on `startup`, `clear`, `compact` and `fork`.
- **Task statuses are kept by Claude in `plan.json`** (SKILL rule). No script edits them, so the "Claude writes plan.json" rule holds.
- The handoff is written *after* the checkpoint commit, so "last commit" is correct, and `.navitok/HANDOFF.md` itself is not committed unless the user tracks `.navitok/`.

### New known issue (v0.5 schedule, found in v0.6, not fixed: out of scope)

- **A manual `/usage` reading does not survive the next prompt.** `schedule.py recompute --session-pct N` writes it to `schedule.json`, but the `UserPromptSubmit` hook then recomputes from the (stale) usage cache and overwrites it. The fit check then reads the stale number again. Fix in v0.7 or v0.8: persist the manual reading (e.g. a `manual` snapshot in `.navitok/` with a timestamp) and let `account_usage` prefer it while it is fresher than the cache.

### Known issue (v0.2 recorder, not fixed: out of scope)

- When `/navitok:plan` creates `.navitok/` partway through a session, `SessionStart` was skipped (no folder yet), so the first snapshot comes from `Stop`, after the work. The record then shows **0 local tokens**. Seen in the sample project's `history.jsonl`. A fix fits v0.5 or v0.6: take the start snapshot from the transcript's first message instead.

### Lessons (v0.2–v0.5) (keep in mind)

- **Hook stdin is UTF-8.** Python on Windows decodes stdin with the ANSI code page (cp1254 here), so always read `sys.stdin.buffer`. Test with non-ASCII paths: this machine's home is `C:\Users\ÜNSAL`.
- To check whether a hook ran, look at the `system` / `stop_hook_summary` record in the transcript. Silent successful hooks leave no other trace.
- **The usage cache (`~/.claude.json`) is effectively frozen.** Neither `/usage` nor a new session refreshed it. The account-wide % in automatic records is unreliable until the statusline snapshot exists (v0.8). Manual `/usage` stays ground truth for the dogfood ledger.
- CLI output must be UTF-8 (`sys.stdout.reconfigure`), or the Bash tool and tests get garbled text on Windows (v0.4).
- Because the usage cache is frozen, the `UserPromptSubmit` hook in a real session will usually see a **stale** reading (`usage_stale: true`) until v0.8's statusline snapshot exists. `schedule.py recompute --session-pct N --weekly-pct N` feeds a manual `/usage` reading (v0.5).

## Next sprint: v0.7 (Learning, external usage, adaptive threshold, `M`): not started, needs approval

See ROADMAP §7 v0.7, §10.1 and §10.3. It is an `M` sprint. Check the scope before starting and propose a split if it looks too big for one session. Inputs from v0.6: `config.max_step_pct` (buffer), `weekly_per_session` (0.15 cold start), the manual-reading issue above, and v0.2's 0-token start snapshot.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
