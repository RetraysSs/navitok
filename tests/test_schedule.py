"""Tests for scripts/schedule.py (synthetic plans and readings only)."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import plan as planmod  # noqa: E402
import schedule as sch  # noqa: E402

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
CFG = {"plan": "pro", "mode": "strict", "threshold_override": None}


def task(tid, hi, status="todo", lo=None, actual=None):
    t = {"id": tid, "title": tid, "type": "feature", "size": "S", "status": status,
         "est_pct": [hi / 2 if lo is None else lo, hi]}
    if actual is not None:
        t["actual_pct"] = actual
    return t


def plan(mode="strict", key="pro", releases=None):
    return {"schema": 1, "project": "Ünïcode app", "plan": key, "mode": mode, "releases": releases or [
        {"id": "v0.1", "title": "One", "tasks": [task("v0.1-t1", 10), task("v0.1-t2", 10)]},
        {"id": "v0.2", "title": "Two", "tasks": [task("v0.2-t1", 30)]},
        {"id": "v0.3", "title": "Three", "tasks": [task("v0.3-t1", 50)]}]}


def reading(s, w=10, s_reset=NOW + timedelta(hours=3), w_reset=NOW + timedelta(days=3), stale=False):
    return {"source": "manual", "session_pct": s, "weekly_pct": w, "stale": stale,
            "session_resets_at": s_reset.strftime("%Y-%m-%dT%H:%M:%SZ") if s_reset else None,
            "weekly_resets_at": w_reset.strftime("%Y-%m-%dT%H:%M:%SZ") if w_reset else None}


class Compute(unittest.TestCase):
    def test_fits_and_placement(self):
        s = sch.compute(plan(), CFG, reading(40), now=NOW)
        self.assertEqual(s["current_release"], "v0.1")
        self.assertEqual(s["current_remaining_pct"], [10.0, 20.0])
        self.assertTrue(s["fits_today"])
        got = [(p["release"], p["week"], p["session"]) for p in s["placement"]]
        # 40 + 20 = 60 fits; +30 = 90 still fits; v0.3 (50) opens the next session.
        self.assertEqual(got, [("v0.1", 1, "current"), ("v0.2", 1, "current"), ("v0.3", 1, "next")])
        self.assertEqual(s["replan"], [])

    def test_threshold_boundary(self):
        self.assertTrue(sch.compute(plan(), CFG, reading(70), now=NOW)["fits_today"])   # 70+20 = 90
        self.assertFalse(sch.compute(plan(), CFG, reading(70.5), now=NOW)["fits_today"])

    def test_done_tasks_are_not_counted(self):
        p = plan()
        p["releases"][0]["tasks"][0]["status"] = "done"
        s = sch.compute(p, CFG, reading(75), now=NOW)
        self.assertEqual(s["current_remaining_pct"], [5.0, 10.0])
        self.assertTrue(s["fits_today"])
        for t in p["releases"][0]["tasks"]:
            t["status"] = "done"
        s = sch.compute(p, CFG, reading(75), now=NOW)
        self.assertEqual(s["current_release"], "v0.2")

    def test_all_done(self):
        p = plan()
        for r in p["releases"]:
            for t in r["tasks"]:
                t["status"] = "done"
        s = sch.compute(p, CFG, reading(50), now=NOW)
        self.assertIsNone(s["current_release"])
        self.assertTrue(s["fits_today"])
        self.assertEqual(s["placement"], [])

    def test_unknown_usage(self):
        s = sch.compute(plan(), CFG, None, now=NOW)
        self.assertIsNone(s["fits_today"])
        self.assertIsNone(s["session"]["used_pct"])

    def test_window_reset_means_fresh(self):
        s = sch.compute(plan(), CFG, reading(85, s_reset=NOW - timedelta(minutes=1)), now=NOW)
        self.assertEqual(s["session"]["used_pct"], 0.0)
        self.assertTrue(s["fits_today"])

    def test_api_plan_has_no_limits(self):
        s = sch.compute(plan(key="api"), dict(CFG, plan="api"), reading(99), now=NOW)
        self.assertIsNone(s["fits_today"])
        self.assertTrue(all(p["session"] == "current" and p["week"] == 1 for p in s["placement"]))

    def test_strict_moves_weekly_overflow_to_next_week(self):
        # 85% of the week used; v0.1 costs 20 * 0.15 = 3 -> 88, v0.2 costs 4.5 -> over 90.
        s = sch.compute(plan(), CFG, reading(10, w=85), now=NOW)
        weeks = {p["release"]: (p["week"], p["session"], p["extra"]) for p in s["placement"]}
        self.assertEqual(weeks["v0.1"], (1, "current", False))
        self.assertEqual(weeks["v0.2"], (2, "next", False))
        self.assertEqual(weeks["v0.3"][0], 2)

    def test_flex_marks_overflow_as_extra(self):
        s = sch.compute(plan(mode="flex"), dict(CFG, mode="flex"), reading(10, w=85), now=NOW)
        weeks = {p["release"]: (p["week"], p["extra"]) for p in s["placement"]}
        self.assertEqual(weeks["v0.1"], (1, False))
        self.assertEqual(weeks["v0.2"], (1, True))
        self.assertEqual(weeks["v0.3"], (1, True))

    def test_weekly_ratio_override(self):
        s = sch.compute(plan(), dict(CFG, weekly_per_session=1.0), reading(10, w=50), now=NOW)
        # 50+20 = 70; +30 = 100 > 90 -> week 2 (30); +50 = 80 stays in week 2.
        self.assertEqual([p["week"] for p in s["placement"]], [1, 2, 2])

    def test_unpriced_plan_is_priced_in_memory(self):
        p = plan()
        for r in p["releases"]:
            for t in r["tasks"]:
                del t["est_pct"]
        s = sch.compute(p, CFG, reading(10), now=NOW)
        self.assertGreater(s["current_remaining_pct"][1], 0)
        self.assertNotIn("est_pct", p["releases"][0]["tasks"][0])  # caller's plan untouched


class Replan(unittest.TestCase):
    def ids(self, s):
        return [t["id"] for t in s["replan"]]

    def test_release_too_big(self):
        p = plan(releases=[{"id": "v0.1", "title": "Huge", "tasks": [task("a", 60), task("b", 40)]}])
        self.assertEqual(self.ids(sch.compute(p, CFG, reading(0), now=NOW)), ["release_too_big"])

    def test_overrun_of_last_two_tasks(self):
        p = plan()
        p["releases"][0]["tasks"] = [task("v0.1-t1", 10, "done", actual=14), task("v0.1-t2", 10, "done", actual=13),
                                     task("v0.1-t3", 5)]
        self.assertIn("overrun", self.ids(sch.compute(p, CFG, reading(0), now=NOW)))
        p["releases"][0]["tasks"][1]["actual_pct"] = 12  # 26 vs 26: not > 30%
        self.assertNotIn("overrun", self.ids(sch.compute(p, CFG, reading(0), now=NOW)))

    def test_slip_of_more_than_a_week(self):
        first = sch.compute(plan(), CFG, reading(10, w=0), now=NOW)
        self.assertEqual(first["baseline"]["final_week_ends_at"], first["final_week_ends_at"])
        later = sch.compute(plan(), dict(CFG, weekly_per_session=4.0), reading(10, w=85), prev=first, now=NOW)
        self.assertIn("slipped", self.ids(later))
        self.assertEqual(later["baseline"], first["baseline"])

    def test_scope_change_resets_baseline(self):
        first = sch.compute(plan(), CFG, reading(10, w=0), now=NOW)
        p = plan()
        p["releases"].append({"id": "v0.4", "title": "Four", "tasks": [task("v0.4-t1", 50)]})
        s = sch.compute(p, dict(CFG, weekly_per_session=4.0), reading(10, w=85), prev=first, now=NOW)
        self.assertNotIn("slipped", self.ids(s))
        self.assertNotEqual(s["baseline"]["fingerprint"], first["baseline"]["fingerprint"])

    def test_settings_changed(self):
        s = sch.compute(plan(), dict(CFG, mode="flex"), reading(10), now=NOW)
        self.assertEqual(self.ids(s), ["settings_changed"])


class Notices(unittest.TestCase):
    def run_seq(self, readings, p=None, cfg=CFG):
        prev, lines = None, []
        for r in readings:
            s = sch.compute(p or plan(), cfg, r, prev, NOW)
            lines.append(sch.notice(s, prev))
            prev = json.loads(json.dumps(s))  # as if written and re-read
        return lines

    def test_first_fit_is_silent(self):
        self.assertEqual(self.run_seq([reading(10)]), [None])

    def test_external_jump_gives_exactly_one_line(self):
        lines = self.run_seq([reading(60), reading(75), reading(75), reading(76)])
        self.assertIsNone(lines[0])
        self.assertIn("v0.1 no longer fits", lines[1])
        self.assertIn("session 75%, was 60%", lines[1])
        self.assertEqual(lines[2:], [None, None])
        self.assertNotIn("\n", lines[1])

    def test_recovery_after_reset(self):
        lines = self.run_seq([reading(80), reading(80), reading(5)])
        self.assertIn("no longer fits", lines[0])
        self.assertIsNone(lines[1])
        self.assertIn("fits this session again", lines[2])

    def test_unknown_usage_keeps_state_and_is_silent(self):
        lines = self.run_seq([reading(80), None, reading(80)])
        self.assertIn("no longer fits", lines[0])
        self.assertEqual(lines[1:], [None, None])

    def test_replan_notice_once(self):
        p = plan(releases=[{"id": "v0.1", "title": "Huge", "tasks": [task("a", 95)]}])
        lines = self.run_seq([reading(0), reading(0)], p=p)
        self.assertIn("replan suggested", lines[0])
        self.assertIn("next task boundary", lines[0])
        self.assertIn("no longer fits", lines[0])  # both notices share the one line
        self.assertIsNone(lines[1])


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "prój ÜNSAL"
        self.nav = self.root / ".navitok"
        self.nav.mkdir(parents=True)
        (self.nav / "plan.json").write_text(json.dumps(plan(), ensure_ascii=False), encoding="utf-8")
        self.cache = Path(self.tmp.name) / "no-cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def recompute(self, s):
        return sch.recompute(self.root, reading=reading(s), now=NOW)

    def test_recompute_writes_schedule_and_roadmap(self):
        sched, line = self.recompute(60)
        self.assertIsNone(line)
        on_disk = json.loads((self.nav / "schedule.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["current_release"], "v0.1")
        md = (self.nav / "ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("## Schedule", md)
        self.assertIn("Session used: 60%", md)
        self.assertIn("fits this session", md)

    def test_acceptance_jump_flips_status_and_updates_roadmap(self):
        self.recompute(60)
        _, line = self.recompute(75)  # +15% from "outside"
        self.assertIn("no longer fits", line)
        md = (self.nav / "ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("does **not** fit", md)
        _, again = self.recompute(75)
        self.assertIsNone(again)

    def test_roadmap_untouched_when_unchanged(self):
        self.recompute(60)
        path = self.nav / "ROADMAP.md"
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        before = path.stat().st_mtime_ns
        self.recompute(60)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_plan_render_keeps_schedule_section(self):
        self.recompute(60)
        self.assertEqual(planmod.main(["render", "--project-dir", str(self.root)]), 0)
        self.assertIn("Session used: 60%", (self.nav / "ROADMAP.md").read_text(encoding="utf-8"))

    def hook(self, payload, raw=None):
        stdin = io.TextIOWrapper(io.BytesIO(raw if raw is not None else json.dumps(payload).encode("utf-8")))
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            rc = sch.hook_main(stdin, cache_path=self.cache)
        finally:
            sys.stdout = old
        return rc, out.getvalue()

    def test_hook_silent_without_plan_or_reading(self):
        self.assertEqual(self.hook({"cwd": str(Path(self.tmp.name))}), (0, ""))
        # No usage source at all: computed, but fit unknown -> silent.
        self.assertEqual(self.hook({"cwd": str(self.root)}), (0, ""))
        self.assertTrue((self.nav / "schedule.json").exists())

    def test_hook_prints_one_line_on_flip(self):
        snap = {"schema": 1, "captured_at": int(datetime.now(timezone.utc).timestamp()),
                "rate_limits": {"five_hour": {"used_percentage": 85.5}, "seven_day": {"used_percentage": 20}}}
        (self.nav / "usage_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
        rc, out = self.hook({"cwd": str(self.root), "prompt": "go"})
        self.assertEqual(rc, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertIn("navitok: v0.1 no longer fits", out)
        self.assertEqual(self.hook({"cwd": str(self.root), "prompt": "again"}), (0, ""))

    def test_hook_never_fails(self):
        (self.nav / "plan.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.hook({"cwd": str(self.root)}), (0, ""))
        self.assertIn("PlanError", (self.nav / "hook-errors.log").read_text(encoding="utf-8"))
        self.assertEqual(self.hook(None, raw=b"\xff not json"), (0, ""))

    def test_cli_subprocess_utf8_stdin(self):
        payload = json.dumps({"cwd": str(self.root)}, ensure_ascii=False).encode("utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "schedule.py"), "hook"],
                           input=payload, capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertTrue((self.nav / "schedule.json").exists())  # non-ASCII cwd was found

    def test_cli_recompute_with_override(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "schedule.py"), "recompute",
                            "--project-dir", str(self.root), "--session-pct", "80", "--weekly-pct", "10"],
                           capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no longer fits", r.stdout.decode("utf-8"))


class PluginFiles(unittest.TestCase):
    def test_user_prompt_submit_registered(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        cmd = hooks["UserPromptSubmit"][0]["hooks"][0]
        self.assertIn("run.sh\" prompt", cmd["command"])
        self.assertLessEqual(cmd["timeout"], 30)
        self.assertNotIn("matcher", hooks["UserPromptSubmit"][0])  # no matcher support

    def test_run_sh_passes_stdout_only_for_prompt(self):
        text = (ROOT / "hooks" / "run.sh").read_text(encoding="utf-8")
        self.assertIn('schedule.py" hook 2>/dev/null', text)
        self.assertIn('hook_session.py" "$@" >/dev/null 2>&1', text)


if __name__ == "__main__":
    unittest.main()
