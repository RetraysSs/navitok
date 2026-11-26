"""Tests for scripts/statusline.py (synthetic statusline JSON and settings only)."""

import json
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "statusline.py"
sys.path.insert(0, str(ROOT / "scripts"))
import statusline as sl  # noqa: E402
import usage_read  # noqa: E402

NOW = 1_800_000_000  # epoch seconds


def payload(root, s=62.4, w=31.0, rl=True):
    p = {"cwd": str(root), "workspace": {"current_dir": str(root), "project_dir": str(root)},
         "session_id": "s-1", "model": {"id": "m"}}
    if rl:
        p["rate_limits"] = {"five_hour": {"used_percentage": s, "resets_at": NOW + 3600},
                            "seven_day": {"used_percentage": w, "resets_at": NOW + 86400}}
    return p


def raw(p):
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Proje ÜNSAL"
        self.nav = self.root / ".navitok"
        self.nav.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, data):
        (self.nav / name).write_text(json.dumps(data), encoding="utf-8")

    def schedule(self, rel="v0.3", remaining=(5, 20), threshold=90, plan="pro", stale=False, used=50):
        self.write("schedule.json", {"plan": plan, "threshold": threshold, "current_release": rel,
                                     "current_remaining_pct": list(remaining), "usage_stale": stale,
                                     "session": {"used_pct": used}, "week": {"used_pct": 30}})


class Segment(Base):
    def test_full_line(self):
        self.schedule()
        self.write("calibration.json", {"confidence": 40, "external": {"known": True, "weekly": {"this_week": 8.2}}})
        line = sl.render(raw(payload(self.root)), now=NOW)
        self.assertEqual(line, "v0.3 ▓▓▓░░ 62% · fits · week 31% (ext 8%) · conf 40")

    def test_no_fit_and_threshold_boundary(self):
        self.schedule(remaining=(5, 28))
        self.assertIn("· fits ·", sl.render(raw(payload(self.root, s=62)), now=NOW))       # 62 + 28 = 90
        self.assertIn("no fit: checkpoint", sl.render(raw(payload(self.root, s=62.5)), now=NOW))

    def test_live_reading_beats_schedule(self):
        self.schedule(used=10)
        self.assertIn("v0.3 ▓▓▓▓▓ 97%", sl.render(raw(payload(self.root, s=97)), now=NOW))

    def test_falls_back_to_schedule_and_marks_stale(self):
        self.schedule(used=44, stale=True)
        line = sl.render(raw(payload(self.root, rl=False)), now=NOW)
        self.assertTrue(line.startswith("v0.3 ▓▓░░░ ~44%"))
        self.assertIn("cold start", line)

    def test_degrades(self):
        self.assertEqual(sl.render(raw(payload(self.root, rl=False)), now=NOW), "navitok: no schedule yet")
        self.assertIn("session 62%", sl.render(raw(payload(self.root)), now=NOW))
        self.schedule(rel=None)
        self.assertTrue(sl.render(raw(payload(self.root)), now=NOW).startswith("done "))
        self.schedule(plan="api")
        self.assertNotIn("fit", sl.render(raw(payload(self.root)), now=NOW))
        (self.nav / "schedule.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(sl.render(raw(payload(self.root, rl=False)), now=NOW), "navitok: no schedule yet")

    def test_outside_navitok_projects_prints_nothing(self):
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        self.assertEqual(sl.render(raw(payload(other)), now=NOW), "")
        self.assertFalse((other / ".navitok").exists())
        self.assertEqual(sl.render(b"\xff not json", now=NOW), "")

    def ctx(self, tokens=None, usage=None):
        p = payload(self.root)
        cw = {"context_window_size": 200000, "used_percentage": None}
        if tokens is not None:
            cw["total_input_tokens"] = tokens
        if usage is not None:
            cw["current_usage"] = usage
        p["context_window"] = cw
        return sl.render(raw(p), now=NOW)

    def test_context_hint_above_threshold_only(self):
        self.schedule()
        base = "v0.3 ▓▓▓░░ 62% · fits · week 31% · cold start"
        self.assertEqual(self.ctx(149_999), base)
        self.assertEqual(self.ctx(150_000), base + " · ctx 150k · checkpoint + new session")
        self.assertEqual(self.ctx(160_400), base + " · ctx 160k · checkpoint + new session")
        self.assertNotIn("/clear", self.ctx(500_000))

    def test_context_hint_missing_fields_stay_silent(self):
        self.schedule()
        self.assertNotIn("ctx", sl.render(raw(payload(self.root)), now=NOW))   # no context_window
        self.assertNotIn("ctx", self.ctx())                                     # no token field
        self.assertNotIn("ctx", self.ctx(usage=None))
        p = payload(self.root)
        p["context_window"] = "broken"
        self.assertNotIn("ctx", sl.render(raw(p), now=NOW))

    def test_context_hint_falls_back_to_current_usage(self):
        self.schedule()
        line = self.ctx(usage={"input_tokens": 10, "output_tokens": 999_999,
                               "cache_creation_input_tokens": 1_000, "cache_read_input_tokens": 170_000})
        self.assertTrue(line.endswith(" · ctx 171k · checkpoint + new session"))

    def test_context_hint_threshold_from_config(self):
        self.schedule()
        self.write("config.json", {"plan": "pro", "context_hint_tokens": 50_000})
        self.assertIn("ctx 60k", self.ctx(60_000))
        for off in (0, False):
            self.write("config.json", {"context_hint_tokens": off})
            self.assertNotIn("ctx", self.ctx(900_000))
        self.write("config.json", {"context_hint_tokens": "lots"})   # invalid: default
        self.assertNotIn("ctx", self.ctx(149_000))
        self.assertIn("ctx 151k", self.ctx(151_000))

    def test_context_hint_without_schedule(self):
        self.assertEqual(self.ctx(200_000),
                         "navitok: no schedule yet · session 62% · ctx 200k · checkpoint + new session")

    def test_bar(self):
        self.assertEqual(sl.bar(0), "░░░░░")
        self.assertEqual(sl.bar(100), "▓▓▓▓▓")
        self.assertEqual(sl.bar(150), "▓▓▓▓▓")
        self.assertEqual(sl.bar(None), "░░░░░")


class Snapshot(Base):
    def test_snapshot_is_read_by_hooks(self):
        sl.render(raw(payload(self.root, s=23.5, w=41.2)), now=NOW)
        snap = json.loads((self.nav / "usage_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(snap["captured_at"], NOW)
        reading = usage_read.read_statusline_snapshot(self.nav / "usage_snapshot.json",
                                                      now=datetime.fromtimestamp(NOW + 5, timezone.utc))
        self.assertEqual((reading["source"], reading["session_pct"], reading["weekly_pct"]), ("statusline", 23.5, 41.2))
        self.assertFalse(reading["stale"])
        self.assertEqual(reading["precision"], "decimal")

    def test_snapshot_written_only_on_change_or_age(self):
        p = payload(self.root)
        self.assertTrue(sl.save_snapshot(self.nav, p, NOW))
        self.assertFalse(sl.save_snapshot(self.nav, p, NOW + 30))
        self.assertTrue(sl.save_snapshot(self.nav, p, NOW + 61))
        self.assertTrue(sl.save_snapshot(self.nav, payload(self.root, s=70), NOW + 62))

    def test_no_rate_limits_no_snapshot(self):
        sl.render(raw(payload(self.root, rl=False)), now=NOW)
        self.assertFalse((self.nav / "usage_snapshot.json").exists())


class Wrap(Base):
    def py(self, code):
        return f"{shlex.quote(sys.executable.replace(chr(92), '/'))} -c {shlex.quote(code)}"

    def test_appends_to_users_line(self):
        self.schedule()
        cmd = self.py("import sys,json; d=json.load(sys.stdin); print('mine:' + d['session_id'])")
        line = sl.render(raw(payload(self.root)), wrap=cmd, now=NOW)
        self.assertTrue(line.startswith("mine:s-1 │ v0.3 "), line)

    def test_users_line_kept_outside_navitok_and_on_failure(self):
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        self.assertEqual(sl.render(raw(payload(other)), wrap=self.py("print('mine')"), now=NOW), "mine")
        self.schedule()
        line = sl.render(raw(payload(self.root)), wrap=self.py("import sys; sys.exit(3)"), now=NOW)
        self.assertTrue(line.startswith("v0.3 "))

    def test_multiline_user_output(self):
        self.schedule()
        line = sl.render(raw(payload(self.root)), wrap=self.py("print('a'); print('b')"), now=NOW)
        self.assertEqual(line.splitlines()[0], "a")
        self.assertTrue(line.splitlines()[1].startswith("b │ v0.3"))


class Setup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "Ü" / "settings.json"

    def tearDown(self):
        self._tmp.cleanup()

    def settings(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing(self):
        rc, text = sl.setup(self.path)
        self.assertEqual(rc, 0)
        self.assertIn("Nothing written", text)
        self.assertFalse(self.path.exists())

    def test_add_then_idempotent_then_remove(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        sl.setup(self.path, apply=True)
        s = self.settings()
        self.assertEqual(s["theme"], "dark")
        self.assertTrue(sl.is_navitok(s["statusLine"]["command"]))
        self.assertTrue(self.path.with_name("settings.json.navitok-backup").exists())
        self.assertIn("already configured", sl.setup(self.path, apply=True)[1])
        sl.setup(self.path, apply=True, action="remove")
        self.assertNotIn("statusLine", self.settings())
        self.assertEqual(self.settings()["theme"], "dark")

    def test_existing_statusline_is_wrapped_and_restored(self):
        self.path.parent.mkdir(parents=True)
        orig = {"type": "command", "command": "~/bin/my line.sh --x 'y'", "padding": 2, "refreshInterval": 5}
        self.path.write_text(json.dumps({"statusLine": orig}), encoding="utf-8")
        _, text = sl.setup(self.path)
        self.assertIn("Wrap your existing statusline", text)
        self.assertEqual(self.settings()["statusLine"], orig)  # dry run
        sl.setup(self.path, apply=True)
        new = self.settings()["statusLine"]
        self.assertEqual((new["padding"], new["refreshInterval"]), (2, 5))
        self.assertEqual(sl.unwrap(new["command"]), orig["command"])
        sl.setup(self.path, apply=True, action="remove")
        self.assertEqual(self.settings()["statusLine"], orig)

    def test_invalid_settings_untouched(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[1, 2]", encoding="utf-8")
        rc, _ = sl.setup(self.path, apply=True)
        self.assertEqual(rc, 2)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "[1, 2]")


class Cli(Base):
    def test_cli_is_fast_and_utf8(self):
        self.schedule()
        start = time.perf_counter()
        r = subprocess.run([sys.executable, str(SCRIPT)], input=raw(payload(self.root)),
                           capture_output=True, timeout=30)
        elapsed = time.perf_counter() - start
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.decode("utf-8").startswith("v0.3 ▓▓▓░░ 62%"))
        self.assertLess(elapsed, 2.0)  # generous for CI; typical is well under 0.2 s

    def test_cli_never_fails(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], input=b"\xff", capture_output=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_generated_command_runs_in_sh(self):
        import shutil
        if not shutil.which("sh"):
            self.skipTest("sh not available")
        self.schedule()
        r = subprocess.run(["sh", "-c", sl.navitok_command()], input=raw(payload(self.root)),
                           capture_output=True, timeout=30)
        self.assertTrue(r.stdout.decode("utf-8").startswith("v0.3 "), r.stderr)


if __name__ == "__main__":
    unittest.main()
