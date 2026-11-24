# Handoff

## Last sprint: v0.1 (Data source spike), done

- **Commits:**
  - `8cb2529 docs(data): record hooks, statusline and costs findings; amend dogfood protocol`
  - `881f3b4 feat(data): usage source spike and adapters (v0.1.0)`
  - `80a80c4 docs: v0.1 handoff`
  - `1869d39 docs(dogfood): v0.1 record`
- **Tests:** 17/17 pass (`python -m unittest discover -s tests -v`). `claude plugin validate .` passes with the same warnings as v0.0.
- **Dogfood record:** v0.1 is in `docs/dogfood/ledger.jsonl` and `REPORT.md`. It was measured in two parts because the 5-hour window reset at 17:50 UTC mid-sprint.

### What v0.1 established (details in `docs/data-sources.md`)

- **Account-wide %:**
  - The best source is the statusline stdin `rate_limits.five_hour` / `seven_day` (`used_percentage`, `resets_at`). It is documented and has decimal precision. It only reaches a configured statusline script, so a snapshot file is needed: v0.8 writes it, `usage_read.read_statusline_snapshot` reads it.
  - The `~/.claude.json` `cachedUsageUtilization` cache exists but is **unstable and stale**. `/usage` does not refresh it, and its refresh trigger is unknown.
  - Manual `/usage` stays ground truth for now.
- **No hook input carries usage %.** Hooks get `transcript_path`, so the local-token signal is available to them.
- **Local tokens:** transcripts must be deduplicated by `message.id` and must include `<session>/subagents/*.jsonl`. Records are timestamped, so tokens can be summed for any time window.

## Next sprint: v0.2 (Ledger), waiting for maintainer approval

Start with the §6.1 protocol, as amended in CLAUDE.md:
1. `/usage` at the start.
2. Ask about claude.ai or other-machine use.
3. Write the estimate.
4. Ask for `/usage` again **only after the last commit**, and record small deltas as ±1%.

Also check the 5-hour `resets_at` at the start. If the window resets mid-sprint, take a reading just before the reset and split the record.

Before using hook fields in v0.2, re-verify the items marked *(unverified)* in `docs/data-sources.md` (hooks section). Use `SessionStart` / `Stop` input and output.

## Notes for the next session

- `python3` is not available on this machine. Use `python` (3.14.8). The code must stay 3.10-compatible.
- **Token windows for the dogfood ledger:**

  ```
  python scripts/usage_read.py tokens <transcript> --since <ISO> --until <ISO>
  ```

  The transcript for this repo is under `~/.claude/projects/<slug>/<session_id>.jsonl`. Never commit transcripts.
- **Ledger schema:** v0.2 may change it. `local_tokens` is now filled from transcripts. Consider adding a `parts` field for split sessions and a per-model token split. Migrate the v0.0/v0.1 records if the schema changes.

## Repository history note

- On 2026-11-24 all local commits after `26303b4` were rewritten to remove AI co-author trailers, at the maintainer's request. Content is unchanged, but the hashes changed.
- The pre-rewrite commits are on the local branch `backup/before-trailer-removal`. The maintainer may delete it.
- **Commit rule:** never add `Co-Authored-By` or any other AI attribution line.
