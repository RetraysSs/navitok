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

## Account-wide usage % sources (evaluated 2026-11-24)

### (A) Statusline stdin `rate_limits`

- **Reliability:** high. Documented, and the numbers come straight from Claude Code.
- **Freshness:** high. The statusline refreshes after every assistant message and on `refreshInterval`.
- **Precision:** decimal.
- **Stability:** documented, so stable.
- **Caveats:**
  - It only reaches a script that the user has configured as `statusLine`, which needs approval. No statusline was configured on the dev machine.
  - It is absent before the first API response and on API-key plans.
  - Hooks cannot read it directly. The statusline script must persist a snapshot to a local file (e.g. `.navitok/usage_snapshot.json`) for hooks and scripts to read. This is planned for v0.8; v0.1 implements the reader side.
- **Not yet observed live:** the field shape is taken from the docs only.

### (B) `~/.claude.json` → `cachedUsageUtilization` — **UNSTABLE, undocumented**

- **Observed shape:** `{fetchedAtMs, accountUuid, utilization: {five_hour: {utilization, resets_at, ...}, seven_day: {utilization, resets_at, ...}, ...}}`.
  - `utilization` is an **integer percent**.
  - `resets_at` is an ISO-8601 string with an offset. This differs from the statusline, which uses epoch seconds.
  - There are many other keys with codenames. Ignore them.
- **Reliability:** medium. The values matched the maintainer's `/usage` reading at the time of the fetch.
- **Freshness:** low.
  - When inspected, the cache was **18 minutes old** and showed 27% while `/usage` showed 30%. Claude Code did not refresh it during normal work in this session.
  - **`/usage` does not refresh it.** The maintainer ran `/usage` at ~17:41, ~17:45 and ~17:50 UTC, and `fetchedAtMs` stayed at 17:25 UTC. Over that time the cache drifted to 26 minutes old and 4% behind.
  - The refresh trigger is unknown. It may happen at Claude Code startup, but that is unverified. Treat the cache as a startup-time snapshot at best.
- **Stability:** low. The key is undocumented and can change or disappear in any release.
- **Rules:**
  - Read it only through the adapter, and always report `fetchedAtMs` as the reading's age.
  - Never print or store `accountUuid` or the rest of the file. It holds personal account data.

### (C) Manual `/usage`

- **Reliability:** high. It is ground truth.
- **Freshness:** whenever the user runs it.
- **Precision:** whole percents (±1).
- **Stability:** stable. Needs a human in the loop.

### Decision (v0.1)

Primary + fallback order for the account-wide %:

1. **(A) statusline snapshot**, if one exists and is younger than 10 minutes.
2. **(B) usage cache**, only if `fetchedAtMs` is younger than 10 minutes.
3. **(A) or (B), older than that:** returned flagged `stale`, together with the reading's age.
4. **(C) manual**, which remains ground truth for the dogfood ledger until (A) has been observed live (v0.8).

Every reading carries `source`, `age_s` and `precision` (`decimal` or `integer`), so the ledger can tell how much to trust it.

## Local transcripts (inspected 2026-11-24, Claude Code 2.1.331) — **UNSTABLE, undocumented format**

Source: `~/.claude/projects/<project-slug>/<session_id>.jsonl`. Hooks and the statusline receive the path as `transcript_path`.

Only field names and token counts were inspected. Transcripts hold prompt text, code and account IDs. **Never commit them, and never copy them into fixtures.**

- **Format:** one JSON object per line, with many record types (`user`, `assistant`, `system`, `attachment`, `api-request`, ...). Only `type == "assistant"` records carry usage.
- **Fields on an assistant record:**
  - `timestamp`, `sessionId`, `isSidechain`, `effort`, `requestId`
  - `message.id` and `message.model`
  - `message.usage`: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, plus a nested `cache_creation`, `server_tool_use`, `service_tier`, ...
- **Duplicates:** one API response is written as **several assistant records** (one per content block) that share `message.id` and carry **identical** `usage`. In this session, 71 records held 37 unique ids. **Totals must deduplicate by `message.id`**, or they are inflated ~2×.
- **Subagents:** subagent transcripts live in `<session_id>/subagents/agent-<id>.jsonl` (with a `.meta.json`), not in the main file. A session total must include them.
  - They can run a **different model**. In this session the web-fetch subagents ran on a lighter model than the main session.
  - Per-model totals are therefore needed (v1.2).
- **Finer-grained cost:** every assistant record has a `timestamp`, so tokens can be summed for any time window, e.g. between two `/usage` readings or per task. This is the finer-grained local signal for the dogfood ledger.
  - It is **local only**, so it excludes claude.ai and other machines.
  - Converting tokens to session % needs calibration (ROADMAP §10.3).
- Old transcripts are deleted after `cleanupPeriodDays` (default 30).
