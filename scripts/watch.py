"""navitok terminal panel (ROADMAP v0.9). Zero tokens, local files only.

  python3 watch.py [--project-dir DIR] [--interval S]      live panel, q to quit
  python3 watch.py --once                                  one plain-text frame
  python3 watch.py --plain                                 force the ANSI mode

Live display, in order of preference:
  1. curses (stdlib on Linux/macOS),
  2. ANSI full-screen redraw (stdlib only) where curses is missing, e.g. on
     Windows, whose Python has no _curses. Virtual-terminal processing is
     enabled via ctypes, so it also works in the legacy console. The q key is
     read with msvcrt on Windows and termios/select elsewhere.
  3. --once: a single plain frame, no escape codes.

It reads plan.json, schedule.json, calibration.json and the statusline's
usage_snapshot.json, and never writes them. A frame fits 80x24. Errors never
end the loop: they are shown on the panel and, with --log, appended to a file.
--duration S stops after S seconds (used for soak tests).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage_read  # noqa: E402

WIDTH, HEIGHT = 80, 24
BAR = 20
DONE = ("done", "skipped")
SNAPSHOT_FRESH_S = 600


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _f(x, unit="%"):
    """One number format for every percentage: one decimal."""
    return "?" + unit if not _num(x) else f"{float(x):.1f}{unit}"


def _rng(r):
    return f"{_f(r[0], '')}–{_f(r[1])}" if isinstance(r, list) and len(r) == 2 else ""


def _zone(dt):
    """The zone name the OS gives: an abbreviation on POSIX (CET, BST), the
    long name on Windows ("GMT Standard Time"; no tz database in the stdlib),
    or the UTC offset if there is none."""
    name = dt.tzname()
    if name:
        return name
    off = dt.utcoffset()
    mins = int(off.total_seconds() // 60) if off is not None else 0
    return f"UTC{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def _local(dt, tz=None):
    return dt.astimezone(tz)  # tz=None: the machine's local zone


def bar(pct, cells=BAR, mark=None):
    """Filled bar; `mark` (e.g. the threshold) is drawn as | inside it."""
    filled = 0 if not _num(pct) else max(0, min(cells, round(pct / 100 * cells)))
    cells_ = ["▓"] * filled + ["░"] * (cells - filled)
    if _num(mark):
        i = max(0, min(cells - 1, round(mark / 100 * cells) - 1))
        cells_[i] = "|"
    return "".join(cells_)


def _until(ts, now, tz=None):
    dt = usage_read.parse_ts(ts)
    if dt is None:
        return None
    loc = _local(dt, tz)
    when = f"{loc:%a %H:%M} {_zone(loc)}"
    secs = int((dt - now).total_seconds())
    if secs <= 0:
        return f"{when} (passed)"
    h, m = divmod(secs // 60, 60)
    d, h = divmod(h, 24)
    left = f"{d}d{h:02d}h" if d else f"{h}h{m:02d}m"
    return f"{when} (in {left})"


# --- data -------------------------------------------------------------------------

def gather(project_dir=".", now=None, tz=None):
    """Everything the panel shows, from local files only. `tz` overrides the
    display zone (tests); None means the machine's local zone."""
    now = now or datetime.now(timezone.utc)
    nav = Path(project_dir) / ".navitok"
    plan = _read(nav / "plan.json")
    sched = _read(nav / "schedule.json") or {}
    cal = _read(nav / "calibration.json") or {}
    snap = usage_read.read_statusline_snapshot(nav / "usage_snapshot.json", now=now)
    live = snap if snap and snap.get("age_s") is not None and snap["age_s"] <= SNAPSHOT_FRESH_S else None
    session, week = sched.get("session") or {}, sched.get("week") or {}
    s_pct = live["session_pct"] if live and _num(live.get("session_pct")) else session.get("used_pct")
    w_pct = live["weekly_pct"] if live and _num(live.get("weekly_pct")) else week.get("used_pct")
    if live:
        source = "statusline (live)"
    elif sched.get("usage_source"):
        source = sched["usage_source"] + (" (stale)" if sched.get("usage_stale") else "")
    else:
        source = "none: run /usage, or set up the statusline"
    return {
        "now": now,
        "tz": tz,
        "project": (plan or {}).get("project") or Path(project_dir).resolve().name,
        "nav_exists": nav.is_dir(),
        "plan": plan,
        "sched": sched,
        "cal": cal,
        "session_pct": s_pct,
        "weekly_pct": w_pct,
        "session_resets": (live or {}).get("session_resets_at") or session.get("resets_at"),
        "weekly_resets": (live or {}).get("weekly_resets_at") or week.get("resets_at"),
        "source": source,
    }


def frame(state, width=WIDTH, height=HEIGHT):
    """List of lines, each at most `width` wide, at most `height` lines."""
    now, tz = state["now"], state.get("tz")
    sched, cal, plan = state["sched"], state["cal"], state["plan"]
    loc = _local(now, tz)
    clock = f"{loc:%H:%M:%S} {_zone(loc)}"
    lines = [f"navitok · {state['project']}".ljust(max(0, width - len(clock) - 1)) + " " + clock]
    if not state["nav_exists"]:
        lines += ["", "No .navitok/ folder here. Run /navitok:plan in this project first."]
        return _fit(lines, width, height)
    threshold = sched.get("threshold") if _num(sched.get("threshold")) else 90
    s, w = state["session_pct"], state["weekly_pct"]
    left = f" · {_f(max(0.0, threshold - s))} left" if _num(s) else ""
    lines.append(f"Session {bar(s, mark=threshold)} {_f(s)} used · stop at {_f(threshold)}{left}")
    reset = _until(state["session_resets"], now, tz)
    if reset:
        lines.append(f"        resets {reset}")
    ext = cal.get("external") if isinstance(cal.get("external"), dict) else {}
    wk = ext.get("weekly") if ext.get("known") and isinstance(ext.get("weekly"), dict) else None
    ext_txt = (f" · external {_f(wk.get('this_week'))} (reserve {_f(ext.get('reserve_pct'))})"
               if wk else " · external unknown")
    lines.append(f"Week    {bar(w)} {_f(w)} used{ext_txt}")
    reset = _until(state["weekly_resets"], now, tz)
    if reset:
        lines.append(f"        resets {reset}")
    if cal.get("learned"):
        conf = f"Confidence {cal.get('confidence', 0)}/100 · {cal.get('n', 0)} learned sessions"
    else:
        conf = f"Confidence {cal.get('confidence', 0)}/100 · cold start ({cal.get('n', 0)} of 5 sessions)"
    lines.append(f"{conf} · usage: {state['source']}")
    lines.append("")

    cur = sched.get("current_release")
    if plan and isinstance(plan.get("releases"), list):
        place = {p.get("release"): p for p in sched.get("placement") or [] if isinstance(p, dict)}
        if cur:
            fits = sched.get("fits_today")
            verdict = {True: "fits this session", False: "does NOT fit: checkpoint"}.get(fits, "fit unknown")
            lines.append(f"Current {cur}: {_rng(sched.get('current_remaining_pct') or [0, 0])} left · {verdict}")
        else:
            lines.append("All releases done.")
        lines.append("Releases")
        for rel in plan["releases"]:
            if not isinstance(rel, dict):
                continue
            tasks = [t for t in rel.get("tasks") or [] if isinstance(t, dict)]
            done = sum(1 for t in tasks if t.get("status", "todo") in DONE)
            doing = any(t.get("status") == "doing" for t in tasks)
            status = "done" if tasks and done == len(tasks) else ("doing" if doing or done else "todo")
            p = place.get(rel.get("id"))
            where = f"week {p['week']} {p['session']}" if p else ""
            est = p.get("est_pct") if p else rel.get("est_pct")
            rng = _rng(est) if status != "done" else ""
            title = str(rel.get("title", ""))[:24]
            lines.append(f"  {str(rel.get('id', '?')):<7}{title:<25}{status:<6}{done:>2}/{len(tasks):<3}"
                         f"{rng:<13}{where}")
    else:
        lines.append("No plan yet: run /navitok:plan.")

    recent = [x for x in cal.get("sessions") or [] if isinstance(x, dict) and _num(x.get("error"))][-4:]
    if recent:
        lines.append("")
        lines.append("Recent sessions: estimate → actual (local)")
        for x in reversed(recent):
            flag = f"  [{', '.join(x['outlier'])}]" if x.get("outlier") else ""
            lines.append(f"  {_session_label(x, tz):<12}"
                         f"{_f(x.get('est_mid')):>6} → {_f(x.get('local_pct')):>6}  ({x['error']:+.1f}){flag}")
    for t in sched.get("replan") or []:
        if isinstance(t, dict) and t.get("reason"):
            lines.append(f"Replan suggested: {t['reason']}")
    return _fit(lines, width, height)


def _session_label(x, tz=None):
    """Release id, else the local end time: history without a release (e.g.
    several sessions a day) must not look like one session shown twice."""
    if x.get("release"):
        return str(x["release"])
    dt = usage_read.parse_ts(x.get("ts_end"))
    return f"{_local(dt, tz):%m-%d %H:%M}" if dt else "?"


def _fit(lines, width, height, footer="q quit"):
    """Truncate to the terminal: keep the header, the footer and the top rows."""
    width, height = max(20, width), max(5, height)
    body = [ln if len(ln) <= width else ln[:width - 1] + "…" for ln in lines]
    if len(body) > height - 1:
        body = body[:height - 2] + ["…"]
    return body + [footer[:width]]


# --- live loops -------------------------------------------------------------------------

def enable_vt():
    """Windows: turn on ANSI escape processing for the console (legacy conhost
    too). Returns True if escapes are expected to work."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # not a console (redirected): plain text is fine
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (OSError, AttributeError, ImportError):
        return False


class Keys:
    """Non-blocking single-key reader: msvcrt on Windows, termios elsewhere."""

    def __init__(self):
        self.ok = sys.stdin is not None and sys.stdin.isatty()
        self._old = None
        if self.ok and os.name != "nt":
            try:
                import termios
                import tty
                self._old = termios.tcgetattr(sys.stdin.fileno())
                tty.setcbreak(sys.stdin.fileno())
            except (ImportError, OSError, ValueError):
                self.ok = False

    def wait(self, seconds):
        """Sleep up to `seconds`; return a pressed key or None."""
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None
            if not self.ok:
                time.sleep(left)
                return None
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(min(0.05, left))
            else:
                import select
                r, _, _ = select.select([sys.stdin], [], [], left)
                if r:
                    return sys.stdin.read(1)

    def close(self):
        if self._old is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old)


def _safe_frame(project_dir, size, log):
    try:
        return frame(gather(project_dir), *size)
    except Exception as exc:  # show it, log it, keep going
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"{usage_read.iso(datetime.now(timezone.utc))} {type(exc).__name__}: {exc}\n")
        return _fit([f"navitok: error reading data ({type(exc).__name__}); retrying"], *size)


def run_ansi(project_dir, interval, duration=None, log=None, out=None):
    out = out or sys.stdout
    vt = enable_vt()
    keys = Keys()
    frames = 0
    start = time.monotonic()
    try:
        if vt:
            out.write("\x1b[?25l")  # hide cursor
        while True:
            size = shutil.get_terminal_size((WIDTH, HEIGHT))
            lines = _safe_frame(project_dir, (size.columns, size.lines), log)
            body = "\n".join(lines)
            out.write(("\x1b[H\x1b[2J" + body) if vt else body + "\n\n")
            out.flush()
            frames += 1
            if duration is not None and time.monotonic() - start >= duration:
                break
            if (keys.wait(interval) or "").lower() == "q":
                break
    except KeyboardInterrupt:
        pass
    finally:
        keys.close()
        if vt:
            out.write("\x1b[?25h\n")
            out.flush()
    return frames


def run_curses(project_dir, interval, duration=None, log=None):
    import curses

    def loop(scr):
        curses.curs_set(0)
        scr.timeout(int(interval * 1000))
        start = time.monotonic()
        frames = 0
        while True:
            h, w = scr.getmaxyx()
            scr.erase()
            for y, ln in enumerate(_safe_frame(project_dir, (w - 1, h), log)[:h]):
                try:
                    scr.addstr(y, 0, ln[:w - 1])
                except curses.error:
                    pass
            scr.refresh()
            frames += 1
            if duration is not None and time.monotonic() - start >= duration:
                return frames
            if scr.getch() in (ord("q"), ord("Q")):
                return frames

    return curses.wrapper(loop)


def has_curses():
    try:
        import curses  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv=None):
    import argparse
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok terminal panel (q to quit)")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--interval", type=float, default=5.0, help="refresh seconds (default 5)")
    ap.add_argument("--once", action="store_true", help="print one plain frame and exit")
    ap.add_argument("--plain", action="store_true", help="use the ANSI mode even if curses exists")
    ap.add_argument("--duration", type=float, help="stop after this many seconds")
    ap.add_argument("--log", help="append errors and a final summary line to this file")
    args = ap.parse_args(argv)
    interval = max(1.0, args.interval)
    if args.once:
        size = shutil.get_terminal_size((WIDTH, HEIGHT))
        print("\n".join(_safe_frame(args.project_dir, (size.columns, size.lines), args.log)))
        return 0
    started = time.monotonic()
    if has_curses() and not args.plain and sys.stdout.isatty():
        mode, frames = "curses", run_curses(args.project_dir, interval, args.duration, args.log)
    else:
        mode, frames = "ansi", run_ansi(args.project_dir, interval, args.duration, args.log)
    if args.log:
        with open(args.log, "a", encoding="utf-8") as f:
            f.write(f"{usage_read.iso(datetime.now(timezone.utc))} done: mode={mode} frames={frames} "
                    f"seconds={time.monotonic() - started:.0f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
