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

## Hooks (checked 2026-11-24, Claude Code 2.1.331)

Source: https://code.claude.com/docs/en/hooks. Status: **documented**. The page is ~290k characters and only partly read verbatim. Items marked *(unverified)* came from a summary and **must be re-checked against the page before they are used** (v0.2, v0.5, v0.12).

- Events include `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch` and `SessionEnd`, among others.
- Plugin hooks live in `hooks/hooks.json`. `${CLAUDE_PLUGIN_ROOT}` is substituted in `command`/`args` and exported as an environment variable. `${CLAUDE_PLUGIN_DATA}` is a persistent data directory *(unverified)*.
- `timeout` is in seconds. The default for `command` hooks is 600, lowered to **30 for command hooks on `UserPromptSubmit`**. navitok's Tier-0 hook must finish well under that.
- Common input fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`, `effort` *(unverified)*. Hooks can therefore find the transcript, and `effort` can fill the ledger field.
- `SessionStart` / `UserPromptSubmit` stdout, or `hookSpecificOutput.additionalContext`, is added to Claude's context *(unverified)*. This is the Tier-1 notice channel.
- `Stop` input has `last_assistant_message`, because `transcript_path` may lag behind *(unverified)*.
- `PreToolUse` can rewrite tool arguments via `hookSpecificOutput.updatedInput`. `PostToolUse` may replace output via `updatedToolOutput` *(unverified)*. Either is the mechanism for v0.12 trimming.
- **No hook input carries rate-limit / usage %.** `SessionStart` on resume reportedly carries `context_tokens` *(unverified)*.

## Statusline (checked 2026-11-24)

Source: https://code.claude.com/docs/en/statusline. Status: **documented**.

- Configured by the `statusLine` settings key: `{"type": "command", "command": "...", "padding": 2}`, optional `refreshInterval` (seconds, min 1). It runs locally and costs no API tokens.
- It refreshes after each assistant message, at session start/resume, after `/compact`, on `refreshInterval`, when a rate-limit window reaches `resets_at`, and on a few other triggers. Debounced at 300 ms.
- **stdin JSON includes `rate_limits`:**
  - `rate_limits.five_hour.used_percentage` and `.resets_at` (Unix epoch seconds)
  - `rate_limits.seven_day.used_percentage` and `.resets_at`
  - `rate_limits.spend_limit.{used_percentage, resets_at, used_usd, limit_usd, period}`
  - The percentages are decimals (the example shows `23.5`), so they are **finer than `/usage`'s whole percents**.
  - It appears only for claude.ai Pro/Max/Ultra subscribers (or behind a gateway with a spend limit) and only after the first API response in a session. Each window may be absent.
- Other fields: `session_id`, `transcript_path`, `model.id`, `effort.level`, `cost.total_cost_usd` (client-side estimate at list price), and `context_window.{total_input_tokens, total_output_tokens, current_usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}}`.
- The docs do not say whether a plugin can provide a statusline itself. Configuring one means editing the user's settings, which requires **explicit approval**.

## Costs / `/usage` (checked 2026-11-24)

Source: https://code.claude.com/docs/en/costs. Status: **documented**.

- `/usage` shows the session cost, durations and usage by model, plus plan usage bars on subscription plans.
- The plan breakdown is "computed from local session history on this machine".
- No programmatic way to read the usage % is documented besides the statusline `rate_limits`.
- Local transcripts are cleaned up after `cleanupPeriodDays` (default 30). The history window is therefore limited, so navitok must keep its own ledger.
