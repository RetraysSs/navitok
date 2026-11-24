# Data sources and verified Claude Code facts

Every Claude Code field navitok relies on is recorded here with its source and the date it was checked.
Undocumented sources are marked **unstable** and may only be used behind an adapter with a fallback.

The usage-source evaluation is done in sprint v0.1.

## Plugin manifest (checked 2026-11-24)

Source: https://code.claude.com/docs/en/plugins-reference, https://code.claude.com/docs/en/plugin-marketplaces. Status: **documented**.

- `.claude-plugin/plugin.json` is optional. Only `name` is required: kebab-case, and must not start with `claude-` or `anthropic-`.
- Optional fields used: `version`, `description`, `author` (`{name, email?, url?}`), `license` (SPDX), `keywords`. Unknown top-level keys are stripped and trigger a validator warning.
- These are discovered automatically at the plugin root: `skills/<name>/SKILL.md`, `commands/*.md`, `agents/*.md`, `hooks/hooks.json` (top-level `"hooks"` key).
- Skills are namespaced as `/<plugin>:<skill-dir>`, so `skills/navitok/` becomes `/navitok:navitok`.
- `.claude-plugin/marketplace.json` requires `name`, `owner` (`{name}`) and `plugins[]`. Each plugin entry requires `name` and `source`. `"source": "./"` points to the repo root.
- Validation: `claude plugin validate <path>` (add `--strict` to turn warnings into failures).
