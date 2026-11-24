# Handoff

## Last sprint: v0.4 (Plan generator), done

- **Commit:** `bf41b06 feat(plan): release plan generation (v0.4.0)`.
- **Tests:** 76/76 pass (17 new).
- **Acceptance:** `/navitok:plan` on a synthetic sample project (a recipe app README), once with `-p` and once interactively by the maintainer. It asked for plan and mode, then wrote `config.json`, `plan.json` and `.navitok/ROADMAP.md`. Five releases, the largest at 33.8% upper vs the 90% threshold.

### What v0.4 built

- `commands/plan.md` → `/navitok:plan`. A thin command: it reads `${CLAUDE_PLUGIN_ROOT}/skills/navitok/SKILL.md` and follows its Plan flow with `$ARGUMENTS`.
- `SKILL.md`: plan → mode → tasks (type/size/files) → releases (3–5 tasks, wrapup last) → write `plan.json` without numbers → `plan.py price` → report. **Claude never writes estimates; the script fills `est_pct`.**
- `scripts/plan.py` with `config`, `price` (exit 0 fits / 1 `OVER:` / 2 malformed) and `render`. `plan.json`'s `plan` drives pricing. `config.json` only supplies `threshold_override`, which can only lower the threshold.
- `.navitok/ROADMAP.md` is rendered from `references/roadmap-template.md`. `schedule.json` is not used yet (v0.5).

### Decisions to review

- `commands/` was kept as the roadmap says, although the docs prefer `skills/` for new plugins.
- The release total is a sum across sessions and is labelled that way everywhere: the first `-p` run called it "one session's usage".

### Known issue (v0.2 recorder, not fixed: out of scope)

- When `/navitok:plan` creates `.navitok/` partway through a session, `SessionStart` was skipped (no folder yet), so the first snapshot comes from `Stop`, after the work. The record then shows **0 local tokens**. Seen in the sample project's `history.jsonl`. A fix fits v0.5 or v0.6: take the start snapshot from the transcript's first message instead.

### Lessons (v0.2–v0.4) (keep in mind)

- **Hook stdin is UTF-8.** Python on Windows decodes stdin with the ANSI code page (cp1254 here), so always read `sys.stdin.buffer`. Test with non-ASCII paths: this machine's home is `C:\Users\ÜNSAL`.
- To check whether a hook ran, look at the `system` / `stop_hook_summary` record in the transcript. Silent successful hooks leave no other trace.
- **The usage cache (`~/.claude.json`) is effectively frozen.** Neither `/usage` nor a new session refreshed it. The account-wide % in automatic records is unreliable until the statusline snapshot exists (v0.8). Manual `/usage` stays ground truth for the dogfood ledger.
- CLI output must be UTF-8 (`sys.stdout.reconfigure`), or the Bash tool and tests get garbled text on Windows (v0.4).

## Next sprint: v0.5 (Schedule engine + update tiers, `M`): not started, needs approval

See ROADMAP §7 v0.5 and §4.2, §10.7. Re-verify the `UserPromptSubmit` hook output fields against the hooks docs first (marked *unverified* in `docs/data-sources.md`).

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
