"""navitok statusline segment (ROADMAP v0.8). Zero tokens, local files only.

  statusline.py [--wrap CMD]
      Statusline entry point. Reads Claude Code's statusline JSON on stdin and
      prints one line, e.g.
          v0.3 ▓▓▓░░ 62% · fits · week 31% (ext 8%) · conf 40
      In a project with .navitok/ it also saves stdin's `rate_limits` to
      .navitok/usage_snapshot.json, the fresh account-wide reading that hooks
      and schedule.py prefer over the stale usage cache.
      --wrap CMD runs the user's own statusline command with the same stdin and
      appends navitok's segment to its last line, so the existing line keeps
      working. Outside navitok projects only the wrapped output is printed.
      Never fails: any error degrades to less output, always exit 0.

  statusline.py setup [--settings PATH] [--apply]
  statusline.py remove [--settings PATH] [--apply]
      Show (default) or apply the `statusLine` change in the user's
      settings.json. An existing statusline is wrapped, never replaced. --apply
      is only run after the user explicitly approved the shown change; it keeps
      a backup next to the file. `remove` restores the wrapped command.

      When the context reaches `context_hint_tokens` (default 150k, in
      .navitok/config.json; 0 or false turns it off), it adds
          ctx 160k · checkpoint + new session
      because every message re-reads the whole context: /navitok:checkpoint
      writes the handoff, and a fresh session continues from it.

Speed: imports only the standard library, reads at most four small files,
no network, no model calls.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

SNAPSHOT_FILE = "usage_snapshot.json"
WRAP_TIMEOUT_S = 3.0
BAR_CELLS = 5
SEP = " · "
WRAP_SEP = " │ "
BACKUP_SUFFIX = ".navitok-backup"
CONTEXT_HINT_TOKENS = 150_000  # default; .navitok/config.json `context_hint_tokens` (0 = off)
CONTEXT_HINT = "checkpoint + new session"


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _pct(x):
    return f"{x:.0f}%" if _num(x) else "?%"


def project_dir(payload):
    ws = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    for d in (ws.get("project_dir"), ws.get("current_dir"), payload.get("cwd")):
        if isinstance(d, str) and d and (Path(d) / ".navitok").is_dir():
            return Path(d)
    return None


# --- snapshot -------------------------------------------------------------------

def save_snapshot(nav, payload, now=None):
    """Persist rate_limits (statusline docs shape) for hooks. Written only when
    the numbers changed, or the last write is older than a minute, so the
    reading's age stays meaningful without rewriting on every refresh."""
    rl = payload.get("rate_limits")
    if not isinstance(rl, dict) or not any(isinstance(rl.get(k), dict) for k in ("five_hour", "seven_day")):
        return False
    now = time.time() if now is None else now
    path = nav / SNAPSHOT_FILE
    old = _read_json(path)
    if old and old.get("rate_limits") == rl and _num(old.get("captured_at")) and now - old["captured_at"] < 60:
        return False
    data = {"schema": 1, "captured_at": int(now), "rate_limits": rl}
    tmp = path.with_name(SNAPSHOT_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return True


# --- segment ---------------------------------------------------------------------

def bar(pct, cells=BAR_CELLS):
    if not _num(pct):
        return "░" * cells
    full = max(0, min(cells, round(pct / 100 * cells)))
    return "▓" * full + "░" * (cells - full)


def context_tokens(payload):
    """Tokens in the context after the last response: what every next message
    re-reads. Statusline docs: context_window.total_input_tokens (input + cache
    creation + cache read); falls back to the current_usage sum. None if unknown."""
    cw = payload.get("context_window")
    if not isinstance(cw, dict):
        return None
    n = cw.get("total_input_tokens")
    if _num(n):
        return n
    cu = cw.get("current_usage")
    if isinstance(cu, dict):
        vals = [cu.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
        if any(_num(v) for v in vals):
            return sum(v for v in vals if _num(v))
    return None


def context_hint(nav, payload):
    """'ctx 160k · checkpoint + new session' once the context reaches the
    threshold, else ''. Silent when the field is missing or the hint is off."""
    cfg = _read_json(nav / "config.json") or {}
    limit = cfg.get("context_hint_tokens", CONTEXT_HINT_TOKENS)
    if limit is False or limit is None:
        return ""
    if not _num(limit) or limit < 0:
        limit = CONTEXT_HINT_TOKENS
    n = context_tokens(payload)
    if not limit or n is None or n < limit:
        return ""
    return f"ctx {n / 1000:.0f}k{SEP}{CONTEXT_HINT}"


def segment(nav, payload):
    line = _segment(nav, payload)
    hint = context_hint(nav, payload)
    return line + SEP + hint if hint else line


def _segment(nav, payload):
    """One line from schedule.json, calibration.json and the live rate_limits."""
    sched = _read_json(nav / "schedule.json")
    cal = _read_json(nav / "calibration.json") or {}
    rl = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else {}
    five = rl.get("five_hour") if isinstance(rl.get("five_hour"), dict) else {}
    week = rl.get("seven_day") if isinstance(rl.get("seven_day"), dict) else {}
    live_s, live_w = five.get("used_percentage"), week.get("used_percentage")
    if sched is None:
        return f"navitok: no schedule yet{SEP}session {_pct(live_s)}" if _num(live_s) else "navitok: no schedule yet"
    s_pct = live_s if _num(live_s) else (sched.get("session") or {}).get("used_pct")
    w_pct = live_w if _num(live_w) else (sched.get("week") or {}).get("used_pct")
    mark = "" if _num(live_s) or not sched.get("usage_stale") else "~"  # ~ = stale reading
    rel = sched.get("current_release")
    parts = []
    if rel is None:
        parts.append(f"done {bar(s_pct)} {mark}{_pct(s_pct)}")
    else:
        parts.append(f"{rel} {bar(s_pct)} {mark}{_pct(s_pct)}")
        threshold, remaining = sched.get("threshold"), sched.get("current_remaining_pct")
        if sched.get("plan") == "api":
            pass
        elif _num(s_pct) and _num(threshold) and isinstance(remaining, list) and len(remaining) == 2:
            parts.append("fits" if s_pct + remaining[1] <= threshold else "no fit: checkpoint")
        else:
            parts.append("fit ?")
    ext = cal.get("external") if isinstance(cal.get("external"), dict) else {}
    wk = ext.get("weekly") if ext.get("known") and isinstance(ext.get("weekly"), dict) else None
    ext_txt = f" (ext {wk['this_week']:.0f}%)" if wk and _num(wk.get("this_week")) else ""
    if _num(w_pct):
        parts.append(f"week {_pct(w_pct)}{ext_txt}")
    conf = cal.get("confidence")
    parts.append(f"conf {conf:.0f}" if _num(conf) else "cold start")
    return SEP.join(parts)


def run_wrapped(cmd, raw):
    """The user's own statusline output (stripped of trailing newlines), or ''."""
    # Claude Code runs statusline commands in a POSIX shell (Git Bash on
    # Windows), so run the wrapped command the same way, not through cmd.exe.
    args, shell = cmd, True
    if os.name == "nt":
        import shutil
        sh = shutil.which("sh") or shutil.which("bash")  # sh first: System32 bash.exe is WSL
        if sh:
            args, shell = [sh, "-c", cmd], False
    try:
        res = subprocess.run(args, shell=shell, input=raw, capture_output=True, timeout=WRAP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    if res.returncode != 0:
        return ""
    return res.stdout.decode("utf-8", errors="replace").rstrip("\r\n")


def render(raw, wrap=None, now=None):
    try:
        payload = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}
    own = run_wrapped(wrap, raw) if wrap else ""
    seg = ""
    try:
        proj = project_dir(payload)
        if proj is not None:
            nav = proj / ".navitok"
            try:
                save_snapshot(nav, payload, now)
            except OSError:
                pass
            seg = segment(nav, payload)
    except Exception:  # never blank the user's line
        seg = ""
    if own and seg:
        return own + WRAP_SEP + seg
    return own or seg


# --- setup -------------------------------------------------------------------------

def default_settings_path():
    return Path(os.path.expanduser("~")) / ".claude" / "settings.json"


def _q(path):
    """Quote for the POSIX shell Claude Code uses (Git Bash on Windows)."""
    return shlex.quote(str(path).replace("\\", "/"))


def navitok_command(wrap=None):
    cmd = f"{_q(sys.executable)} {_q(Path(__file__).resolve())}"
    return cmd + (f" --wrap {shlex.quote(wrap)}" if wrap else "")


def is_navitok(cmd):
    return isinstance(cmd, str) and "statusline.py" in cmd and "navitok" in cmd.lower()


def unwrap(cmd):
    """The user's original command inside a navitok command, or None."""
    try:
        args = shlex.split(cmd)
    except ValueError:
        return None
    return args[args.index("--wrap") + 1] if "--wrap" in args[:-1] else None


def plan_change(settings, action="setup"):
    """(new statusLine or None to delete, message). Pure."""
    cur = settings.get("statusLine") if isinstance(settings.get("statusLine"), dict) else None
    cur_cmd = cur.get("command") if cur else None
    if action == "remove":
        if not is_navitok(cur_cmd):
            return cur, "No navitok statusline is configured. Nothing to change."
        orig = unwrap(cur_cmd)
        if orig:
            new = dict(cur, command=orig)
            return new, f"Restore your own statusline command: {orig}"
        return None, "Remove the navitok statusline (you had none before)."
    if is_navitok(cur_cmd):
        return cur, "The navitok statusline is already configured. Nothing to change."
    if cur_cmd:
        new = dict(cur, command=navitok_command(wrap=cur_cmd))
        return new, ("Wrap your existing statusline: its output stays first, navitok's segment is "
                     "appended after ' │ '.")
    return {"type": "command", "command": navitok_command(), "padding": 0}, "Add the navitok statusline."


def setup(settings_path=None, apply=False, action="setup"):
    path = Path(settings_path) if settings_path else default_settings_path()
    exists = path.exists()
    settings = _read_json(path) if exists else {}
    if exists and settings is None:
        return 2, f"{path} is not a JSON object; not touching it."
    new, msg = plan_change(settings, action)
    old = settings.get("statusLine")
    if new == old:
        return 0, msg
    lines = [msg, f"File: {path}", "Current statusLine: " + json.dumps(old, ensure_ascii=False),
             "New statusLine:     " + json.dumps(new, ensure_ascii=False)]
    if not apply:
        lines.append("Nothing written. Run again with --apply only after the user approves this change.")
        return 0, "\n".join(lines)
    if exists:
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        backup.write_bytes(path.read_bytes())
        lines.append(f"Backup: {backup}")
    out = dict(settings)
    if new is None:
        out.pop("statusLine", None)
    else:
        out["statusLine"] = new
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    lines.append("Written. The statusline picks it up on its next refresh.")
    return 0, "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("setup", "remove"):
        import argparse
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        ap = argparse.ArgumentParser(description="navitok statusline setup")
        ap.add_argument("action", choices=("setup", "remove"))
        ap.add_argument("--settings", help="settings.json (default ~/.claude/settings.json)")
        ap.add_argument("--apply", action="store_true", help="write the change (needs the user's approval)")
        args = ap.parse_args(argv)
        rc, text = setup(args.settings, args.apply, args.action)
        print(text)
        return rc
    wrap = None
    if len(argv) >= 2 and argv[0] == "--wrap":
        wrap = argv[1]
    try:
        raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
        line = render(raw, wrap)
        if line:
            sys.stdout.buffer.write((line + "\n").encode("utf-8"))
            sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
