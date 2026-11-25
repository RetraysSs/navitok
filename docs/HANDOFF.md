# Handoff

## Last sprint: v0.8 (Statusline), done

- **Commit:** `79a7837 feat(ui): statusline segment (v0.8.0)`.
- **Tests:** 180/180 pass (20 new, `tests/test_statusline.py`).
- **Acceptance:** a synthetic project in the scratchpad (non-ASCII path), with the generated command run through `sh -c` on synthetic stdin.
  - Session 40 → 81 → 93% gave "fits" → "fits" → "no fit: checkpoint", in 123–148 ms each and with no model calls.
  - The `UserPromptSubmit` hook then read the snapshot as `source: statusline, stale: false` and printed exactly one Tier-1 line at 93%.
  - A wrapped user command kept its output first (`my-line 15:30 │ v0.1 …`).
  - `setup` against the maintainer's real settings was a dry run only ("Current statusLine: null"); nothing was written.
- **Not yet verified live:** a real Claude Code session with the statusline configured. That needs the maintainer's approval to run `statusline.py setup --apply`, which edits `~/.claude/settings.json`.

### What v0.8 built

- `scripts/statusline.py`:
  - default: the segment, plus the snapshot writer (on a change or once a minute).
  - `--wrap CMD`: composes with the user's statusline (`sh -c`; sh first, because System32 `bash.exe` is WSL).
  - `setup` / `remove [--settings P] [--apply]`: approval-gated settings change, with a backup.
- `SKILL.md`: a "Statusline" section (show the change, ask, apply only on an explicit yes).

### Decisions to review

- **The statusline fit** uses the live session % + `current_remaining_pct[1]` ≤ `threshold` from `schedule.json`. It does not recompute or write the schedule; only the prompt hook does that.
- **The command embeds absolute paths** (`sys.executable` and this plugin version's `statusline.py`). After a plugin update, `setup` must be run again. v0.13 (doctor) should detect a stale path.
- **`is_navitok`** recognises its own command by `statusline.py` plus "navitok" in the path.
- **The manual-reading issue** below is solved in practice once the statusline is configured, because the fresh snapshot wins. Without a statusline it is still open.

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

## Next sprint: v0.9 (Terminal panel, `S`): not started, needs approval

See ROADMAP §7 v0.9. Stdlib `curses` only. On Windows, `curses` is not in the standard library (it needs the third-party `windows-curses`, which is not allowed), so check that first and propose a fallback (e.g. a plain refreshing text view) before building. The v0.2 0-token start snapshot is still open.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
