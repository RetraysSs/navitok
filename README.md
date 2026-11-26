# navitok

> Navigation for your tokens.

navitok is a Claude Code plugin that plans a project into session-sized releases. Each release is sized to fit your plan's 5-hour session and weekly usage limits. navitok keeps the schedule current as your real usage changes, including usage outside Claude Code, and it calibrates its estimates from your own history, so a prompt is never cut off halfway.

**Status: early development (v0.0.1).** The plugin loads, but it does not plan or estimate anything yet. See [ROADMAP.md](ROADMAP.md) for the build plan.

## Try the development version

```bash
git clone <this-repo> navitok
claude --plugin-dir ./navitok
```

## Terminal panel

A live view of your releases, session and weekly usage, external usage and calibration, for a second terminal. It costs zero tokens and reads local files only.

```bash
python3 <plugin>/scripts/watch.py            # live, q to quit (python on Windows)
python3 <plugin>/scripts/watch.py --once     # one plain frame
alias navitok-watch='python3 <plugin>/scripts/watch.py'
```

It uses `curses` where available. Otherwise, on Windows for example, it redraws with ANSI escape codes, also in the legacy console.

## Works with Superpowers

If you plan with [Superpowers](https://github.com/obra/superpowers) (brainstorming → writing-plans), navitok can import the plan file and turn it into versioned releases that each fit one session, with a schedule. The plan file is only read, never changed.

```bash
python3 <plugin>/scripts/integrations/superpowers.py detect
python3 <plugin>/scripts/integrations/superpowers.py ingest [--execution inline|subagent]
```

navitok works with Superpowers. It is not an official integration, and everything works without it.

## Works with Graphify

If the project has a [Graphify](https://github.com/Graphify-Labs/graphify) knowledge graph (`graphify-out/graph.json`), navitok reads it to estimate which files and how many lines each task touches, and prices tasks from that. Without a graph it can add a separately priced "build the map" release. Graphify's files are only read, never changed, and Graphify is never run or installed by navitok.

```bash
python3 <plugin>/scripts/integrations/graphify.py detect
python3 <plugin>/scripts/integrations/graphify.py apply        # scope plan.json tasks
python3 <plugin>/scripts/integrations/graphify.py map [--apply]
```

Sessions with and without a graph are calibrated separately. navitok works with Graphify. It is not an official integration, and everything works without it.

## Development

Scripts use the Python 3.10+ standard library only.

```bash
python3 -m unittest discover -s tests -v
```

On Windows, use `python` if `python3` is not available.

## License

MIT. See [LICENSE](LICENSE).
