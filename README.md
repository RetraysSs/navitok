# navitok

> Navigation for your tokens.

navitok is a Claude Code plugin that plans a project into session-sized releases. Each release is sized to fit your plan's 5-hour session and weekly usage limits. navitok keeps the schedule current as your real usage changes, including usage outside Claude Code, and it calibrates its estimates from your own history, so a prompt is never cut off halfway.

**Status: pre-1.0 (0.13.0).** Everything described here works. The 1.0 release (marketplace install test, screenshots) is in progress, see [ROADMAP.md](ROADMAP.md).

> **Disclaimer.** Estimates rely on personal calibration and are not guarantees. Anthropic's limits may change. Usage from other devices is detected only through account-wide numbers.

## What it does

- **Plans in releases that fit.** `/navitok:plan` splits a project into releases of 3–5 tasks. A script prices every task as a range of session % with a confidence score, and no release is planned past the stop threshold (90% at the start, never above 98%).
- **Checks before every task.** Before each task, the remaining session is checked against the task's upper estimate. If it no longer fits, navitok says so in one line and offers a clean checkpoint and handoff instead of a half-finished prompt.
- **Follows your real usage.** It reads the account-wide session and weekly % (from the statusline, or a `/usage` reading you give it), so claude.ai and other machines are taken into account. That usage is shown separately and never counted as estimation error.
- **Learns from your history.** Every session is recorded locally. After a few sessions the ranges and the threshold calibrate to your own numbers.
- **Costs nothing to watch.** The statusline, the terminal panel and the hooks are plain Python scripts that read local files. They make no model calls and no network calls.

## Install

```text
/plugin marketplace add RetraysSs/navitok
/plugin install navitok@navitok
/navitok:setup
```

Needs Python 3.10+ (standard library only). On Windows, `python` works where `python3` is the Microsoft Store alias.

Development version: `git clone https://github.com/RetraysSs/navitok`, then `claude --plugin-dir ./navitok`, and `/reload-plugins` after changes.

## 60-second example

```text
/navitok:setup
```

A table of what navitok can use, with ✅ / ❌ and the command for each gap. Then a short wizard asks for your plan, mode, statusline and trimming preference.

```text
/navitok:plan a small command-line todo app with due dates and tag filters
```

Claude breaks the project into tasks and groups them into releases. `plan.py` prices them and renders `.navitok/ROADMAP.md`:

```text
v0.1           2.3–8.0%  conf  30  Skeleton and storage
v0.2          3.8–12.0%  conf  30  Core commands
v0.3          4.5–14.0%  conf  30  Due dates and filters
v0.4           2.1–7.5%  conf  30  Release
All releases together: 12.7–41.5% (a sum across sessions, not one session's usage)
All releases fit under 90%.
```

Then work through the releases. The statusline shows where you are, for example `v0.3 ▓▓▓░░ 62% · fits · week 31% (ext 8%) · conf 40`. `/navitok:status` shows the same with more detail. `/navitok:checkpoint` commits at a clean point and writes a handoff that the next session picks up.

Full sample roadmaps for Pro (strict) and Max 5x (flex) are in [`examples/`](examples/).

## Commands

| Command | What it does |
|---|---|
| `/navitok:setup` | Doctor table (Python, project state, usage source, statusline, trimming, Superpowers, Graphify) and first-run wizard. Installs and changes nothing without your approval. |
| `/navitok:plan [description]` | Plans the project into releases that each fit one session. |
| `/navitok:status` | Session left, threshold, confidence, external usage this week, next release. |
| `/navitok:checkpoint [note]` | Stops at a clean point, commits and writes a handoff. |

## First run: `/navitok:setup`

`/navitok:setup` shows one table of what navitok can use: Python, the project's `.navitok/` state, which account-usage source is active, the statusline, output trimming, and whether Superpowers and Graphify are there. Each gap comes with why it helps and the command that would fix it. A short wizard then asks for your plan, mode, statusline and trimming preference and writes `.navitok/config.json`. Nothing is installed or changed without your approval. The statusline change is shown first and applied only if you say yes. The same table: `python scripts/doctor.py check`.

## Statusline

The statusline segment shows the current release, session used, whether the next task fits, weekly use with the external share, and confidence. It also saves the fresh account-wide reading that the fit check prefers. If you already have a statusline, navitok wraps it, so your line stays first, and it never replaces it. `/navitok:setup` shows the exact settings change before anything is written.

## Terminal panel

A live view of your releases, session and weekly usage, external usage and calibration, for a second terminal. It costs zero tokens and reads local files only.

```bash
python3 <plugin>/scripts/watch.py            # live, q to quit (python on Windows)
python3 <plugin>/scripts/watch.py --once     # one plain frame
alias navitok-watch='python3 <plugin>/scripts/watch.py'
```

It uses `curses` where available. Otherwise, on Windows for example, it redraws with ANSI escape codes, also in the legacy console.

## Works with Superpowers and Graphify

Both are optional third-party tools that belong to their owners. navitok works with them by detecting them and reading their output files. It never copies their code, never changes their files and never installs them. These are not official integrations, and everything works without them.

**[Superpowers](https://github.com/obra/superpowers).** If you plan with Superpowers (brainstorming → writing-plans), navitok can import the plan file and turn it into versioned releases that each fit one session, with a schedule. The plan file is only read.

```bash
python3 <plugin>/scripts/integrations/superpowers.py detect
python3 <plugin>/scripts/integrations/superpowers.py ingest [--execution inline|subagent]
```

**[Graphify](https://github.com/Graphify-Labs/graphify).** If the project has a Graphify knowledge graph (`graphify-out/graph.json`), navitok reads it to estimate which files and how many lines each task touches, and prices tasks from that. Without a graph it can add a separately priced "build the map" release. Sessions with and without a graph are calibrated separately.

```bash
python3 <plugin>/scripts/integrations/graphify.py detect
python3 <plugin>/scripts/integrations/graphify.py apply        # scope plan.json tasks
python3 <plugin>/scripts/integrations/graphify.py map [--apply]
```

## Output trimming (optional)

Long test and build output can fill the context quickly. With `"trim_output": true` in `.navitok/config.json`, a `PostToolUse` hook gives Claude a trimmed copy of long Bash output (errors, tracebacks and the last lines kept, repeats collapsed) and saves the full output to `.navitok/logs/`. It is off by default, never changes the command, and works alongside other hooks such as Graphify's. While it is off, it costs about 20 ms per Bash call and starts no Python.

The hook only sees commands that succeed: Claude Code does not run `PostToolUse` for a command that exits non-zero. For tests and builds, navitok's skill therefore tells Claude to use the wrapper `python scripts/run.py -- CMD ...`. It trims the same way, saves the full log and exits with the command's real exit code.

## How estimates work

- **Ranges with a confidence score, never single numbers.** Cold-start ranges come from a heuristics table by task type and size. They narrow as your own history calibrates them.
- **Percentages, not tokens.** Plan limits are modelled as % of a session and a week. navitok makes no claims about absolute token limits.
- **Never being cut off matters more than using the whole limit.** The stop threshold starts at 90% and can rise from your history, but never above 98%. In **strict** mode a release that does not fit is not started. **Flex** mode continues on extra usage past the limit.
- **Scripts compute, the model decides.** Claude splits the work into tasks. Every number comes from deterministic scripts, and replanning happens only between tasks, never mid-task.

## FAQ

**Does navitok send my data anywhere?** No. Its scripts read and write local files only (`.navitok/` in your project) and make no network calls. The hooks and the statusline cost zero tokens.

**Does it see what I do on claude.ai or another machine?** Only through the account-wide session and weekly % that Claude Code reports (the statusline) or that you read from `/usage`. That usage shows up as external and is never treated as an estimation error.

**Do I need Superpowers or Graphify?** No. navitok works without both. They add plan import and file-level scoping.

**Will it change my Claude Code settings?** Only the statusline, and only after you approve the exact change it shows. An existing statusline is wrapped, not replaced, and a backup is kept. It installs nothing.

**Why are the first estimates so wide?** They are cold-start ranges with low confidence. In navitok's own build the early ranges overestimated by 2–10×. After a few recorded sessions they calibrate to your usage (see below).

**Does it work on Windows?** Yes. navitok was built on Windows 11, and the tests run there. Use `python` where `python3` is the Store alias.

## Built with navitok

navitok was built in 16 measured sprints before the 1.0 release (v0.0–v0.13, the v0.12.1 patch and v1.0a), each planned and measured with navitok's own approach. At the start of each sprint, Claude wrote per-task estimates as ranges, before any work. After the last commit, the maintainer read the real cost from `/usage`. All 16 sprints used 79% of a 5-hour session in total, 4.9% on average.

| Sprints | Actual inside the estimated range | Mean absolute error (vs. midpoint) | Mean actual | Mean estimate midpoint |
|---|---|---|---|---|
| v0.0–v0.8 (9) | 2 of 9 | 6.1 points | 4.4% | 10.6% |
| v0.9–v1.0a (7) | **7 of 7** | 2.1 points | 5.6% | 7.2% |

The estimates started out 2–10× too high and have stayed inside their range since v0.9. They still lean high, which is the intended direction: being cut off is worse than finishing early. `/usage` reports whole percents, so every number is ±1. One maintainer, one plan (Pro), one project: this improves the cold start, but it does not replace your own calibration. The sprint-by-sprint records are in [`docs/dogfood/REPORT.md`](docs/dogfood/REPORT.md) and [`docs/dogfood/ledger.jsonl`](docs/dogfood/ledger.jsonl).

## Contributing

- Scripts use the **Python 3.10+ standard library only** (including `curses` for the panel). Do not add dependencies.
- Tests: `python3 -m unittest discover -s tests -v` (`python` on Windows).
- Local plugin testing: `claude --plugin-dir .`, then `/reload-plugins` after changes.
- Hooks and the statusline must be fast. They read local files only, make no network calls, and stay silent unless something changed.
- Claude Code's hook events, statusline fields and plugin manifest fields change over time. Check the official docs before using one, and record what you find in [`docs/data-sources.md`](docs/data-sources.md). Undocumented sources are allowed only behind an adapter with a fallback, marked unstable there.
- Never commit real user transcripts as fixtures. Use synthetic or anonymised data. The dogfood ledger is public and holds only percentages, token counts, task metadata and short notes.
- Third-party tools (Superpowers, Graphify): detect them and read their output files only. Never copy their code, never write into their files, and say "works with", never "official".
- Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
- The build plan, sprint rules (§5) and measurement protocol (§6.1) are in [ROADMAP.md](ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).
