# Plan profiles

navitok models every plan as **percentages**: % of the 5-hour session limit and % of the weekly limit, as `/usage` and the statusline show them. Anthropic does not publish fixed token limits for these plans, and the limits can change. navitok therefore makes **no absolute token claims** and never converts a percentage into a token budget.

Multipliers scale the Pro-based heuristics in [`heuristics.md`](heuristics.md). They follow the plans' nominal names ("5x", "20x" the usage of Pro). They are a cold-start guess, not a measurement. Your own history replaces them once navitok has calibrated (v0.7).

| Plan | `--plan` key | Multiplier vs Pro | 5-hour session | Weekly limit | Notes |
|---|---|---|---|---|---|
| Pro | `pro` | 1.0 | yes | yes | Seed data comes from this plan. |
| Max 5x | `max5x` | 0.2 | yes | yes | A task costs about a fifth of the Pro session %. |
| Max 20x | `max20x` | 0.05 | yes | yes | Small tasks round to fractions of a percent. |
| API | `api` | 1.0 (units only) | no | no | Pay per token. Estimates are shown in Pro-equivalent units for relative sizing, and no fit check applies. |

## Rules

- The cold-start stop threshold is **90%** of a session on every limited plan. The ceiling is 98%, reached only through calibration (ROADMAP §10.1).
- Usage outside Claude Code (claude.ai, other machines) shares the same limits. navitok measures it separately and never counts it as estimation error.
- The weekly limit is tracked as a % as well. Weekly packing arrives with the schedule engine (v0.5).
