"""Usage data source adapters (stdlib only).

Two signals (see docs/data-sources.md):

* Local tokens: summed from Claude Code session transcripts. The format is
  undocumented, so it is treated as UNSTABLE.
* Account-wide %: the 5-hour and 7-day utilization, read through a fallback
  chain: statusline snapshot -> usage cache in ~/.claude.json (UNSTABLE) ->
  stale reading -> nothing (the user reports /usage manually).

These functions never call the network or the model. They also never return
account identifiers or message content.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_AGE_S = 600  # readings older than this are flagged stale
TOKEN_FIELDS = (
    ("input", "input_tokens"),
    ("output", "output_tokens"),
    ("cache_read", "cache_read_input_tokens"),
    ("cache_write", "cache_creation_input_tokens"),
)


# --------------------------------------------------------------------------
# helpers


def parse_ts(value):
    """Parse an ISO-8601 string (with 'Z' or an offset) or epoch seconds or
    milliseconds into an aware datetime. Return None if it can't be parsed."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# local tokens from transcripts


def _iter_jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # tolerate corrupt or partially written lines
    except OSError:
        return


def subagent_transcripts(transcript_path):
    """Subagent transcripts live in <session>/subagents/*.jsonl next to the
    main transcript <session>.jsonl."""
    base = Path(transcript_path)
    folder = base.with_suffix("") / "subagents"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl"))


def transcript_tokens(transcript_path, since=None, until=None, include_subagents=True):
    """Sum token usage of assistant messages in a transcript.

    One API response appears as several records that share `message.id` and
    carry identical usage, so usage is counted once per id. `since` and
    `until` are datetimes (or anything parse_ts accepts) and filter on the
    record timestamp: since <= ts < until.
    """
    since, until = parse_ts(since), parse_ts(until)
    files = [Path(transcript_path)]
    if include_subagents:
        files += subagent_transcripts(transcript_path)

    totals = {name: 0 for name, _ in TOKEN_FIELDS}
    by_model = {}
    seen = set()
    first = last = None
    found = False

    for path in files:
        if not path.is_file():
            continue
        found = True
        for rec in _iter_jsonl(path):
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            key = (str(path), msg.get("id") or rec.get("uuid"))
            if key in seen:
                continue
            ts = parse_ts(rec.get("timestamp"))
            if (since or until) and ts is None:
                continue
            if since and ts < since:
                continue
            if until and ts >= until:
                continue
            seen.add(key)
            usage = msg["usage"]
            model = msg.get("model") or "unknown"
            bucket = by_model.setdefault(model, {name: 0 for name, _ in TOKEN_FIELDS})
            for name, field in TOKEN_FIELDS:
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[name] += value
                    bucket[name] += value
            if ts:
                first = ts if first is None or ts < first else first
                last = ts if last is None or ts > last else last

    if not found:
        return None
    return {
        "tokens": totals,
        "total": sum(totals.values()),
        "messages": len(seen),
        "by_model": by_model,
        "files": sum(1 for p in files if p.is_file()),
        "first_ts": iso(first),
        "last_ts": iso(last),
    }


# --------------------------------------------------------------------------
# account-wide %


def _reading(source, session_pct, weekly_pct, session_resets, weekly_resets,
             fetched_at, precision, now):
    age = None if fetched_at is None else max(0, int((now - fetched_at).total_seconds()))
    return {
        "source": source,
        "session_pct": session_pct,
        "weekly_pct": weekly_pct,
        "session_resets_at": iso(session_resets),
        "weekly_resets_at": iso(weekly_resets),
        "fetched_at": iso(fetched_at),
        "age_s": age,
        "precision": precision,
        "stale": age is None or age > MAX_AGE_S,
    }


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read_statusline_snapshot(path, now=None):
    """Read a snapshot the statusline script writes (v0.8):
    {"schema": 1, "captured_at": <epoch s>, "rate_limits": <statusline rate_limits>}.
    The rate_limits shape is documented in the statusline docs."""
    now = now or datetime.now(timezone.utc)
    data = _load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("rate_limits"), dict):
        return None
    rl = data["rate_limits"]
    five = rl.get("five_hour") if isinstance(rl.get("five_hour"), dict) else {}
    week = rl.get("seven_day") if isinstance(rl.get("seven_day"), dict) else {}
    s_pct, w_pct = _num(five.get("used_percentage")), _num(week.get("used_percentage"))
    if s_pct is None and w_pct is None:
        return None
    return _reading("statusline", s_pct, w_pct, parse_ts(five.get("resets_at")),
                    parse_ts(week.get("resets_at")), parse_ts(data.get("captured_at")),
                    "decimal", now)


def read_usage_cache(path=None, now=None):
    """UNSTABLE: read `cachedUsageUtilization` from ~/.claude.json. The key is
    undocumented. Only the 5-hour and 7-day numbers are extracted; nothing
    else from the file (account IDs etc.) is returned."""
    now = now or datetime.now(timezone.utc)
    path = path or os.path.join(os.path.expanduser("~"), ".claude.json")
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    cache = data.get("cachedUsageUtilization")
    if not isinstance(cache, dict) or not isinstance(cache.get("utilization"), dict):
        return None
    util = cache["utilization"]
    five = util.get("five_hour") if isinstance(util.get("five_hour"), dict) else {}
    week = util.get("seven_day") if isinstance(util.get("seven_day"), dict) else {}
    s_pct, w_pct = _num(five.get("utilization")), _num(week.get("utilization"))
    if s_pct is None and w_pct is None:
        return None
    return _reading("cache", s_pct, w_pct, parse_ts(five.get("resets_at")),
                    parse_ts(week.get("resets_at")), parse_ts(cache.get("fetchedAtMs")),
                    "integer", now)


def account_usage(snapshot_path=None, cache_path=None, now=None):
    """Best available account-wide reading, in this order:
    1. fresh statusline snapshot, 2. fresh usage cache,
    3. the freshest stale reading (stale=True), 4. None (ask for /usage)."""
    now = now or datetime.now(timezone.utc)
    candidates = []
    if snapshot_path:
        candidates.append(read_statusline_snapshot(snapshot_path, now))
    candidates.append(read_usage_cache(cache_path, now))
    candidates = [c for c in candidates if c]
    for c in candidates:
        if not c["stale"]:
            return c
    if candidates:
        return min(candidates, key=lambda c: float("inf") if c["age_s"] is None else c["age_s"])
    return None


# --------------------------------------------------------------------------
# CLI


def main(argv=None):
    parser = argparse.ArgumentParser(description="navitok usage source adapters")
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tokens", help="sum local tokens in a session transcript")
    t.add_argument("transcript")
    t.add_argument("--since", help="ISO-8601 start (inclusive)")
    t.add_argument("--until", help="ISO-8601 end (exclusive)")
    t.add_argument("--no-subagents", action="store_true")
    a = sub.add_parser("account", help="account-wide session/weekly %% (best source)")
    a.add_argument("--snapshot", help="statusline snapshot file")
    a.add_argument("--cache", help="path to .claude.json (default: ~/.claude.json)")
    args = parser.parse_args(argv)

    if args.cmd == "tokens":
        result = transcript_tokens(args.transcript, args.since, args.until,
                                   include_subagents=not args.no_subagents)
    else:
        result = account_usage(args.snapshot, args.cache)
    if result is None:
        print(json.dumps({"error": "no data", "hint": "run /usage and report it manually"
                          if args.cmd == "account" else "transcript not found"}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
