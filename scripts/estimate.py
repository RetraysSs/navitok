"""navitok estimator v1 (cold start).

Turns a task list into cost ranges, as % of one 5-hour session on the
user's plan. Stdlib only, deterministic, never calls the model.

The numbers below are documented in skills/navitok/references/heuristics.md
and skills/navitok/references/plans.md. A test keeps them in sync.

Input (JSON): either a list of tasks, or {"plan": "pro", "tasks": [...]}.
Each task: {"id": "t1", "type": "feature", "size": "S", "files": 2}.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# Fixed cold-start stop threshold (ROADMAP §10.1, n < 5).
THRESHOLD = 90.0

# Base range for a size-S task on Pro, in session %. Seeded from the dogfood
# ledger (v0.0-v0.2, one maintainer). See heuristics.md.
BASE = {
    "config":    (0.3, 1.0),
    "docs":      (0.3, 1.0),
    "migration": (0.3, 1.0),
    "scaffold":  (0.3, 1.5),
    "wrapup":    (0.5, 1.5),
    "research":  (0.5, 2.0),
    "test":      (0.5, 2.0),
    "refactor":  (0.5, 2.5),
    "feature":   (1.0, 3.0),
    "bugfix":    (1.0, 4.0),
}

SIZE = {"S": 1.0, "M": 2.5, "L": 6.0}
# Unknown or missing size is priced as the largest size (safety first).
UNKNOWN_SIZE = "L"

# Files beyond FILES_FREE add FILES_STEP to the multiplier, capped at FILES_CAP.
FILES_FREE = 3
FILES_STEP = 0.1
FILES_CAP = 2.0

# Plan multipliers relative to Pro (nominal; see plans.md). For "api" there is
# no 5-hour window: numbers are Pro-equivalent units and no fit check applies.
PLANS = {"pro": 1.0, "max5x": 0.2, "max20x": 0.05, "api": 1.0}
PLAN_ALIASES = {"max 5x": "max5x", "max-5x": "max5x", "max_5x": "max5x",
                "max 20x": "max20x", "max-20x": "max20x", "max_20x": "max20x"}

# Cold-start confidence (0-100). Low on purpose: one maintainer's data.
CONF_KNOWN = 30
CONF_UNKNOWN_SIZE = 20
CONF_UNKNOWN_TYPE = 10


class EstimateError(ValueError):
    pass


def widest_range():
    return (min(lo for lo, _ in BASE.values()), max(hi for _, hi in BASE.values()))


def normalize_plan(plan):
    if plan is None:
        return "pro"
    key = str(plan).strip().lower()
    key = PLAN_ALIASES.get(key, key)
    if key not in PLANS:
        raise EstimateError(f"unknown plan {plan!r}; expected one of {sorted(PLANS)}")
    return key


def files_factor(files):
    if files is None:
        return 1.0
    if isinstance(files, bool) or not isinstance(files, int) or files < 0:
        raise EstimateError(f"files must be a non-negative integer, got {files!r}")
    return min(FILES_CAP, 1.0 + FILES_STEP * max(0, files - FILES_FREE))


def estimate_task(task, plan="pro"):
    """Return a dict with the task's range (lo, hi) and confidence."""
    if not isinstance(task, dict):
        raise EstimateError(f"task must be an object, got {task!r}")
    plan = normalize_plan(plan)
    ttype = str(task.get("type") or "").strip().lower()
    size = str(task.get("size") or "").strip().upper()
    notes = []

    if ttype in BASE:
        lo, hi = BASE[ttype]
        conf = CONF_KNOWN
    else:
        lo, hi = widest_range()
        conf = CONF_UNKNOWN_TYPE
        notes.append("unknown type: widest range")

    if size not in SIZE:
        size_used = UNKNOWN_SIZE
        conf = min(conf, CONF_UNKNOWN_SIZE)
        notes.append(f"unknown size: priced as {UNKNOWN_SIZE}")
    else:
        size_used = size

    mult = SIZE[size_used] * files_factor(task.get("files")) * PLANS[plan]
    return {
        "id": task.get("id"),
        "type": ttype or None,
        "size": size_used,
        "files": task.get("files"),
        "est_pct": [round(lo * mult, 2), round(hi * mult, 2)],
        "confidence": conf,
        "notes": notes,
    }


def estimate(tasks, plan="pro"):
    """Estimate a task list. Totals are plain sums (no variance pooling)."""
    if not isinstance(tasks, list):
        raise EstimateError("tasks must be a list")
    plan = normalize_plan(plan)
    rows = [estimate_task(t, plan) for t in tasks]
    lo = round(sum(r["est_pct"][0] for r in rows), 2)
    hi = round(sum(r["est_pct"][1] for r in rows), 2)
    weight = sum(r["est_pct"][1] for r in rows)
    conf = round(sum(r["confidence"] * r["est_pct"][1] for r in rows) / weight) if weight else 0
    limited = plan != "api"
    return {
        "plan": plan,
        "threshold": THRESHOLD,
        "tasks": rows,
        "total_pct": [lo, hi],
        "confidence": conf,
        "fits_one_session": (hi <= THRESHOLD) if limited else None,
        "sessions_needed": max(1, math.ceil(hi / THRESHOLD)) if limited and rows else None,
    }


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return None, data
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return data.get("plan"), data["tasks"]
    raise EstimateError("input must be a task list or an object with a 'tasks' list")


def _fmt(x):
    return f"{x:.1f}"


def render(result):
    unit = "Pro-equivalent units (API: no session limit)" if result["plan"] == "api" \
        else f"% of one 5-hour session on {result['plan']}"
    head = ("Task", "Type", "Size", "Files", "Estimate", "Conf", "Notes")
    body = []
    for r in result["tasks"]:
        lo, hi = r["est_pct"]
        body.append((str(r["id"] or "-"), r["type"] or "?", r["size"],
                     "-" if r["files"] is None else str(r["files"]),
                     f"{_fmt(lo)}-{_fmt(hi)}", str(r["confidence"]), "; ".join(r["notes"])))
    lo, hi = result["total_pct"]
    body.append(("TOTAL", "", "", "", f"{_fmt(lo)}-{_fmt(hi)}", str(result["confidence"]), ""))
    widths = [max(len(row[i]) for row in [head] + body) for i in range(len(head))]

    def line(row):
        return "  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip()

    out = [f"navitok estimate ({unit})", "", line(head),
           "  ".join("-" * w for w in widths)]
    out += [line(r) for r in body[:-1]]
    out += ["  ".join("-" * w for w in widths), line(body[-1]), ""]
    if result["fits_one_session"] is None:
        out.append("No 5-hour session limit on the API plan; no fit check.")
    else:
        verdict = "yes" if result["fits_one_session"] else "no"
        out.append(f"Threshold: {result['threshold']:.0f}%. Fits one session: {verdict}"
                   f" (sessions needed: {result['sessions_needed']}).")
    out.append("Cold-start heuristics (one maintainer's data). Confidence is 0-100.")
    return "\n".join(out)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok cold-start estimator")
    ap.add_argument("tasks", help="JSON file: task list or {plan, tasks}")
    ap.add_argument("--plan", help="pro | max5x | max20x | api (overrides the file)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = ap.parse_args(argv)
    try:
        file_plan, tasks = load(args.tasks)
        result = estimate(tasks, args.plan or file_plan)
    except (OSError, json.JSONDecodeError, EstimateError) as exc:
        print(f"estimate: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
