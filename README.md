# navitok

> Navigation for your tokens.

navitok is a Claude Code plugin that plans a project into session-sized releases. Each release is sized to fit your plan's 5-hour session and weekly usage limits. navitok keeps the schedule current as your real usage changes, including usage outside Claude Code, and it calibrates its estimates from your own history, so a prompt is never cut off halfway.

**Status: early development (v0.0.1).** The plugin loads, but it does not plan or estimate anything yet. See [ROADMAP.md](ROADMAP.md) for the build plan.

## Try the development version

```bash
git clone <this-repo> navitok
claude --plugin-dir ./navitok
```

## Development

Scripts use the Python 3.10+ standard library only.

```bash
python3 -m unittest discover -s tests -v
```

On Windows, use `python` if `python3` is not available.

## License

MIT. See [LICENSE](LICENSE).
