"""Session recorder hooks: SessionStart / Stop / SessionEnd.

Reads the hook JSON from stdin. It records only when the project already has
a `.navitok/` directory, so navitok never creates files in projects the user
has not set up. It is always silent: no stdout, exit 0, even on errors.
SessionStart stdout would be added to Claude's context, and Stop exit 2
would block Claude from stopping.

  start  save a start snapshot (account-wide % + local tokens so far)
  stop   refresh the "latest" snapshot (runs after every response)
  end    combine start + latest into one ledger record and append it.
         SessionEnd has a ~1.5 s budget, so the transcript is not re-read here.

On start, sessions left over without a SessionEnd (crash, kill) are flushed
as records with ended_cleanly=false.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger  # noqa: E402
import usage_read  # noqa: E402

STATE_DIR = "sessions"
SNAPSHOT_FILE = "usage_snapshot.json"  # written by the statusline (v0.8)


def _now():
    return datetime.now(timezone.utc)


def _navitok_dir(payload):
    cwd = payload.get("cwd") or os.getcwd()
    d = Path(cwd) / ".navitok"
    return d if d.is_dir() else None


def _state_path(nav, session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")[:100]
    return nav / STATE_DIR / f"{safe}.json"


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def snapshot(payload, nav, now=None, cache_path=None, read_tokens=True):
    now = now or _now()
    reading = usage_read.account_usage(nav / SNAPSHOT_FILE, cache_path, now=now)
    tokens = None
    if read_tokens and payload.get("transcript_path"):
        tokens = usage_read.transcript_tokens(payload["transcript_path"])
    effort = payload.get("effort")
    return {
        "ts": usage_read.iso(now),
        "account": reading,
        "tokens": tokens["tokens"] if tokens else None,
        "by_model": {m: sum(v.values()) for m, v in tokens["by_model"].items()} if tokens else None,
        "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
        "effort": effort.get("level") if isinstance(effort, dict) else (effort if isinstance(effort, str) else None),
    }


def _diff_tokens(end, start):
    if end is None:
        return None
    start = start or {}
    return {k: max(0, (end.get(k) or 0) - (start.get(k) or 0)) for k in ledger.TOKEN_KEYS}


def _diff_models(end, start):
    if not end:
        return None
    start = start or {}
    out = {m: max(0, v - start.get(m, 0)) for m, v in end.items()}
    return {m: v for m, v in out.items() if v} or None


def _pct(reading, key):
    return reading.get(key) if reading else None


def build_record(state, end_reading=None, ended_cleanly=True, reason=None, ts_end=None):
    start = state.get("start") or {}
    last = state.get("last") or start
    # Never reuse the start reading as the end reading: that would fake a 0 delta.
    end_account = end_reading or (state["last"].get("account") if state.get("last") else None)
    start_account = start.get("account")
    models = _diff_models(last.get("by_model"), start.get("by_model"))
    model = start.get("model") or (max(models, key=models.get) if models else None)
    notes = []
    for label, r in (("start", start_account), ("end", end_account)):
        if r is None:
            notes.append(f"{label}: no account reading")
        elif r.get("stale"):
            notes.append(f"{label}: account reading from {r['source']} is stale (age {r['age_s']}s)")
    if reason:
        notes.append(f"end reason: {reason}")
    sources = {r["source"] for r in (start_account, end_account) if r}
    return ledger.new_record(
        ts_start=start.get("ts") or last.get("ts"),
        ts_end=ts_end or last.get("ts"),
        session_id=state.get("session_id"),
        model=model,
        effort=last.get("effort") or start.get("effort"),
        source=sources.pop() if len(sources) == 1 else "transcript",
        account_session_pct_start=_pct(start_account, "session_pct"),
        account_session_pct_end=_pct(end_account, "session_pct"),
        account_weekly_pct_start=_pct(start_account, "weekly_pct"),
        account_weekly_pct_end=_pct(end_account, "weekly_pct"),
        local_tokens=_diff_tokens(last.get("tokens"), start.get("tokens")),
        local_tokens_by_model=models,
        ended_cleanly=ended_cleanly,
        notes="; ".join(notes),
    )


def on_start(payload, nav, now=None, cache_path=None):
    session_id = payload.get("session_id")
    # Flush sessions that never got a SessionEnd.
    for stale in sorted((nav / STATE_DIR).glob("*.json")) if (nav / STATE_DIR).is_dir() else []:
        state = _read_json(stale)
        if state and state.get("session_id") != session_id and state.get("start"):
            ledger.append(build_record(state, ended_cleanly=False, reason="no SessionEnd"),
                          nav / "history.jsonl")
        if not state or state.get("session_id") != session_id:
            stale.unlink(missing_ok=True)
    path = _state_path(nav, session_id)
    if _read_json(path):  # resume/compact of a live session: keep the original start
        return
    _write_json(path, {"session_id": session_id,
                       "start": snapshot(payload, nav, now, cache_path)})


def on_stop(payload, nav, now=None, cache_path=None):
    path = _state_path(nav, payload.get("session_id"))
    state = _read_json(path) or {"session_id": payload.get("session_id")}
    snap = snapshot(payload, nav, now, cache_path)
    state.setdefault("start", snap)
    state["last"] = snap
    _write_json(path, state)


def on_end(payload, nav, now=None, cache_path=None):
    path = _state_path(nav, payload.get("session_id"))
    state = _read_json(path)
    if not state or not state.get("start"):
        return
    now = now or _now()
    end_reading = usage_read.account_usage(nav / SNAPSHOT_FILE, cache_path, now=now)
    ledger.append(build_record(state, end_reading, reason=payload.get("reason"), ts_end=usage_read.iso(now)),
                  nav / "history.jsonl")
    path.unlink(missing_ok=True)


HANDLERS = {"start": on_start, "stop": on_stop, "end": on_end}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        handler = HANDLERS[argv[0]]
        # Claude Code sends UTF-8. Do not rely on sys.stdin's encoding: on Windows it
        # is the ANSI code page (e.g. cp1254), which garbles non-ASCII paths.
        raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
        payload = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
        nav = _navitok_dir(payload)
        if nav:
            handler(payload, nav)
    except Exception as exc:  # never break the user's session
        try:
            if "nav" in locals() and nav:
                with open(nav / "hook-errors.log", "a", encoding="utf-8") as f:
                    f.write(f"{usage_read.iso(_now())} {argv[:1]} {type(exc).__name__}: {exc}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
