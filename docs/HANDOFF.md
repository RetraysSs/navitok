# Handoff

## Last sprint: v1.0a (fast trim off path, README, examples), done

- **Split:** v1.0 is `M` and partly outward-facing, so it was split into v1.0a (this) and v1.0b (release steps). Noted in ROADMAP v1.0.
- **Commits:** `70be5b9 perf(hooks): fast off path for the trim hook`, `0256052 docs: v1.0 README, examples and ROADMAP without CLAUDE.md`. Tests 278/278 (3 new in `tests/test_run_sh_fast.py`).
- **Trim hook (the maintainer's first task):** kept registered. `run.sh trim` decides "off" with shell builtins only (no fork, no Python). Every other config layout falls through to Python, which checks the config before its heavier imports. Measured: **231 ms → 19 ms** per Bash call with trimming off (Claude Code's own timing: 60 ms). On: ~236 ms, unchanged. Table and method in `docs/data-sources.md`.
- **Behaviour change to review:** the shell fast path reads `$CLAUDE_PROJECT_DIR/.navitok/config.json` and `./.navitok/config.json`, not the payload `cwd`. Verified live that `CLAUDE_PROJECT_DIR` is set for plugin hooks. A `.navitok/` that exists only in the session's current folder is no longer seen; trimming was only meant for the project root anyway. The hook tests now set `CLAUDE_PROJECT_DIR`, as Claude Code does.
- **ROADMAP §2.2/§9:** no longer tell anyone to read `CLAUDE.md`; they point to §5, §6.1 and the README. The contributor rules from `CLAUDE.md` are in README "Contributing". The local `CLAUDE.md` is unchanged.
- **README:** rewritten for 1.0. "Built with navitok" uses the real REPORT.md numbers: 15 sprints; 2 of 9 inside the range for v0.0–v0.8, 6 of 6 for v0.9–v0.13; mean error 6.1 then 2.5 points. The install commands are not tested yet (v1.0b). There are no screenshots yet; the statusline example is a text line.
- **examples/:** `pro-strict/` and `max5x-flex/` (same todo-cli project) were generated with `plan.py config` + `price`. Their estimates are real script output.
- **Small finding:** `plan.py`'s `_write_json` (and the doctor wizard through it) writes CRLF on Windows (`write_text` without `newline`). `.gitattributes` normalises it in the repo. It's harmless for JSON, but could be fixed with `newline="\n"`.
- **Local cleanup:** the headless check session was removed from `.navitok/history.jsonl`, and its `config.json`, `logs/` and `calibration.json` were deleted.

## Previous sprint: v0.13 (`/navitok:setup`, doctor, wizard), done

- **Commit:** `8769bd5 feat(setup): doctor and first-run wizard (v0.13.0)`. Tests 275/275 (9 new in `tests/test_doctor.py`).
- **What it does:** `doctor.py check` is a read-only ✅/❌ table covering Python (the only required item), `.navitok/` state, usage source and freshness, statusline (navitok, custom-not-wrapped or none; project-local > project > user), trimming, Superpowers, and Graphify (CLI + graph). Each gap has why it helps and the command to fix it. `doctor.py wizard` writes plan, mode, statusline and trimming to `config.json` only and explains both trimming paths. The statusline change is only proposed, via `statusline.py setup` without `--apply`. `commands/setup.md` points to the new **Setup** section in `SKILL.md`, which says to run nothing without explicit approval of that command.
- **Acceptance:** a clean machine is simulated in tests (empty home and project, no CLI): all 6 gaps reported, both folders untouched. A CLI run with an empty `HOME`/`USERPROFILE` and a minimal `PATH` exits 0. Live: `/navitok:setup` in `claude -p --plugin-dir` in an empty folder ran the doctor, reported the gaps correctly, asked the wizard questions with both trimming paths, installed nothing and created nothing.
- **Verified, in `docs/data-sources.md`:** settings precedence from the docs. Install commands from each tool's own README (Superpowers 7.0.2, graphifyy 0.9.120), not from memory.
- **Decisions to review:** a fix command is marked `$ ` in the JSON (notes are not). Trimming off and missing optional tools show as ❌ "not set up", while only Python counts as required. The trim hook is still always registered (it probes Python on every Bash call); registering it only when enabled was not done (not in the sprint's checklist). ROADMAP v0.13 boxes left unticked, as before.

## Previous sprint: v0.12.1 (trim wrapper for failing commands), done

- **Commit:** `d8fb877 fix(trim): run.py wrapper for failing commands (v0.12.1)`. Tests 266/266 (9 new in `tests/test_run.py`).
- **Live check of v0.12 (before the patch):** `claude -p --plugin-dir .` with `trim_output` on, debug log read. Exit 0, 303 lines: `PostToolUse:Bash ... replaced tool output`, so Claude got the marker plus 6 lines (`updatedToolOutput` for Bash is **verified**). Exit 1, same output: `outcome=error`, no `PostToolUse` at all, so Claude got all 303 lines. The hooks docs confirm `PostToolUse` is success-only, and `PostToolUseFailure` can only add `additionalContext`.
- **Fix, as the maintainer specified:** `scripts/run.py -- CMD ...` (no hook) runs the command, trims with the same trimmer, saves the full log and exits with the real code. The `SKILL.md` rule says to run tests and builds through it when `trim_output` is on. The hook is kept for long successful output. Both paths are documented in the CHANGELOG, `docs/data-sources.md`, ROADMAP v0.12, `SKILL.md` and the README.
- **Live acceptance:** the failing 303-line command through `run.py` in `claude -p --plugin-dir .` gave Claude exit code 1 and 7 lines, with the assertion and `FAILED (failures=1)` kept and the 308-line log saved.
- **Local cleanup:** the 5 headless test sessions were removed from `.navitok/history.jsonl` (only `a1f8d2b7` is left). The `calibration.json`, `logs/` and `config.json` they created were deleted.
- **Lesson:** `Path.write_text` on Windows writes CRLF. `.gitattributes` normalises on commit, but the working copy was restored with `git checkout`. Use the Edit tool, or `newline="\n"`.
- **Decisions to review:** `run.py` trims whenever it is called, even when `trim_output` is off, because calling it is an explicit choice; it still uses the config overrides. It shows nothing until the command ends. A single argument runs in the platform shell (cmd.exe on Windows when called from Python).

## Previous sprint: v0.12 (Output trimming hook), done

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
- ~~Not verified live yet~~: verified in v0.12.1 for exit 0. A failing command never reaches the hook (see v0.12.1).
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

## Next sprint: v1.0b (release steps): not started, each step needs approval

See ROADMAP §7 v1.0 "Split". Push to `origin`; test the marketplace install (`/plugin marketplace add RetraysSs/navitok`, `/plugin install navitok@navitok`, `/navitok:setup`) from GitHub; statusline and panel screenshots or a GIF (the maintainer captures them); version `1.0.0` in both manifests, move CHANGELOG `[Unreleased]` to `[1.0.0]`, tag `v1.0.0`, GitHub release notes. Commit per ROADMAP: `release: v1.0.0`. Still open: the v0.2 0-token start snapshot, the manual-reading issue when no statusline is configured, a live curses run on Linux or macOS, and the decision on Graphify's local `CLAUDE.md` section and `.claude/settings.json`.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
