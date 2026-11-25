"""navitok external usage (ROADMAP §4.3, §10.3).

Usage outside Claude Code on this machine (claude.ai, other machines) shows up
in the account-wide % but not in local transcripts. Per session:

    account_delta  = account_session_pct_end - account_session_pct_start
    local_delta    = weighted local tokens x pct_per_token
    external_delta = max(0, account_delta - local_delta)

External usage is never counted as estimation error (calibrate.py uses
local_delta only). Deterministic, stdlib only, never calls the model.

Assumptions (marked unstable in docs/data-sources.md):
- Token types are weighted by TOKEN_WEIGHTS before converting to %. The
  weights follow relative API prices; how plan limits really count tokens is
  not documented.
- pct_per_token is a low quantile of per-session account_delta / weighted
  tokens: external usage only ever raises that ratio, so the low end is the
  cleanest estimate of "Claude Code alone". It needs MIN_SESSIONS sessions;
  until then external usage is unknown (None), never zero.

  external.py report [--history PATH]   print the profile as JSON
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
import usage_read  # noqa: E402

TOKEN_WEIGHTS = {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25}
MIN_SESSIONS = 5          # §10.3: "first ~5 sessions"
RATIO_QUANTILE = 0.25
WEEKLY_PER_SESSION = 0.15  # cold start; same seed as schedule.py
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def quantile(values, q):
    """Linear-interpolated quantile of a non-empty list."""
    xs = sorted(values)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def weighted_tokens(record):
    toks = record.get("local_tokens")
    if not isinstance(toks, dict):
        return None
    total = sum(TOKEN_WEIGHTS[k] * toks[k] for k in TOKEN_WEIGHTS if _num(toks.get(k)))
    return total if total > 0 else None


def account_delta(record, key="session"):
    """Account-wide change over the session, or None. A record split into
    `parts` (a window reset mid-session) sums its parts. A drop means a reset
    that the record does not explain, so the delta is unknown."""
    s, e = f"account_{key}_pct_start", f"account_{key}_pct_end"
    if _num(record.get(s)) and _num(record.get(e)):
        d = record[e] - record[s]
        return float(d) if d >= 0 else None
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        total = 0.0
        for p in parts:
            if not (isinstance(p, dict) and _num(p.get(s)) and _num(p.get(e))) or p[e] < p[s]:
                return None
            total += p[e] - p[s]
        return total
    return None


def pct_per_token(records):
    """Fit % per weighted token, or None until MIN_SESSIONS usable sessions.
    A recorded external_pct is subtracted first (that session is clean)."""
    ratios = []
    for r in records:
        if r.get("outlier") is True:
            continue
        d, w = account_delta(r), weighted_tokens(r)
        if d is None or w is None:
            continue
        if _num(r.get("external_pct")):
            d = max(0.0, d - r["external_pct"])
        ratios.append(d / w)
    if len(ratios) < MIN_SESSIONS:
        return None
    return quantile(ratios, RATIO_QUANTILE)


def local_pct(record, ppt):
    """Local (this machine's Claude Code) session % of one record, or None."""
    w = weighted_tokens(record)
    if w is not None and ppt is not None:
        return w * ppt
    d = account_delta(record)
    if d is not None and _num(record.get("external_pct")):
        return max(0.0, d - record["external_pct"])
    return None


def session_external(record, ppt):
    """(external session %, explained) for one record. `explained` is True when
    the record states external_pct itself. (None, False) when unknown."""
    if _num(record.get("external_pct")):
        return float(record["external_pct"]), True
    d, loc = account_delta(record), local_pct(record, ppt)
    if d is None or loc is None or ppt is None:
        return None, False
    return max(0.0, d - loc), False


def weekly_ratio(records, default=WEEKLY_PER_SESSION):
    """Weekly % per session % (sum of weekly deltas / sum of session deltas)."""
    s_sum = w_sum = 0.0
    n = 0
    for r in records:
        s, w = account_delta(r), account_delta(r, "weekly")
        if s is None or w is None or s <= 0:
            continue
        s_sum, w_sum, n = s_sum + s, w_sum + w, n + 1
    if n < MIN_SESSIONS or s_sum <= 0:
        return default, False
    return w_sum / s_sum, True


def _ts(record, key):
    return usage_read.parse_ts(record.get(key))


def _week_key(dt):
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def profile(records, now=None, ratio=None):
    """External-usage profile (§10.3).

    per_weekday: mean / P80 of in-session external session % by weekday of the
      session start (UTC).
    weekly: per ISO week, external weekly % = in-session external x ratio, plus
      the weekly % that rose *between* consecutive records in the same week
      (usage no local session explains). mean / P80 over weeks, this week's
      total so far, and reserve_pct = max(0, P80 - this week so far).
    known is False (and the numbers None) until pct_per_token is calibrated.
    """
    now = now or datetime.now(timezone.utc)
    recs = sorted((r for r in records if _ts(r, "ts_end")), key=lambda r: r["ts_end"])
    ppt = pct_per_token(recs)
    if ratio is None:
        ratio, _ = weekly_ratio(recs)
    out = {"known": ppt is not None, "pct_per_token": ppt, "weekly_ratio": ratio,
           "per_weekday": {}, "weekly": None, "reserve_pct": None}
    if ppt is None:
        return out
    by_day = defaultdict(list)
    by_week = defaultdict(float)
    prev = None
    for r in recs:
        ext, _ = session_external(r, ppt)
        start = _ts(r, "ts_start") or _ts(r, "ts_end")
        if ext is not None:
            by_day[WEEKDAYS[start.weekday()]].append(ext)
            by_week[_week_key(start)] += ext * ratio
        if prev is not None:
            a, b = prev.get("account_weekly_pct_end"), r.get("account_weekly_pct_start")
            if _num(a) and _num(b) and b >= a and _week_key(_ts(prev, "ts_end")) == _week_key(start):
                by_week[_week_key(start)] += b - a
        prev = r
    out["per_weekday"] = {d: {"n": len(v), "mean": round(sum(v) / len(v), 2),
                              "p80": round(quantile(v, 0.8), 2)}
                          for d, v in ((d, by_day[d]) for d in WEEKDAYS) if v}
    weeks = list(by_week.values())
    this_week = by_week.get(_week_key(now), 0.0)
    if weeks:
        p80 = quantile(weeks, 0.8)
        out["weekly"] = {"n_weeks": len(weeks), "mean": round(sum(weeks) / len(weeks), 2),
                         "p80": round(p80, 2), "this_week": round(this_week, 2)}
        out["reserve_pct"] = round(max(0.0, p80 - this_week), 2)
    return out


def main(argv=None):
    import argparse
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="navitok external usage profile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--history", default=None, help="history.jsonl (default .navitok/history.jsonl)")
    args = ap.parse_args(argv)
    print(json.dumps(profile(ledger.read_all(args.history)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
