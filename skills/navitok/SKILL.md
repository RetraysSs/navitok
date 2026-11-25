---
name: navitok
description: Plans a project into releases that each fit one 5-hour Claude session under the user's usage limits, priced as ranges of session %. Use when the user asks to plan or break down a project around their Claude usage limits, or runs /navitok:plan, /navitok:checkpoint or /navitok:status. Keeps a live schedule, checks before every task that it still fits, writes handoffs, and reacts to one-line navitok notices about fit and replans.
---

# navitok: plan a project into session-sized releases

You do the judgement (tasks, grouping). Scripts do all the numbers. **Never write, guess or adjust a cost estimate yourself.** Every number comes from `plan.py`.

Scripts (Python 3.10+ standard library). Run them from the user's project root with `python3`, or with `python` if `python3` is missing or does not run (common on Windows). Keep the path in quotes:

- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py" config --plan <plan> --mode <mode>`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py" price`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py" render`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/schedule.py" recompute [--session-pct N --weekly-pct N]`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/schedule.py" show`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py" fit [--task <id>]`
- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py" write [--note "<text>"]...`

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

## Schedule and notices

A `UserPromptSubmit` hook runs `schedule.py` before every prompt. It writes `.navitok/schedule.json` (script-owned: never edit it) and refreshes the Schedule section of `.navitok/ROADMAP.md`. It costs no tokens and is silent unless the fit status changes.

- **A line starting with `navitok:` and saying a release no longer fits** (Tier 1): finish the task you are on, then stop at a clean point and offer the user a checkpoint (commit + short handoff). Do not start the next task. Mention it once; do not repeat it.
- **A line saying `replan suggested`** (Tier 2): do not replan mid-task. When the current task is done, tell the user the reason in one sentence and ask whether to replan. Only if they agree, edit `plan.json` and run `plan.py price`. If they decline, continue.
- **If the user gives you a `/usage` reading**, run `schedule.py recompute --session-pct <session> --weekly-pct <weekly>` so the schedule uses it.
- To answer "where are we?", run `schedule.py show`. Do not compute fits yourself.

## Before every task: fit check

In a project with `.navitok/plan.json`, **before you start each task** of the plan, run `handoff.py fit` (add `--task <id>` if you are not doing the plan's next task). It checks `remaining ≥ task upper estimate + buffer` against `schedule.json`. Act on its first word:

- `FITS`: start the task. Say nothing about it.
- `NO-FIT`: do not start the task. Tell the user in one sentence and propose `/navitok:checkpoint`.
- `UNKNOWN`: there is no usage reading. Ask the user once per session for `/usage`, run `schedule.py recompute --session-pct N --weekly-pct N`, then run `fit` again.
- If the line says the reading is stale, continue on `FITS`, but say it once per session.

Keep task statuses current in `plan.json`: set `"status": "doing"` when you start a task and `"done"` when it is finished and tested. The schedule, fit check and handoff read them.

## Checkpoint flow

On `/navitok:checkpoint`, or when the user agrees to one:

1. **Stop at a clean point.** Do not start new work. If a task is half done, either finish its current small step or leave it as `doing`.
2. **Update `plan.json`:** mark finished tasks `done`. Run `plan.py render`.
3. **Commit** the work (`git status`, then one commit with a Conventional Commits message). Do not add `.navitok/` unless the user already tracks it. If nothing changed, skip the commit. If the project is not a git repository, skip this step and say so.
4. **Write the handoff:** run `handoff.py write`, with one `--note` per thing the next session must know and cannot see in the files: a decision, a dead end, a half-finished idea, the user's note. Keep each note to one line. It writes `.navitok/HANDOFF.md` with what is done, the next task, any uncommitted (half-edited) files and the last commit.
5. **Report** in two lines: the commit (or "nothing to commit") and the `Resume:` line the script printed.

## Resuming

When a session starts and `.navitok/HANDOFF.md` exists, a `navitok handoff` line is added to your context. Use it to say where work stands, for example "continuing v0.2, task 3", and continue from the next task. Run the fit check first. Read `.navitok/HANDOFF.md` only if you need the notes or the file list. Do not re-explore the repository to rediscover the state.

## Learning and status

navitok calibrates itself from `.navitok/history.jsonl`. The session hooks record each session and the plan tasks finished in it. A `SessionStart` hook refreshes `.navitok/calibration.json` (script-owned: never edit it). After 5 learned sessions:

- `plan.py price` uses the learned per-type ranges (task notes say "learned from history"),
- the stop threshold can rise from 90% up to 98% when estimates are steady (§10.1),
- the fit-check buffer uses the largest observed step,
- usage outside Claude Code (claude.ai, other machines) is measured, kept out of estimation error, and reserved in the weekly schedule.

Before that, everything stays at the cold start, and external usage is reported as unknown, not zero.

On `/navitok:status`, or when the user asks how much is left, run `calibrate.py status` and show its output as is. Never compute or adjust these numbers yourself.

## Statusline

navitok can show one line in Claude Code's statusline at zero token cost, e.g. `v0.3 ▓▓▓░░ 62% · fits · week 31% (ext 8%) · conf 40`. It also gives navitok fresh account-wide usage: the statusline receives the live 5-hour and weekly %, and saves them to `.navitok/usage_snapshot.json` for the hooks.

Set it up **only when the user asks for it**, and change their settings **only after they approve the exact change**:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/statusline.py" setup`. It writes nothing. It shows the current and the new `statusLine` value of `~/.claude/settings.json`. An existing statusline is wrapped (its output stays first), never replaced.
2. Show that to the user and ask whether to apply it.
3. Only on an explicit yes, run the same command with `--apply`. It keeps a backup (`settings.json.navitok-backup`).
4. To undo: `statusline.py remove` to show the change, then `remove --apply` after approval. This restores the user's own command.

The command points at this plugin version's path, so after a plugin update run `setup` again (it shows the change, then needs approval). On Windows it needs Git Bash, like the hooks.

## Terminal panel

For a live full-screen view in a second terminal (zero tokens, local files only), tell the user to run, from the project root:

`python3 "<plugin path>/scripts/watch.py"` (`python` on Windows), `q` to quit. `--interval S` sets the refresh (default 5 s), and `--once` prints a single frame.

Give them the real path: `${CLAUDE_PLUGIN_ROOT}` expanded. Suggest an alias such as `alias navitok-watch='python3 "<plugin path>/scripts/watch.py"'`. Do not run the live panel yourself: it is for the user's own terminal.

## Not available yet

Superpowers and Graphify integration, output trimming and `/navitok:setup` arrive in later navitok releases. If the user asks for them, say so. Do not invent usage numbers.
