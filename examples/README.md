# Examples

- `tasks.json`: input for `scripts/estimate.py` (`python3 scripts/estimate.py examples/tasks.json`).
- `pro-strict/`: a small CLI project planned for **Pro, strict mode**: four releases, each priced well under the 90% cold-start threshold.
- `max5x-flex/`: the same project for **Max 5x, flex mode**. The larger limit lets the same tasks go into two releases.

Each folder holds the `plan.json` that Claude writes in `/navitok:plan` and the `ROADMAP.md` that `plan.py` renders from it. The estimates are cold-start ranges (confidence 30); they narrow as navitok calibrates from your own history.

To regenerate one, copy its `plan.json` into `<dir>/.navitok/` and run:

```bash
python3 scripts/plan.py config --plan pro --mode strict --project-dir <dir>   # or max5x / flex
python3 scripts/plan.py price --project-dir <dir>
```
