# Cold-start heuristics

navitok uses this table only until it has your own history (ROADMAP §10.1: fewer than 5 learned sessions). After that, `scripts/calibrate.py` learns a range per task type from your history (a type needs at least 3 task samples), and that range replaces the row below. Types without enough samples keep this table.

> **Seed data: one maintainer, one plan (Pro), one project.** The table comes from the dogfood ledger (`docs/dogfood/ledger.jsonl`, sprints v0.0–v0.2 of navitok itself). It improves the cold start. It does not replace per-user calibration.

All numbers are **% of one 5-hour session on Pro**. Other plans scale them with the multipliers in [`plans.md`](plans.md). `scripts/estimate.py` holds the same numbers, and a test keeps the two in sync.

## Base range by task type (size S, Pro)

| Type | Low | High | Seed evidence |
|---|---|---|---|
| config | 0.3 | 1.0 | v0.0: config + scaffold + docs, 5 tasks, ~1% in total |
| docs | 0.3 | 1.0 | v0.0 docs tasks; README/CHANGELOG edits |
| migration | 0.3 | 1.0 | v0.2-t5: two-line ledger migration |
| scaffold | 0.3 | 1.5 | v0.0-t3: 5 files, 154 lines, inside the ~1% sprint |
| wrapup | 0.5 | 1.5 | CHANGELOG, dogfood record, commit, handoff in every sprint |
| research | 0.5 | 2.0 | v0.1, v0.2: one docs fetch through a subagent costs 60–110k tokens |
| test | 0.5 | 2.0 | v0.1-t5, v0.2-t4: ~200–260 lines of tests |
| refactor | 0.5 | 2.5 | No seed data yet; placed between test and feature |
| feature | 1.0 | 3.0 | v0.1-t4, v0.2-t2/t3: ~250–290 lines of stdlib Python |
| bugfix | 1.0 | 4.0 | v0.2: one unplanned debugging loop drove most of an 8% sprint |

**Unknown type → widest range:** the lowest Low and the highest High of the table (0.3–4.0), with confidence 10.

## Size multiplier

| Size | Multiplier |
|---|---|
| S | 1.0 |
| M | 2.5 |
| L | 6.0 |

Unknown or missing size is priced as **L** (confidence at most 20). A wrong guess on the high side wastes some of the limit. A wrong guess on the low side gets you cut off.

## File-count adjustment

The first 3 files are free. Each further file adds **0.1** to the multiplier, up to **2.0** in total. A missing `files` value counts as no adjustment.

## Execution style (v0.10)

| Execution | Multiplier |
|---|---|
| inline | ×1.0 |
| subagent | ×1.5 |

`subagent` is set when a Superpowers plan will run with subagent-driven-development, which starts a fresh implementer context and a fresh reviewer context for each task. **×1.5 is an unmeasured assumption.** No dogfood sprint has used that workflow yet. On Pro in strict mode, navitok recommends inline execution (`superpowers:executing-plans`) instead.

## Totals, threshold, confidence

- **Total** = sum of task lows and sum of task highs. Ranges are not pooled, so the total stays conservative.
- **Threshold:** fixed at **90%** of a session during the cold start. A list fits one session when the total high is ≤ 90.
- **Confidence (0–100):** 30 for a known type and size, 20 for an unknown size, 10 for an unknown type. The total's confidence is the mean weighted by each task's high. These values are low on purpose: the seed is three sprints from one person.

## What the seed taught

- The first two sprints were overestimated 3–10×. Pure scaffolding and docs are cheap. Hence the low S ranges.
- Cost is driven less by lines written than by **context**: re-reading large files, long conversations (cache reads grew to 7.3M tokens in v0.2) and big docs fetches.
- Unplanned debugging is the largest single risk. That is why `bugfix` has the widest range.
