"""Tests for scripts/hook_session.py (synthetic transcripts and caches only)."""

import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import hook_session as hs  # noqa: E402
import ledger  # noqa: E402

T0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def msg(i, out, model="model-x"):
    return json.dumps({"type": "assistant", "timestamp": f"2026-01-01T10:{i:02d}:00Z",
                       "message": {"id": f"m{i}", "model": model,
                                   "usage": {"input_tokens": 1, "output_tokens": out,
                                             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}})


class HookSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.nav = self.root / ".navitok"
        self.nav.mkdir()
        self.transcript = self.root / "t.jsonl"
        self.transcript.write_text(msg(0, 10) + "\n", encoding="utf-8")
        self.cache = self.root / "claude.json"
        self.payload = {"session_id": "s1", "cwd": str(self.root), "transcript_path": str(self.transcript),
                        "effort": {"level": "high"}}

    def tearDown(self):
        self.tmp.cleanup()

    def set_cache(self, five, week, at):
        self.cache.write_text(json.dumps({"cachedUsageUtilization": {
            "fetchedAtMs": int(at.timestamp() * 1000),
            "utilization": {"five_hour": {"utilization": five}, "seven_day": {"utilization": week}}}}),
            encoding="utf-8")

    def history(self):
        return ledger.read_all(self.nav / "history.jsonl")

    def test_full_session_records_deltas(self):
        self.set_cache(20, 40, T0)
        hs.on_start(self.payload, self.nav, now=T0, cache_path=self.cache)
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(msg(1, 100) + "\n" + msg(2, 50, model="model-y") + "\n")
        self.set_cache(26, 41, T0 + timedelta(minutes=30))
        hs.on_stop(self.payload, self.nav, now=T0 + timedelta(minutes=30), cache_path=self.cache)
        hs.on_end(dict(self.payload, reason="prompt_input_exit"), self.nav,
                  now=T0 + timedelta(minutes=31), cache_path=self.cache)
        [r] = self.history()
        self.assertEqual(ledger.validate(r), [])
        self.assertEqual((r["account_session_pct_start"], r["account_session_pct_end"]), (20, 26))
        self.assertEqual((r["account_weekly_pct_start"], r["account_weekly_pct_end"]), (40, 41))
        self.assertEqual(r["local_tokens"]["output"], 150)  # the message before start is excluded
        self.assertEqual(r["local_tokens_by_model"], {"model-x": 101, "model-y": 51})
        self.assertEqual(r["effort"], "high")
        self.assertEqual(r["source"], "cache")
        self.assertTrue(r["ended_cleanly"])
        self.assertIn("prompt_input_exit", r["notes"])
        self.assertFalse(any((self.nav / "sessions").glob("*.json")))

    def test_resume_keeps_original_start(self):
        self.set_cache(10, 10, T0)
        hs.on_start(self.payload, self.nav, now=T0, cache_path=self.cache)
        self.set_cache(50, 50, T0 + timedelta(hours=1))
        hs.on_start(self.payload, self.nav, now=T0 + timedelta(hours=1), cache_path=self.cache)
        hs.on_end(self.payload, self.nav, now=T0 + timedelta(hours=1), cache_path=self.cache)
        [r] = self.history()
        self.assertEqual(r["account_session_pct_start"], 10)

    def test_orphaned_session_is_flushed_unclean(self):
        self.set_cache(10, 10, T0)
        hs.on_start(self.payload, self.nav, now=T0, cache_path=self.cache)
        hs.on_start(dict(self.payload, session_id="s2"), self.nav, now=T0, cache_path=self.cache)
        [r] = self.history()
        self.assertEqual(r["session_id"], "s1")
        self.assertFalse(r["ended_cleanly"])
        self.assertTrue((self.nav / "sessions" / "s2.json").exists())

    def test_stale_and_missing_readings_are_noted(self):
        self.set_cache(10, 10, T0 - timedelta(hours=2))
        hs.on_start(self.payload, self.nav, now=T0, cache_path=self.cache)
        hs.on_end(self.payload, self.nav, now=T0, cache_path=self.root / "missing.json")
        [r] = self.history()
        self.assertIn("start: account reading from cache is stale", r["notes"])
        self.assertIn("end: no account reading", r["notes"])
        self.assertIsNone(r["account_session_pct_end"])  # not faked from the start reading
        self.assertEqual(r["ts_end"], "2026-01-01T10:00:00Z")

    def test_end_without_start_does_nothing(self):
        hs.on_end(self.payload, self.nav, now=T0, cache_path=self.cache)
        self.assertEqual(self.history(), [])

    def test_main_is_silent_and_skips_projects_without_navitok(self):
        other = self.root / "other"
        other.mkdir()
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(dict(self.payload, cwd=str(other))))), \
                mock.patch("sys.stdout", out):
            self.assertEqual(hs.main(["start"]), 0)
        self.assertEqual(out.getvalue(), "")
        self.assertFalse((other / ".navitok").exists())

    def test_main_never_raises(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("{not json")), mock.patch("sys.stdout", out):
            self.assertEqual(hs.main(["start"]), 0)
        with mock.patch("sys.stdin", io.StringIO("{}")), mock.patch("sys.stdout", out):
            self.assertEqual(hs.main(["bogus"]), 0)
        self.assertEqual(out.getvalue(), "")

    def test_main_decodes_utf8_stdin_with_non_ascii_path(self):
        # Regression: on Windows sys.stdin uses the ANSI code page (e.g. cp1254),
        # which garbled a "C:\Users\ÜNSAL\..." cwd so .navitok/ was never found.
        project = self.root / "ÜNSAL-şçğ"
        (project / ".navitok").mkdir(parents=True)
        raw = json.dumps({"session_id": "u1", "cwd": str(project)}, ensure_ascii=False).encode("utf-8")
        fake_stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="cp1254")
        with mock.patch("sys.stdin", fake_stdin), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(hs.main(["start"]), 0)
        self.assertTrue((project / ".navitok" / "sessions" / "u1.json").exists())

    def test_hooks_json_wiring(self):
        path = Path(hs.__file__).resolve().parent.parent / "hooks" / "hooks.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for event, arg in (("SessionStart", "start"), ("Stop", "stop"), ("SessionEnd", "end")):
            cmd = data["hooks"][event][0]["hooks"][0]["command"]
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/run.sh", cmd)
            self.assertTrue(cmd.endswith(" " + arg))


if __name__ == "__main__":
    unittest.main()
