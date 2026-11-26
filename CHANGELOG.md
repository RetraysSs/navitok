# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.10.0] - 2026-11-26

### Added

- `scripts/integrations/superpowers.py` (ROADMAP v0.10): navitok **works with** Superpowers plans. It reads them only and copies none of Superpowers' code.
  - `detect`: finds Superpowers in Claude Code's plugin registry (undocumented, marked unstable in `docs/data-sources.md`; missing means "not installed") and lists `docs/superpowers/plans/*.md`.
  - `ingest`: parses `### Task N:` sections (the `**Files:**` list, checkbox steps, fenced code skipped) into a draft `.navitok/plan.json`.
    - Type comes from title keywords, size from the step count, and done tasks from checked boxes.
    - Tasks are packed greedily into `v0.N` releases under the threshold, each with a wrapup task. Each task keeps a `source` pointer to its plan file and task number.
    - It then prices the draft and renders `ROADMAP.md`.
    - It refuses to overwrite an existing `plan.json` without `--force`, and it never opens a plan file for writing.
  - `--execution auto|subagent|inline`. On Pro + strict with subagents it prints a recommendation to run inline instead, with both upper estimates.
- `estimate.py`: optional task field `execution` (`inline` ×1.0, `subagent` ×1.5). `plan.py` validates it. The ×1.5 is an unmeasured assumption, documented in `heuristics.md` and kept in sync by a test.
- `SKILL.md` "Works with Superpowers plans" flow, README section, `docs/data-sources.md` entry for the plan format (checked against Superpowers 7.0.2).
- 22 tests: detection (registry present, missing or broken), parsing (header, files with line suffixes, code-fence checkboxes, done status, inferred type/size), release packing under the threshold, a task too big on its own, the multiplier and the recommendation, the CLI (overwrite guard, no plans), a byte-and-mtime check that the plan file is untouched, end-to-end plan → ROADMAP → schedule, and the v0.4 flow without Superpowers.

## [0.9.0] - 2026-11-25

### Added

- `scripts/watch.py`, the terminal panel (ROADMAP v0.9). Zero tokens, standard library only, local files only.
  - **Shows:** releases with status, done/total and placement; session and weekly bars (threshold marked); next reset times; external usage and reserve; calibration confidence; the last sessions' estimate vs. local actual; replan suggestions.
  - **Data:** a fresh statusline snapshot (≤ 10 min) wins over `schedule.json`.
  - **Format:** the session line reads `45.0% used · stop at 96.5% · 51.5% left`, and every percentage and range uses one decimal.
  - **Times** are shown in the machine's local zone with the zone name the OS provides: an abbreviation on POSIX (`CET`, `BST`); the long name on Windows (`GMT Standard Time`), because the stdlib has no tz database there; else `UTC±HH:MM`.
  - **Recent sessions** without a release id are labelled by local date and time, so several sessions on one day stay distinguishable.
  - **Display**, in order of preference:
    1. `curses` where Python ships it.
    2. An **ANSI full-screen redraw** elsewhere. Windows' Python has no `_curses`, and `windows-curses` is third-party, so it is not used. On Windows, virtual-terminal processing is enabled through `ctypes`, so it works in the legacy console too. `q` is read with `msvcrt` (Windows) or `termios`/`select`. `--plain` forces this mode.
    3. `--once`: one plain frame without escape codes.
  - **Sizing:** fits 80×24, truncates cleanly in smaller terminals, follows resizes.
  - **Resilience:** data errors are shown on the panel and appended to `--log`, never fatal. `--duration S` stops after S seconds (soak tests), and `--interval S` sets the refresh (min 1, default 5).
- `SKILL.md`, `README.md`: entry point and alias suggestion.
- Tests for the 80×24 frame, truncation, tiny terminals, live vs. old snapshots, missing and broken data, the threshold bar, the ANSI loop (escapes, cursor restore, plain mode without VT, `q`, duration), error logging, zone names and local time, number format, session labels, the CLI (`--once` UTF-8, live mode with log), and a **regression test for non-ASCII and 8.3 short paths** (`C:\Users\ÜNSAL` vs `C:\Users\NSAL~1`) across the panel, statusline and hooks.

### Changed

- ROADMAP v0.9: the bullets describe the curses + ANSI fallback design.

## [0.8.0] - 2026-11-25

### Added

- `scripts/statusline.py`, the statusline segment (ROADMAP v0.8). Zero tokens, standard library only, local files only.
  - Prints one line from `schedule.json`, `calibration.json` and the live `rate_limits`, e.g. `v0.3 ▓▓▓░░ 62% · fits · week 31% (ext 8%) · conf 40`. The fit uses the live session % with the current release's remaining upper estimate.
  - **Degrades gracefully:** a stale schedule reading is marked `~`. Before a schedule exists it shows "no schedule yet", and before calibration "cold start". Outside navitok projects it prints nothing. Broken input prints nothing. It always exits 0.
  - **Fresh account-wide usage:** saves stdin's `rate_limits` to `.navitok/usage_snapshot.json`, only on a change or once a minute. Hooks and `schedule.py` already prefer this over the stale usage cache. With the statusline configured, the schedule and the fit check use live decimal percentages.
  - **Compose, don't replace:** `--wrap CMD` runs the user's existing statusline with the same stdin, through `sh -c` (Git Bash on Windows), and appends navitok's segment to its last line after ` │ `. The user's line is kept if navitok has nothing to add or fails.
  - `setup` / `remove`: a dry run that shows the exact `statusLine` change to `~/.claude/settings.json`. An existing statusline is wrapped, and `padding` / `refreshInterval` are kept. `--apply` writes the change only after the user approves, keeping `settings.json.navitok-backup`. `remove` restores the user's own command.
- `SKILL.md`: statusline setup flow (show the change, ask, apply only on an explicit yes).
- Tests for the segment, fit boundary, live vs. schedule readings, degradation, the snapshot round trip through `usage_read`, write throttling, wrapping (multi-line, failing command, outside projects), setup (dry run, add, idempotent, wrap and restore, invalid settings untouched), CLI speed and UTF-8, and the generated command under `sh`.

## [0.7.0] - 2026-11-25

### Added

- `scripts/calibrate.py`: learning from `.navitok/history.jsonl` (ROADMAP §10.1). Deterministic, stdlib only.
  - **Error on local usage only.** A session's local % is split across its tasks by estimate midpoint, then normalised to size S, Pro, ≤3 files. This gives a weighted mean and standard deviation per task type. A type with at least 3 samples (after 5 learned sessions) replaces its cold-start range.
  - **Outlier guard:** missing data, debugging spirals (local actual more than 2× the summed upper estimates) and large unexplained external usage are flagged. They get weight ×0.2 and are not counted in `n`.
  - **Weights:** recency (half-life of 10 records). Records with a different model or plan get ×0.3.
  - **Adaptive threshold** `100 − 1.5·max_step − 2·sigma_err`, clamped to 90–98, with 90 while `n < 5`. Confidence `min(100, 5n)·(1 − min(1, sigma_err/10))`. `max_step` is the largest recorded step, else the largest apportioned task actual.
  - Also learns the weekly-%-per-session-% ratio after 5 sessions.
  - `update` writes `.navitok/calibration.json` (script-owned). `report --history PATH` prints the calibration as JSON. `status` is the `/navitok:status` text. `hook` runs at `SessionStart` and is silent.
- `scripts/external.py`: external usage (§10.3), meaning account delta − local delta. Local delta is weighted tokens × a fitted %-per-token rate. Also a per-weekday mean/P80, and a per-week mean/P80 with this week's total and the reserve still to hold. It is "unknown" for the first 5 sessions. The token weights are an assumption, marked unstable in `docs/data-sources.md`.
- `/navitok:status` (`commands/status.md`): session used and left, threshold, calibration and confidence, external usage this week, and the next release.
- The session recorder attaches the plan tasks finished during a session (status diff of `plan.json` between `SessionStart` and `SessionEnd`) to each history record, so calibration has estimate/actual pairs.

### Changed

- `plan.py`:
  - `load_config` attaches `calibration.json` and `write_config` never writes it back.
  - `threshold_for` uses the learned threshold. An override can still only lower it.
  - `price` uses the learned per-type ranges (task note "learned from history").
- `schedule.py`:
  - Weekly packing reserves the learned external usage (`week.external_reserved_pct`; null while unknown).
  - It uses the learned weekly ratio unless `config.json` sets one.
  - The Schedule section says how much is reserved.
- `handoff.py fit`: the buffer uses the learned `max_step`. `config.max_step_pct` still wins.
- `hooks/run.sh start`: recorder, then calibration refresh (silent), then the handoff summary.
- `SKILL.md`: a "Learning and status" section.

## [0.6.0] - 2026-11-25

### Added

- `scripts/handoff.py`, handoff and safe stopping (ROADMAP v0.6). Deterministic, stdlib only, never calls the model.
  - `fit`: the per-task fit check of §10.2, `remaining ≥ task upper estimate + buffer` with `buffer = max(2, max_step)`, read from `schedule.json`. It picks the plan's next task (first `doing`, else first `todo`) or `--task <id>`. Exit 0 `FITS`, 1 `NO-FIT` (propose a checkpoint), 3 `UNKNOWN` (no usage reading). A stale reading is checked but flagged. `max_step_pct` in `config.json` raises the buffer; until v0.7 it is 2%.
  - `write`: renders `.navitok/HANDOFF.md` from `plan.json` and git. It holds a one-line `Resume:` summary, what is done in the current release, the next task (with its position, e.g. "task 3 of 5"), half-edited (uncommitted) files outside `.navitok/`, the last commit, and Claude's `--note` lines. It works outside git repositories too. Template: `skills/navitok/references/handoff-template.md`.
  - `summary` / `hook`: a summary of at most 600 characters for `SessionStart`. It notes when `plan.json` has moved on since the handoff was written, and accepts hand-written handoffs.
- `SessionStart` (`hooks/run.sh start`): after the silent recorder, prints the handoff summary to Claude's context when `.navitok/HANDOFF.md` exists. Silent on `resume`, without a handoff, and on errors. Always exits 0. The hook JSON is read once and passed to both scripts.
- `/navitok:checkpoint` (`commands/checkpoint.md`): stop at a clean point, update task statuses, commit, write the handoff, report the resume line.
- `SKILL.md`: run `handoff.py fit` before every task and act on `FITS` / `NO-FIT` / `UNKNOWN`. Keep task statuses (`doing`, `done`) current. Checkpoint and resume flows.
- Tests for the fit boundary, buffer, unknown and stale readings, task selection, handoff rendering (git, no git, clean tree, non-ASCII paths), summary freshness and cap, hook sources, and `run.sh start` (recorder plus summary).

## [0.5.0] - 2026-11-24

### Added

- `scripts/schedule.py`, the schedule engine (ROADMAP §4.1–4.2). Deterministic, stdlib only, never calls the model.
  - **Tier 0:** `recompute` turns `plan.json`, `config.json` and the best account reading (statusline snapshot, then usage cache) into `.navitok/schedule.json` (§10.7). It covers the current release, fits this session or not, and placement of every pending release into sessions and weeks. A window whose reset time has passed counts as fresh.
  - **Weekly packing:** strict mode moves a release that would overflow the week into the next week. Flex mode keeps it and marks it as extra usage. Weekly cost is 0.15× the session cost at cold start (from the dogfood ledger), overridable with `weekly_per_session` in `config.json`.
  - **Tier 1:** one line for Claude, only when the fit status changes: "no longer fits", or "fits again" after a no-fit. Unchanged or unknown usage prints nothing.
  - **Tier 2:** detects the §10.4 replan triggers. They are a release larger than one session, the last two tasks over their upper estimates by more than 30%, the final release slipping more than a week from its baseline, and `config.json` plan or mode differing from `plan.json`. These are only offered at the next task boundary; the script never edits `plan.json`.
  - `--session-pct` / `--weekly-pct` feed a manual `/usage` reading or simulate usage jumps. `show` prints the schedule.
- `UserPromptSubmit` hook (`hooks/run.sh prompt`): recomputes before every prompt in projects with `.navitok/plan.json`. Plain stdout is the Tier-1 channel (verified against the hooks docs, see `docs/data-sources.md`). Always exits 0.
- `.navitok/ROADMAP.md` gets a Schedule section, re-rendered after every recompute and written only when its text changes. `plan.py render` and `price` keep the last schedule section.
- `SKILL.md`: how to react to Tier-1 and Tier-2 lines (finish the task, then checkpoint; offer replans only at task boundaries), and how to feed a `/usage` reading.
- Tests for packing, the threshold boundary, strict and flex weeks, every replan trigger, notice de-duplication, the hook (UTF-8 stdin, non-ASCII paths, never failing) and the plugin files.

## [0.4.0] - 2026-11-24

### Added

- `/navitok:plan` (`commands/plan.md`) and the skill's plan flow (`skills/navitok/SKILL.md`): ask for plan and mode, break the project into typed and sized tasks, group them into releases that each end in a commit, and let the script price them. Claude never writes cost numbers.
- `scripts/plan.py`:
  - `config` writes `.navitok/config.json` (§10.8 defaults).
  - `price` validates `.navitok/plan.json` (§10.6), fills `est_pct` on every task and release with `estimate.py`, and renders `.navitok/ROADMAP.md`. It exits 1 with an `OVER:` line for each release whose upper estimate is above the threshold, and renders nothing then.
  - `render` re-renders the roadmap only.
  - `threshold_override` can only lower the 90% cold-start threshold.
- `skills/navitok/references/roadmap-template.md` (stdlib `string.Template`).
- Tests for validation, pricing, the threshold boundary, rendering, the CLI and the plugin files.

### Fixed

- `estimate.py` and `plan.py` write UTF-8 to stdout and stderr. On Windows the ANSI code page garbled non-ASCII paths and the en dash.

## [0.3.0] - 2026-11-24

### Added

- `scripts/estimate.py`, the cold-start estimator:
  - Input: a task list (type, size, file count), bare or as `{plan, tasks}`.
  - Output: a range per task, a total range, a 0-100 confidence, and a fit check against the fixed 90% threshold. Readable table by default, `--json` on request, `--plan` to override the file.
  - Unknown type gets the widest range (confidence 10). Unknown size is priced as L. The API plan gets Pro-equivalent units and no fit check.
- `skills/navitok/references/heuristics.md`: type x size cost table seeded from the dogfood ledger (v0.0-v0.2), labelled as one maintainer's data.
- `skills/navitok/references/plans.md`: Pro / Max 5x / Max 20x / API profiles, percentages only, no token claims.
- `examples/tasks.json` and tests for boundaries, unknown types and sizes, plans, the CLI, and doc/script sync.

## [0.2.0] - 2026-11-24

### Added

- `scripts/ledger.py`: `.navitok/history.jsonl` with schema 2 (§10.5 plus `session_id`, `local_tokens_by_model`, `parts`).
  - `append` validates the record and is safe across processes (lock file via `msvcrt`/`fcntl`; it repairs half-written lines).
  - `read_all` skips corrupt or invalid lines. `last_session` returns the latest record.
  - CLI: `validate`, `last`.
- Session recorder hooks (`hooks/hooks.json`, `hooks/run.sh`, `scripts/hook_session.py`):
  - `SessionStart` saves a start snapshot. `Stop` refreshes the latest snapshot. `SessionEnd` appends one record with the account-wide % and the local token delta.
  - Silent, always exit 0, and active only in projects that have a `.navitok/` folder.
  - Sessions without a `SessionEnd` are flushed with `ended_cleanly: false`.
- Tests for the ledger (corrupt lines, 4 concurrent writers) and the hooks (deltas, resume, orphans, stale readings, silence, non-ASCII paths).

### Changed

- `docs/dogfood/ledger.jsonl` migrated to schema 2.
- `docs/data-sources.md`: verbatim hook facts (Stop runs per response, SessionEnd has a 1.5 s budget, Windows uses Git Bash). Hook stdin is UTF-8. The usage cache is not refreshed by `/usage` or by session start.

### Fixed

- Hooks decode stdin as UTF-8. On Windows, Python's default code page garbled non-ASCII project paths, so nothing was recorded.

## [0.1.0] - 2026-11-24

### Added

- `scripts/usage_read.py`, the usage source adapters:
  - `tokens`: sums local token usage from a session transcript, deduplicated by `message.id`, including subagent transcripts, split by model and filterable by time window.
  - `account`: account-wide 5-hour and 7-day %, using the fallback chain statusline snapshot → `~/.claude.json` usage cache (unstable) → stale reading. Every reading carries source, age and precision.
- `docs/data-sources.md`: verified findings on hooks, statusline (`rate_limits`), costs/`/usage`, the usage cache and the transcript format, plus the source decision.
- Tests for the adapters, using synthetic fixtures only.

### Changed

- Dogfood protocol: the final `/usage` is taken after the last commit, and small deltas are recorded as ±1%.
- Docs say "python3 (python on Windows)". `.gitattributes` enforces LF line endings.

## [0.0.1] - 2026-11-24

### Added

- Plugin manifest (`.claude-plugin/plugin.json`) and a single-plugin marketplace (`.claude-plugin/marketplace.json`).
- `navitok` skill stub (`skills/navitok/SKILL.md`), marked as work in progress.
- `docs/data-sources.md` with verified plugin-manifest facts.
- Dogfood ledger (`docs/dogfood/ledger.jsonl`) and report (`docs/dogfood/REPORT.md`), with the first record (v0.0).
- Smoke test for the manifests, skill frontmatter and dogfood ledger format.
- MIT license, stub README, `.gitignore`.
