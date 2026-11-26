"""navitok calibration (ROADMAP v0.7, §10.1).

Learns from history.jsonl. Deterministic, stdlib only, never calls the model.

- Estimation error is computed on LOCAL usage only (external.py). Usage
  outside Claude Code never counts as error.
- Per-task actuals are rarely known (manual records and hooks see only the
  session). A session's local % is split across its tasks in proportion to
  their estimate midpoints, then normalised to a size-S, Pro, <=3-file task
  so it can be compared with the cold-start table.
- Outlier guard: sessions with missing data, debugging spirals or large
  unexplained external usage are flagged, down-weighted and not counted in n.
- Weights: recent sessions weigh more (half-life HALF_LIFE records); records
  whose model or plan differs from the latest one are down-weighted.
- Threshold (§10.1): 90 while n < 5, else 100 - 1.5 max_step - 2 sigma_err,
  clamped to [90, 98]. sigma_err is the weighted standard deviation of
  (local actual - estimate midpoint) per session.
  Confidence: min(100, 5n) x (1 - min(1, sigma_err / 10)).

  calibrate.py update [--project-dir DIR]   write .navitok/calibration.json
  calibrate.py report --history PATH        print the calibration as JSON
  calibrate.py status [--project-dir DIR]   /navitok:status text
  calibrate.py hook                          SessionStart: update, silent
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate  # noqa: E402
import external  # noqa: E402
import ledger  # noqa: E402
import usage_read  # noqa: E402

SCHEMA = 1
CALIBRATION_FILE = "calibration.json"
MIN_N = 5               # §10.1
MIN_TYPE_SAMPLES = 3    # a type needs this many task samples to replace the cold start
HALF_LIFE = 10.0        # records
CHANGE_WEIGHT = 0.3     # model or plan differs from the latest record
OUTLIER_WEIGHT = 0.2
MAX_STEP_WINDOW = 10    # "last N sessions"
SPIRAL_FACTOR = 2.0     # local actual > 2x the summed upper estimates
SPIRAL_MIN_PCT = 3.0
EXTERNAL_OUTLIER_PCT = 5.0
THRESHOLD_MIN, THRESHOLD_MAX = 90.0, 98.0


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _wstats(pairs):
    """Weighted mean and standard deviation of [(value, weight)]."""
    pairs = [(v, w) for v, w in pairs if w > 0]
    tw = sum(w for _, w in pairs)
    if not pairs or tw <= 0:
        return None, None
    mean = sum(v * w for v, w in pairs) / tw
    var = sum(w * (v - mean) ** 2 for v, w in pairs) / tw
    return mean, math.sqrt(var)


def size_factor(task, plan):
    size = str(task.get("size") or "").upper()
    files = task.get("files", task.get("files_touched"))
    try:
        ff = estimate.files_factor(files)
    except estimate.EstimateError:
        ff = 1.0
    try:
        pm = estimate.PLANS[estimate.normalize_plan(plan)]
    except estimate.EstimateError:
        pm = 1.0
    return estimate.SIZE.get(size, estimate.SIZE[estimate.UNKNOWN_SIZE]) * ff * pm


def _priced_tasks(record):
    return [t for t in record.get("tasks") or []
            if isinstance(t.get("est_pct"), list) and len(t["est_pct"]) == 2
            and all(_num(x) for x in t["est_pct"])]


def session_rows(records, ppt):
    """One row per record: local actual, estimate, error, outlier reasons."""
    rows = []
    for r in records:
        tasks = _priced_tasks(r)
        est_mid = sum((t["est_pct"][0] + t["est_pct"][1]) / 2 for t in tasks)
        est_hi = sum(t["est_pct"][1] for t in tasks)
        local = external.local_pct(r, ppt)
        ext, explained = external.session_external(r, ppt)
        reasons = []
        if r.get("outlier") is True:
            reasons.append("flagged")
        if local is None or not tasks:
            reasons.append("missing data")
        else:
            if local > SPIRAL_FACTOR * est_hi and local > SPIRAL_MIN_PCT:
                reasons.append("debugging spiral")
        if ext is not None and not explained and ext > max(EXTERNAL_OUTLIER_PCT, 2 * (local or 0)):
            reasons.append("large unexplained external usage")
        rows.append({"record": r, "tasks": tasks, "ts_end": r.get("ts_end"),
                     "model": r.get("model"), "plan": r.get("plan"),
                     "group": estimate.helper_group(r.get("helpers")),
                     "local_pct": local, "external_pct": ext, "est_mid": est_mid,
                     "error": None if local is None or not tasks else local - est_mid,
                     "outlier": reasons})
    return rows


def _weights(rows):
    """Recency x model/plan change x outlier weight, newest record first."""
    ordered = sorted(rows, key=lambda x: x["ts_end"] or "", reverse=True)
    ref = next((x for x in ordered if x["error"] is not None), ordered[0] if ordered else None)
    for i, row in enumerate(ordered):
        w = 0.5 ** (i / HALF_LIFE)
        if ref is not None and ((row["model"] and ref["model"] and row["model"] != ref["model"])
                                or (row["plan"] and ref["plan"] and row["plan"] != ref["plan"])):
            w *= CHANGE_WEIGHT
        if row["outlier"]:
            w *= OUTLIER_WEIGHT
        row["weight"] = w
    return ordered


def threshold_from(n, max_step, sigma_err):
    if n < MIN_N or max_step is None or sigma_err is None:
        return THRESHOLD_MIN
    t = 100.0 - 1.5 * max_step - 2.0 * sigma_err
    return min(THRESHOLD_MAX, max(THRESHOLD_MIN, t))


def confidence_from(n, sigma_err):
    if sigma_err is None:
        return 0
    return round(min(100, n * 5) * (1 - min(1.0, sigma_err / 10.0)))


def calibrate(records, now=None):
    """Pure. Return the calibration dict (§10.1, §10.3)."""
    now = now or datetime.now(timezone.utc)
    records = [r for r in records if r.get("ts_end")]
    ppt = external.pct_per_token(records)
    ratio, ratio_learned = external.weekly_ratio(records)
    rows = _weights(session_rows(records, ppt))
    data = [x for x in rows if x["error"] is not None]
    clean = [x for x in data if not x["outlier"]]
    n = len(clean)
    _, sigma = _wstats([(x["error"], x["weight"]) for x in data])

    # max_step: a recorded per-task max step if any, else the largest
    # apportioned task actual (a task is an upper bound on one step).
    steps = []
    by_type = {}
    for x in sorted(clean, key=lambda x: x["ts_end"] or "", reverse=True)[:MAX_STEP_WINDOW]:
        recorded = [t["max_step_pct"] for t in x["tasks"] if _num(t.get("max_step_pct"))]
        steps.extend(recorded)
        if not recorded and x["est_mid"] > 0:
            steps.extend(x["local_pct"] * ((t["est_pct"][0] + t["est_pct"][1]) / 2) / x["est_mid"]
                         for t in x["tasks"])
    for x in data:
        if x["est_mid"] <= 0:
            continue
        group = by_type.setdefault(x["group"], {})
        for t in x["tasks"]:
            actual = t.get("actual_pct")
            if not _num(actual):
                actual = x["local_pct"] * ((t["est_pct"][0] + t["est_pct"][1]) / 2) / x["est_mid"]
            ttype = str(t.get("type") or "").lower() or "unknown"
            base = actual / size_factor(t, x["plan"])
            group.setdefault(ttype, []).append((base, x["weight"]))
    max_step = max(steps) if steps else None
    threshold = threshold_from(n, max_step, sigma)
    conf = confidence_from(n, sigma) if n else 0

    # Per-type ranges are learned per helper group (v0.11): sessions helped by
    # Graphify never price unhelped tasks, and vice versa. Each group needs
    # MIN_N clean sessions of its own.
    groups = {}
    for g in sorted(set(by_type) | {x["group"] for x in clean} | {estimate.PLAIN_GROUP}):
        n_g = sum(1 for x in clean if x["group"] == g)
        types_g = {}
        for ttype, pairs in sorted(by_type.get(g, {}).items()):
            mean, std = _wstats(pairs)
            entry = {"n": len(pairs), "mean": _r(mean), "std": _r(std), "est_pct": None}
            if n_g >= MIN_N and len(pairs) >= MIN_TYPE_SAMPLES and mean is not None:
                lo = max(0.05, min(mean - std, 0.7 * mean))
                hi = max(mean + 1.5 * std, 1.3 * mean, lo + 0.1)
                entry["est_pct"] = [_r(lo), _r(hi)]
            types_g[ttype] = entry
        groups[g] = {"n": n_g, "learned": n_g >= MIN_N, "types": types_g}
    types = groups[estimate.PLAIN_GROUP]["types"]

    prof = external.profile(records, now=now, ratio=ratio)
    return {
        "schema": SCHEMA,
        "computed_at": usage_read.iso(now),
        "n": n,
        "n_records": len(records),
        "learned": n >= MIN_N,
        "pct_per_token": ppt,
        "token_weights": external.TOKEN_WEIGHTS,
        "weekly_per_session": _r(ratio, 4),
        "weekly_per_session_learned": ratio_learned,
        "sigma_err": _r(sigma),
        "max_step": _r(max_step),
        "threshold": _r(threshold),
        "confidence": conf,
        "types": types,
        "helper_groups": groups,
        "external": prof,
        "sessions": [{"ts_end": x["ts_end"], "release": x["record"].get("release"),
                      "local_pct": _r(x["local_pct"]), "external_pct": _r(x["external_pct"]),
                      "est_mid": _r(x["est_mid"]), "error": _r(x["error"]), "group": x["group"],
                      "weight": _r(x["weight"], 3), "outlier": x["outlier"]}
                     for x in sorted(rows, key=lambda x: x["ts_end"] or "")],
    }


# --- files ----------------------------------------------------------------------

def _nav(project_dir):
    return Path(project_dir) / ".navitok"


def load(project_dir="."):
    try:
        data = json.loads((_nav(project_dir) / CALIBRATION_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def update(project_dir=".", now=None):
    nav = _nav(project_dir)
    cal = calibrate(ledger.read_all(nav / "history.jsonl"), now)
    tmp = nav / (CALIBRATION_FILE + ".tmp")
    tmp.write_text(json.dumps(cal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, nav / CALIBRATION_FILE)
    return cal


# --- /navitok:status --------------------------------------------------------------

def _f(x, unit="%"):
    return "unknown" if x is None else f"{float(x):.1f}".rstrip("0").rstrip(".") + unit


def status_text(project_dir="."):
    import plan as planmod
    import handoff
    nav = _nav(project_dir)
    cal = load(project_dir) or {}
    try:
        sched = json.loads((nav / "schedule.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sched = {}
    cfg = planmod.load_config(project_dir)
    threshold = sched.get("threshold") if _num(sched.get("threshold")) else planmod.threshold_for(cfg)
    used = (sched.get("session") or {}).get("used_pct")
    stale = " (reading stale: give a /usage reading to refresh)" if sched.get("usage_stale") else ""
    left = None if used is None else max(0.0, threshold - used)
    lines = ["navitok status",
             f"- Session: {_f(used)} used, {_f(left)} left before the {_f(threshold)} threshold{stale}"]
    n = cal.get("n", 0)
    if cal.get("learned"):
        lines.append(f"- Calibration: {n} learned sessions, confidence {cal.get('confidence')}/100, "
                     f"error spread ±{_f(cal.get('sigma_err'))}, largest step {_f(cal.get('max_step'))}")
    else:
        lines.append(f"- Calibration: cold start ({n} of {MIN_N} sessions learned), "
                     f"threshold fixed at 90%, confidence {cal.get('confidence', 0)}/100")
    week = sched.get("week") or {}
    ext = cal.get("external") or {}
    if ext.get("known") and ext.get("weekly"):
        wk = ext["weekly"]
        lines.append(f"- Week: {_f(week.get('used_pct'))} used; external usage this week "
                     f"{_f(wk['this_week'])} (typical week P80 {_f(wk['p80'])}), "
                     f"{_f(ext.get('reserve_pct'))} reserved")
    else:
        lines.append(f"- Week: {_f(week.get('used_pct'))} used; external usage unknown "
                     f"(needs {external.MIN_SESSIONS} sessions with token data)")
    try:
        _, plan = planmod._load_plan(project_dir)
        rel, task, idx = handoff.next_task(plan)
    except (OSError, ValueError, planmod.PlanError):
        rel = task = None
    if rel is None:
        lines.append("- Next: no plan, or every release is done")
    else:
        fits = sched.get("fits_today")
        verdict = {True: "fits this session", False: "does not fit this session",
                   None: "fit unknown"}[fits if fits in (True, False) else None]
        rng = sched.get("current_remaining_pct") or rel.get("est_pct") or [0, 0]
        nxt = f", next task {task['id']} {task.get('title', '')}" if task else ""
        lines.append(f"- Next release: {rel['id']} {rel.get('title', '')}, "
                     f"{_f(rng[0], '')}–{_f(rng[1])} left, {verdict}{nxt}")
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------------------

def hook_main(stdin=None):
    """SessionStart: refresh calibration.json. Silent, never fails."""
    try:
        stdin = stdin or sys.stdin
        raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read().encode("utf-8")
        payload = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
        project = payload.get("cwd") or os.getcwd()
        if (_nav(project) / "history.jsonl").is_file():
            update(project)
    except Exception:
        pass
    return 0


def main(argv=None):
    import argparse
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok calibration")
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("update")
    st = sub.add_parser("status")
    for p in (up, st):
        p.add_argument("--project-dir", default=".")
    rp = sub.add_parser("report")
    rp.add_argument("--history", required=True)
    rp.add_argument("--summary", action="store_true", help="omit the per-session rows")
    sub.add_parser("hook")
    args = ap.parse_args(argv)
    if args.cmd == "hook":
        return hook_main()
    try:
        if args.cmd == "update":
            cal = update(args.project_dir)
            print(f"Calibrated from {cal['n_records']} records: n={cal['n']}, "
                  f"threshold {cal['threshold']}%, confidence {cal['confidence']}")
        elif args.cmd == "report":
            cal = calibrate(ledger.read_all(args.history))
            if args.summary:
                cal.pop("sessions")
            print(json.dumps(cal, indent=2, ensure_ascii=False))
        else:
            print(status_text(args.project_dir))
        return 0
    except OSError as exc:
        print(f"calibrate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
