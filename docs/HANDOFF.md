# Handoff

## Last sprint: v0.12 (Output trimming hook), done

- **Commits:** `d10c4f4 feat(ledger): record predicted scope next to actuals; plan.json write rule` (the maintainer's v0.11 review items 2 and 3, as asked), then `5fa88b1 feat(hooks): optional output trimming (v0.12.0)`.
- **Tests:** 257/257 pass (13 new in `tests/test_trim_output.py`, 2 in `tests/test_graphify.py`). Every commit ran only after the test command's own exit code was 0, and after `git diff --cached` showed no `CLAUDE.md`, `.claude/` or `graphify-out/`.
- **Acceptance:** a real generated 400-test unittest run with one failure (~410 stderr lines) is trimmed to under 80 lines. The assertion message, the failing test's name and the `FAILED (failures=1)` summary are kept, and the full output is in `.navitok/logs/`. Graphify's real `PreToolUse` hook (`graphify hook-guard search`) and navitok's `PostToolUse` hook ran concurrently on one Bash call: both exit 0, Graphify still returns its `additionalContext`, and our output is trimmed.
- **Graphify in use this session:** `graphify-out/` is gitignored, and the graph of this repo was built with `graphify update .` (910 nodes, 1867 edges, no LLM). `graphify claude install` was run with the maintainer's approval. Its `PreToolUse` hook was live during the sprint and added a nudge to every Bash call. I did not run `graphify query`/`apply` for this sprint's tasks; the graph was used for the hook test.

### Local changes from Graphify's install (not committed, need the maintainer's decision)

- `CLAUDE.md` (gitignored): an 11-line `## graphify` section was appended. The pre-install copy is in this session's scratchpad (`.../scratchpad/backup/CLAUDE.md`). Remove it with `graphify claude uninstall`, or keep it.
- `.claude/settings.json` (new, untracked): Graphify's `PreToolUse` (`Bash|Grep`, `Read|Glob`) and `SessionStart` (`compact`) hooks. Listed in `.git/info/exclude` (local only) so it cannot be staged by accident.
- Also in the local `CLAUDE.md`: the maintainer's new rule that scripts change `plan.json` only through user-run apply/ingest commands, never from hooks (also in ROADMAP §4.1, committed).

### Decisions to review

- **Mechanism: `PostToolUse` + `updatedToolOutput`**, not `PreToolUse` + `updatedInput`. Checked against the hooks docs: `updatedInput` replaces the whole input, matching hooks run in parallel with no documented winner, and auto mode can deny a changed call. `PostToolUse` never changes the command, so it cannot race Graphify's hook. The trade-off: the command's full output is still produced (the saving is in context, not in run time).
- **Not verified live yet:** that Claude Code accepts the replacement `tool_response` object for Bash (`stdout`, `stderr`, `interrupted`, `isImage`). To check: `claude --plugin-dir .`, set `"trim_output": true` in `.navitok/config.json`, run a long failing command, and confirm the trimmed text with the `[navitok: ... trimmed ...]` marker reaches Claude.
- Defaults: `max_lines` 120, `head` 10, `tail` 40, `context` 3, `keep_logs` 20. The error regex is broad (it matches `error`, `fail`, `assert`, `cannot`, ...), which errs toward keeping lines.
- `run.sh trim` probes Python on every Bash call even when trimming is off (two short Python starts). Acceptable for now; `/navitok:setup` (v0.13) could register the hook only when it is enabled.
- `files_predicted` / `lines_predicted` are recorded by the session hook from `task.scope`. Calibration does not learn from them yet (as agreed).
- ROADMAP v0.12 checkboxes were left unticked, as before.

### Still open from v0.11

- Lines are recorded, not priced (agreed). Broad scope (agreed for now). The map release sizes are low-confidence guesses (agreed).

### Earlier decisions still open (v0.10)

- ×1.5 for subagent-driven is a guess; `--execution auto` assumes subagents; the script writes the `plan.json` draft; type and size are inferred from keywords and step counts.

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

## Next sprint: v0.13 (`/navitok:setup`, doctor, `S`): not started, needs approval

See ROADMAP §7 v0.13. It should offer to enable `trim_output` (and could register the trim hook only then). Still open: the live check of `updatedToolOutput` above, the v0.2 0-token start snapshot, the manual-reading issue when no statusline is configured, a live curses run on Linux or macOS, and the decision on Graphify's local `CLAUDE.md` section and `.claude/settings.json`.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
