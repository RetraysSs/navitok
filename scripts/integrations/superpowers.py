"""navitok works with Superpowers: plan ingestion (v0.10).

Detects Superpowers and reads its implementation plans
(docs/superpowers/plans/*.md, the format its writing-plans skill documents).
Turns their tasks into a draft .navitok/plan.json, split into versioned
releases that each fit one session, then prices it and renders ROADMAP.md.

Read-only towards Superpowers: plan files are opened for reading only and
never modified. No Superpowers code is used or copied. Stdlib only,
deterministic, never calls the model.

  superpowers.py detect [--project-dir DIR]
  superpowers.py ingest [--project-dir DIR] [--plan-file F ...]
                        [--execution auto|subagent|inline] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import estimate  # noqa: E402
import plan as planmod  # noqa: E402

PLANS_DIR = Path("docs") / "superpowers" / "plans"
PLUGIN_PREFIX = "superpowers@"
MAX_TASKS = 4  # plan tasks per release; navitok adds one wrapup task (3-5 rule)
EXECUTIONS = ("auto", "subagent", "inline")

_TITLE = re.compile(r"^#\s+(.+?)\s*$")
_GOAL = re.compile(r"^\*\*Goal:\*\*\s*(.+?)\s*$")
_TASK = re.compile(r"^#{2,4}\s+Task\s+(\d+)\s*:\s*(.+?)\s*$", re.I)
_FILE = re.compile(r"^\s*[-*]\s*(?:Create|Modify|Test|Delete|Rename)\s*:\s*`([^`]+)`", re.I)
_STEP = re.compile(r"^\s*[-*]\s+\[([ xX])\]")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")

# Keyword -> type, first match wins. Claude reviews the draft and may change it.
_TYPE_WORDS = [
    ("bugfix", r"\b(fix|fixes|bug|crash|regression)\b"),
    ("refactor", r"\brefactor"),
    ("migration", r"\bmigrat"),
    ("config", r"\b(config|configure|configuration|setup|ci|settings)\b"),
    ("scaffold", r"\b(scaffold|skeleton|bootstrap)\b"),
    ("research", r"\b(spike|research|investigate)\b"),
    ("docs", r"\b(docs?|documentation|readme)\b"),
    ("test", r"^tests?\b"),
]
_DOC_EXT = (".md", ".rst", ".txt")


class IngestError(ValueError):
    pass


# --- detection ----------------------------------------------------------------

def registry_path(home=None):
    """Claude Code's plugin registry. Undocumented: UNSTABLE (docs/data-sources.md)."""
    return Path(home or os.path.expanduser("~")) / ".claude" / "plugins" / "installed_plugins.json"


def detect(home=None, project_dir="."):
    info = {"installed": False, "version": None, "install_path": None, "plans": []}
    try:
        data = json.loads(registry_path(home).read_text(encoding="utf-8"))
        for key, entries in (data.get("plugins") or {}).items():
            if key.startswith(PLUGIN_PREFIX) and isinstance(entries, list) and entries:
                entry = entries[0] if isinstance(entries[0], dict) else {}
                info.update(installed=True, version=entry.get("version"),
                            install_path=entry.get("installPath"))
                break
    except (OSError, ValueError, AttributeError):
        pass  # no registry or an unknown format: treat as not installed
    folder = Path(project_dir) / PLANS_DIR
    if folder.is_dir():
        info["plans"] = [str(p) for p in sorted(folder.glob("*.md"), key=lambda p: p.name)]
    return info


# --- parsing -----------------------------------------------------------------

def _infer_type(title, files):
    low = title.lower()
    for ttype, pattern in _TYPE_WORDS:
        if re.search(pattern, low):
            return ttype
    if files and all(f.lower().endswith(_DOC_EXT) for f in files):
        return "docs"
    if files and all(re.match(r"^tests?/", f) for f in files):
        return "test"
    return "feature"


def _infer_size(steps):
    if steps <= 0:
        return None  # priced as L by estimate.py
    return "S" if steps <= 6 else "M" if steps <= 12 else "L"


def parse_plan(text):
    """Parse a Superpowers plan's markdown into a title, goal and task list."""
    title = goal = None
    header = []
    tasks = []
    cur = None
    fence = None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not line.strip()[len(m.group(1)):].strip():
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        tm = _TASK.match(line)
        if tm:
            cur = {"number": int(tm.group(1)), "title": tm.group(2), "paths": [],
                   "steps": 0, "done_steps": 0}
            tasks.append(cur)
            continue
        if cur is None:
            header.append(line)
            if title is None and (m := _TITLE.match(line)):
                title = re.sub(r"\s+Implementation Plan$", "", m.group(1), flags=re.I)
            if goal is None and (m := _GOAL.match(line)):
                goal = m.group(1)
            continue
        if fm := _FILE.match(line):
            path = _LINE_SUFFIX.sub("", fm.group(1).strip())
            if path not in cur["paths"]:
                cur["paths"].append(path)
        elif sm := _STEP.match(line):
            cur["steps"] += 1
            cur["done_steps"] += sm.group(1) != " "
    for t in tasks:
        paths = t.pop("paths")
        t["files"] = len(paths) or None
        t["type"] = _infer_type(t["title"], paths)
        t["size"] = _infer_size(t["steps"])
        t["status"] = "done" if t["steps"] and t["done_steps"] == t["steps"] else "todo"
    return {"title": title, "goal": goal,
            "recommends_subagents": "subagent-driven-development" in "\n".join(header),
            "tasks": tasks}


# --- conversion ----------------------------------------------------------------

def _wrapup(rid):
    return {"id": f"{rid}-t0", "title": "Wrap up: tests, changelog, commit", "type": "wrapup", "size": "S"}


def _hi(tasks, plan, learned):
    return estimate.estimate(tasks, plan, learned)["total_pct"][1]


def to_plan(parsed, plan="pro", mode="strict", execution="auto", threshold=estimate.THRESHOLD,
            learned=None, project=None):
    """parsed: [(source_path, parse_plan(...)), ...] in order.
    Returns (plan_dict, recommendation or None). Releases are packed greedily
    in task order, each under `threshold` (upper estimate, wrapup included)."""
    if execution not in EXECUTIONS:
        raise IngestError(f"execution must be one of {EXECUTIONS}")
    plan = estimate.normalize_plan(plan)
    limited = plan != "api"
    groups = []  # [(plan title, [tasks])]
    used = set()
    for source, p in parsed:
        mode_used = execution if execution != "auto" else \
            ("subagent" if p["recommends_subagents"] else "inline")
        used.add(mode_used)
        buf = []
        for t in p["tasks"]:
            task = {"title": t["title"], "type": t["type"], "size": t["size"], "files": t["files"],
                    "status": t["status"], "execution": mode_used,
                    "source": {"superpowers_plan": source, "task": t["number"]}}
            trial = buf + [task]
            if buf and (len(trial) > MAX_TASKS or
                        (limited and _hi(trial + [_wrapup("x")], plan, learned) > threshold)):
                groups.append((p["title"], buf))
                trial = [task]
            buf = trial
        if buf:
            groups.append((p["title"], buf))
    if not groups:
        raise IngestError("the Superpowers plan has no tasks (expected '### Task N: ...' headings)")

    releases = []
    for i, (title, tasks) in enumerate(groups, 1):
        rid = f"v0.{i}"
        nums = [t["source"]["task"] for t in tasks]
        span = f"task {nums[0]}" if len(nums) == 1 else f"tasks {nums[0]}–{nums[-1]}"
        for n, t in enumerate(tasks, 1):
            t["id"] = f"{rid}-t{n}"
        wrap = _wrapup(rid)
        wrap["id"] = f"{rid}-t{len(tasks) + 1}"
        releases.append({"id": rid, "title": f"{title or 'Superpowers plan'} ({span})",
                         "tasks": [{"id": t.pop("id"), **t} for t in tasks] + [wrap]})

    titles = [p["title"] for _, p in parsed if p["title"]]
    out = {"schema": planmod.SCHEMA, "project": project or (titles[0] if titles else "Superpowers plan"),
           "plan": plan, "mode": mode, "source": "superpowers", "releases": releases}

    rec = None
    if "subagent" in used and plan == "pro" and mode == "strict":
        tasks = [t for r in releases for t in r["tasks"]]
        sub = estimate.estimate(tasks, plan, learned)["total_pct"][1]
        inl = estimate.estimate([dict(t, execution="inline") for t in tasks], plan, learned)["total_pct"][1]
        rec = (f"Pro + strict: consider inline execution (superpowers:executing-plans) instead of "
               f"subagent-driven-development. Upper estimate {inl:.1f}% inline vs {sub:.1f}% with "
               f"subagents (x{estimate.EXECUTION['subagent']}, an unmeasured assumption). "
               f"Re-run with --execution inline to plan for it.")
    return out, rec


# --- CLI -----------------------------------------------------------------------

def _rel(path, project_dir):
    try:
        return Path(path).resolve().relative_to(Path(project_dir).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def cmd_detect(args):
    info = detect(project_dir=args.project_dir)
    if info["installed"]:
        print(f"Superpowers {info['version'] or '(unknown version)'} installed.")
    else:
        print("Superpowers not installed (or not found). The normal navitok plan flow works without it.")
    if info["plans"]:
        print("Plans found:")
        for p in info["plans"]:
            print(f"  {_rel(p, args.project_dir)}")
    else:
        print(f"No plans in {PLANS_DIR.as_posix()}/.")
    return 0


def cmd_ingest(args):
    files = [Path(args.project_dir) / f for f in args.plan_file] if args.plan_file \
        else [Path(p) for p in detect(project_dir=args.project_dir)["plans"]]
    if not files:
        raise IngestError(f"no Superpowers plan found in {PLANS_DIR.as_posix()}/ (use --plan-file)")
    target = planmod.navitok_dir(args.project_dir) / "plan.json"
    if target.exists() and not args.force:
        raise IngestError(f"{target} already exists; re-run with --force to replace it")
    parsed = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:  # read-only, never written
            parsed.append((_rel(f, args.project_dir), parse_plan(fh.read())))
    cfg = planmod.load_config(args.project_dir)
    threshold = planmod.threshold_for(cfg)
    learned = planmod.learned_types(cfg)
    draft, rec = to_plan(parsed, cfg["plan"], cfg["mode"], args.execution, threshold, learned)
    priced, over = planmod.price(draft, threshold, learned)
    planmod._write_json(target, priced)
    for rel in priced["releases"]:
        print(f"{rel['id']:<8} {planmod._rng(rel['est_pct']):>14}  conf {rel['confidence']:>3}  {rel['title']}")
    print(f"Wrote {target} from {len(files)} Superpowers plan(s); the plan files were not changed.")
    if rec:
        print(rec)
    if over:
        for rid, hi in over:
            print(f"OVER: {rid} upper estimate {hi:.1f}% > threshold {threshold:.0f}%. "
                  f"One task is too big for a session: split it in plan.json.")
        print("ROADMAP.md not rendered.")
        return 1
    out = planmod.write_roadmap(args.project_dir, priced, threshold)
    print(f"All releases fit under {threshold:.0f}%. Wrote {out}. Review the inferred types and sizes; "
          f"after edits run plan.py price.")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok: works with Superpowers plans")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    ing = sub.add_parser("ingest")
    ing.add_argument("--plan-file", action="append", default=[])
    ing.add_argument("--execution", choices=EXECUTIONS, default="auto")
    ing.add_argument("--force", action="store_true")
    for p in sub.choices.values():
        p.add_argument("--project-dir", default=".")
    args = ap.parse_args(argv)
    try:
        return {"detect": cmd_detect, "ingest": cmd_ingest}[args.cmd](args)
    except (OSError, IngestError, planmod.PlanError, estimate.EstimateError) as exc:
        print(f"superpowers: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
