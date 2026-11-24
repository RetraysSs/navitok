---
name: navitok
description: Plans a project into releases that each fit one 5-hour Claude session under the user's usage limits, priced as ranges of session %. Use when the user asks to plan or break down a project around their Claude usage limits, or runs /navitok:plan. Checking fit during work and handoffs arrive in later releases.
---

# navitok: plan a project into session-sized releases

You do the judgement (tasks, grouping). Scripts do all the numbers. **Never write, guess or adjust a cost estimate yourself.** Every number comes from `plan.py`.

Scripts (Python 3.10+ standard library). Run them from the user's project root with `python3`, or with `python` if `python3` is missing or does not run (common on Windows). Keep the path in quotes:

- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py" config --plan <plan> --mode <mode>`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py" price`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py" render`

Cost table: `${CLAUDE_PLUGIN_ROOT}/skills/navitok/references/heuristics.md`. Plans: `${CLAUDE_PLUGIN_ROOT}/skills/navitok/references/plans.md`. Read them only if the user asks how estimates work.

## Plan flow

Keep the conversation short. Each question and each file read costs the user's usage.

1. **Plan and mode.** If `.navitok/config.json` exists, reuse its `plan` and `mode` and say so. Otherwise ask, in one message (use the AskUserQuestion tool if available):
   - Plan: Pro, Max 5x, Max 20x or API.
   - Mode: **strict** (never go past the limit, never pay extra) or **flex** (continue on extra usage past the limit).
   Then run `plan.py config --plan <pro|max5x|max20x|api> --mode <strict|flex>`.
2. **Understand the project.** Use the description the user gave. If it is missing or too vague to split into tasks, ask once. In an existing repository, read the README and list the top-level files. Do not read the whole codebase.
3. **Break it into tasks.** Each task does one thing and can be finished and tested on its own. For each task choose:
   - `type`: one of `feature`, `bugfix`, `refactor`, `test`, `docs`, `config`, `scaffold`, `research`, `migration`, `wrapup`. Use another word only if none fits: unknown types get the widest range.
   - `size`: `S`, `M` or `L` (relative effort). If unsure, pick the larger size.
   - `files`: rough number of files the task touches.
4. **Group tasks into releases** (`v0.1`, `v0.2`, ...). Each release:
   - works on its own and ends in a commit,
   - has 3–5 tasks, in dependency order, and ends with a `wrapup` task (tests, changelog, commit),
   - fits one session. `plan.py price` checks this.
5. **Write `.navitok/plan.json`**, with no `est_pct` fields (the script adds them):
   ```json
   {"schema": 1, "project": "<name>", "plan": "<plan>", "mode": "<mode>",
    "releases": [{"id": "v0.1", "title": "<title>",
      "tasks": [{"id": "v0.1-t1", "title": "<title>", "type": "feature", "size": "S", "files": 2}]}]}
   ```
   Task ids are `<release>-t<n>` and unique across the plan.
6. **Price it:** run `plan.py price`.
   - Exit 0: the script wrote the prices into `plan.json` and rendered `.navitok/ROADMAP.md`.
   - Exit 1: a line starts with `OVER:` for each release whose upper estimate is above the threshold. Split that release or move tasks to a later one, edit `plan.json`, and run `price` again. Do not shrink sizes just to make a release fit.
   - Exit 2: the plan is malformed. Fix what the message names.
7. **Report** in a few lines: the release table from the script output (id, range, title), the sum of all releases (say it spans several sessions; never present it as one session's usage), and that estimates are cold-start ranges that will calibrate from the user's own history. Point to `.navitok/ROADMAP.md`. Suggest adding `.navitok/` to `.gitignore`, except `ROADMAP.md` and `HANDOFF.md` if they want to share them. Do not change `.gitignore` without asking.

To change the plan later, edit `plan.json` and run `price` again. To refresh only the roadmap view, run `render`.

## Not available yet

Live fit checks during work, the schedule, the statusline and handoffs arrive in later navitok releases. If the user asks for them, say so. Do not invent usage numbers.
