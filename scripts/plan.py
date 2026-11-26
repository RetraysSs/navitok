"""navitok plan tools: config.json, plan.json pricing/validation, ROADMAP.md.

Claude writes the plan structure (releases, tasks, type, size, files) to
.navitok/plan.json. This script prices it with estimate.py, checks that every
release fits one session under the threshold, and renders .navitok/ROADMAP.md.
Stdlib only, deterministic, never calls the model.

  plan.py config --plan pro --mode strict [--project-dir DIR]
  plan.py price  [--project-dir DIR]     # validate + price + render; exit 1 if a release does not fit
  plan.py render [--project-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate  # noqa: E402

SCHEMA = 1
MODES = ("strict", "flex")
STATUSES = ("todo", "doing", "done", "skipped")
CONFIG_DEFAULTS = {"schema": SCHEMA, "plan": "pro", "mode": "strict", "threshold_override": None,
                   "statusline": False, "trim_output": False}
CALIBRATION_KEY = "calibration"  # attached by load_config from calibration.json
TEMPLATE = Path(__file__).resolve().parent.parent / "skills" / "navitok" / "references" / "roadmap-template.md"


class PlanError(ValueError):
    pass


def navitok_dir(project_dir="."):
    return Path(project_dir) / ".navitok"


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path}: invalid JSON ({exc})") from exc


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


# --- config -----------------------------------------------------------------

def load_config(project_dir="."):
    path = navitok_dir(project_dir) / "config.json"
    cfg = dict(CONFIG_DEFAULTS)
    if path.exists():
        data = _read_json(path)
        if not isinstance(data, dict):
            raise PlanError(f"{path}: must be an object")
        cfg.update(data)
    cfg.pop(CALIBRATION_KEY, None)
    cal_path = navitok_dir(project_dir) / "calibration.json"
    if cal_path.exists():  # script-owned (calibrate.py); attached, never written back
        try:
            cal = json.loads(cal_path.read_text(encoding="utf-8"))
            if isinstance(cal, dict):
                cfg[CALIBRATION_KEY] = cal
        except (OSError, ValueError):
            pass
    return cfg


def write_config(project_dir=".", plan=None, mode=None):
    cfg = load_config(project_dir)
    if plan is not None:
        cfg["plan"] = estimate.normalize_plan(plan)
    if mode is not None:
        if mode not in MODES:
            raise PlanError(f"mode must be one of {MODES}, got {mode!r}")
        cfg["mode"] = mode
    _write_json(navitok_dir(project_dir) / "config.json",
                {k: v for k, v in cfg.items() if k != CALIBRATION_KEY})
    return cfg


def threshold_for(cfg):
    """90 at cold start; the learned §10.1 threshold (clamped to 90-98) once
    calibrate.py has enough history. An override may only lower it."""
    base = estimate.THRESHOLD
    cal = cfg.get(CALIBRATION_KEY)
    learned = cal.get("threshold") if isinstance(cal, dict) and cal.get("learned") else None
    if isinstance(learned, (int, float)) and not isinstance(learned, bool):
        base = min(98.0, max(estimate.THRESHOLD, float(learned)))
    override = cfg.get("threshold_override")
    if isinstance(override, (int, float)) and not isinstance(override, bool) and 0 < override < base:
        return float(override)
    return base


def learned_types(cfg, helpers=None):
    """Per-type learned ranges for estimate.py, or None at cold start.
    `helpers` (the plan's) picks the calibration group: a Graphify-helped plan
    is priced only from Graphify-helped history, and falls back to the cold
    start (not to unhelped history) until that group has learned (v0.11)."""
    cal = cfg.get(CALIBRATION_KEY)
    if not isinstance(cal, dict) or not cal.get("learned"):
        return None
    group = estimate.helper_group(helpers)
    if group == estimate.PLAIN_GROUP:
        types = cal.get("types")
    else:
        g = (cal.get("helper_groups") or {}).get(group)
        if not isinstance(g, dict) or not g.get("learned"):
            return None
        types = g.get("types")
    out = {t: {"est_pct": v["est_pct"], "confidence": cal.get("confidence", 0)}
           for t, v in (types or {}).items()
           if isinstance(v, dict) and isinstance(v.get("est_pct"), list)}
    return out or None


# --- plan -------------------------------------------------------------------

def validate(plan):
    """Return a list of problems with the plan's structure (empty = valid)."""
    errs = []
    if not isinstance(plan, dict):
        return ["plan must be a JSON object"]
    if plan.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    if not isinstance(plan.get("project"), str) or not plan["project"].strip():
        errs.append("project must be a non-empty string")
    try:
        estimate.normalize_plan(plan.get("plan"))
    except estimate.EstimateError as exc:
        errs.append(str(exc))
    if plan.get("mode") not in MODES:
        errs.append(f"mode must be one of {MODES}")
    releases = plan.get("releases")
    if not isinstance(releases, list) or not releases:
        return errs + ["releases must be a non-empty list"]
    rel_ids, task_ids = set(), set()
    for i, rel in enumerate(releases):
        where = f"releases[{i}]"
        if not isinstance(rel, dict):
            errs.append(f"{where} must be an object")
            continue
        rid = rel.get("id")
        if not isinstance(rid, str) or not rid:
            errs.append(f"{where}.id must be a non-empty string")
        elif rid in rel_ids:
            errs.append(f"duplicate release id {rid!r}")
        rel_ids.add(rid)
        if not isinstance(rel.get("title"), str) or not rel["title"].strip():
            errs.append(f"{where}.title must be a non-empty string")
        tasks = rel.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errs.append(f"{where}.tasks must be a non-empty list")
            continue
        for j, task in enumerate(tasks):
            tw = f"{where}.tasks[{j}]"
            if not isinstance(task, dict):
                errs.append(f"{tw} must be an object")
                continue
            tid = task.get("id")
            if not isinstance(tid, str) or not tid:
                errs.append(f"{tw}.id must be a non-empty string")
            elif tid in task_ids:
                errs.append(f"duplicate task id {tid!r}")
            task_ids.add(tid)
            if not isinstance(task.get("title"), str) or not task["title"].strip():
                errs.append(f"{tw}.title must be a non-empty string")
            if task.get("status", "todo") not in STATUSES:
                errs.append(f"{tw}.status must be one of {STATUSES}")
            try:
                estimate.files_factor(task.get("files"))
            except estimate.EstimateError as exc:
                errs.append(f"{tw}: {exc}")
            if task.get("execution", "inline") not in estimate.EXECUTION:
                errs.append(f"{tw}.execution must be one of {sorted(estimate.EXECUTION)}")
    return errs


def price(plan, threshold=estimate.THRESHOLD, learned=None):
    """Fill est_pct on every task and release (in place).

    Returns (plan, over) where `over` lists releases whose upper estimate is
    above the threshold. On the API plan nothing is ever over.
    """
    errs = validate(plan)
    if errs:
        raise PlanError("; ".join(errs))
    key = estimate.normalize_plan(plan["plan"])
    plan["plan"] = key
    over = []
    for rel in plan["releases"]:
        res = estimate.estimate(rel["tasks"], key, learned)
        for task, row in zip(rel["tasks"], res["tasks"]):
            task["est_pct"] = row["est_pct"]
            task.setdefault("status", "todo")
            task.setdefault("suggested_model", None)
            task.setdefault("suggested_effort", None)
            if row["notes"]:
                task["est_notes"] = row["notes"]
            else:
                task.pop("est_notes", None)
        rel["est_pct"] = res["total_pct"]
        rel["confidence"] = res["confidence"]
        if key != "api" and res["total_pct"][1] > threshold:
            over.append((rel["id"], res["total_pct"][1]))
    return plan, over


# --- render -----------------------------------------------------------------

def _rng(r):
    return f"{r[0]:.1f}–{r[1]:.1f}%"


def render(plan, threshold=estimate.THRESHOLD, template_path=TEMPLATE, schedule=None):
    unit = "Pro-equivalent units (API plan: no session limit)" if plan["plan"] == "api" \
        else f"% of one 5-hour session on {plan['plan']}"
    summary = ["| Release | Title | Tasks | Estimate | Confidence |", "|---|---|---|---|---|"]
    details = []
    total = [0.0, 0.0]
    for rel in plan["releases"]:
        est = rel.get("est_pct") or [0, 0]
        total = [total[0] + est[0], total[1] + est[1]]
        summary.append(f"| {rel['id']} | {rel['title']} | {len(rel['tasks'])} | {_rng(est)} "
                       f"| {rel.get('confidence', '-')} |")
        details += [f"### {rel['id']} — {rel['title']}", "",
                    "| Task | Title | Type | Size | Estimate | Status |", "|---|---|---|---|---|---|"]
        for t in rel["tasks"]:
            details.append(f"| {t['id']} | {t['title']} | {t.get('type') or '?'} | {t.get('size') or '?'} "
                           f"| {_rng(t.get('est_pct') or [0, 0])} | {t.get('status', 'todo')} |")
        details.append("")
    text = Template(Path(template_path).read_text(encoding="utf-8")).safe_substitute(
        project=plan["project"], plan=plan["plan"], mode=plan["mode"], unit=unit,
        threshold=f"{threshold:.0f}", total=_rng(total), release_count=len(plan["releases"]),
        summary="\n".join(summary), releases="\n".join(details).rstrip(),
        schedule=schedule or "Not computed yet. It appears after the first `schedule.py recompute`.")
    return text.rstrip() + "\n"


def write_roadmap(project_dir, plan, threshold, schedule=None):
    out = navitok_dir(project_dir) / "ROADMAP.md"
    if schedule is None:  # keep the last computed schedule section (lazy import: schedule imports plan)
        import schedule as schedmod
        sched = schedmod.load_schedule(project_dir)
        schedule = schedmod.render_section(sched) if sched else None
    out.write_text(render(plan, threshold, schedule=schedule), encoding="utf-8", newline="\n")
    return out


# --- CLI --------------------------------------------------------------------

def _load_plan(project_dir):
    path = navitok_dir(project_dir) / "plan.json"
    if not path.exists():
        raise PlanError(f"{path} not found; write the plan structure there first")
    return path, _read_json(path)


def cmd_config(args):
    cfg = write_config(args.project_dir, args.plan, args.mode)
    print(f"config: plan={cfg['plan']} mode={cfg['mode']}")
    return 0


def cmd_price(args):
    path, plan = _load_plan(args.project_dir)
    cfg = load_config(args.project_dir)
    threshold = threshold_for(cfg)
    plan, over = price(plan, threshold, learned_types(cfg, plan.get("helpers")))
    _write_json(path, plan)
    for rel in plan["releases"]:
        print(f"{rel['id']:<8} {_rng(rel['est_pct']):>14}  conf {rel['confidence']:>3}  {rel['title']}")
    total = [round(sum(r["est_pct"][i] for r in plan["releases"]), 2) for i in (0, 1)]
    print(f"All releases together: {_rng(total)} (a sum across sessions, not one session's usage)")
    if over:
        for rid, hi in over:
            print(f"OVER: {rid} upper estimate {hi:.1f}% > threshold {threshold:.0f}%. "
                  f"Split it or move tasks to another release.")
        print("ROADMAP.md not rendered.")
        return 1
    out = write_roadmap(args.project_dir, plan, threshold)
    print(f"All releases fit under {threshold:.0f}%. Wrote {path} and {out}.")
    return 0


def cmd_render(args):
    _, plan = _load_plan(args.project_dir)
    errs = validate(plan)
    if errs:
        raise PlanError("; ".join(errs))
    out = write_roadmap(args.project_dir, plan, threshold_for(load_config(args.project_dir)))
    print(f"Wrote {out}.")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok plan tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config", help="create or update .navitok/config.json")
    c.add_argument("--plan")
    c.add_argument("--mode", choices=MODES)
    for name in ("price", "render"):
        sub.add_parser(name)
    for p in sub.choices.values():
        p.add_argument("--project-dir", default=".")
    args = ap.parse_args(argv)
    try:
        return {"config": cmd_config, "price": cmd_price, "render": cmd_render}[args.cmd](args)
    except (OSError, PlanError, estimate.EstimateError) as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
