# Handoff

## Last sprint: v0.2 (Ledger), done

- **Commit:** `112ec71 feat(ledger): session history recording (v0.2.0)`.
- **Tests:** 36/36 pass. `claude plugin validate .` passes with the same warnings as before.
- **Acceptance:** a real `claude --plugin-dir .` session (send `hi`, then `/exit`) appended one valid record to `.navitok/history.jsonl`:
  - local tokens (96.5k total), model, effort, `ended_cleanly: true`;
  - an account-wide % from the usage cache, **flagged stale** (56 minutes old).

### What v0.2 built

- `scripts/ledger.py`: schema 2 (§10.5 plus `session_id`, `local_tokens_by_model`, `parts`). `append` is locked and validated; `read_all` tolerates corrupt lines; `last_session`.
- Hooks (`hooks/hooks.json` → `sh hooks/run.sh <start|stop|end>` → `scripts/hook_session.py`):
  - `SessionStart` saves a snapshot, `Stop` refreshes it, `SessionEnd` writes the record. `SessionEnd` does no transcript parsing because of its 1.5 s budget.
  - Active only when `<cwd>/.navitok/` exists. Always silent. Errors go to `.navitok/hook-errors.log`.
  - State lives in `.navitok/sessions/<session_id>.json`. Orphans are flushed at the next start with `ended_cleanly: false`.
- `run.sh` probes `python3`, then `python`, because the Windows Store alias does not run.

### Lessons (keep in mind)

- **Hook stdin is UTF-8.** Python on Windows decodes stdin with the ANSI code page (cp1254 here), so always read `sys.stdin.buffer`. Test with non-ASCII paths: this machine's home is `C:\Users\ÜNSAL`.
- To check whether a hook ran, look at the `system` / `stop_hook_summary` record in the transcript. Silent successful hooks leave no other trace.
- **The usage cache (`~/.claude.json`) is effectively frozen.** Neither `/usage` nor a new session refreshed it. The account-wide % in automatic records is unreliable until the statusline snapshot exists (v0.8). Manual `/usage` stays ground truth for the dogfood ledger.

## Next sprint: v0.3 (Estimator v1, cold start), waiting for maintainer approval

- Start with the §6.1 protocol: `/usage` + reset time, claude.ai / other use, the estimate. Ask for the final `/usage` only after the last commit, and record small deltas as ±1.
- Seed `references/heuristics.md` from `docs/dogfood/ledger.jsonl`, which now holds v0.0–v0.2. The first sprints were overestimated 3–10×.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
