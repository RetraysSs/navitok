"""Tests for scripts/ledger.py (synthetic data only)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ledger  # noqa: E402

WRITER = """
import sys
sys.path.insert(0, sys.argv[1])
import ledger
w, n = int(sys.argv[3]), int(sys.argv[4])
for i in range(n):
    ledger.append(ledger.new_record(
        ts_start="2026-01-01T00:00:00Z", ts_end="2026-01-01T01:00:00Z", source="transcript",
        notes="w%02d-%03d-" % (w, i) + "x" * 2000), sys.argv[2])
"""


def rec(n=0, **kw):
    fields = dict(ts_start=f"2026-01-01T10:{n:02d}:00Z", ts_end=f"2026-01-01T11:{n:02d}:00Z",
                  source="manual", account_session_pct_start=10, account_session_pct_end=20,
                  local_tokens={"input": 1, "output": 2, "cache_read": 3, "cache_write": 4})
    fields.update(kw)
    return ledger.new_record(**fields)


class ValidateTest(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(ledger.validate(rec()), [])

    def test_errors(self):
        bad = rec(source="guess", account_session_pct_end=140, ended_cleanly="yes")
        bad["schema"] = 1
        bad["local_tokens"]["output"] = -1
        bad["tasks"] = [{"id": "t1", "est_pct": [9, 3]}, {"no": "id"}]
        bad["parts"] = [{"ts_start": "x"}]
        errors = " | ".join(ledger.validate(bad))
        for fragment in ("schema must be 2", "source must be", "account_session_pct_end must be within",
                         "ended_cleanly", "local_tokens.output", "tasks[0].est_pct", "tasks[1]", "parts[0]"):
            self.assertIn(fragment, errors)
        self.assertEqual(ledger.validate([]), ["record must be a JSON object"])

    def test_nulls_are_allowed(self):
        self.assertEqual(ledger.validate(rec(account_session_pct_start=None, local_tokens=None, parts=None)), [])


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".navitok" / "history.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read(self):
        ledger.append(rec(1), self.path)
        ledger.append(rec(2), self.path)
        self.assertEqual(len(ledger.read_all(self.path)), 2)
        self.assertEqual(ledger.last_session(self.path)["ts_end"], "2026-01-01T11:02:00Z")

    def test_append_rejects_invalid(self):
        with self.assertRaises(ValueError):
            ledger.append(rec(source="nope"), self.path)
        self.assertFalse(self.path.exists())

    def test_tolerates_corrupt_lines(self):
        ledger.append(rec(1), self.path)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"schema": 2, "ts_sta\n')          # truncated line
            f.write("\n")                                 # blank line
            f.write(json.dumps({"schema": 2}) + "\n")     # valid JSON, invalid record
        ledger.append(rec(3), self.path)
        records, problems = ledger.read_all(self.path, with_errors=True)
        self.assertEqual([r["ts_end"] for r in records], ["2026-01-01T11:01:00Z", "2026-01-01T11:03:00Z"])
        self.assertEqual([n for n, _ in problems], [2, 4])

    def test_does_not_glue_onto_half_written_line(self):
        ledger.append(rec(1), self.path)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"partial": ')                       # crash mid-write, no newline
        ledger.append(rec(2), self.path)
        self.assertEqual(len(ledger.read_all(self.path)), 2)

    def test_missing_file(self):
        self.assertEqual(ledger.read_all(self.path), [])
        self.assertIsNone(ledger.last_session(self.path))

    def test_concurrent_writers_keep_lines_intact(self):
        writers, per_writer = 4, 40
        procs = [subprocess.Popen([sys.executable, "-c", WRITER, str(SCRIPTS), str(self.path),
                                   str(w), str(per_writer)]) for w in range(writers)]
        for p in procs:
            self.assertEqual(p.wait(timeout=60), 0)
        records, problems = ledger.read_all(self.path, with_errors=True)
        self.assertEqual(problems, [])
        self.assertEqual(len(records), writers * per_writer)
        self.assertEqual(len({r["notes"][:8] for r in records}), writers * per_writer)


class DogfoodLedgerTest(unittest.TestCase):
    def test_dogfood_ledger_is_valid_schema(self):
        path = SCRIPTS.parent / "docs" / "dogfood" / "ledger.jsonl"
        records, problems = ledger.read_all(path, with_errors=True)
        self.assertEqual(problems, [])
        self.assertGreaterEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
