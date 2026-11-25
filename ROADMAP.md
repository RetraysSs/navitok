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
# Put ROADMAP.md and CLAUDE.md in this folder (CLAUDE.md stays local: it is gitignored, not committed)
git add ROADMAP.md
git commit -m "docs: initial roadmap and project rules"

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

> Model and agent optimization is deliberately **not** in v1.0. It is its own release, v1.2 (§8). The ledger records the model and effort of every session from v0.2 onward, so by the time v1.2 starts there is real per-model data to learn from.

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

- [ ] `scripts/external.py`: external usage = account-wide change − local change (§10.3); per-day and per-week profile of the user's external usage
- [ ] `scripts/calibrate.py`: per-task-type mean and standard deviation; estimation error computed on **local** usage only
- [ ] Outlier guard: flag and down-weight sessions that break assumptions (debugging spirals, sessions with large unexplained external usage, sessions with missing data)
- [ ] Adaptive threshold (§10.1) and confidence score; recent sessions weigh more; records after a model or plan change are down-weighted
- [ ] `schedule.py` reserves the learned external usage in weekly packing
- [ ] `commands/status.md` → `/navitok:status` (remaining, threshold, confidence, external usage this week, next release)
- [ ] Test against synthetic history **and** the real dogfood ledger

**Accept:** with 20 low-variance synthetic sessions the threshold rises above 90%; with high variance it stays at 90–92%; it never exceeds 98%. Synthetic web usage is classified as external and leaves estimation error unchanged.
**Commit:** `feat(learn): calibration, external usage and adaptive threshold (v0.7.0)`

---

### v0.8 — Statusline `S`

**Goal:** always-visible progress at zero token cost.

- [ ] `scripts/statusline.py`: one line from `schedule.json` and the usage source, e.g. `v0.3 ▓▓▓▓░ 62% · fits · week 31% (ext 8%) · conf 40`
- [ ] Must be fast (reads local files only, no network) and degrade gracefully when data is missing
- [ ] **Compose, don't replace:** if the user already has a statusline, offer a wrapper that appends navitok's segment to the user's existing output
- [ ] Configuration is written to the user's settings **only with explicit approval** (method per v0.1 findings)

**Accept:** the line updates as usage changes, costs no tokens, and an existing custom statusline keeps working.
**Commit:** `feat(ui): statusline segment (v0.8.0)`

---

### v0.9 — Terminal panel `S`

**Goal:** a live, full-screen view in a second terminal.

- [ ] `scripts/watch.py` (stdlib `curses`): releases with status, current session and weekly bars, external usage, estimate vs actual for recent tasks, confidence, next reset time
- [ ] Refreshes on an interval from local files only; `q` to quit; works in an 80×24 terminal
- [ ] Plain-text fallback (`--once`) for terminals without curses support
- [ ] Entry point documented: `python3 <plugin>/scripts/watch.py` (`python` on Windows) (and a short alias suggestion)

**Accept:** the panel runs next to a Claude Code session for an hour without errors and without any model call.
**Commit:** `feat(ui): live terminal panel (v0.9.0)`

---

### v0.10 — Superpowers integration `S`

**Goal:** brainstorming → writing-plans → **navitok** → executing-plans.

- [ ] `scripts/integrations/superpowers.py`: detect installation; read `docs/superpowers/plans/*.md`
- [ ] Convert plan tasks into `plan.json` releases with cost ranges. **Never modify the original plan file**
- [ ] If subagent-driven-development is in use, apply a cost multiplier; on Pro + strict, recommend inline execution
- [ ] Without Superpowers, the v0.4 flow still works (tested)

**Accept:** a sample Superpowers plan file yields a versioned roadmap and schedule.
**Commit:** `feat(integrations): superpowers plan ingestion (v0.10.0)`

---

### v0.11 — Graphify integration `S`

**Goal:** cheaper reading, and file-scope data for the estimator.

- [ ] `scripts/integrations/graphify.py`: detect `graphify-out/` and `GRAPH_REPORT.md`
- [ ] Task → relevant nodes → estimated files/lines touched (fed into `estimate.py`)
- [ ] No graph yet: add a **"build the map"** release and price it separately
- [ ] Ledger field `helpers: ["graphify", ...]` so calibration keeps helped and unhelped sessions apart

**Accept:** synthetic history with and without Graphify stays separate; estimates come from the right group.
**Commit:** `feat(integrations): graphify scope estimation (v0.11.0)`

---

### v0.12 — Output trimming hook `S`

**Goal:** stop test and build output from bloating the context.

- [ ] Choose the mechanism based on v0.1 findings (e.g. a `PreToolUse` hook that pipes Bash output through a trimmer)
- [ ] Trimmer keeps error lines and the last N lines, collapses repeats, and saves the full output to `.navitok/logs/`
- [ ] On/off via `config.json`; **off by default** (enabled in `/navitok:setup`)
- [ ] Coexistence test with Graphify's `PreToolUse` hook

**Accept:** a long test run is trimmed without losing the error message; Graphify's hook still works.
**Commit:** `feat(hooks): optional output trimming (v0.12.0)`

---

### v0.13 — `/navitok:setup` (doctor) `S`

**Goal:** one command that shows everything.

- [ ] `scripts/doctor.py`: Superpowers, Graphify, Python version, usage sources (which one is active), statusline state, `.navitok/` state
- [ ] Table output (✅ / ❌, why it helps, install or enable command)
- [ ] Never auto-install or auto-configure: show the commands and run them only on explicit approval
- [ ] First-run wizard: plan + mode + statusline + trimming preference → `config.json`

**Accept:** on a clean machine `/navitok:setup` runs without errors and reports gaps correctly.
**Commit:** `feat(setup): doctor and first-run wizard (v0.13.0)`

---

### v1.0 — Release `M`

**Goal:** ready to share.

- [ ] README: what it does, install (§2.6), a 60-second example, statusline and panel screenshots/GIF, FAQ
- [ ] README disclaimer: *"Estimates rely on personal calibration and are not guarantees. Anthropic's limits may change. Usage from other devices is detected only through account-wide numbers."*
- [ ] README "Built with navitok" section: sprint count and the estimate-accuracy trend from `docs/dogfood/REPORT.md`
- [ ] "Works with Superpowers & Graphify" section. Never call it "official"; note that third-party tools belong to their owners
- [ ] `examples/`: one Pro-strict and one Max-flex sample roadmap
- [ ] Version `1.0.0`, git tag `v1.0.0`, GitHub release notes
- [ ] Install test through the marketplace (§2.6)

**Accept:** a new user can read the README, install in 5 minutes and run `/navitok:plan`.
**Commit:** `release: v1.0.0`

---

## 8. After v1.0

| Version | Topic |
|---|---|
| v1.1 | HTML dashboard: local page with release timeline, estimate-vs-actual chart, learning curve and external-usage trend (reads the same local files, zero tokens) |
| v1.2 | **Model & agent optimization** (see below) |
| v1.3 | Opt-in, anonymous community calibration (**off by default**) for a better cold start |
| v1.4 | Team mode: shared roadmaps for Team/Enterprise plans |

### v1.2 — Model & agent optimization

**Goal:** tell the user not only *how much* a release costs, but *how to make it cheaper*: which model for which task, when to use subagents, and when to hand work to another agent. Planned as four one-session sprints, using the same rules as §5.

**v1.2.0 — Model routing `S`**
- [ ] Each task in `plan.json` gets `suggested_model` + `suggested_effort` (rule-based on task type and size, e.g. search/rename/docs → lighter model, architecture/hard debugging → strongest model)
- [ ] `/navitok:status`, the statusline and the panel show "suggested for this task: X"
- [ ] Suggestions are never forced; the user always chooses

**v1.2.1 — Per-model calibration and limits `M`**
- [ ] Calibration splits cost by model, using the ledger data collected since v0.2
- [ ] Release-level comparison: "v0.4 with model A ≈ 30–40%, with model B ≈ 55–65% of a session"
- [ ] Per-model weekly buckets where a plan has model-specific weekly limits (verify current plan rules against official docs); when one bucket runs low, propose moving remaining work to another model
- [ ] Low confidence is shown honestly for models the user rarely uses

**v1.2.2 — Agent strategy `S`**
- [ ] Per-release strategy suggestion: which work goes to a subagent (and on which model), and which stays in the main session
- [ ] Parallel vs serial advice by plan and mode (e.g. Pro + strict → serial; Max → parallel when the quota allows)
- [ ] `schedule.py` accounts for the faster burn rate of parallel agents
- [ ] Offer project-specific subagent templates for `.claude/agents/`, created **only with explicit approval** (verify current subagent fields, including per-agent model selection, against official docs)

**v1.2.3 — Other agents `S`**
- [ ] Plan profiles for Codex / Cursor / Gemini CLI in `references/plans.md` (open to contributions)
- [ ] Cross-agent suggestions: "this release's mechanical tasks fit your Codex quota better", produced as a handoff the user runs, never executed automatically
- [ ] External-usage accounting stays correct when the user works across several agents

---

## 9. Driving the build with Claude Code

1. Put this file and `CLAUDE.md` at the repo root (§2.2). `CLAUDE.md` stays local and is not committed; Claude Code reads it from the working tree.
2. Run `claude` in the repo folder.
3. First message:

```text
Read ROADMAP.md and CLAUDE.md. Implement sprint v0.0 only.
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
      "lines_changed": 220,
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
