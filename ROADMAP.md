# navitok — Roadmap

> **navitok** — navigation for your tokens.
>
> navitok is a Claude Code plugin that turns a project into **session-sized releases**. It plans work to fit your plan's **5-hour session** and **weekly** limits, keeps the schedule up to date as your real usage changes (including usage outside Claude Code, such as claude.ai in the browser), ends every session at a clean commit with a handoff note, and **calibrates its own estimates** from your history, so your prompt never gets cut off halfway.

---

## Contents

1. [Principles](#1-principles)
2. [Setup (development environment)](#2-setup-development-environment)
3. [Target repository layout](#3-target-repository-layout)
4. [Core architecture](#4-core-architecture)
5. [How sprints work](#5-how-sprints-work)
6. [Dogfooding: navitok learns from building navitok](#6-dogfooding-navitok-learns-from-building-navitok)
7. [Sprints (v0.0 → v1.0)](#7-sprints)
8. [After v1.0](#8-after-v10)
9. [Driving the build with Claude Code](#9-driving-the-build-with-claude-code)
10. [Appendix: formulas and schemas](#10-appendix-formulas-and-schemas)

---

## 1. Principles

- **Never being cut off matters more than using the whole limit.** Start conservative (stop at 90% of a session) and climb toward a 98% ceiling only as evidence accumulates.
- **Estimates are ranges.** Always `12–20%` plus a confidence score, never a single number.
- **Personal calibration wins.** Built-in heuristics exist only for the cold start. After that, the user's own history drives every estimate.
- **Scripts compute, the model decides.** Anything that can be calculated (schedule, fit, dashboards) is done by deterministic scripts at zero token cost. Claude is involved only when judgement is needed (§4).
- **The account is the truth.** Usage outside Claude Code (claude.ai web, other machines) is real and shared. navitok measures it and does not mistake it for estimation error.
- **Works alone, better together.** Superpowers and Graphify improve navitok when present. navitok works fully without them.
- **Detect and recommend, never vendor.** No third-party code is copied into this repo. Nothing is installed or configured without the user's explicit approval.
- **Zero dependencies.** Scripts use only the Python 3.10+ standard library.
- **We use navitok's own approach while building it.** Every sprint in this roadmap is sized to fit a single 5-hour session, and every sprint's real cost is recorded (§6).

---

## 2. Setup (development environment)

### 2.1 Requirements

| Tool | Why | Check |
|---|---|---|
| Claude Code (latest) | Development and plugin testing | `claude --version` |
| Git | Version control | `git --version` |
| Python 3.10+ | Scripts and tests | `python3 --version` (`python` on Windows) |
| GitHub CLI (optional) | Creating the repo, releases | `gh --version` |

### 2.2 Create the repository

```bash
mkdir navitok && cd navitok
git init
# Put ROADMAP.md in this folder
git add ROADMAP.md
git commit -m "docs: initial roadmap"

# Publish (now or at v1.0):
gh repo create navitok --public --source=. --push
```

### 2.3 Install Superpowers (recommended; used during development and an integration target)

Inside Claude Code:

```text
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

Restart Claude Code or run `/reload-plugins`, then confirm via `/plugin`.

> Install commands change over time. Source of truth: https://github.com/obra/superpowers (README → Claude Code).

### 2.4 Install Graphify (optional; needed from sprint v0.11)

```bash
pip install graphifyy     # double "y" on PyPI; other graphify* packages are not affiliated
graphify install          # registers the Claude Code skill
```

Use inside Claude Code: `/graphify .`. Source of truth: https://github.com/Graphify-Labs/graphify

> Building the graph costs tokens (non-code files go through LLM extraction). navitok accounts for this as its own roadmap step (v0.11).

### 2.5 Local plugin test loop

From v0.0 onward, load the plugin straight from the working tree:

```bash
claude --plugin-dir .
```

After changes, run `/reload-plugins` in the open session. Tests:

```bash
python3 -m unittest discover -s tests -v   # use python on Windows
```

### 2.6 End-user install (goes into the README at v1.0)

```text
/plugin marketplace add <your-github-user>/navitok
/plugin install navitok@navitok
/navitok:setup
```

> Plugin commands are namespaced as `/<plugin>:<command>`. Sprint v0.1 verifies this against the current docs.

---

## 3. Target repository layout

```
navitok/
├── .claude-plugin/
│   ├── plugin.json              # plugin manifest
│   └── marketplace.json         # makes the repo a one-plugin marketplace
├── skills/
│   └── navitok/
│       ├── SKILL.md             # core flow: plan, check, hand off
│       └── references/
│           ├── plans.md         # plan profiles (Pro, Max 5x, Max 20x, API)
│           ├── heuristics.md    # cold-start cost table (seeded by §6 data)
│           └── roadmap-template.md
├── commands/                    # /navitok:plan, :status, :checkpoint, :setup
├── hooks/
│   └── hooks.json               # SessionStart / UserPromptSubmit / Stop / PreToolUse
├── scripts/                     # Python stdlib only
│   ├── usage_read.py            # usage data source adapters
│   ├── ledger.py                # .navitok/history.jsonl read/write
│   ├── estimate.py              # estimator
│   ├── schedule.py              # plan → schedule, fit checks, replan triggers
│   ├── external.py              # usage outside Claude Code (web, other machines)
│   ├── calibrate.py             # learning and threshold
│   ├── handoff.py               # HANDOFF.md generation
│   ├── statusline.py            # one-line status for Claude Code
│   ├── watch.py                 # live terminal panel (curses)
│   ├── doctor.py                # /navitok:setup checks
│   └── integrations/
│       ├── superpowers.py
│       └── graphify.py
├── tests/
├── docs/
│   ├── data-sources.md
│   ├── HANDOFF.md               # development handoff between sprints
│   └── dogfood/
│       ├── ledger.jsonl         # real cost of each sprint (§6)
│       └── REPORT.md            # estimate vs actual, per sprint
├── examples/
├── README.md
├── LICENSE                      # MIT
└── CHANGELOG.md
```

Files navitok creates inside a **user's** project (suggest gitignoring all but `ROADMAP.md` and `HANDOFF.md`):

```
<user-project>/.navitok/
├── config.json      # plan, mode, preferences
├── plan.json        # releases and tasks (written by Claude, changes rarely)
├── schedule.json    # which release lands in which session/week (written by scripts, changes often)
├── history.jsonl    # per-session/per-task records (learning data)
├── ROADMAP.md       # human-readable view of plan + schedule
├── HANDOFF.md       # "where we left off"
└── logs/            # full outputs saved by the trimming hook
```

---

## 4. Core architecture

### 4.1 Plan vs schedule

The roadmap has two halves with very different update costs:

| | **Plan** (`plan.json`) | **Schedule** (`schedule.json`) |
|---|---|---|
| Contains | Releases, tasks, cost ranges, dependencies | Which release lands in which session and week, whether today's release still fits |
| Written by | Claude (the skill) | `schedule.py` (deterministic) |
| Changes | Rarely, when scope or estimates change | Constantly, as usage moves |
| Cost of an update | Real tokens | **0 tokens** |

`ROADMAP.md` is rendered from both files by a script, so it is always current without Claude rewriting it.

**Scripts and `plan.json`:** a script may change `plan.json` only through an explicit command the user runs (`superpowers.py ingest`, `graphify.py apply`, `graphify.py map --apply`). Hooks never write `plan.json`.

`files_predicted` / `lines_predicted` (§10.5) hold the scope Graphify predicted for a task, next to the actual `files_touched` / `lines_changed`, so calibration can later learn a scope correction.

### 4.2 Three update tiers

| Tier | What happens | When | Cost |
|---|---|---|---|
| **0 · Recompute** | `schedule.py` recomputes the schedule from the latest usage | Before every prompt (hook), on every dashboard refresh | 0 tokens |
| **1 · Notify** | One line is added to Claude's context, e.g. *"navitok: v0.4 no longer fits today (web usage +9%). Finish the current task, then checkpoint."* | Only when the fit status **changes** | ~20–50 tokens |
| **2 · Replan** | Claude revises `plan.json` | Only at task boundaries, when a replan trigger fires (§10.4) or the user asks | Real cost, but rare |

### 4.3 Usage outside Claude Code

claude.ai and Claude Code share one usage pool, but local transcripts only see Claude Code on this machine. navitok compares two signals:

- **Account-wide %** (Claude Code's usage cache or `/usage`): includes everything.
- **Local %** (estimated from local transcripts): only this machine's Claude Code.

The gap is **external usage** (§10.3). navitok:
- keeps it **out of** estimation error, so calibration is not polluted,
- learns the user's typical external usage per day and week,
- reserves that amount in the weekly schedule.

### 4.4 Zero-token dashboards

The statusline and the terminal panel are plain scripts that read local files. They never call Claude. Claude Code's statusline runs locally and does not consume API tokens.

---

## 5. How sprints work

Rules for every sprint:

1. **One sprint = one session.** Each sprint is sized to use at most ~70% of a single 5-hour session. If it looks like it won't fit, split it. Never widen the scope.
2. **3–5 tasks per sprint.** Each task does one thing.
3. **Definition of done:** tests pass → `CHANGELOG.md` updated → dogfood record written (§6) → commit → `docs/HANDOFF.md` updated.
4. **Stop rule:** at ~85% session usage, start no new task. Commit the current task at a clean point and write the handoff.
5. **Approval gate:** never start the next sprint without the maintainer's go-ahead.
6. **Verify, don't guess:** Claude Code hook, statusline and plugin fields change over time. Check the official docs (see v0.1).

Size labels: **S** ≈ 20–35% of a session, **M** ≈ 35–60% of a session.

---

## 6. Dogfooding: navitok learns from building navitok

navitok is built in sprints, and those sprints are exactly the kind of data navitok needs. From the very first sprint, every session's real cost is recorded. This gives us:

- **Seed data** for the cold-start heuristics (`references/heuristics.md`), taken from real work rather than guesses.
- **A test fixture** for the calibration engine (v0.7), with real estimate-vs-actual pairs.
- **A public track record** for the README: "navitok was built in N sessions; its estimates improved from ±X% to ±Y%."

### 6.1 Measurement protocol (manual until the tooling exists)

At the **start** of every sprint, Claude Code:
1. Asks the maintainer to run `/usage` and report the current **session %** and **weekly %**.
2. Asks whether the maintainer has been using claude.ai or another machine since the last sprint (a rough note is enough).
3. Writes its own **estimate** for the sprint (per task, as a range), *before* starting work.

At the **end** of every sprint (or when the stop rule triggers), Claude Code:
1. Asks for `/usage` again, **only after the last commit** (including the handoff commit), so the wrap-up cost is included. Only the small dogfood-record commit comes after this reading.
2. Appends one record to `docs/dogfood/ledger.jsonl` (schema §10.5, with `"source": "manual"`).
3. Adds a row to `docs/dogfood/REPORT.md`: sprint, estimate, actual, error, notes (e.g. "big test output", "re-read many files", "used claude.ai in parallel").

`/usage` shows whole percents, so a small delta has a measurement error of **±1%**. Say so in the record's notes and in the REPORT row. Finer-grained numbers (statusline `rate_limits`, transcripts) replace this from v0.1 on, where available.

If a sprint spans more than one session, record each session separately.

### 6.2 Automation takes over

- **From v0.1:** token counts are also pulled from the session transcript.
- **From v0.2:** hooks record session start/end automatically. The manual `/usage` step remains as ground truth until v0.1 proves an automatic source for the account-wide %.
- **At v0.3:** `heuristics.md` is seeded from the dogfood ledger, clearly labelled as one maintainer's data.
- **At v0.7:** the calibration engine and external-usage detection are tested against the real dogfood ledger, not only synthetic data.

> Caveat for the README: dogfood data comes from one person, one plan and one kind of project. It improves the cold start; it does not replace per-user calibration.

---

## 7. Sprints

| Sprint | Topic | Size |
|---|---|---|
| v0.0 | Skeleton + dogfood ledger | S |
| v0.1 | Data source spike | S |
| v0.2 | Ledger | S |
| v0.3 | Estimator v1 (cold start) | S |
| v0.4 | Plan generator | M |
| v0.5 | Schedule engine + update tiers | M |
| v0.6 | Handoff and safe stopping | S |
| v0.7 | Learning, external usage, adaptive threshold | M |
| v0.8 | Statusline | S |
| v0.9 | Terminal panel | S |
| v0.10 | Superpowers integration | S |
| v0.11 | Graphify integration | S |
| v0.12 | Output trimming hook | S |
| v0.13 | `/navitok:setup` (doctor) | S |
| v1.0 | Release | M |

> Model and agent optimization is deliberately **not** in v1.0. It is its own release, v1.3 (§8). The ledger records the model and effort of every session from v0.2 onward, so by the time v1.3 starts there is real per-model data to learn from.

---

### v0.0 — Skeleton `S`

**Goal:** an empty but loadable plugin, plus the dogfood ledger.

- [X] `.claude-plugin/plugin.json` (name `navitok`, version `0.0.1`, description, author, license)
- [X] `.claude-plugin/marketplace.json` (single plugin at `./`)
- [X] `skills/navitok/SKILL.md` with frontmatter and a "work in progress" body
- [X] `LICENSE` (MIT), stub `README.md`, `CHANGELOG.md`, `.gitignore`, `tests/` with one smoke test
- [X] `docs/dogfood/ledger.jsonl` (empty) and `docs/dogfood/REPORT.md` (table header); record this sprint (§6.1)

**Accept:** `claude --plugin-dir .` lists the skill; `python3 -m unittest` (`python` on Windows) passes; the first dogfood record exists.
**Commit:** `chore: plugin skeleton and dogfood ledger (v0.0.1)`

---

### v0.1 — Data source spike `S`

**Goal:** pin down where usage % and token counts can be read. Verification only, no assumptions.

- [X] Read the official docs and record findings in `docs/data-sources.md`:
  - Hooks: https://code.claude.com/docs/en/hooks (available events; whether `UserPromptSubmit` and `SessionStart` output is added to context; whether `PreToolUse` supports input rewriting)
  - Statusline: https://code.claude.com/docs/en/statusline (stdin JSON fields; whether 5-hour/weekly usage % is included; how a plugin or user configures it)
  - Plugins reference: https://code.claude.com/docs/en/plugins-reference (manifest fields, command namespacing)
  - Costs/usage: https://code.claude.com/docs/en/costs
- [X] Evaluate candidate sources for the **account-wide %**:
  - (A) statusline stdin JSON, if it carries usage %
  - (B) Claude Code's local usage cache in `~/.claude.json` (reported by other tools as `cachedUsageUtilization`). **Undocumented**: verify that it exists, how fresh it is, and treat it as unstable
  - (C) user-reported `/usage` %
- [X] Inspect the transcript format in `~/.claude/projects/**/*.jsonl` (per-message `usage`: input, output, cache read/write) as the source of **local** usage
- [X] `scripts/usage_read.py`: first adapters, (1) total tokens for a session transcript and (2) the account-wide % from the best available source, with a fallback chain
- [X] Tests with synthetic or anonymised fixtures

**Accept:** `docs/data-sources.md` rates every source for reliability, freshness and stability, and records the chosen primary + fallback order as a written decision.
**Commit:** `feat(data): usage source spike and adapters (v0.1.0)`

---

### v0.2 — Ledger `S`

**Goal:** record the raw material for learning.

- [X] Implement the `history.jsonl` schema (§10.5)
- [X] `scripts/ledger.py`: `append`, `read_all`, `last_session`, schema validation
- [X] `hooks/hooks.json`: `SessionStart` and `Stop` snapshots (account-wide % and local tokens)
- [X] Tests: tolerate corrupt lines; keep lines intact under concurrent writes
- [X] Migrate `docs/dogfood/ledger.jsonl` to the final schema if it changed

**Accept:** opening and closing a real Claude Code session appends a record with both signals.
**Commit:** `feat(ledger): session history recording (v0.2.0)`

---

### v0.3 — Estimator v1 (cold start) `S`

**Goal:** safe estimates with little or no history.

- [X] `references/heuristics.md`: task type × size → cost range (as % of a session, with per-plan multipliers), **seeded from the dogfood ledger**
- [X] `references/plans.md`: Pro / Max 5x / Max 20x / API profiles, percentage-based. Anthropic does not publish fixed token limits, so make **no absolute token claims**
- [X] `scripts/estimate.py`: input = task list (type, size, file count); output = per-task range, total, confidence
- [X] Fixed threshold: **90%**
- [X] Tests: boundary values; unknown task type → widest range

**Accept:** `python3 scripts/estimate.py examples/tasks.json` (`python` on Windows) prints a readable table.
**Commit:** `feat(estimate): cold-start estimator (v0.3.0)`

---

### v0.4 — Plan generator `M`

**Goal:** navitok's core promise. Turn a project into priced releases.

- [X] `SKILL.md` flow:
  1. Ask for the plan (Pro / Max 5x / Max 20x / API)
  2. Ask for the mode: **strict** (never pay extra) or **flex** (continue on extra usage past the limit)
  3. Break the project into tasks and price them with `estimate.py`
  4. Group tasks into releases (v0.1, v0.2…) that each work on their own and end in a commit, with each release sized to fit one session under the threshold
- [X] Write `.navitok/plan.json` (§10.6) and `.navitok/config.json`
- [X] `references/roadmap-template.md` + a renderer that turns `plan.json` into `ROADMAP.md`
- [X] `commands/plan.md` → `/navitok:plan`

**Accept:** given a sample project description, `/navitok:plan` writes `plan.json` and `ROADMAP.md`; no release's upper estimate exceeds the threshold.
**Commit:** `feat(plan): release plan generation (v0.4.0)`

---

### v0.5 — Schedule engine + update tiers `M`

**Goal:** a schedule that is always current and costs nothing to keep current (§4.1–4.2).

- [X] `scripts/schedule.py`: plan + current usage + reset times → `schedule.json` (release → session/week, "fits today?", weekly packing; strict mode moves overflow to the next week, flex mode marks it as extra usage)
- [X] Tier 0: `UserPromptSubmit` hook recomputes the schedule before every prompt (no output unless something changed)
- [X] Tier 1: emit **one line** to context only when the fit status changes; never repeat an unchanged message
- [X] Tier 2: replan triggers (§10.4) are detected and offered at the next task boundary; Claude never replans mid-task
- [X] `ROADMAP.md` re-rendered by script after every recompute

**Accept:** simulated usage jumps (e.g. +15% from "outside") flip the fit status, produce exactly one Tier-1 line, and update `ROADMAP.md` without any model call; unchanged usage produces no output.
**Commit:** `feat(schedule): live schedule with tiered updates (v0.5.0)`

---

### v0.6 — Handoff and safe stopping `S`

**Goal:** the second half of "never cut off".

- [X] `scripts/handoff.py` + `HANDOFF.md` template: done, next task, half-edited files, last commit
- [X] `commands/checkpoint.md` → `/navitok:checkpoint` (clean commit + handoff)
- [X] `SKILL.md` rule: **before every task**, check `remaining ≥ task upper estimate + buffer` using `schedule.json`; if it fails, propose a checkpoint
- [X] `SessionStart` hook: if `HANDOFF.md` exists, add a short summary to context

**Accept:** in a new session, Claude can say "continuing v0.x, task 3" without re-exploring the repo.
**Commit:** `feat(handoff): checkpoints and session resume (v0.6.0)`

---

### v0.7 — Learning, external usage, adaptive threshold `M`

**Goal:** estimates that improve with use, honest accounting of usage outside Claude Code, and a controlled climb from 90% toward 98%.

- [X] `scripts/external.py`: external usage = account-wide change − local change (§10.3); per-day and per-week profile of the user's external usage
- [X] `scripts/calibrate.py`: per-task-type mean and standard deviation; estimation error computed on **local** usage only
- [X] Outlier guard: flag and down-weight sessions that break assumptions (debugging spirals, sessions with large unexplained external usage, sessions with missing data)
- [X] Adaptive threshold (§10.1) and confidence score; recent sessions weigh more; records after a model or plan change are down-weighted
- [X] `schedule.py` reserves the learned external usage in weekly packing
- [X] `commands/status.md` → `/navitok:status` (remaining, threshold, confidence, external usage this week, next release)
- [X] Test against synthetic history **and** the real dogfood ledger

**Accept:** with 20 low-variance synthetic sessions the threshold rises above 90%; with high variance it stays at 90–92%; it never exceeds 98%. Synthetic web usage is classified as external and leaves estimation error unchanged.
**Commit:** `feat(learn): calibration, external usage and adaptive threshold (v0.7.0)`

---

### v0.8 — Statusline `S`

**Goal:** always-visible progress at zero token cost.

- [X] `scripts/statusline.py`: one line from `schedule.json` and the usage source, e.g. `v0.3 ▓▓▓▓░ 62% · fits · week 31% (ext 8%) · conf 40`
- [X] Must be fast (reads local files only, no network) and degrade gracefully when data is missing
- [X] **Compose, don't replace:** if the user already has a statusline, offer a wrapper that appends navitok's segment to the user's existing output
- [X] Configuration is written to the user's settings **only with explicit approval** (method per v0.1 findings)

**Accept:** the line updates as usage changes, costs no tokens, and an existing custom statusline keeps working.
**Commit:** `feat(ui): statusline segment (v0.8.0)`

---

### v0.9 — Terminal panel `S`

**Goal:** a live, full-screen view in a second terminal.

- [X] `scripts/watch.py`: releases with status, current session and weekly bars, external usage, estimate vs actual for recent sessions, confidence, next reset time
- [X] Live display, stdlib only, in order of preference:
  - `curses` where Python ships it (Linux, macOS).
  - Otherwise an **ANSI full-screen redraw**. Windows' Python has no `_curses`, and `windows-curses` is a third-party package, so it is not allowed. On Windows, virtual-terminal processing is enabled via `ctypes` at startup, so ANSI also works in the legacy console, not only Windows Terminal / VS Code. `q` is read with `msvcrt` on Windows and `termios`/`select` elsewhere. `--plain` forces this mode.
  - `--once`: one plain-text frame without escape codes, for any terminal or a pipe.
- [X] Refreshes on an interval from local files only (`plan.json`, `schedule.json`, `calibration.json`, the statusline's `usage_snapshot.json`; a fresh snapshot wins); `q` to quit; works in an 80×24 terminal and truncates cleanly in smaller ones; data errors are shown and logged (`--log`), never fatal
- [X] Entry point documented: `python3 <plugin>/scripts/watch.py` (`python` on Windows) (and a short alias suggestion)

**Accept:** the panel runs next to a Claude Code session for an hour without errors and without any model call (a 60-minute `--duration` soak with `--log`, plus a manual look in a real terminal).
**Commit:** `feat(ui): live terminal panel (v0.9.0)`

---

### v0.10 — Superpowers integration `S`

**Goal:** brainstorming → writing-plans → **navitok** → executing-plans.

- [X] `scripts/integrations/superpowers.py`: detect installation; read `docs/superpowers/plans/*.md`
- [X] Convert plan tasks into `plan.json` releases with cost ranges. **Never modify the original plan file**
- [X] If subagent-driven-development is in use, apply a cost multiplier; on Pro + strict, recommend inline execution
- [X] Without Superpowers, the v0.4 flow still works (tested)

**Accept:** a sample Superpowers plan file yields a versioned roadmap and schedule.
**Commit:** `feat(integrations): superpowers plan ingestion (v0.10.0)`

---

### v0.11 — Graphify integration `S`

**Goal:** cheaper reading, and file-scope data for the estimator.

- [X] `scripts/integrations/graphify.py`: detect `graphify-out/` and `GRAPH_REPORT.md`
- [X] Task → relevant nodes → estimated files/lines touched (fed into `estimate.py`)
- [X] No graph yet: add a **"build the map"** release and price it separately
- [X] Ledger field `helpers: ["graphify", ...]` so calibration keeps helped and unhelped sessions apart

**Accept:** synthetic history with and without Graphify stays separate; estimates come from the right group.
**Commit:** `feat(integrations): graphify scope estimation (v0.11.0)`

---

### v0.12 — Output trimming hook `S`

**Goal:** stop test and build output from bloating the context.

- [X] Choose the mechanism based on v0.1 findings (e.g. a `PreToolUse` hook that pipes Bash output through a trimmer)
- [X] Trimmer keeps error lines and the last N lines, collapses repeats, and saves the full output to `.navitok/logs/`
- [X] On/off via `config.json`; **off by default** (enabled in `/navitok:setup`)
- [X] Coexistence test with Graphify's `PreToolUse` hook

**Accept:** a long test run is trimmed without losing the error message; Graphify's hook still works.
**Commit:** `feat(hooks): optional output trimming (v0.12.0)`

**v0.12.1 (patch, found in the live check):** `PostToolUse` fires only for calls that succeed. A Bash command that exits non-zero fires `PostToolUseFailure`, which cannot replace output, so the hook never trims a failing test run. Two paths now:
- the `PostToolUse` hook (unchanged) trims long output of commands that **succeed**;
- `scripts/run.py -- CMD ...` runs a command, trims its output with the same trimmer, saves the full log and exits with the real exit code. `SKILL.md`: when `trim_output` is on, run tests and builds through it. No hook, so no race with Graphify and nothing for auto mode to deny.

**Accept (live):** a failing 300-line command through `run.py` in `claude -p --plugin-dir .` reaches Claude trimmed, with the error lines and the real exit code.
**Commit:** `fix(trim): run.py wrapper for failing commands (v0.12.1)`

---

### v0.13 — `/navitok:setup` (doctor) `S`

**Goal:** one command that shows everything.

- [X] `scripts/doctor.py`: Superpowers, Graphify, Python version, usage sources (which one is active), statusline state, `.navitok/` state
- [X] Table output (✅ / ❌, why it helps, install or enable command)
- [X] Never auto-install or auto-configure: show the commands and run them only on explicit approval
- [X] First-run wizard: plan + mode + statusline + trimming preference → `config.json`

**Accept:** on a clean machine `/navitok:setup` runs without errors and reports gaps correctly.
**Commit:** `feat(setup): doctor and first-run wizard (v0.13.0)`

---

### v1.0 — Release `M`

**Goal:** ready to share.

- [X] README: what it does, install (§2.6), a 60-second example, FAQ
- [X] README statusline and panel output as real text output
- [ ] README statusline and panel screenshots/GIF: moved to 1.0.2
- [X] README disclaimer: *"Estimates rely on personal calibration and are not guarantees. Anthropic's limits may change. Usage from other devices is detected only through account-wide numbers."*
- [X] README "Built with navitok" section: sprint count and the estimate-accuracy trend from `docs/dogfood/REPORT.md`
- [X] "Works with Superpowers & Graphify" section. Never call it "official"; note that third-party tools belong to their owners
- [X] `examples/`: one Pro-strict and one Max-flex sample roadmap
- [X] Version `1.0.0`, git tag `v1.0.0`, GitHub release notes
- [X] Install test through the marketplace (§2.6)

**Accept:** a new user can read the README, install in 5 minutes and run `/navitok:plan`.
**Commit:** `release: v1.0.0`

**Split (2026-11-26):** the sprint is `M` and partly outward-facing, so it has two parts.
- **v1.0a:** a fast off path for the trim hook (the maintainer's first task), the README items, ROADMAP §9 without `CLAUDE.md`, and `examples/`.
- **v1.0b** (each step needs the maintainer's approval): push; the marketplace install test; statusline and panel screenshots or a GIF; version `1.0.0`, the tag and the GitHub release notes.

---

## 8. After v1.0

| Version | Topic | Size |
|---|---|---|
| 1.0.2 | **Patch for current users** (see below): statusline survives plugin updates, statusline wrapper uses the Git Bash lookup, the remaining 1.0.0 limitations, and CI. Comes first, so CI is in place before the v1.1 calibration changes | S–M |
| v1.1 | **Learning across projects** (see below): four one-session sprints, v1.1.0–v1.1.3 | 4 × S/M |
| v1.2 | HTML dashboard: local page with release timeline, estimate-vs-actual chart, learning curve and external-usage trend (reads the same local files, zero tokens) | M |
| v1.3 | **Model & agent optimization** (see below): v1.3.0–v1.3.3 | 4 × S/M |
| v1.4 | Opt-in, anonymous community calibration (**off by default**) for a better cold start | M |
| v1.5 | Team mode: shared roadmaps for Team/Enterprise plans | M |
| ongoing | Measure the Max 5x / Max 20x multipliers from Max users' anonymised ledger numbers (not tied to a version) | — |

### 1.0.2 — Patch for current users `S–M`

**Goal:** fixes that affect people using 1.0.x now, without waiting for v1.1, and CI in place before the v1.1 calibration changes. One session under §5. If the estimate does not fit, split off the low-priority images item first; if it still does not fit, move CI to 1.0.3. Never widen the session.

- [ ] **Statusline survives plugin updates.** The statusline setting points at the installed plugin version's folder, so an update can break it. Either a stable launcher path that does not change with the version, or a one-line `SessionStart` notice when the configured version differs from the running one. Setup is re-run only after the user approves the shown change.
- [ ] **Statusline wrapper uses the Git Bash lookup.** `statusline.py run_wrapped` still finds the shell with `which("sh") or which("bash")`. Reuse `doctor.find_shell` (1.0.1) so a wrapped statusline works where Git Bash is not on `PATH`.
- [ ] **Remaining 1.0.0 limitations.** (a) Without a statusline, a manual `/usage` reading is overwritten by the stale usage cache at the next prompt: persist it with a timestamp and prefer it while it is fresher. (b) When `/navitok:plan` creates `.navitok/` mid-session, that first session is recorded with 0 local tokens: take the start snapshot from the transcript's first message.
- [ ] **CI.** GitHub Actions runs `python -m unittest discover -s tests -v` on Windows, Linux and macOS (Python 3.10 and the latest 3.x) on every push and PR. On Linux and macOS a curses smoke test starts `watch.py` in a pseudo-terminal and quits it. No new dependencies in the plugin.
- [ ] **README screenshots/GIF and a plugin icon** (512–2048 px square PNG). Low priority: the first thing split off if the sprint does not fit.

### v1.1 — Learning across projects

**Goal:** a new project starts from what navitok has already learned about *this user*, not only from the maintainer's seed. Today calibration is per project (`.navitok/calibration.json`), and every new project starts from the built-in seed (v0.0–v0.2 dogfood records: one maintainer, Pro, one project). Planned as four one-session sprints, using the same rules as §5. Everything stays local.

**v1.1.0 — Seed from all dogfood records `S`**
- [ ] Rebuild the cold-start seed from every record in `docs/dogfood/ledger.jsonl` (18 records, v0.0–v1.0.1, at the time of writing), not only v0.0–v0.2
- [ ] Exclude or down-weight noisy records, e.g. v1.0b (parallel claude.ai use and a second Claude Code session of unknown size, plus a long un-restarted context). The rule is written down and applied by script, not decided per record by hand
- [ ] Account for the ±1 resolution of `/usage`: treat each manual actual as an interval, so 1–2% sprints do not dominate the ratios (§10.9)
- [ ] `references/heuristics.md` and `estimate.py` stay in sync; a test fails when they differ
- [ ] The seed label ("one maintainer, Pro, one project") and the README numbers are updated

**v1.1.1 — User profile and project correction `M`**
- [ ] Two layers: a user-level profile in `~/.navitok/profile.json`, learned from all projects (per-type ranges, stop threshold, external-usage profile), plus a small per-project correction in `.navitok/calibration.json`
- [ ] Each project's learned sessions feed the profile from its `history.jsonl`. External usage is never counted as error (§4.3)
- [ ] One-time import of existing project histories into the profile, shown first and run only on approval. The project files are read, never changed
- [ ] Local only: no network, nothing uploaded. Per-project opt-out (`"profile": false` in `.navitok/config.json`): that project neither reads nor feeds the profile
- [ ] Hooks stay fast: the profile is a small precomputed file, rebuilt at `SessionStart`, never on every prompt

**v1.1.2 — Blending, not overwriting `S`**
- [ ] The seed is a prior. The user's data gains weight with every learned session until it takes over (§10.9). This replaces today's switch from cold start to learned at `MIN_TYPE_SAMPLES`
- [ ] Outliers cannot swing an estimate: clamped per-session ratios, a cap on any one session's weight, and the existing outlier guard (§10.1)
- [ ] Tests: a synthetic history moves smoothly from the seed to the user's numbers, and one extreme session moves a range by a bounded amount only

**v1.1.3 — Where an estimate comes from `S`**
- [ ] `/navitok:status`, the panel and `.navitok/ROADMAP.md` show the source of each estimate (`seed`, `profile` or `project`) with each layer's weight, e.g. `profile 70% · seed 30%`
- [ ] The statusline keeps `cold start` / `conf N` and adds the source only where it fits on one line

### v1.3 — Model & agent optimization

**Goal:** tell the user not only *how much* a release costs, but *how to make it cheaper*: which model for which task, when to use subagents, and when to hand work to another agent. Planned as four one-session sprints, using the same rules as §5.

**v1.3.0 — Model routing `S`**
- [ ] Each task in `plan.json` gets `suggested_model` + `suggested_effort` (rule-based on task type and size, e.g. search/rename/docs → lighter model, architecture/hard debugging → strongest model)
- [ ] `/navitok:status`, the statusline and the panel show "suggested for this task: X"
- [ ] Suggestions are never forced; the user always chooses

**v1.3.1 — Per-model calibration and limits `M`**
- [ ] Calibration splits cost by model, using the ledger data collected since v0.2
- [ ] Release-level comparison: "v0.4 with model A ≈ 30–40%, with model B ≈ 55–65% of a session"
- [ ] Per-model weekly buckets where a plan has model-specific weekly limits (verify current plan rules against official docs); when one bucket runs low, propose moving remaining work to another model
- [ ] Low confidence is shown honestly for models the user rarely uses

**v1.3.2 — Agent strategy `S`**
- [ ] Per-release strategy suggestion: which work goes to a subagent (and on which model), and which stays in the main session
- [ ] Parallel vs serial advice by plan and mode (e.g. Pro + strict → serial; Max → parallel when the quota allows)
- [ ] `schedule.py` accounts for the faster burn rate of parallel agents
- [ ] Offer project-specific subagent templates for `.claude/agents/`, created **only with explicit approval** (verify current subagent fields, including per-agent model selection, against official docs)

**v1.3.3 — Other agents `S`**
- [ ] Plan profiles for Codex / Cursor / Gemini CLI in `references/plans.md` (open to contributions)
- [ ] Cross-agent suggestions: "this release's mechanical tasks fit your Codex quota better", produced as a handoff the user runs, never executed automatically
- [ ] External-usage accounting stays correct when the user works across several agents

### Ongoing — Measure Max 5x / 20x

Not a version: it runs alongside the releases above. The multipliers in `references/plans.md` are nominal (0.2 and 0.05). Invite Max users, through a GitHub issue template, to share anonymised ledger numbers (percentages, token counts, task types; no prompts, code or personal data). Update the multipliers and their confidence once enough records exist.

---

## 9. Driving the build with Claude Code

1. Put this file at the repo root (§2.2). Everything Claude needs is in the repository: the sprint rules (§5), the measurement protocol (§6.1) and, from the second sprint on, `docs/HANDOFF.md`. Contributor rules are in the README's "Contributing" section. A maintainer may keep personal instructions in a local `CLAUDE.md`; it is gitignored, and nothing in this plan depends on it.
2. Run `claude` in the repo folder.
3. First message:

```text
Read ROADMAP.md (sprint rules §5, measurement protocol §6.1). Implement sprint v0.0 only.
Start with the dogfood measurement protocol (ROADMAP §6.1): ask me for my /usage
numbers and write your estimate before any work. Report briefly after each task.
At the end: run tests, update CHANGELOG, write the dogfood record, commit,
update docs/HANDOFF.md, and stop. Do not start v0.1 without my approval.
```

4. Every following session:

```text
Read docs/HANDOFF.md and implement the next sprint in ROADMAP.md.
Same rules: measurement protocol first, then tests, CHANGELOG, dogfood record,
commit, HANDOFF, stop.
```

> Tip: with Superpowers installed, ask for `brainstorming` before the larger sprints (v0.4, v0.5, v0.7). Skip it for small sprints, since it costs usage.

---

## 10. Appendix: formulas and schemas

### 10.1 Adaptive stop threshold

```
n          = number of learned sessions (outliers excluded)
max_step   = largest single-step cost observed (session %, last N sessions)
sigma_err  = standard deviation of |estimate − actual| on LOCAL usage (session %)

if n < 5:
    threshold = 90
else:
    threshold = 100 − 1.5 × max_step − 2 × sigma_err
    threshold = min(98, max(90, threshold))
```

Confidence (0–100): `min(100, n × 5) × (1 − min(1, sigma_err / 10))`

### 10.2 Fit check (before every task)

```
remaining = threshold − current_session_pct
fits      = remaining ≥ task_est_high + buffer
buffer    = max(2, max_step)            # in session %
```

### 10.3 External usage

```
account_delta  = account_pct_end − account_pct_start      # includes web, other machines
local_delta    = local usage converted to % (from transcripts, calibrated pct-per-token)
external_delta = max(0, account_delta − local_delta)
```

- `external_delta` is stored per session and never counted as estimation error.
- Weekly profile: rolling mean and P80 of external usage per weekday.
- Weekly packing reserves the P80 external usage before placing releases.
- Until `pct-per-token` is calibrated (first ~5 sessions), external usage is reported as "unknown", not zero.

### 10.4 Replan triggers (Tier 2)

Offer a replan at the next task boundary when any of these holds:
- the current release's upper estimate no longer fits today and cannot simply move to the next session,
- actual cost of the last 2 tasks exceeds their upper estimates by > 30%,
- weekly packing pushes the final release more than one week later than planned,
- the user changes plan, mode or scope.

### 10.5 `history.jsonl` record (draft)

The same schema is used for `docs/dogfood/ledger.jsonl`.

```json
{
  "schema": 1,
  "ts_start": "2026-11-24T15:00:00Z",
  "ts_end": "2026-11-24T18:40:00Z",
  "release": "v0.4",
  "plan": "pro",
  "mode": "strict",
  "model": "claude-opus-...",
  "effort": "medium",
  "helpers": ["superpowers", "graphify"],
  "source": "statusline|cache|manual|transcript",
  "account_session_pct_start": 0,
  "account_session_pct_end": 84,
  "account_weekly_pct_start": 22,
  "account_weekly_pct_end": 31,
  "local_tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
  "external_pct": 6,
  "tasks": [
    {
      "id": "v0.4-t2",
      "type": "feature",
      "size": "M",
      "files_touched": 4,
      "files_predicted": 5,
      "lines_changed": 220,
      "lines_predicted": 180,
      "est_pct": [12, 20],
      "actual_pct": 17,
      "max_step_pct": 3.1
    }
  ],
  "outlier": false,
  "ended_cleanly": true,
  "notes": ""
}
```

When per-task actuals are unknown (manual source), set `actual_pct` to `null` and record only session-level numbers. When external usage cannot be computed yet, set `external_pct` to `null`.

### 10.6 `plan.json` (draft)

```json
{
  "schema": 1,
  "project": "example-app",
  "plan": "pro",
  "mode": "strict",
  "releases": [
    {
      "id": "v0.1",
      "title": "Auth skeleton",
      "est_pct": [45, 60],
      "tasks": [
        {"id": "v0.1-t1", "title": "User model", "type": "feature", "size": "S",
         "est_pct": [8, 12], "suggested_model": null, "suggested_effort": null,
         "status": "todo"}
      ]
    }
  ]
}
```

### 10.7 `schedule.json` (draft, script-owned)

```json
{
  "schema": 1,
  "computed_at": "2026-11-24T16:00:00Z",
  "threshold": 90,
  "session": {"used_pct": 62, "resets_at": "2026-11-24T19:00:00Z"},
  "week": {"used_pct": 31, "external_reserved_pct": 10, "resets_at": "2026-11-28T09:00:00Z"},
  "current_release": "v0.3",
  "fits_today": true,
  "placement": [
    {"release": "v0.3", "week": 1, "session": "current"},
    {"release": "v0.4", "week": 1, "session": "next"},
    {"release": "v0.5", "week": 2, "session": "first"}
  ],
  "last_notice": "v0.3 fits"
}
```

### 10.8 `config.json` (draft)

```json
{
  "schema": 1,
  "plan": "pro",
  "mode": "strict",
  "threshold_override": null,
  "statusline": false,
  "trim_output": false
}
```

### 10.9 Blending seed, profile and project (draft, v1.1)

Three layers, each the prior for the next: **seed** (built-in, `heuristics.md`) → **profile** (`~/.navitok/profile.json`, all of the user's projects) → **project** (`.navitok/calibration.json`). Per task type, each layer learns a ratio `r = local actual / seed estimate midpoint`.

```
# per learned session i (outliers already down-weighted, §10.1)
r_i     = clamp(local_actual_i / seed_mid_i, 1/3, 3)   # one session cannot move far
w_i     = recency_i × change_i × outlier_i × res_i
res_i   = min(1, a_i / 3)          # manual /usage is ±1: 1–2% sessions count less
w_i     = min(w_i, 0.25 × Σw)      # no session carries more than a quarter (once n ≥ 4)

# profile layer (all projects)
n_p     = Σ w_i                                   # over all projects
r_p     = exp(Σ w_i · log r_i / n_p)              # weighted geometric mean
alpha_p = n_p / (n_p + K_PROFILE)                 # K_PROFILE = 5
ratio_p = exp(alpha_p · log r_p)                  # = 1 (seed) at n_p = 0

# project correction (this project only, relative to the profile)
r_j     = exp(Σ_project w_i · log(r_i / ratio_p) / n_j)
alpha_j = n_j / (n_j + K_PROJECT)                 # K_PROJECT = 5
corr_j  = clamp(exp(alpha_j · log r_j), 0.5, 2)

estimate = seed_range × ratio_p × corr_j
weights  = seed (1 − alpha_p) · profile alpha_p (1 − alpha_j) · project alpha_p · alpha_j
```

With no data the estimate is the seed. Each learned session moves it a little; after about `K` sessions the user's data carries half the weight, and from there it takes over. Range width follows the same weights: the seed's relative width shrinks toward the user's observed spread, but never below ±20% of the midpoint. While a project has fewer than `MIN_N` learned sessions, the stop threshold (§10.1) and the external-usage profile (§10.3) come from the profile. The constants are starting values, tuned against the dogfood ledger in v1.1.2.
