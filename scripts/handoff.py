"""navitok handoff and safe stopping (ROADMAP v0.6, §10.2).

Deterministic, stdlib only, never calls the model.

  handoff.py fit     [--task ID] [--project-dir DIR]
      Per-task fit check from schedule.json (§10.2):
        remaining = threshold - session used %
        fits      = remaining >= task upper estimate + buffer,  buffer = max(2, max_step)
      Exit 0 FITS, 1 NO-FIT (propose a checkpoint), 3 UNKNOWN (no usage reading),
      2 error. A stale reading is still checked but flagged.
  handoff.py write   [--note TEXT]... [--project-dir DIR]
      Write .navitok/HANDOFF.md from plan.json + git: done, next task,
      half-edited (uncommitted) files, last commit. Notes come from Claude.
  handoff.py summary [--project-dir DIR]
      Print the short resume summary (what SessionStart adds to context).
  handoff.py hook
      SessionStart entry point: reads hook JSON on stdin and prints the summary
      when .navitok/HANDOFF.md exists. Silent on resume (context is intact)
      and on any error. Always exits 0.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan as planmod  # noqa: E402
import usage_read  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "skills" / "navitok" / "references" / "handoff-template.md"
HANDOFF_FILE = "HANDOFF.md"
DONE = ("done", "skipped")
MIN_BUFFER = 2.0  # §10.2, session %
SUMMARY_MAX = 600  # characters; far below the 10,000-character hook cap
QUIET_SOURCES = ("resume",)  # the conversation is restored, so a summary is noise


def _now():
    return datetime.now(timezone.utc)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x):
    return f"{float(x):.1f}".rstrip("0").rstrip(".")


# --- plan helpers -------------------------------------------------------------

def _priced(plan, cfg):
    if all(isinstance(t.get("est_pct"), list) for r in plan["releases"] for t in r["tasks"]):
        return plan
    priced, _ = planmod.price(copy.deepcopy(plan), planmod.threshold_for(cfg), planmod.learned_types(cfg, plan.get("helpers")))
    return priced


def current_release(plan):
    for rel in plan.get("releases", []):
        if any(t.get("status", "todo") not in DONE for t in rel["tasks"]):
            return rel
    return None


def next_task(plan):
    """(release, task, 1-based index) of the task to work on: the first `doing`
    task of the current release, else its first `todo`. (None, None, None) if done."""
    rel = current_release(plan)
    if rel is None:
        return None, None, None
    tasks = rel["tasks"]
    for status in ("doing", "todo"):
        for i, t in enumerate(tasks, 1):
            if t.get("status", "todo") == status:
                return rel, t, i
    return rel, None, None


def find_task(plan, task_id):
    for rel in plan.get("releases", []):
        for i, t in enumerate(rel["tasks"], 1):
            if t["id"] == task_id:
                return rel, t, i
    return None, None, None


# --- fit check (§10.2) --------------------------------------------------------

def fit_check(plan, cfg, sched, task_id=None):
    """Pure. Returns a dict with verdict FITS / NO-FIT / UNKNOWN / DONE and a line."""
    plan = _priced(plan, cfg)
    rel, task, _ = find_task(plan, task_id) if task_id else next_task(plan)
    if task_id and task is None:
        raise planmod.PlanError(f"unknown task id: {task_id}")
    if task is None:
        return {"verdict": "DONE", "line": "DONE: no task left in the plan."}
    hi = float((task.get("est_pct") or [0, 0])[1])
    max_step = cfg.get("max_step_pct")
    if not _num(max_step):  # learned by calibrate.py (§10.1)
        cal = cfg.get(planmod.CALIBRATION_KEY)
        max_step = cal.get("max_step") if isinstance(cal, dict) and cal.get("learned") else None
    buffer = max(MIN_BUFFER, float(max_step) if _num(max_step) else 0.0)
    sched = sched or {}
    threshold = sched.get("threshold")
    if not _num(threshold):
        threshold = planmod.threshold_for(cfg)
    used = (sched.get("session") or {}).get("used_pct")
    out = {"task": task["id"], "release": rel["id"], "task_hi": hi, "buffer": buffer,
           "threshold": threshold, "used_pct": used, "stale": bool(sched.get("usage_stale"))}
    if plan.get("plan") == "api":
        out.update(verdict="FITS", line=f"FITS: {task['id']} (API plan: no session limit).")
        return out
    if not _num(used):
        out.update(verdict="UNKNOWN",
                   line=f"UNKNOWN: no usage reading for {task['id']}. Ask the user for /usage, "
                        f"then run schedule.py recompute --session-pct N --weekly-pct N.")
        return out
    remaining = float(threshold) - float(used)
    need = hi + buffer
    out["remaining"] = remaining
    detail = (f"{task['id']} needs up to {_fmt(hi)}% + {_fmt(buffer)}% buffer = {_fmt(need)}%, "
              f"{_fmt(remaining)}% left before the {_fmt(threshold)}% threshold "
              f"(session at {_fmt(used)}%)")
    stale = " Usage reading is stale: ask for /usage if unsure." if out["stale"] else ""
    if remaining >= need:
        out.update(verdict="FITS", line=f"FITS: {detail}.{stale}")
    else:
        out.update(verdict="NO-FIT",
                   line=f"NO-FIT: {detail}. Do not start it: propose /navitok:checkpoint.{stale}")
    return out


# --- git ------------------------------------------------------------------------

def _git(project_dir, *args):
    try:
        res = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(project_dir), *args],
                             capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.decode("utf-8", errors="replace")


def git_state(project_dir):
    """{'commit': 'abc1234 subject' | None, 'dirty': [(status, path)] | None (no git)}."""
    log = _git(project_dir, "log", "-1", "--format=%h %s")
    status = _git(project_dir, "status", "--porcelain=v1", "--untracked-files=all")
    dirty = None
    if status is not None:
        dirty = []
        for line in status.splitlines():
            if len(line) < 4:
                continue
            code, path = line[:2].strip() or "?", line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path.strip('"').startswith(".navitok/"):
                continue  # navitok's own state is not the user's work
            dirty.append((code, path))
    return {"commit": (log or "").strip() or None, "dirty": dirty}


# --- handoff ----------------------------------------------------------------------

def resume_line(plan, git):
    rel, task, idx = next_task(plan)
    commit = git.get("commit")
    tail = f" Last commit: {commit.split(' ', 1)[0]}." if commit else ""
    dirty = git.get("dirty")
    if dirty:
        tail += f" {len(dirty)} uncommitted file{'s' if len(dirty) != 1 else ''}."
    if rel is None:
        return f"all releases in the plan are done.{tail}"
    total = len(rel["tasks"])
    done = sum(1 for t in rel["tasks"] if t.get("status", "todo") in DONE)
    head = f"continuing {rel['id']} ({rel.get('title', '')})"
    if task is None:
        return f"{head}, all {total} tasks done or skipped.{tail}"
    return (f"{head}, task {idx} of {total}: {task['id']} {task.get('title', '')} "
            f"[{task.get('status', 'todo')}]. {done} done.{tail}")


def render_handoff(plan, git, notes=(), now=None, template_path=TEMPLATE):
    now = now or _now()
    rel, task, idx = next_task(plan)
    done = [f"- {t['id']} {t.get('title', '')} ({t.get('status')})"
            for t in (rel["tasks"] if rel else []) if t.get("status", "todo") in DONE]
    if task is not None:
        est = task.get("est_pct")
        rng = f", est {_fmt(est[0])}–{_fmt(est[1])}%" if isinstance(est, list) else ""
        nxt = f"- {task['id']} {task.get('title', '')} (task {idx} of {len(rel['tasks'])}, " \
              f"{task.get('status', 'todo')}{rng})"
    else:
        nxt = "- None: the release is complete." if rel else "- None: the plan is complete."
    dirty = git.get("dirty")
    if dirty is None:
        dirty_txt = "- Unknown (not a git repository)."
    elif not dirty:
        dirty_txt = "- None: the working tree is clean."
    else:
        dirty_txt = "\n".join(f"- `{p}` ({c})" for c, p in dirty)
    tpl = Template(Path(template_path).read_text(encoding="utf-8"))
    return tpl.safe_substitute(
        project=plan.get("project", ""),
        resume=resume_line(plan, git),
        written=usage_read.iso(now),
        commit=f"`{git['commit']}`" if git.get("commit") else "none",
        release=f"{rel['id']} {rel.get('title', '')}" if rel else "none (plan complete)",
        done="\n".join(done) or "- Nothing yet in this release.",
        next=nxt,
        dirty=dirty_txt,
        notes="\n".join(f"- {n}" for n in notes if n.strip()) or "- None.",
    )


def write_handoff(project_dir=".", notes=(), now=None):
    _, plan = planmod._load_plan(project_dir)
    errs = planmod.validate(plan)
    if errs:
        raise planmod.PlanError("; ".join(errs))
    cfg = planmod.load_config(project_dir)
    text = render_handoff(_priced(plan, cfg), git_state(project_dir), notes, now)
    out = planmod.navitok_dir(project_dir) / HANDOFF_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out, text


def summary(project_dir="."):
    """Short resume text for SessionStart, or None if there is no handoff."""
    nav = planmod.navitok_dir(project_dir)
    try:
        text = (nav / HANDOFF_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    resume = next((ln[len("> Resume:"):].strip() for ln in lines if ln.startswith("> Resume:")), None)
    if resume is None:  # hand-written handoff: first non-heading lines
        body = " ".join(ln.strip() for ln in lines if ln.strip() and not ln.startswith("#"))
        resume = body or None
    if not resume:
        return None
    written = next((ln.split("**Written:**", 1)[1].strip() for ln in lines if "**Written:**" in ln), None)
    parts = [f"navitok handoff{f' ({written})' if written else ''}: {resume}"]
    # The plan may have moved on since the handoff was written.
    try:
        _, plan = planmod._load_plan(project_dir)
        if not planmod.validate(plan):
            live = resume_line(plan, {})
            if live.split(" Last commit:")[0] not in resume:
                parts.append(f"plan.json now says: {live.strip()}")
    except (OSError, ValueError, planmod.PlanError, KeyError):
        pass
    parts.append("Full handoff: .navitok/HANDOFF.md. Run handoff.py fit before the next task.")
    out = " ".join(parts)
    return out if len(out) <= SUMMARY_MAX else out[:SUMMARY_MAX - 1] + "…"


# --- CLI ----------------------------------------------------------------------------

def hook_main(stdin=None):
    """SessionStart: plain stdout on exit 0 is added to Claude's context
    (docs/data-sources.md). Print the summary or nothing. Never fail."""
    try:
        stdin = stdin or sys.stdin
        raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read().encode("utf-8")
        payload = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
        if payload.get("source") in QUIET_SOURCES:
            return 0
        text = summary(payload.get("cwd") or os.getcwd())
        if text:
            out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else None
            if out is not None:
                out.write((text + "\n").encode("utf-8"))
                out.flush()
            else:
                sys.stdout.write(text + "\n")
    except Exception:  # never break the user's session
        pass
    return 0


def main(argv=None):
    import argparse
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok handoff and safe stopping")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit", help="per-task fit check (§10.2) from schedule.json")
    f.add_argument("--task")
    w = sub.add_parser("write", help="write .navitok/HANDOFF.md")
    w.add_argument("--note", action="append", default=[])
    sub.add_parser("summary", help="print the SessionStart resume summary")
    sub.add_parser("hook", help="SessionStart hook entry point")
    for name in ("fit", "write", "summary"):
        sub.choices[name].add_argument("--project-dir", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "hook":
        return hook_main()
    try:
        if args.cmd == "fit":
            _, plan = planmod._load_plan(args.project_dir)
            errs = planmod.validate(plan)
            if errs:
                raise planmod.PlanError("; ".join(errs))
            sched_path = planmod.navitok_dir(args.project_dir) / "schedule.json"
            try:
                sched = json.loads(sched_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                sched = None
            res = fit_check(plan, planmod.load_config(args.project_dir), sched, args.task)
            print(res["line"])
            return {"FITS": 0, "DONE": 0, "NO-FIT": 1, "UNKNOWN": 3}[res["verdict"]]
        if args.cmd == "write":
            path, text = write_handoff(args.project_dir, args.note)
            print(f"Wrote {path}")
            print(next((ln for ln in text.splitlines() if ln.startswith("> Resume:")), ""))
            return 0
        text = summary(args.project_dir)
        print(text or "No handoff (.navitok/HANDOFF.md not found).")
        return 0 if text else 1
    except (OSError, planmod.PlanError) as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
