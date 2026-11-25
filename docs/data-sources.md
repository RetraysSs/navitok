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

### Commands and skill content (checked 2026-11-24, for v0.4)

Source: https://code.claude.com/docs/en/plugins-reference and https://code.claude.com/docs/en/slash-commands, partly verbatim.

- `commands/` (flat Markdown command files) is still supported. Verbatim: "Prefer `skills/` for new plugins." Custom commands "have been merged into skills", and existing command files keep working.
- `${CLAUDE_PLUGIN_ROOT}` is substituted "Anywhere in the Markdown body" of skill, command and agent content (verbatim). These variables are **not** in the environment of Bash tool commands, so the body must spell the path out.
- `$ARGUMENTS` holds the command arguments *(from a summary, confirmed live)*. Frontmatter `description` and `argument-hint` are supported *(summary)*.
- **Observed live (v0.4 acceptance, Claude Code 2.1.331):** `commands/plan.md` in plugin `navitok` runs as `/navitok:plan`, both with `-p` and interactively. The `${CLAUDE_PLUGIN_ROOT}` path was substituted, and the agent ran `plan.py` through it.

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

### Hooks re-verification for v0.2 (checked 2026-11-24, verbatim sections)

Source: https://code.claude.com/docs/en/hooks, the SessionStart, Stop, SessionEnd, exit-code and plugin sections, read verbatim. This supersedes the *(unverified)* marks above for these items.

- **Common input:** `session_id`, `prompt_id`, `transcript_path`, `cwd`, `scratchpad_dir`, `permission_mode`, `effort` (an object with `level`), `hook_event_name`. There is no `model` in the common fields.
- **`SessionStart`:**
  - Matchers / `source` values: `startup`, `resume`, `clear`, `compact`, `fork`. Input may include `model`, and on resume/fork also `context_tokens`.
  - Plain stdout **is added to Claude's context**. So navitok's SessionStart recorder must print nothing.
- **`Stop`:** "Runs when the main Claude Code agent has finished responding." It runs **after every response**, not once per session. It does not run on user interrupt (API errors fire `StopFailure`). Omitting `decision` lets Claude stop normally.
- **`SessionEnd`:**
  - Runs when the session ends. `reason` is one of `clear`, `resume`, `logout`, `prompt_input_exit`, `other`.
  - It has no decision control, and its output is discarded.
  - **The default budget is 1.5 s, and plugin-provided `timeout`s do not raise it** (user env `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` can). The work done here must therefore be tiny.
- **Exit codes:**
  - 0: success.
  - 2: blocking. For Stop it continues the conversation, so navitok must never return 2 from Stop.
  - Anything else: non-blocking error with a visible notice.
  - Claude never sees stderr from a hook that exits 0.
- **Plugin `hooks/hooks.json` shape:** `{"description": ..., "hooks": {"<Event>": [{"matcher": ..., "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/...", "timeout": N}]}]}}`.
  - `${CLAUDE_PLUGIN_ROOT}` is the plugin's install directory.
  - `${CLAUDE_PLUGIN_DATA}` is "the plugin's persistent data directory". Its on-disk location is not verified.
- **Windows:** shell-form commands run in **Git Bash**, or in PowerShell if Git Bash is missing. Exec form (`command` + `args`) skips the shell and needs a real `.exe`. navitok uses a POSIX `hooks/run.sh` wrapper that picks a working `python3`/`python`.
- **No hook input carries rate-limit / usage %** (confirmed).
- **Observed live (v0.2 acceptance run, Windows, Claude Code 2.1.331):**
  - Hook stdin is **UTF-8**. Python on Windows decodes `sys.stdin` with the ANSI code page (cp1254 on the dev machine), which garbled the non-ASCII `cwd`, so the hook silently found no `.navitok/`. **Hooks must read `sys.stdin.buffer` and decode it as UTF-8.**
  - Successful silent hooks leave no `attachment` in the transcript. Stop hooks do appear in a `system` / `stop_hook_summary` record (`hookInfos[].command`, `durationMs`, `hookErrors`), which is useful for checking that a hook ran.

### Hooks re-verification for v0.5: `UserPromptSubmit` (checked 2026-11-24)

Source: https://code.claude.com/docs/en/hooks. The page is too long for one fetch. Items marked *verbatim* were quoted from raw page text; the rest came from a model summary of the UserPromptSubmit section and are marked *(summary)*.

- *Verbatim:* "**`UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and `PostModelSwitch`**: Claude Code adds plain-text stdout as context that Claude can see and act on. It doesn't add stdout it failed to parse." **This is navitok's Tier-1 channel: one plain line on exit 0.**
- *Verbatim:* "Claude never sees stderr from a hook that exits 0." Exit 2 on `UserPromptSubmit` rejects the prompt, so navitok never exits 2 there.
- *Verbatim:* `UserPromptSubmit` has "no matcher support" and "always fires on every occurrence".
- *Verbatim:* the default `command` timeout is lowered to 30 s on `UserPromptSubmit`. navitok sets 10 s.
- *(summary)* Input: the common fields plus `prompt` (and `session_title` when set). navitok reads only `cwd`.
- *(summary)* Neither plain stdout nor `additionalContext` makes a visible transcript entry; each is injected as a system reminder that starts with the hook's name.
- *(summary)* JSON alternative: `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}`. `decision: "block"` rejects the prompt. Not used.
- *(summary)* Hook strings and plain stdout are capped at 10,000 characters; longer output is moved to a file with a 2,000-character preview. navitok's line is far below that.
- *(summary)* A `UserPromptSubmit` hook that times out is cancelled and its output discarded; the prompt still goes through.
- **Observed locally (v0.5 acceptance, Git Bash, Windows):** `sh hooks/run.sh prompt` with UTF-8 stdin and a non-ASCII `cwd` printed nothing for unchanged usage and exactly one line when the fit status flipped. A live in-session check that the line reaches Claude's context is still pending (needs `/reload-plugins` in a project with `.navitok/plan.json`).

### Hooks re-verification for v0.6: `SessionStart` context output (checked 2026-11-25)

Source: https://code.claude.com/docs/en/hooks, SessionStart section. Read through a page summary, not verbatim; it agrees with the verbatim v0.5 quote above ("`SessionStart` ... adds plain-text stdout as context").

- *(summary)* "A hook that only adds context can print it without building JSON, because Claude Code adds a SessionStart hook's plain-text stdout to Claude's context." The JSON alternative is `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "...", "sessionTitle": "..."}}`; `additionalContext` is added "at the start of the conversation, before the first prompt". navitok uses plain stdout.
- *(summary)* Sources: `startup`, `resume` (`--resume`, `--continue`, `/resume`), `clear` (`/clear`), `compact` (auto or manual), `fork`. Hooks run again on resume "so they can refresh their context". The page does not say whether context is injected after `compact`. navitok prints the summary for every source except `resume`, where the conversation is intact.
- *(summary)* Plain stdout and `additionalContext` are capped at 10,000 characters (longer text goes to a file with a 2,000-character preview). navitok's summary is capped at 600.
- **Observed locally (v0.6 acceptance, Git Bash, Windows):** in a synthetic project with a non-ASCII path, `claude -p --plugin-dir .` with all file tools disabled answered "v0.1 (Core), task 3 of 4, Storage to JSON, in progress, `storage.py` uncommitted" from the injected line alone. This also confirms that plain SessionStart stdout reaches context in `-p` mode. The recorder in the same hook still wrote its record.

## Local usage % from tokens (v0.7, 2026-11-25) — **UNSTABLE, navitok's own assumption**

External usage (§10.3) needs the local share of the account-wide %. No documented source converts tokens to plan-limit %. `scripts/external.py` therefore:

- **Weights token types** before converting: input 1, output 5, cache read 0.1, cache write 1.25. These follow relative API prices. How plan limits really count tokens is **not documented**, so the weights are an assumption. Change them only in `external.TOKEN_WEIGHTS`.
- **Fits % per weighted token** as the 25th percentile of `account_delta / weighted_tokens` over at least 5 sessions. External usage only raises that ratio, so the low end is the cleanest estimate of Claude Code alone. A recorded `external_pct` is subtracted first.
- **On the dogfood ledger** (7 records, 6 usable) it fits ≈8.0e-6 % per weighted token. Local % then explains the account delta of every sprint to within about 1.4%, which is within `/usage`'s ±1 resolution.
- **Weekly profile:** uses ISO weeks (UTC), not the account's own weekly window. The weekly % rise *between* consecutive records in the same week counts as external. In the dogfood ledger that gap also holds unrecorded local chores, so the profile overstates external usage there.
- **Until 5 sessions** have token data, external usage is `unknown` (null) and nothing is reserved.

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

### Statusline re-verification for v0.8 (checked 2026-11-25)

Sources: https://code.claude.com/docs/en/statusline and https://code.claude.com/docs/en/plugins-reference, read through a fetch subagent. Items marked *(summary)* were not verbatim.

- Stdin has `cwd`, `workspace.current_dir` and `workspace.project_dir`. *Verbatim:* `cwd` and `workspace.current_dir` "contain the same value; `workspace.current_dir` is preferred". `project_dir` "may differ from `cwd` if the working directory changes during a session". navitok looks for `.navitok/` in `project_dir`, then `current_dir`, then `cwd`.
- `rate_limits.five_hour` / `.seven_day` = `{"used_percentage": 23.5, "resets_at": 1738425600}`. *Verbatim:* `resets_at` is "Unix epoch seconds".
- Settings: `{"type": "command", "command": ..., "padding": N}`, plus `refreshInterval` (min 1) and `hideVimModeIndicator`. Multi-line output and ANSI colours are supported.
- *(summary)* Output shows "only after the script exits with code 0". A non-zero exit or no output blanks the line, and a slow script blocks updates. No timeout value is given. navitok always exits 0 and runs a wrapped command with a 3 s timeout.
- **A plugin cannot provide a statusline itself:** plugins-reference never mentions `statusLine`. Setup therefore edits the user's `~/.claude/settings.json`, only with explicit approval (`statusline.py setup` is a dry run; `--apply` writes and keeps a backup).
- **Observed live (2026-11-25, Pro, Windows, after the maintainer approved `setup --apply`):** within seconds the statusline wrote `.navitok/usage_snapshot.json` with `five_hour.used_percentage: 20`, `seven_day.used_percentage: 19` and epoch `resets_at`. That matches `/usage` (20% / 19%) exactly. **The live values were whole numbers**, not decimals like the docs example (`23.5`). So decimal precision is not guaranteed, and `usage_read` labels the precision `decimal` only nominally.
- **Observed locally (v0.8 acceptance, Git Bash, Windows, synthetic stdin):** the generated command ran through `sh -c` in 123–148 ms with a non-ASCII path. The snapshot it wrote was picked up by the `UserPromptSubmit` hook as `source: statusline`, `stale: false`. Live observation: see the next point.

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
  - **Starting a new Claude Code session does not refresh it either.** In the v0.2 acceptance run, a fresh `claude --plugin-dir .` session at 18:21 UTC still read `fetchedAtMs` = 17:25 UTC (56 minutes old).
  - The refresh trigger is unknown. Treat the cache as **unreliable for deltas**. Until the statusline snapshot (A) exists (v0.8), the account-wide % in automatic records is usually stale. Records flag this in `notes`, and manual `/usage` stays ground truth.
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
