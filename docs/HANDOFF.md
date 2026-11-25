# Handoff

## Last sprint: v0.9 (Terminal panel), done

- **Commit:** `7e06d3e feat(ui): live terminal panel (v0.9.0)`. The ROADMAP v0.9 bullets were updated in the same commit, at the maintainer's request.
- **Tests:** 204/204 pass (24 new, `tests/test_watch.py`). They include a regression test for non-ASCII and real 8.3 short paths (`C:\Users\ÜNSAL` ↔ `C:\Users\NSAL~1`) across the panel, the statusline and both hooks. It runs for real on this machine, not skipped.
- **Acceptance:**
  - A 60-minute background soak (`--plain --interval 2 --duration 3600 --log`) on the synthetic scratchpad project ran 3602 s with 1799 frames, 0 errors, empty stderr and no error frames. Five rounds of schedule/snapshot/calibration rewrites ran underneath it. It started once and its log was read once at the end, as the maintainer asked.
  - The soak ran the code from **before** the formatting polish (Python had already loaded the module). The polish changed formatting and labels only, and the tests cover it.
  - The maintainer looked at the live panel in a real terminal: "looks good".
- **Polish from that review:** local time zone, `used · stop at · left` wording, one decimal everywhere, session labels by local date and time.

### What v0.9 built

- `scripts/watch.py`: `gather()` (local files; a fresh snapshot ≤10 min wins) → `frame()` (≤80×24, truncates).
- **Display**, in order of preference:
  - `run_curses` where `curses` exists.
  - Otherwise `run_ansi`: `enable_vt()` via ctypes `SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)`, and `Keys` (`msvcrt` on Windows, `termios`/`select` elsewhere; no tty → plain sleep).
  - `--once` plain.
- **Options:** `--plain`, `--interval`, `--duration`, `--log`.
- SKILL.md "Terminal panel" section and a README section with the alias suggestion.

### Decisions to review

- **The curses path is untested live here:** Windows' Python has no `_curses`. It is a thin loop around the same `frame()`. It should get a manual run on Linux or macOS before v1.0.
- **Zone names:** the abbreviation comes from the OS. On Windows that is the long name (`GMT Standard Time`), because the stdlib has no tz database and inventing initials would be wrong (UK time is GMT/BST, not "GST").
- **"Estimate vs actual for recent tasks"** shows recent *sessions* (estimate midpoint vs local actual), because per-task actuals are not recorded.
- **README status line** still says v0.0.1. The full README rewrite belongs to v1.0, so it was left alone.

### Known issue (v0.5 schedule, found in v0.6, open only without a statusline)

- **A manual `/usage` reading does not survive the next prompt.** `schedule.py recompute --session-pct N` writes it to `schedule.json`, but the `UserPromptSubmit` hook then recomputes from the (stale) usage cache and overwrites it. The fit check then reads the stale number again. Fix in v0.7 or v0.8: persist the manual reading (e.g. a `manual` snapshot in `.navitok/` with a timestamp) and let `account_usage` prefer it while it is fresher than the cache.

### Known issue (v0.2 recorder, not fixed: out of scope)

- When `/navitok:plan` creates `.navitok/` partway through a session, `SessionStart` was skipped (no folder yet), so the first snapshot comes from `Stop`, after the work. The record then shows **0 local tokens**. Seen in the sample project's `history.jsonl`. A fix fits v0.5 or v0.6: take the start snapshot from the transcript's first message instead.

### Lessons (v0.2–v0.5) (keep in mind)

- **Hook stdin is UTF-8.** Python on Windows decodes stdin with the ANSI code page (cp1254 here), so always read `sys.stdin.buffer`. Test with non-ASCII paths: this machine's home is `C:\Users\ÜNSAL`.
- To check whether a hook ran, look at the `system` / `stop_hook_summary` record in the transcript. Silent successful hooks leave no other trace.
- **The usage cache (`~/.claude.json`) is effectively frozen.** Neither `/usage` nor a new session refreshed it. The account-wide % in automatic records is unreliable until the statusline snapshot exists (v0.8). Manual `/usage` stays ground truth for the dogfood ledger.
- CLI output must be UTF-8 (`sys.stdout.reconfigure`), or the Bash tool and tests get garbled text on Windows (v0.4).
- Because the usage cache is frozen, the `UserPromptSubmit` hook in a real session will usually see a **stale** reading (`usage_stale: true`) until v0.8's statusline snapshot exists. `schedule.py recompute --session-pct N --weekly-pct N` feeds a manual `/usage` reading (v0.5).

## Next sprint: v0.10 (Superpowers integration, `S`): not started, needs approval

See ROADMAP §7 v0.10. Integrate **only by detecting Superpowers and reading its output files**. Never copy its code, never write into its plan files (navitok's output goes under `.navitok/`), and say "works with", not "official". Check Superpowers' current plan-file format from its repository or docs first; do not write it from memory. Still open: the v0.2 0-token start snapshot, and the manual-reading issue when no statusline is configured.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
