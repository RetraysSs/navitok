# Handoff

## Last sprint: v0.0 (Skeleton + dogfood ledger), done

- Commit: `de801c3 chore: plugin skeleton and dogfood ledger (v0.0.1)`
- Tests: 4/4 pass (`python -m unittest discover -s tests -v`)
- `claude plugin validate .` passes with warnings:
  - no icon (out of scope),
  - no marketplace install line in the README (planned for v1.0, §2.6),
  - `CLAUDE.md` at the root is not loaded as plugin context (expected: it holds the dev rules).
- Dogfood record v0.0 is in `docs/dogfood/ledger.jsonl` and `REPORT.md`. Estimate 8–17%, actual ~1%.

## Next sprint: v0.1 (Data source spike), waiting for maintainer approval

Start with the §6.1 protocol: `/usage` session % and weekly %, claude.ai or other-machine use, then the estimate.

## Notes for the next session

- **Python:** on this Windows machine `python3` is the Microsoft Store alias and does not work. Use `python` (3.14.8).
- **Claude Code** 2.1.331. Plugin manifest facts are already verified in `docs/data-sources.md`. Don't re-fetch the plugins reference unless you need new fields.
- **Line endings:** git warns LF→CRLF (`core.autocrlf` is on). Consider a `.gitattributes` (`* text=auto eol=lf`) so `.jsonl` and `.py` files stay LF. This needs maintainer approval because it is outside v0.0's scope.
- **Estimation:** v0.0 was overestimated about 10×. Scaffolding with no exploration costs ~1–2%. The doc fetches in v0.1 will be the main cost driver. Fetch through a subagent and ask for concise facts only.
- `/usage` reports whole percents, so small sprints have ±1% measurement noise.
