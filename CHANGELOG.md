# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

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
