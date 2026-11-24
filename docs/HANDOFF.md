# Handoff

## Last sprint: v0.3 (Estimator v1, cold start), done

- **Commit:** `b326561 feat(estimate): cold-start estimator (v0.3.0)`.
- **Tests:** 59/59 pass (23 new).
- **Acceptance:** `python scripts/estimate.py examples/tasks.json` prints a table: per-task range, confidence, notes, total `5.4-20.9`, and the 90% fit check.

### What v0.3 built

- `scripts/estimate.py`: `estimate_task`, `estimate`, `render`, CLI (`--plan`, `--json`). Exit 2 with a one-line error on bad input.
  - Range = base(type, Pro, size S) x size (S 1 / M 2.5 / L 6) x files (first 3 free, +0.1 each, cap 2.0) x plan.
  - Unknown type → widest range, confidence 10. Unknown or missing size → L, confidence at most 20. Known → 30.
  - Totals are plain sums. `fits_one_session` = total high ≤ 90. API: no fit check (`null`).
- `skills/navitok/references/heuristics.md` and `plans.md`. A test parses their tables and fails if they drift from the script's constants.

### Decisions to review

- Plan multipliers (Max 5x = 0.2, Max 20x = 0.05) follow the plans' nominal names. They are a cold-start guess, labelled as such.
- `refactor` has no seed data; its range sits between `test` and `feature`.
- Cold-start confidence is capped at 30, since §10.1 gives 0 with no history.

## Next sprint: v0.4 (Plan generator, `M`): not started, needs approval

See ROADMAP §7 v0.4. It is size M: consider whether it needs a split before starting. It uses `estimate.py` to price tasks.

## Notes

- Use `python`, not `python3`, on this machine. The code must stay 3.10-compatible.
- `.navitok/` in this repo is local and gitignored. The hooks record our own dogfood sessions there when Claude Code runs with `--plugin-dir .`.
- Token windows: `python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>`.

## Repository history note

- On 2026-11-24 all local commits after the initial commit were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
- `CLAUDE.md` was then removed from the whole history, at the maintainer's request. It is **local-only** now: gitignored, kept on the maintainer's machine, and still read by Claude Code from the working tree. The pre-removal history is on the local branch `backup/before-claude-md-removal`.
