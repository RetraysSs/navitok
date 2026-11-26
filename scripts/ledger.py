"""navitok ledger: .navitok/history.jsonl (and docs/dogfood/ledger.jsonl).

One JSON object per line, schema 2 (ROADMAP §10.5, plus the fields below).
Stdlib only.

Schema 2 adds three optional fields to the §10.5 draft:
  session_id             Claude Code session id, if known
  local_tokens_by_model  {model: total tokens}
  parts                  list of sub-windows of one record (e.g. a 5-hour
                         reset in the middle of a sprint). Each part has
                         ts_start, ts_end, account_*_pct_start/end and
                         local_tokens.
Unknown numbers are null, never guessed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = 2
SOURCES = {"statusline", "cache", "manual", "transcript"}
TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")

REQUIRED = ("schema", "ts_start", "ts_end", "source")
NULLABLE_NUMBERS = (
    "account_session_pct_start", "account_session_pct_end",
    "account_weekly_pct_start", "account_weekly_pct_end", "external_pct",
)
NULLABLE_STRINGS = ("release", "plan", "mode", "model", "effort", "session_id", "notes")


def default_path(project_dir="."):
    return Path(project_dir) / ".navitok" / "history.jsonl"


# --------------------------------------------------------------------------
# validation


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_tokens(value, where, errors):
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object or null")
        return
    for k in TOKEN_KEYS:
        v = value.get(k)
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            errors.append(f"{where}.{k} must be a non-negative integer or null")


def validate(record):
    """Return a list of error strings (empty if the record is valid)."""
    errors = []
    if not isinstance(record, dict):
        return ["record must be a JSON object"]
    for key in REQUIRED:
        if key not in record:
            errors.append(f"missing {key}")
    if record.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if "source" in record and record["source"] not in SOURCES:
        errors.append(f"source must be one of {sorted(SOURCES)}")
    for key in ("ts_start", "ts_end"):
        if key in record and not isinstance(record[key], str):
            errors.append(f"{key} must be an ISO-8601 string")
    for key in NULLABLE_NUMBERS:
        v = record.get(key)
        if v is not None and not _is_num(v):
            errors.append(f"{key} must be a number or null")
        elif _is_num(v) and key != "external_pct" and not 0 <= v <= 100:
            errors.append(f"{key} must be within 0..100")
    for key in NULLABLE_STRINGS:
        v = record.get(key)
        if v is not None and not isinstance(v, str):
            errors.append(f"{key} must be a string or null")
    _check_tokens(record.get("local_tokens"), "local_tokens", errors)
    if not isinstance(record.get("helpers", []), list):
        errors.append("helpers must be a list")
    tasks = record.get("tasks", [])
    if not isinstance(tasks, list):
        errors.append("tasks must be a list")
    else:
        for i, t in enumerate(tasks):
            if not isinstance(t, dict) or "id" not in t:
                errors.append(f"tasks[{i}] must be an object with an id")
                continue
            for key in ("files_touched", "files_predicted", "lines_changed", "lines_predicted"):
                v = t.get(key)
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                    errors.append(f"tasks[{i}].{key} must be a non-negative integer or null")
            est = t.get("est_pct")
            if est is not None and not (isinstance(est, list) and len(est) == 2
                                        and all(_is_num(x) for x in est) and est[0] <= est[1]):
                errors.append(f"tasks[{i}].est_pct must be [low, high] or null")
    parts = record.get("parts")
    if parts is not None:
        if not isinstance(parts, list):
            errors.append("parts must be a list or null")
        else:
            for i, part in enumerate(parts):
                if not isinstance(part, dict) or "ts_start" not in part or "ts_end" not in part:
                    errors.append(f"parts[{i}] needs ts_start and ts_end")
                else:
                    _check_tokens(part.get("local_tokens"), f"parts[{i}].local_tokens", errors)
    for key in ("outlier", "ended_cleanly"):
        if key in record and not isinstance(record[key], bool):
            errors.append(f"{key} must be a boolean")
    return errors


def new_record(**fields):
    """A schema-2 record with every §10.5 field present (unknowns null)."""
    record = {
        "schema": SCHEMA, "ts_start": None, "ts_end": None, "session_id": None,
        "release": None, "plan": None, "mode": None, "model": None, "effort": None,
        "helpers": [], "source": "transcript",
        "account_session_pct_start": None, "account_session_pct_end": None,
        "account_weekly_pct_start": None, "account_weekly_pct_end": None,
        "local_tokens": None, "local_tokens_by_model": None, "external_pct": None,
        "tasks": [], "outlier": False, "ended_cleanly": True, "notes": "",
    }
    record.update(fields)
    return record


# --------------------------------------------------------------------------
# locking (cross-process, stdlib only)


@contextmanager
def _locked(path, timeout_s=5.0):
    lock_path = str(path) + ".lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"could not lock {lock_path}")
                time.sleep(0.005)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


# --------------------------------------------------------------------------
# read / write


def append(record, path=None, check=True):
    """Validate and append one record as a single line. Safe across processes."""
    path = Path(path) if path else default_path()
    if check:
        errors = validate(record)
        if errors:
            raise ValueError("invalid ledger record: " + "; ".join(errors))
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        # Make sure we never glue onto a half-written last line.
        needs_newline = False
        if path.exists() and path.stat().st_size > 0:
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                needs_newline = f.read(1) != b"\n"
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if needs_newline:
                f.write("\n")
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def read_all(path=None, with_errors=False):
    """Return valid records in file order. Corrupt or invalid lines are skipped.
    With with_errors=True, return (records, [(line_no, reason), ...])."""
    path = Path(path) if path else default_path()
    records, problems = [], []
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    problems.append((n, "not valid JSON"))
                    continue
                errors = validate(rec)
                if errors:
                    problems.append((n, "; ".join(errors)))
                    continue
                records.append(rec)
    except FileNotFoundError:
        pass
    return (records, problems) if with_errors else records


def last_session(path=None):
    """The record with the latest ts_end, or None."""
    records = read_all(path)
    return max(records, key=lambda r: r["ts_end"]) if records else None


# --------------------------------------------------------------------------
# CLI


def main(argv=None):
    parser = argparse.ArgumentParser(description="navitok ledger tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check every line of a ledger file")
    v.add_argument("path")
    last = sub.add_parser("last", help="print the latest record")
    last.add_argument("path", nargs="?")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        records, problems = read_all(args.path, with_errors=True)
        for n, reason in problems:
            print(f"line {n}: {reason}")
        print(f"{len(records)} valid, {len(problems)} invalid")
        return 1 if problems else 0
    rec = last_session(args.path)
    print(json.dumps(rec, indent=2) if rec else "no records")
    return 0 if rec else 1


if __name__ == "__main__":
    sys.exit(main())
