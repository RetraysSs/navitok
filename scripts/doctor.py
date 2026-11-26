"""navitok doctor and first-run wizard (ROADMAP v0.13), behind /navitok:setup.

  doctor.py check [--project-dir DIR] [--json]
      One table of everything navitok can use: Python, a POSIX shell (Git Bash
      on Windows, `sh -c 'echo ok'` is the only command it runs), the project's .navitok/
      state, the account usage source, the statusline, output trimming,
      Superpowers and Graphify. Each row: ✅ / ❌, why it helps, and the command
      that would fix a gap. Read-only: it reads local files and PATH, runs
      only that shell probe, installs nothing, changes nothing.

  doctor.py wizard [--plan P] [--mode strict|flex] [--trim on|off]
                   [--statusline on|off] [--project-dir DIR]
      Write the user's answers to .navitok/config.json (only the keys given;
      the rest is kept). It never edits Claude Code's settings: for the
      statusline it only prints the change `statusline.py setup` would make,
      which is applied only after the user approves it.

Stdlib only. No network, no model calls.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "integrations"))
import estimate  # noqa: E402
import plan as planmod  # noqa: E402
import statusline  # noqa: E402
import usage_read  # noqa: E402
import graphify as gfy  # noqa: E402
import superpowers as spw  # noqa: E402

MIN_PY = (3, 10)
OK, GAP = "✅", "❌"

# Verified against each tool's own README (docs/data-sources.md, v0.13).
SUPERPOWERS_INSTALL = ["$ /plugin install superpowers@claude-plugins-official",
                       "or: /plugin marketplace add obra/superpowers-marketplace, then "
                       "/plugin install superpowers@superpowers-marketplace"]
GRAPHIFY_INSTALL = ["$ uv tool install graphifyy", "or: pipx install graphifyy"]
GRAPHIFY_BUILD = ["$ graphify update .", "builds the graph from the code (AST only, no model calls)"]

TRIM_PATHS = ("two paths: the PostToolUse hook trims long output of commands that succeed; "
              "tests and builds go through `scripts/run.py -- CMD ...`, because Claude Code "
              "gives no PostToolUse to commands that exit non-zero")


def _q(path):
    return shlex.quote(str(path).replace("\\", "/"))


def _py():
    return _q(sys.executable)


def _script(name):
    return f"{_py()} {_q(SCRIPTS / name)}"


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _row(key, label, ok, detail, why, fix=(), required=False):
    """One table row. In `fix`, a command starts with "$ "; other items are notes."""
    return {"key": key, "label": label, "ok": bool(ok), "required": required,
            "detail": detail, "why": why, "fix": list(fix) if not ok else []}


# --- checks ------------------------------------------------------------------------

def check_python(version=None, executable=None):
    v = tuple(version or sys.version_info[:3])
    ok = v[:2] >= MIN_PY
    return _row("python", "Python", ok, f"{'.'.join(map(str, v))} ({executable or sys.executable})",
                "navitok's scripts, hooks and statusline need Python 3.10+ (stdlib only)",
                ["install Python 3.10 or newer from https://www.python.org/downloads/"], required=True)


GIT_FOR_WINDOWS = ["install Git for Windows (it includes Git Bash): https://git-scm.com/downloads/win",
                   "$ winget install --id Git.Git -e",
                   "then restart Claude Code; if Git Bash is installed somewhere Claude Code does not "
                   "find it, set CLAUDE_CODE_GIT_BASH_PATH to its bash.exe"]


def find_shell(which=shutil.which, env=None, nt=None):
    """Path of the POSIX shell Claude Code would run hook and statusline commands
    in, or None. On Windows that is Git Bash (hooks docs): CLAUDE_CODE_GIT_BASH_PATH,
    then sh/bash on PATH (never System32's bash.exe, which is WSL), then the
    bash.exe next to git.exe."""
    env = os.environ if env is None else env
    nt = (os.name == "nt") if nt is None else nt
    if not nt:
        return which("sh")
    cand = [env.get("CLAUDE_CODE_GIT_BASH_PATH"), which("sh"), which("bash")]
    git = which("git")
    if git:  # ...\Git\cmd\git.exe or ...\Git\mingw64\bin\git.exe
        for up in Path(git).parents:
            if up.name.lower() == "git":
                cand.append(str(up / "bin" / "bash.exe"))
                break
    for c in cand:
        if c and "system32" not in c.lower() and Path(c).is_file():
            return c
    return None


def _run_sh(sh):
    import subprocess
    res = subprocess.run([sh, "-c", "echo ok"], capture_output=True, timeout=10)
    return res.returncode == 0 and res.stdout.strip() == b"ok"


def check_shell(which=shutil.which, run=_run_sh, env=None, nt=None):
    nt = (os.name == "nt") if nt is None else nt
    sh = find_shell(which, env, nt)
    try:
        ok = bool(sh) and run(sh)
    except Exception:  # OSError, timeout: a shell that does not run is a gap
        ok = False
    if ok:
        detail = f"works: {sh}"
    elif sh:
        detail = f"found but `sh -c 'echo ok'` failed: {sh}"
    else:
        detail = "no Git Bash found" if nt else "no sh on PATH"
    fix = GIT_FOR_WINDOWS if nt else ["install a POSIX sh (it is part of every Linux and macOS base system)"]
    return _row("shell", "POSIX shell (sh)", ok, detail,
                "Claude Code runs navitok's hooks and statusline as shell commands: sh on macOS and "
                "Linux, Git Bash on Windows (without it, PowerShell, where they fail)",
                fix, required=True)


def check_project(project_dir):
    nav = Path(project_dir) / ".navitok"
    have = {name: (nav / name).is_file() for name in ("config.json", "plan.json", "schedule.json")}
    if not nav.is_dir():
        detail = "no .navitok/ folder: navitok is not set up in this project"
    else:
        detail = ", ".join(f"{n} {'yes' if v else 'no'}" for n, v in have.items())
        cfg = _read_json(nav / "config.json")
        if cfg:
            detail += f" (plan {cfg.get('plan', '?')}, mode {cfg.get('mode', '?')})"
    fix = []
    if not have["config.json"]:
        fix.append("answer the /navitok:setup wizard (writes .navitok/config.json)")
    if not have["plan.json"]:
        fix.append("$ /navitok:plan")
    return _row("project", ".navitok/ project", have["config.json"] and have["plan.json"], detail,
                "the plan, schedule and session history live here; the hooks only run where it exists",
                fix)


def check_usage(project_dir, home):
    snap = Path(project_dir) / ".navitok" / statusline.SNAPSHOT_FILE
    r = usage_read.account_usage(snapshot_path=snap, cache_path=str(Path(home) / ".claude.json"))
    if r is None:
        detail, ok = "no reading: no statusline snapshot and no usage cache", False
    else:
        age = "unknown age" if r["age_s"] is None else f"{r['age_s'] // 60} min old"
        detail = (f"{r['source']} ({'stale' if r['stale'] else 'fresh'}, {age}): "
                  f"session {r['session_pct']}%, week {r['weekly_pct']}%")
        ok = not r["stale"]
    return _row("usage", "Account usage source", ok, detail,
                "the fit check needs a fresh account-wide %, including claude.ai and other machines; "
                "the statusline snapshot is the documented, fresh source (the usage cache is "
                "undocumented and often stale)",
                ["set up the statusline (see the statusline row)",
                 "or give a /usage reading: /navitok:status, then the session % and weekly %"])


def statusline_state(project_dir, home):
    """(state, file): state is 'navitok', 'custom' or 'none'. Highest scope first
    (settings docs: project local > shared project > user)."""
    files = [Path(project_dir) / ".claude" / "settings.local.json",
             Path(project_dir) / ".claude" / "settings.json",
             Path(home) / ".claude" / "settings.json"]
    for f in files:
        cfg = _read_json(f)
        sl = cfg.get("statusLine") if cfg else None
        if isinstance(sl, dict) and sl.get("command"):
            return ("navitok" if statusline.is_navitok(sl["command"]) else "custom"), f
    return "none", None


def check_statusline(project_dir, home):
    state, f = statusline_state(project_dir, home)
    detail = {"navitok": f"navitok's statusline ({f})",
              "custom": f"your own statusline, not wrapped yet ({f})",
              "none": "no statusline configured"}[state]
    fix = [f"$ {_script('statusline.py')} setup",
           ("wraps yours (it stays first); " if state == "custom" else "")
           + "shows the change, writes nothing; after you approve it, the same command with "
           "--apply (keeps a backup)"]
    return _row("statusline", "Statusline", state == "navitok", detail,
                "shows session left and fit at zero tokens, and saves the fresh usage snapshot "
                "the fit check prefers", fix)


def check_trimming(project_dir):
    cfg = _read_json(Path(project_dir) / ".navitok" / "config.json") or {}
    opt = cfg.get("trim_output")
    on = opt is True or (isinstance(opt, dict) and opt.get("enabled") is True)
    return _row("trimming", "Output trimming", on, ("on: " if on else "off (default): ") + TRIM_PATHS,
                "keeps long test and build output out of the context; the full output is saved "
                "to .navitok/logs/",
                [f"$ {_script('doctor.py')} wizard --trim on"])


def check_superpowers(project_dir, home):
    info = spw.detect(home=home, project_dir=project_dir)
    detail = (f"installed {info['version'] or ''}".strip() if info["installed"] else "not installed")
    if info["plans"]:
        detail += f"; {len(info['plans'])} plan file(s) in {spw.PLANS_DIR}"
    return _row("superpowers", "Superpowers (optional)", info["installed"], detail,
                "navitok works with its plan files: /navitok:plan can ingest them "
                "(detection reads an undocumented registry, see docs/data-sources.md)",
                SUPERPOWERS_INSTALL)


def check_graphify(project_dir, which=shutil.which):
    cli = which("graphify")
    info = gfy.detect(project_dir)
    if info["present"]:
        detail = f"graph: {info['nodes']} nodes, {info['edges']} edges"
    else:
        detail = "no graph (graphify-out/graph.json)"
    detail += "; CLI on PATH" if cli else "; CLI not on PATH"
    fix = [] if cli else list(GRAPHIFY_INSTALL)
    if not info["present"]:
        fix.extend(GRAPHIFY_BUILD)
    return _row("graphify", "Graphify (optional)", info["present"], detail,
                "navitok works with its graph: tasks are scoped and priced from the files they touch",
                fix)


def run_checks(project_dir=".", home=None, which=shutil.which, run_sh=_run_sh):
    home = home or os.path.expanduser("~")
    return [check_python(), check_shell(which, run_sh), check_project(project_dir), check_usage(project_dir, home),
            check_statusline(project_dir, home), check_trimming(project_dir),
            check_superpowers(project_dir, home), check_graphify(project_dir, which)]


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(rows):
    out = ["| | Check | State | Why it helps | To enable |", "|---|---|---|---|---|"]
    for r in rows:
        fix = "<br>".join(f"`{_cell(c[2:])}`" if c.startswith("$ ") else _cell(c)
                          for c in r["fix"]) or "–"
        out.append(f"| {OK if r['ok'] else GAP} | {r['label']} | {_cell(r['detail'])} | "
                   f"{_cell(r['why'])} | {fix} |")
    req = [r for r in rows if r["required"] and not r["ok"]]
    opt = [r for r in rows if not r["required"] and not r["ok"]]
    out.append("")
    out.append(("Required: missing " + ", ".join(r["label"] for r in req)) if req else "Required: all OK.")
    out.append(f"Not set up: {', '.join(r['label'] for r in opt)}." if opt else "Everything is set up.")
    out.append("Nothing was installed or changed. Commands run only after you approve them.")
    return "\n".join(out)


# --- wizard ------------------------------------------------------------------------

def wizard(project_dir=".", plan=None, mode=None, trim=None, statusline_on=None, home=None):
    """Write the given answers to config.json. Returns the lines to show."""
    home = home or os.path.expanduser("~")
    cfg = planmod.write_config(project_dir, plan=plan, mode=mode)
    path = Path(project_dir) / ".navitok" / "config.json"
    data = _read_json(path) or {}
    if trim is not None:
        cur = data.get("trim_output")
        data["trim_output"] = dict(cur, enabled=trim) if isinstance(cur, dict) else trim
    if statusline_on is not None:
        data["statusline"] = statusline_on
    planmod._write_json(path, data)
    lines = [f"Wrote {path}: plan {cfg['plan']}, mode {cfg['mode']}, "
             f"trimming {'on' if _trim_on(data) else 'off'}, statusline {'wanted' if data.get('statusline') else 'not wanted'}."]
    if _trim_on(data):
        lines.append("Trimming has " + TRIM_PATHS + ". Full output is kept in .navitok/logs/.")
    if data.get("statusline"):
        state, _ = statusline_state(project_dir, home)
        if state == "navitok":
            lines.append("The navitok statusline is already configured.")
        else:
            code, msg = statusline.setup(Path(home) / ".claude" / "settings.json", apply=False)
            lines.append("Statusline: this change is proposed, not made:")
            lines.append(msg)
    return lines


def _trim_on(data):
    opt = data.get("trim_output")
    return opt is True or (isinstance(opt, dict) and opt.get("enabled") is True)


def _onoff(v):
    if v is None:
        return None
    if v not in ("on", "off"):
        raise argparse.ArgumentTypeError("expected on or off")
    return v == "on"


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok doctor and setup wizard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    w = sub.add_parser("wizard")
    w.add_argument("--plan")
    w.add_argument("--mode", choices=planmod.MODES)
    w.add_argument("--trim", type=_onoff)
    w.add_argument("--statusline", type=_onoff)
    for p in (c, w):
        p.add_argument("--project-dir", default=".")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            rows = run_checks(args.project_dir)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else render(rows))
            return 0
        print("\n".join(wizard(args.project_dir, args.plan, args.mode, args.trim, args.statusline)))
        return 0
    except (OSError, planmod.PlanError, estimate.EstimateError) as exc:
        print(f"doctor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
