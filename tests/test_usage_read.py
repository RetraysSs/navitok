"""Tests for scripts/usage_read.py. All fixtures are synthetic and built in temp dirs."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import usage_read as ur  # noqa: E402

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def assistant(msg_id, ts, model="model-a", inp=1, out=10, cr=100, cw=50):
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "id": msg_id,
            "model": model,
            "content": [{"type": "text", "text": "synthetic"}],
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cr,
                "cache_creation_input_tokens": cw,
                "service_tier": "standard",
            },
        },
    }


def write_jsonl(path, records, raw_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
        for line in raw_lines:
            f.write(line + "\n")


class TranscriptTokensTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.main = self.dir / "sess.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_dedupes_records_sharing_message_id(self):
        write_jsonl(self.main, [
            {"type": "user", "timestamp": "2026-01-01T10:00:00Z", "message": {"role": "user"}},
            assistant("m1", "2026-01-01T10:00:01Z"),
            assistant("m1", "2026-01-01T10:00:02Z"),  # same response, second content block
            assistant("m2", "2026-01-01T10:01:00Z", out=20),
        ])
        r = ur.transcript_tokens(self.main)
        self.assertEqual(r["messages"], 2)
        self.assertEqual(r["tokens"], {"input": 2, "output": 30, "cache_read": 200, "cache_write": 100})
        self.assertEqual(r["total"], 332)

    def test_includes_subagents_split_by_model(self):
        write_jsonl(self.main, [assistant("m1", "2026-01-01T10:00:00Z")])
        write_jsonl(self.dir / "sess" / "subagents" / "agent-x.jsonl",
                    [assistant("m1", "2026-01-01T10:00:05Z", model="model-b", out=5)])
        r = ur.transcript_tokens(self.main)
        self.assertEqual(r["files"], 2)
        self.assertEqual(r["messages"], 2)  # same id in a different file is a different message
        self.assertEqual(r["by_model"]["model-b"]["output"], 5)
        self.assertEqual(r["tokens"]["output"], 15)
        r = ur.transcript_tokens(self.main, include_subagents=False)
        self.assertEqual(r["tokens"]["output"], 10)

    def test_time_window_is_half_open(self):
        write_jsonl(self.main, [
            assistant("m1", "2026-01-01T10:00:00Z", out=1),
            assistant("m2", "2026-01-01T11:00:00Z", out=2),
            assistant("m3", "2026-01-01T12:00:00Z", out=4),
        ])
        r = ur.transcript_tokens(self.main, since="2026-01-01T11:00:00Z", until="2026-01-01T12:00:00Z")
        self.assertEqual(r["tokens"]["output"], 2)
        self.assertEqual(r["first_ts"], "2026-01-01T11:00:00Z")

    def test_tolerates_corrupt_lines_and_bad_values(self):
        bad = assistant("m2", "2026-01-01T10:00:01Z")
        bad["message"]["usage"]["output_tokens"] = "oops"
        write_jsonl(self.main, [assistant("m1", "2026-01-01T10:00:00Z"), bad],
                    raw_lines=['{"type": "assistant", "message": {', "not json"])
        r = ur.transcript_tokens(self.main)
        self.assertEqual(r["messages"], 2)
        self.assertEqual(r["tokens"]["output"], 10)

    def test_missing_transcript(self):
        self.assertIsNone(ur.transcript_tokens(self.dir / "nope.jsonl"))


class AccountUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cache = self.dir / "claude.json"
        self.snap = self.dir / "snapshot.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_cache(self, age_s, five=27, week=11):
        fetched = int((NOW - timedelta(seconds=age_s)).timestamp() * 1000)
        self.cache.write_text(json.dumps({
            "oauthAccount": {"emailAddress": "someone@example.invalid"},
            "cachedUsageUtilization": {
                "fetchedAtMs": fetched,
                "accountUuid": "00000000-0000-0000-0000-000000000000",
                "utilization": {
                    "five_hour": {"utilization": five, "resets_at": "2026-01-01T14:00:00.123+00:00"},
                    "seven_day": {"utilization": week, "resets_at": "2026-01-05T08:00:00+00:00"},
                    "seven_day_opus": None,
                },
            },
        }), encoding="utf-8")

    def write_snapshot(self, age_s, five=31.5, week=12.25):
        self.snap.write_text(json.dumps({
            "schema": 1,
            "captured_at": int((NOW - timedelta(seconds=age_s)).timestamp()),
            "rate_limits": {
                "five_hour": {"used_percentage": five, "resets_at": int(NOW.timestamp()) + 3600},
                "seven_day": {"used_percentage": week, "resets_at": int(NOW.timestamp()) + 86400},
            },
        }), encoding="utf-8")

    def test_cache_reading_exposes_no_account_data(self):
        self.write_cache(age_s=60)
        r = ur.read_usage_cache(self.cache, now=NOW)
        self.assertEqual((r["session_pct"], r["weekly_pct"]), (27, 11))
        self.assertEqual(r["source"], "cache")
        self.assertEqual(r["precision"], "integer")
        self.assertEqual(r["age_s"], 60)
        self.assertFalse(r["stale"])
        self.assertEqual(r["session_resets_at"], "2026-01-01T14:00:00Z")
        dumped = json.dumps(r)
        self.assertNotIn("0000-0000", dumped)
        self.assertNotIn("example.invalid", dumped)

    def test_fresh_snapshot_wins(self):
        self.write_snapshot(age_s=30)
        self.write_cache(age_s=10)
        r = ur.account_usage(self.snap, self.cache, now=NOW)
        self.assertEqual(r["source"], "statusline")
        self.assertEqual(r["precision"], "decimal")
        self.assertEqual(r["session_pct"], 31.5)

    def test_stale_snapshot_falls_back_to_fresh_cache(self):
        self.write_snapshot(age_s=ur.MAX_AGE_S + 1)
        self.write_cache(age_s=5)
        self.assertEqual(ur.account_usage(self.snap, self.cache, now=NOW)["source"], "cache")

    def test_all_stale_returns_freshest_flagged(self):
        self.write_snapshot(age_s=5000)
        self.write_cache(age_s=1500)
        r = ur.account_usage(self.snap, self.cache, now=NOW)
        self.assertEqual(r["source"], "cache")
        self.assertTrue(r["stale"])
        self.assertEqual(r["age_s"], 1500)

    def test_no_sources(self):
        self.assertIsNone(ur.account_usage(self.dir / "none.json", self.dir / "none2.json", now=NOW))

    def test_corrupt_or_unexpected_files(self):
        self.cache.write_text("{not json", encoding="utf-8")
        self.assertIsNone(ur.read_usage_cache(self.cache, now=NOW))
        self.cache.write_text(json.dumps({"cachedUsageUtilization": {"utilization": {"five_hour": None}}}),
                              encoding="utf-8")
        self.assertIsNone(ur.read_usage_cache(self.cache, now=NOW))
        self.snap.write_text(json.dumps({"rate_limits": {}}), encoding="utf-8")
        self.assertIsNone(ur.read_statusline_snapshot(self.snap, now=NOW))

    def test_missing_fetch_time_is_stale(self):
        self.cache.write_text(json.dumps({"cachedUsageUtilization": {
            "utilization": {"five_hour": {"utilization": 5}}}}), encoding="utf-8")
        r = ur.read_usage_cache(self.cache, now=NOW)
        self.assertIsNone(r["age_s"])
        self.assertTrue(r["stale"])


class ParseTsTest(unittest.TestCase):
    def test_formats(self):
        z = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(ur.parse_ts("2026-01-01T00:00:00Z"), z)
        self.assertEqual(ur.parse_ts("2026-01-01T00:00:00+00:00"), z)
        self.assertEqual(ur.parse_ts(z.timestamp()), z)
        self.assertEqual(ur.parse_ts(z.timestamp() * 1000), z)
        self.assertIsNone(ur.parse_ts("garbage"))
        self.assertIsNone(ur.parse_ts(True))


if __name__ == "__main__":
    unittest.main()
