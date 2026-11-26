# Handoff

## Last sprint: v0.10 (Superpowers integration), done

- **Commit:** `74319d9 feat(integrations): superpowers plan ingestion (v0.10.0)`.
- **Tests:** 226/226 pass (22 new: `tests/test_superpowers.py`, plus execution tests in `test_estimate.py` and `test_plan.py`).
- **Acceptance:** a synthetic Superpowers-format plan (4 tasks, non-ASCII title) went through `ingest`, then `schedule.py recompute`. Result: a versioned roadmap (`v0.1`, 5 tasks with a wrapup, priced) and a schedule. The plan file's bytes and mtime were unchanged. This was also run by hand in the scratchpad.
- **Model:** the first exchange ran on Sonnet 5.5, the rest on Opus 5.5 (the maintainer switched).
- **Mistake caught:** the first commit was made with one failing test. A `&&` chain checked the exit code of `tail`, not of the tests. The failure was a stale version in `marketplace.json`; it was fixed and the commit amended (local, unpushed). **Lesson:** capture the test command's own exit code before committing.

### What v0.10 built

- `scripts/integrations/superpowers.py`: `detect()` (plugin registry, unstable, with a fallback) → `parse_plan()` (Task headings, Files list, checkboxes, fences skipped) → `to_plan()` (greedy packing under the threshold, a wrapup per release, `source` pointers) → `ingest` CLI (prices and renders; refuses to overwrite `plan.json` without `--force`).
- `estimate.EXECUTION` = `{inline: 1.0, subagent: 1.5}`, task field `execution`, validated by `plan.py`.
- SKILL.md "Works with Superpowers plans", a README section, a data-sources entry.

### Decisions to review

- **×1.5 for subagent-driven is a guess.** No dogfood data uses that workflow. It should be calibrated once a sprint is run subagent-driven (calibrate.py does not learn it per execution style yet).
- **`--execution auto` assumes subagents**, because the Superpowers header recommends them and the user's handoff choice is not written to the file. That is safety-first (more expensive). On Pro + strict the script recommends inline.
- **The script writes the `plan.json` draft.** That bends "Claude writes plan.json". The skill tells Claude to review the inferred types and sizes and re-price, so Claude still decides; the script only removes the transcription step. Reject this if you prefer the script to print the draft instead.
- **Type and size inference is keyword- and step-count-based** (≤6 steps S, ≤12 M, else L). A standard 5-step TDD task is S.
- Releases are numbered `v0.1…` per ingest, not merged into an existing navitok plan.
- ROADMAP v0.10 checkboxes were left unticked, as in v0.9.

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

## Next sprint: v0.11 (Graphify integration, `S`): not started, needs approval

See ROADMAP §7 v0.11. Integrate **only by detecting Graphify and reading its output files**: no copied code, no writes into its files, "works with", not "official". Check Graphify's current output format from its repository or docs first, and install it only with the maintainer's approval (ROADMAP §2.4). Still open: the v0.2 0-token start snapshot, the manual-reading issue when no statusline is configured, and a live curses run on Linux or macOS.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
