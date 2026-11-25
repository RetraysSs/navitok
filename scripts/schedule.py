"""navitok schedule engine: plan + current usage -> .navitok/schedule.json.

Deterministic, stdlib only, never calls the model (ROADMAP §4.1-4.2).

  Tier 0  recompute the schedule from the latest usage reading (every prompt).
  Tier 1  print ONE line for Claude only when the fit status changes.
  Tier 2  detect replan triggers (§10.4). They are only *offered* at the next
          task boundary; this script never edits plan.json.

  schedule.py recompute [--project-dir DIR] [--session-pct N] [--weekly-pct N]
  schedule.py show      [--project-dir DIR]
  schedule.py hook      # UserPromptSubmit: reads hook JSON on stdin, prints the
                        # Tier-1 line (or nothing), always exits 0

`--session-pct` / `--weekly-pct` override the account reading. They exist to
simulate usage jumps (tests, acceptance) and to feed a manual /usage reading.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan as planmod  # noqa: E402
import usage_read  # noqa: E402

SCHEMA = 1
SNAPSHOT_FILE = "usage_snapshot.json"  # written by the statusline (v0.8)
# Cold start: weekly % consumed per session %. Seeded from the dogfood ledger
# (one maintainer, Pro: ~34 session-% moved the weekly % by ~5). Overridable
# with config.json "weekly_per_session"; calibrated from history in v0.7.
WEEKLY_PER_SESSION = 0.15
OVERRUN_FACTOR = 1.3  # §10.4: last 2 tasks > upper estimates by more than 30%
DONE = ("done", "skipped")


def _now():
    return datetime.now(timezone.utc)


def _r(x):
    return round(float(x), 2)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# --- inputs -----------------------------------------------------------------

def remaining_cost(release):
    """[lo, hi] of the tasks still to do in a release (est_pct must be present)."""
    lo = hi = 0.0
    for t in release["tasks"]:
        if t.get("status", "todo") in DONE:
            continue
        est = t.get("est_pct") or [0, 0]
        lo, hi = lo + est[0], hi + est[1]
    return [_r(lo), _r(hi)]


def _priced(plan, threshold, cfg=None):
    """Use plan.json's prices. If any task is unpriced, price a copy in memory."""
    if all(isinstance(t.get("est_pct"), list) for r in plan["releases"] for t in r["tasks"]):
        return plan
    priced, _ = planmod.price(copy.deepcopy(plan), threshold, planmod.learned_types(cfg or {}))
    return priced


def _effective_pct(pct, resets_at, now):
    """A reading taken before its window reset no longer applies: the window is fresh."""
    if pct is None:
        return None
    reset = usage_read.parse_ts(resets_at)
    if reset is not None and reset <= now:
        return 0.0
    return float(pct)


def fingerprint(plan):
    key = [plan.get("plan"), plan.get("mode"),
           [(r["id"], [t["id"] for t in r["tasks"]]) for r in plan["releases"]]]
    return hashlib.sha256(json.dumps(key).encode("utf-8")).hexdigest()[:16]


# --- Tier 0: compute ----------------------------------------------------------

def compute(plan, cfg, reading, prev=None, now=None):
    """Return a fresh schedule dict (§10.7). Pure: no file access."""
    now = now or _now()
    threshold = planmod.threshold_for(cfg)
    mode = plan.get("mode", "strict")
    limited = plan.get("plan") != "api"
    plan = _priced(plan, threshold, cfg)
    cal = cfg.get(planmod.CALIBRATION_KEY) if isinstance(cfg.get(planmod.CALIBRATION_KEY), dict) else {}
    ratio = cfg.get("weekly_per_session")
    if not (_num(ratio) and ratio > 0):  # explicit config wins, then the learned ratio
        ratio = cal.get("weekly_per_session") if cal.get("weekly_per_session_learned") else None
    ratio = float(ratio) if _num(ratio) and ratio > 0 else WEEKLY_PER_SESSION
    # §10.3: reserve the learned P80 external weekly usage (unknown -> None, nothing reserved)
    ext = cal.get("external") if isinstance(cal.get("external"), dict) else {}
    reserve = float(ext["reserve_pct"]) if ext.get("known") and _num(ext.get("reserve_pct")) else None

    reading = reading or {}
    s_pct = _effective_pct(reading.get("session_pct"), reading.get("session_resets_at"), now)
    w_pct = _effective_pct(reading.get("weekly_pct"), reading.get("weekly_resets_at"), now)
    known = s_pct is not None

    pending = [r for r in plan["releases"] if any(t.get("status", "todo") not in DONE for t in r["tasks"])]
    current = pending[0] if pending else None
    cur_cost = remaining_cost(current) if current else [0.0, 0.0]

    if not limited:
        fits = None
    elif current is None or not known:
        fits = None if current else True
    else:
        fits = s_pct + cur_cost[1] <= threshold

    # Session + weekly packing. Releases are placed greedily in order: a release
    # joins the open session if it fits what is left of it, else opens a new one.
    week_cap = threshold - (reserve or 0.0)
    placement = []
    week, session_idx = 1, 0
    session_left = threshold - (s_pct or 0.0)
    week_used = w_pct or 0.0
    for rel in pending:
        cost = remaining_cost(rel)
        entry = {"release": rel["id"], "est_pct": cost, "week": 1, "session": "current",
                 "extra": False, "over": False}
        if limited:
            new_session = cost[1] > session_left
            if new_session:
                session_idx += 1
                session_left = threshold
            entry["over"] = cost[1] > threshold
            w_cost = cost[1] * ratio
            if week_used + w_cost > week_cap:
                if mode == "strict":  # overflow moves to the next week, in a fresh session
                    week += 1
                    week_used = 0.0
                    if not new_session:
                        session_idx += 1
                    session_left = threshold
                    entry["first_of_week"] = True
                else:  # flex: continue on extra usage
                    entry["extra"] = True
            session_left -= cost[1]
            week_used += w_cost
            entry["week"] = week
            entry["session"] = "current" if session_idx == 0 else ("next" if session_idx == 1 else f"+{session_idx}")
        placement.append(entry)

    w_reset = usage_read.parse_ts(reading.get("weekly_resets_at"))
    final_week = placement[-1]["week"] if placement else 1
    final_end = usage_read.iso(w_reset + timedelta(days=7 * (final_week - 1))) if w_reset else None

    fp = fingerprint(plan)
    base = (prev or {}).get("baseline") or {}
    if base.get("fingerprint") != fp or (base.get("final_week_ends_at") is None and final_end):
        base = {"fingerprint": fp, "final_week_ends_at": final_end}

    sched = {
        "schema": SCHEMA,
        "computed_at": usage_read.iso(now),
        "plan": plan.get("plan"),
        "mode": mode,
        "threshold": threshold,
        "usage_source": reading.get("source"),
        "usage_stale": bool(reading.get("stale")) if reading else None,
        "session": {"used_pct": None if s_pct is None else _r(s_pct),
                    "resets_at": reading.get("session_resets_at")},
        "week": {"used_pct": None if w_pct is None else _r(w_pct), "external_reserved_pct": None if reserve is None else _r(reserve),
                 "resets_at": reading.get("weekly_resets_at"), "per_session_ratio": ratio},
        "current_release": current["id"] if current else None,
        "current_remaining_pct": cur_cost,
        "fits_today": fits,
        "placement": placement,
        "final_week_ends_at": final_end,
        "baseline": base,
    }
    sched["replan"] = replan_triggers(plan, cfg, sched)
    return sched


# --- Tier 2: replan triggers --------------------------------------------------

def replan_triggers(plan, cfg, sched):
    """§10.4. Returns a list of {"id", "reason"}. Detection only, never acts."""
    out = []
    threshold = sched["threshold"]
    limited = plan.get("plan") != "api"
    cur = sched["current_release"]
    if limited and cur and sched["current_remaining_pct"][1] > threshold:
        out.append({"id": "release_too_big",
                    "reason": f"{cur} needs up to {sched['current_remaining_pct'][1]:.1f}%, "
                              f"more than one session ({threshold:.0f}%)"})
    done = [t for r in plan["releases"] for t in r["tasks"]
            if t.get("status") == "done" and isinstance(t.get("actual_pct"), (int, float))
            and isinstance(t.get("est_pct"), list)]
    if len(done) >= 2:
        last = done[-2:]
        actual = sum(t["actual_pct"] for t in last)
        upper = sum(t["est_pct"][1] for t in last)
        if upper > 0 and actual > OVERRUN_FACTOR * upper:
            out.append({"id": "overrun",
                        "reason": f"last 2 tasks cost {actual:.1f}% vs {upper:.1f}% upper estimate"})
    base_end = usage_read.parse_ts(sched["baseline"].get("final_week_ends_at"))
    now_end = usage_read.parse_ts(sched.get("final_week_ends_at"))
    if limited and base_end and now_end and now_end > base_end + timedelta(days=7):
        out.append({"id": "slipped",
                    "reason": f"final release slipped more than a week (now ends {now_end.date()}, "
                              f"planned {base_end.date()})"})
    changed = [k for k in ("plan", "mode") if cfg.get(k) and plan.get(k) and cfg[k] != plan[k]]
    if changed:
        out.append({"id": "settings_changed",
                    "reason": "config " + ", ".join(f"{k}={cfg[k]}" for k in changed)
                              + " differs from plan.json"})
    return out


# --- Tier 1: notices ----------------------------------------------------------

def status_key(sched):
    if sched["fits_today"] is None or sched["current_release"] is None:
        return None
    return f"{sched['current_release']}:{'fits' if sched['fits_today'] else 'no-fit'}"


def notice(sched, prev):
    """The one Tier-1 line, or None. Never repeats while the status is unchanged."""
    prev = prev or {}
    parts = []
    key, old = status_key(sched), prev.get("status_key")
    sched["status_key"] = key if key is not None else old  # unknown usage keeps the old state
    if key is not None and key != old:
        rel = sched["current_release"]
        used = sched["session"]["used_pct"]
        hi = sched["current_remaining_pct"][1]
        was = prev.get("session", {}).get("used_pct") if prev else None
        moved = f", was {was:.0f}%" if isinstance(was, (int, float)) and was != used else ""
        if not sched["fits_today"]:
            parts.append(f"navitok: {rel} no longer fits this session (session {used:.0f}%{moved}, "
                         f"+ up to {hi:.1f}% remaining > {sched['threshold']:.0f}% threshold). "
                         f"Finish the current task, then checkpoint.")
        elif old == f"{rel}:no-fit":
            parts.append(f"navitok: {rel} fits this session again (session {used:.0f}%{moved}).")
    ids = sorted(t["id"] for t in sched["replan"])
    sched["replan_key"] = ",".join(ids)
    if ids and sched["replan_key"] != prev.get("replan_key"):
        parts.append("navitok: replan suggested (" + "; ".join(t["reason"] for t in sched["replan"])
                     + "). Do not replan mid-task: at the next task boundary, offer the user a replan.")
    line = " ".join(parts) or None
    sched["last_notice"] = line or prev.get("last_notice")
    return line


# --- render -----------------------------------------------------------------

def render_section(sched):
    if not sched:
        return "Not computed yet. Run `schedule.py recompute`."
    if sched["plan"] == "api":
        return "API plan: no session or weekly limit, so every release can run now."
    s, w = sched["session"]["used_pct"], sched["week"]["used_pct"]
    fits = {True: "fits this session", False: "does **not** fit this session", None: "fit unknown"}
    head = (f"Session used: {'unknown' if s is None else f'{s:.0f}%'} · "
            f"Week used: {'unknown' if w is None else f'{w:.0f}%'} · ")
    head += f"Current release: **{sched['current_release']}**, {fits[sched['fits_today']]}." \
        if sched["current_release"] else "All releases done."
    if sched.get("usage_stale"):
        head += " (Usage reading is stale.)"
    rows = ["| Release | Remaining estimate | Week | Session | Note |", "|---|---|---|---|---|"]
    for p in sched["placement"]:
        note = []
        if p.get("extra"):
            note.append("extra usage (flex)")
        if p.get("over"):
            note.append("larger than one session")
        rows.append(f"| {p['release']} | {p['est_pct'][0]:.1f}–{p['est_pct'][1]:.1f}% | {p['week']} "
                    f"| {p['session']} | {', '.join(note)} |")
    out = [head, "", *rows]
    if sched["replan"]:
        out += ["", "Replan suggested at the next task boundary: "
                + "; ".join(t["reason"] for t in sched["replan"]) + "."]
    reserved = sched["week"].get("external_reserved_pct")
    ext = (f"{reserved:g}% of the week is reserved for usage outside Claude Code."
           if reserved is not None else "External usage is unknown, so nothing is reserved yet.")
    out += ["", f"Weekly cost is estimated as {sched['week']['per_session_ratio']:.3g}× the session cost. {ext}"]
    return "\n".join(out)


# --- files --------------------------------------------------------------------

def schedule_path(project_dir):
    return planmod.navitok_dir(project_dir) / "schedule.json"


def load_schedule(project_dir):
    path = schedule_path(project_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def recompute(project_dir=".", reading=None, now=None, cache_path=None, use_account=True):
    """Tier 0 + 1 + 2 detection. Writes schedule.json and (if changed) ROADMAP.md.
    Returns (schedule, notice_line_or_None)."""
    now = now or _now()
    nav = planmod.navitok_dir(project_dir)
    _, plan = planmod._load_plan(project_dir)
    errs = planmod.validate(plan)
    if errs:
        raise planmod.PlanError("; ".join(errs))
    cfg = planmod.load_config(project_dir)
    if reading is None and use_account:
        reading = usage_read.account_usage(nav / SNAPSHOT_FILE, cache_path, now=now)
    prev = load_schedule(project_dir)
    sched = compute(plan, cfg, reading, prev, now)
    line = notice(sched, prev)
    planmod._write_json(schedule_path(project_dir), sched)
    threshold = planmod.threshold_for(cfg)
    text = planmod.render(_priced(plan, threshold, cfg), threshold, schedule=render_section(sched))
    out = nav / "ROADMAP.md"
    try:
        old = out.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old != text:
        out.write_text(text, encoding="utf-8", newline="\n")
    return sched, line


def _override(reading, session_pct, weekly_pct):
    if session_pct is None and weekly_pct is None:
        return reading
    r = dict(reading or {})
    r["source"] = "manual"
    r["stale"] = False
    now = _now()
    for pct_key, reset_key, value in (("session_pct", "session_resets_at", session_pct),
                                      ("weekly_pct", "weekly_resets_at", weekly_pct)):
        if value is None:
            continue
        r[pct_key] = value
        reset = usage_read.parse_ts(r.get(reset_key))
        if reset is not None and reset <= now:  # a fresh manual reading outlives an old reset time
            r[reset_key] = None
    return r


# --- CLI --------------------------------------------------------------------

def hook_main(stdin=None, cache_path=None):
    """UserPromptSubmit: plain stdout on exit 0 is added to Claude's context
    (docs/data-sources.md). Print the Tier-1 line or nothing. Never fail."""
    nav = None
    try:
        stdin = stdin or sys.stdin
        raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read().encode("utf-8")
        payload = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
        project = payload.get("cwd") or os.getcwd()
        nav = planmod.navitok_dir(project)
        if not (nav / "plan.json").is_file():
            return 0
        _, line = recompute(project, cache_path=cache_path)
        if line:
            sys.stdout.write(line + "\n")
    except Exception as exc:  # never break the user's session
        try:
            if nav is not None and nav.is_dir():
                with open(nav / "hook-errors.log", "a", encoding="utf-8") as f:
                    f.write(f"{usage_read.iso(_now())} ['prompt'] {type(exc).__name__}: {exc}\n")
        except Exception:
            pass
    return 0


def main(argv=None):
    import argparse
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok schedule engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("recompute", help="recompute schedule.json and ROADMAP.md")
    rc.add_argument("--session-pct", type=float)
    rc.add_argument("--weekly-pct", type=float)
    sub.add_parser("show", help="print the current schedule.json summary")
    sub.add_parser("hook", help="UserPromptSubmit hook entry point")
    for name in ("recompute", "show"):
        sub.choices[name].add_argument("--project-dir", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "hook":
        return hook_main()
    try:
        if args.cmd == "show":
            sched = load_schedule(args.project_dir)
            print(render_section(sched))
            return 0 if sched else 1
        reading = None
        if args.session_pct is not None or args.weekly_pct is not None:
            nav = planmod.navitok_dir(args.project_dir)
            reading = _override(usage_read.account_usage(nav / SNAPSHOT_FILE), args.session_pct, args.weekly_pct)
        sched, line = recompute(args.project_dir, reading=reading)
        print(line or "No change in fit status.")
        print(render_section(sched))
        return 0
    except (OSError, planmod.PlanError) as exc:
        print(f"schedule: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
