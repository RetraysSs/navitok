"""Tests for scripts/watch.py (synthetic project files only)."""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "watch.py"
sys.path.insert(0, str(ROOT / "scripts"))
import watch  # noqa: E402

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
TZ = timezone(timedelta(hours=3), "TRT")  # fixed display zone for the tests


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Proje ÜNSAL"
        self.nav = self.root / ".navitok"
        self.nav.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, data):
        (self.nav / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def full(self, n_releases=3):
        rels = []
        for r in range(1, n_releases + 1):
            rels.append({"id": f"v0.{r}", "title": f"Release number {r} with a long title",
                         "est_pct": [2, 6], "tasks": [
                             {"id": f"v0.{r}-t1", "status": "done" if r == 1 else "todo"},
                             {"id": f"v0.{r}-t2", "status": "doing" if r == 2 else ("done" if r == 1 else "todo")}]})
        self.write("plan.json", {"project": "Ünïcode app", "releases": rels})
        self.write("schedule.json", {
            "threshold": 92, "current_release": "v0.2", "current_remaining_pct": [2, 6], "fits_today": True,
            "usage_source": "cache", "usage_stale": True,
            "session": {"used_pct": 40, "resets_at": iso(NOW + timedelta(hours=2, minutes=5))},
            "week": {"used_pct": 30, "resets_at": iso(NOW + timedelta(days=3))},
            "placement": [{"release": f"v0.{r}", "week": 1, "session": "current" if r == 2 else "next",
                           "est_pct": [2, 6]} for r in range(2, n_releases + 1)],
            "replan": [{"reason": "the last 2 tasks went over"}]})
        self.write("calibration.json", {
            "learned": True, "n": 7, "confidence": 24,
            "external": {"known": True, "weekly": {"this_week": 3.2}, "reserve_pct": 1.5},
            "sessions": [{"release": f"v0.{i}", "est_mid": 8, "local_pct": 4 + i / 10, "error": -4 + i / 10,
                          "outlier": ["missing data"] if i == 5 else []} for i in range(6)]})

    def frame(self, w=80, h=24, root=None):
        return watch.frame(watch.gather(root or self.root, NOW, TZ), w, h)


class Frame(Base):
    def test_full_frame_fits_80x24(self):
        self.full()
        lines = self.frame()
        self.assertLessEqual(len(lines), 24)
        self.assertTrue(all(len(ln) <= 80 for ln in lines))
        text = "\n".join(lines)
        self.assertIn("navitok · Ünïcode app", lines[0])
        self.assertTrue(lines[0].endswith("15:00:00 TRT"))
        self.assertIn("40.0% used · stop at 92.0% · 52.0% left", text)
        self.assertIn("resets Mon 17:05 TRT (in 2h05m)", text)
        self.assertIn("30.0% used · external 3.2% (reserve 1.5%)", text)
        self.assertIn("Confidence 24/100 · 7 learned sessions · usage: cache (stale)", text)
        self.assertIn("Current v0.2: 2.0–6.0% left · fits this session", text)
        self.assertRegex(text, r"v0\.1 +Release number 1 with a +done +2/2")
        self.assertRegex(text, r"v0\.2 .* doing +0/2 +2\.0–6\.0% +week 1 current")
        self.assertIn("estimate → actual (local)", text)
        self.assertIn("[missing data]", text)
        self.assertIn("Replan suggested: the last 2 tasks went over", text)
        self.assertEqual(lines[-1], "q quit")

    def test_one_decimal_everywhere(self):
        self.full()
        nums = re.findall(r"(\d+(?:\.\d+)?)%", "\n".join(self.frame()))
        self.assertGreater(len(nums), 10)
        self.assertEqual([n for n in nums if not re.fullmatch(r"\d+\.\d", n)], [])
        self.assertEqual(watch._rng([2, 6.25]), "2.0–6.2%")
        self.assertEqual(watch._f(None), "?%")

    def test_many_releases_are_truncated(self):
        self.full(n_releases=30)
        lines = self.frame()
        self.assertEqual(len(lines), 24)
        self.assertEqual(lines[-2:], ["…", "q quit"])

    def test_tiny_terminal(self):
        self.full()
        lines = self.frame(30, 8)
        self.assertLessEqual(len(lines), 8)
        self.assertTrue(all(len(ln) <= 30 for ln in lines))

    def test_live_snapshot_beats_schedule(self):
        self.full()
        epoch = int(NOW.timestamp())
        self.write("usage_snapshot.json", {"schema": 1, "captured_at": epoch - 30, "rate_limits": {
            "five_hour": {"used_percentage": 71, "resets_at": epoch + 600},
            "seven_day": {"used_percentage": 45, "resets_at": epoch + 86400}}})
        text = "\n".join(self.frame())
        self.assertIn("71.0% used · stop at 92.0% · 21.0% left", text)
        self.assertIn("usage: statusline (live)", text)
        self.assertIn("resets Mon 15:10 TRT (in 0h10m)", text)

    def test_old_snapshot_is_ignored(self):
        self.full()
        epoch = int(NOW.timestamp())
        self.write("usage_snapshot.json", {"schema": 1, "captured_at": epoch - 3600, "rate_limits": {
            "five_hour": {"used_percentage": 71}}})
        self.assertIn("40.0% used", "\n".join(self.frame()))

    def test_degrades_without_data(self):
        text = "\n".join(self.frame())
        self.assertIn("?% used · stop at 90.0%", text)
        self.assertIn("external unknown", text)
        self.assertIn("cold start (0 of 5 sessions)", text)
        self.assertIn("usage: none", text)
        self.assertIn("No plan yet", text)
        (self.nav / "plan.json").write_text("{broken", encoding="utf-8")
        self.assertIn("No plan yet", "\n".join(self.frame()))

    def test_no_navitok_folder(self):
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        self.assertIn("No .navitok/ folder", "\n".join(self.frame(root=other)))

    def test_bar_with_threshold_mark(self):
        self.assertEqual(watch.bar(50, 10, mark=90), "▓▓▓▓▓░░░|░")
        self.assertEqual(watch.bar(None, 4), "░░░░")
        self.assertEqual(watch.bar(120, 4), "▓▓▓▓")


class Zones(unittest.TestCase):
    def test_zone_names(self):
        self.assertEqual(watch._zone(NOW.astimezone(TZ)), "TRT")
        self.assertEqual(watch._zone(NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))), "UTC+05:30")

        class Nameless(tzinfo):
            def utcoffset(self, dt):
                return timedelta(hours=-4)

            def tzname(self, dt):
                return None

            def dst(self, dt):
                return timedelta(0)

        self.assertEqual(watch._zone(NOW.astimezone(Nameless())), "UTC-04:00")
        self.assertTrue(watch._zone(watch._local(NOW)))  # the machine's own zone has some name

    def test_local_zone_is_the_default(self):
        state = watch.gather(tempfile.gettempdir(), NOW)
        loc = NOW.astimezone()
        self.assertTrue(watch.frame(state)[0].endswith(f"{loc:%H:%M:%S} {watch._zone(loc)}"))

    def test_sessions_without_release_are_distinguishable(self):
        a = {"ts_end": "2026-01-05T05:00:00Z", "release": None}
        b = {"ts_end": "2026-01-05T11:00:00Z", "release": None}
        self.assertEqual(watch._session_label(a, TZ), "01-05 08:00")
        self.assertNotEqual(watch._session_label(a, TZ), watch._session_label(b, TZ))
        self.assertEqual(watch._session_label({"release": "v0.3"}, TZ), "v0.3")


class Loops(Base):
    def test_ansi_loop_draws_and_stops(self):
        self.full()
        out = io.StringIO()
        with mock.patch.object(watch, "enable_vt", return_value=True), \
                mock.patch.object(watch.Keys, "wait", side_effect=[None, "q"]):
            frames = watch.run_ansi(self.root, 1, out=out)
        self.assertEqual(frames, 2)
        text = out.getvalue()
        self.assertEqual(text.count("\x1b[H\x1b[2J"), 2)
        self.assertTrue(text.startswith("\x1b[?25l"))
        self.assertIn("\x1b[?25h", text)   # cursor restored

    def test_ansi_loop_without_vt_is_plain(self):
        out = io.StringIO()
        with mock.patch.object(watch, "enable_vt", return_value=False), \
                mock.patch.object(watch.Keys, "wait", return_value="Q"):
            watch.run_ansi(self.root, 1, out=out)
        self.assertNotIn("\x1b", out.getvalue())

    def test_duration_stops_loop(self):
        out = io.StringIO()
        with mock.patch.object(watch, "enable_vt", return_value=False), \
                mock.patch.object(watch.Keys, "wait", return_value=None):
            self.assertEqual(watch.run_ansi(self.root, 1, duration=0, out=out), 1)

    def test_errors_are_shown_and_logged(self):
        log = Path(self._tmp.name) / "err.log"
        with mock.patch.object(watch, "gather", side_effect=RuntimeError("boom")):
            lines = watch._safe_frame(self.root, (80, 24), str(log))
        self.assertIn("error reading data (RuntimeError)", lines[0])
        self.assertIn("RuntimeError: boom", log.read_text(encoding="utf-8"))

    def test_keys_without_tty_just_sleeps(self):
        k = watch.Keys.__new__(watch.Keys)
        k.ok, k._old = False, None
        self.assertIsNone(k.wait(0.01))

    def test_enable_vt_never_raises(self):
        self.assertIn(watch.enable_vt(), (True, False))


class Cli(Base):
    def test_once_is_plain_utf8(self):
        self.full()
        r = subprocess.run([sys.executable, str(SCRIPT), "--once", "--project-dir", str(self.root)],
                           capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.decode("utf-8")
        self.assertIn("navitok · Ünïcode app", out)
        self.assertNotIn("\x1b", out)

    def test_live_mode_with_duration_and_log(self):
        log = Path(self._tmp.name) / "soak.log"
        r = subprocess.run([sys.executable, str(SCRIPT), "--plain", "--project-dir", str(self.root),
                            "--interval", "1", "--duration", "0", "--log", str(log)],
                           capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(log.read_text(encoding="utf-8"), r"done: mode=ansi frames=1 ")


def _win_path(fn, path):
    """GetShortPathNameW / GetLongPathNameW, or None if unavailable."""
    if os.name != "nt":
        return None
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = getattr(ctypes.windll.kernel32, fn)(str(path), buf, 1024)
    return buf.value if 0 < n < 1024 else None


class NonAsciiPaths(Base):
    """Regression: the maintainer's home has "Ü", and Windows may show the same
    folder as an 8.3 short path (C:\\Users\\NSAL~1). Both forms must work for
    the panel, the statusline and the hooks."""

    def forms(self):
        long_ = _win_path("GetLongPathNameW", self.root) or str(self.root.resolve())
        out = {"long": long_}
        short = _win_path("GetShortPathNameW", self.root)
        if short and short != long_:
            out["short"] = short
        return out

    def test_long_form_has_non_ascii(self):
        self.assertIn("Ü", self.forms()["long"])

    def test_short_form_when_available(self):
        forms = self.forms()
        if "short" not in forms:
            self.skipTest("no distinct 8.3 short path on this system")
        self.assertIn("~", forms["short"])
        self.assertTrue(os.path.samefile(forms["short"], forms["long"]))

    def test_every_entry_point_accepts_both_forms(self):
        self.full()
        scripts = ROOT / "scripts"
        for label, path in self.forms().items():
            with self.subTest(form=label):
                r = subprocess.run([sys.executable, str(scripts / "watch.py"), "--once", "--project-dir", path],
                                   capture_output=True, timeout=30)
                self.assertIn("navitok · Ünïcode app", r.stdout.decode("utf-8"), r.stderr)
                stdin = json.dumps({"cwd": path, "workspace": {"project_dir": path}, "rate_limits": {
                    "five_hour": {"used_percentage": 33, "resets_at": 1900000000}}}, ensure_ascii=False)
                r = subprocess.run([sys.executable, str(scripts / "statusline.py")],
                                   input=stdin.encode("utf-8"), capture_output=True, timeout=30)
                self.assertIn("33%", r.stdout.decode("utf-8"), r.stderr)
                snap = json.loads((self.nav / "usage_snapshot.json").read_text(encoding="utf-8"))
                self.assertEqual(snap["rate_limits"]["five_hour"]["used_percentage"], 33)
                (self.nav / "usage_snapshot.json").unlink()
                # the frame from either form shows the same data
                self.assertEqual(self.frame(root=Path(path))[1:], self.frame()[1:])

    def test_hooks_accept_both_forms(self):
        if not shutil.which("sh"):
            self.skipTest("sh not available")
        self.write("plan.json", {"schema": 1, "project": "Ünïcode app", "plan": "pro", "mode": "strict",
                                 "releases": [{"id": "v0.1", "title": "a", "tasks": [
                                     {"id": "v0.1-t1", "title": "a", "type": "feature", "size": "S"}]}]})
        for label, path in self.forms().items():
            with self.subTest(form=label):
                (self.nav / "schedule.json").unlink(missing_ok=True)
                stdin = json.dumps({"cwd": path, "session_id": f"s-{label}", "source": "startup"},
                                   ensure_ascii=False).encode("utf-8")
                r = subprocess.run(["sh", str(ROOT / "hooks" / "run.sh"), "prompt"], input=stdin,
                                   capture_output=True, timeout=60)
                self.assertEqual(r.returncode, 0)
                self.assertTrue((self.nav / "schedule.json").is_file(), label)
                subprocess.run(["sh", str(ROOT / "hooks" / "run.sh"), "start"], input=stdin,
                               capture_output=True, timeout=60)
                self.assertTrue((self.nav / "sessions" / f"s-{label}.json").is_file(), label)


if __name__ == "__main__":
    unittest.main()
