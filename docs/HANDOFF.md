# Handoff

## Last sprint: v0.11 (Graphify integration), done

- **Commit:** `440516e feat(integrations): graphify scope estimation (v0.11.0)`.
- **Tests:** 244/244 pass (18 new in `tests/test_graphify.py`). The commit ran only after the test command's own exit code was 0, as v0.10's lesson asked.
- **Acceptance:** synthetic history with 20 unhelped and 10 Graphify-helped sessions gives two separate groups (feature mean 2.0 vs 1.0 per task). A helped plan is priced from the helped group, an unhelped plan from the plain group. A helped group with fewer than 5 sessions falls back to the cold start, not to unhelped history.
- **Graphify check:** the maintainer installed `graphifyy` 0.9.120 (correct package, Apache-2.0, CLI on PATH). `graphify install` (the Claude Code skill) has **not** been run, and navitok does not need it. The output format was checked by running `graphify update` (AST only, no LLM, 0 tokens) on a scratchpad copy of `scripts/`: 290 nodes, 753 edges. Nothing was written into this repo.

### What v0.11 built

- `scripts/integrations/graphify.py`: `detect()` / `present()` (graph exists) → `load_graph()` (node-link JSON; `links` or `edges`) → `index()` (terms, line spans, adjacency) → `scope(task)` (files, lines, paths) → `annotate(plan)` (fills `files` only where no count was set, marks `helpers: ["graphify"]`). The CLI has `detect`, `scope`, `apply` and `map [--apply]`.
- "Build the map" release: code only → `config` S inline (`graphify update .`); otherwise `research` S/M/L by non-code file count (≤20, ≤100), subagent.
- `estimate.helper_group()`; `calibrate.py` writes `helper_groups` (each group needs its own 5 clean sessions); `plan.learned_types(cfg, helpers)`; `plan.py price`, `schedule.py` and `handoff.py` pass `plan.helpers`.
- `hook_session.py` records `helpers: ["graphify"]` when the project has a graph (lazy import, failure-safe).

### Decisions to review

- **Lines are recorded, not priced.** Only the file count feeds `estimate.py` (through the existing files factor). The ROADMAP says "files/lines touched (fed into estimate.py)". A lines factor would be a new unmeasured heuristic, so it was left out. Say if you want one.
- **Files include direct neighbours** (callers and callees of the matched nodes). On real data a title like "Statusline: show weekly reset time" gave 5 files and ~290 lines. That is plausible but broad: the line estimate is inflated when a file name matches, because every node in that file matches. The files factor caps at ×2.0, which limits the damage.
- **`apply` writes `plan.json`**, like Superpowers `ingest` does. It never overwrites a hand-set `files`. Same "Claude writes plan.json" bend as in v0.10.
- **Map release sizes and the subagent multiplier for `/graphify .` are guesses.**
- Only Graphify splits calibration history. Superpowers records (all our dogfood so far) stay in the plain group.
- ROADMAP v0.11 checkboxes were left unticked, as in v0.9 and v0.10.

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

## Next sprint: v0.12 (Output trimming hook, `S`): not started, needs approval

See ROADMAP §7 v0.12. Check the current hook events and output fields in the official hooks docs before writing anything. Still open: the v0.2 0-token start snapshot, the manual-reading issue when no statusline is configured, a live curses run on Linux or macOS, and a first real Graphify-helped dogfood sprint (a graph of this repo can be built for free with `graphify update .`; `graphify-out/` would then need to be gitignored).

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
