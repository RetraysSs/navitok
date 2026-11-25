"""Tests for scripts/handoff.py (synthetic plans and repos only)."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import handoff  # noqa: E402

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
CFG = {"plan": "pro", "mode": "strict", "threshold_override": None}
HAS_GIT = shutil.which("git") is not None
HAS_SH = shutil.which("sh") is not None


def task(tid, hi, status="todo", title=None):
    return {"id": tid, "title": title or f"Task {tid}", "type": "feature", "size": "S",
            "status": status, "est_pct": [hi / 2, hi]}


def plan(key="pro", statuses=("done", "done", "todo", "todo", "todo")):
    return {"schema": 1, "project": "Ünïcode app", "plan": key, "mode": "strict", "releases": [
        {"id": "v0.1", "title": "Base", "tasks": [task("v0.1-t1", 3, "done")]},
        {"id": "v0.2", "title": "Sync", "tasks": [task(f"v0.2-t{i}", 4, s)
                                                  for i, s in enumerate(statuses, 1)]}]}


def sched(used, threshold=90, stale=False):
    return {"threshold": threshold, "session": {"used_pct": used}, "usage_stale": stale}


class FitCheck(unittest.TestCase):
    def test_fits_with_room(self):
        r = handoff.fit_check(plan(), CFG, sched(50))
        self.assertEqual(r["verdict"], "FITS")
        self.assertEqual(r["task"], "v0.2-t3")
        self.assertEqual(r["buffer"], 2.0)
        self.assertTrue(r["line"].startswith("FITS: v0.2-t3"))

    def test_boundary_is_inclusive(self):
        # remaining 90-84 = 6 = hi 4 + buffer 2
        self.assertEqual(handoff.fit_check(plan(), CFG, sched(84))["verdict"], "FITS")
        self.assertEqual(handoff.fit_check(plan(), CFG, sched(84.5))["verdict"], "NO-FIT")

    def test_no_fit_proposes_checkpoint(self):
        r = handoff.fit_check(plan(), CFG, sched(88))
        self.assertEqual(r["verdict"], "NO-FIT")
        self.assertIn("/navitok:checkpoint", r["line"])

    def test_max_step_raises_buffer(self):
        cfg = dict(CFG, max_step_pct=5)
        r = handoff.fit_check(plan(), cfg, sched(82))  # remaining 8 < 4 + 5
        self.assertEqual(r["buffer"], 5.0)
        self.assertEqual(r["verdict"], "NO-FIT")

    def test_small_max_step_keeps_minimum_buffer(self):
        self.assertEqual(handoff.fit_check(plan(), dict(CFG, max_step_pct=0.5), sched(10))["buffer"], 2.0)

    def test_unknown_without_reading(self):
        for s in (None, {}, sched(None)):
            r = handoff.fit_check(plan(), CFG, s)
            self.assertEqual(r["verdict"], "UNKNOWN")
            self.assertIn("/usage", r["line"])

    def test_stale_is_flagged_not_blocked(self):
        r = handoff.fit_check(plan(), CFG, sched(10, stale=True))
        self.assertEqual(r["verdict"], "FITS")
        self.assertIn("stale", r["line"])

    def test_threshold_from_schedule(self):
        self.assertEqual(handoff.fit_check(plan(), CFG, sched(80, threshold=96))["verdict"], "FITS")
        self.assertEqual(handoff.fit_check(plan(), CFG, sched(80, threshold=85))["verdict"], "NO-FIT")

    def test_doing_task_comes_first(self):
        p = plan(statuses=("done", "todo", "doing", "todo", "todo"))
        self.assertEqual(handoff.fit_check(p, CFG, sched(10))["task"], "v0.2-t3")

    def test_explicit_task(self):
        self.assertEqual(handoff.fit_check(plan(), CFG, sched(10), "v0.2-t5")["task"], "v0.2-t5")
        with self.assertRaises(handoff.planmod.PlanError):
            handoff.fit_check(plan(), CFG, sched(10), "nope")

    def test_api_plan_always_fits(self):
        self.assertEqual(handoff.fit_check(plan("api"), CFG, sched(99))["verdict"], "FITS")

    def test_plan_complete(self):
        p = plan(statuses=("done",) * 5)
        self.assertEqual(handoff.fit_check(p, CFG, sched(99))["verdict"], "DONE")

    def test_unpriced_plan_is_priced_in_memory(self):
        p = plan()
        for r in p["releases"]:
            for t in r["tasks"]:
                del t["est_pct"]
        r = handoff.fit_check(p, CFG, sched(10))
        self.assertGreater(r["task_hi"], 0)
        self.assertNotIn("est_pct", p["releases"][1]["tasks"][2])  # caller's plan untouched


class Render(unittest.TestCase):
    GIT = {"commit": "abc1234 feat: sync", "dirty": [("M", "src/sync.py"), ("??", "docs/ñ.md")]}

    def test_resume_line_names_release_and_task(self):
        line = handoff.resume_line(plan(), self.GIT)
        self.assertIn("continuing v0.2 (Sync), task 3 of 5: v0.2-t3", line)
        self.assertIn("2 done", line)
        self.assertIn("Last commit: abc1234", line)
        self.assertIn("2 uncommitted files", line)

    def test_handoff_sections(self):
        text = handoff.render_handoff(plan(), self.GIT, ["chose SQLite", "  "], NOW)
        self.assertIn("> Resume: continuing v0.2", text)
        self.assertIn("2026-01-05T12:00:00Z", text)
        self.assertIn("`abc1234 feat: sync`", text)
        self.assertIn("- v0.2-t1 Task v0.2-t1 (done)", text)
        self.assertIn("v0.2-t3 Task v0.2-t3 (task 3 of 5, todo, est 2–4%)", text)
        self.assertIn("- `docs/ñ.md` (??)", text)
        self.assertIn("- chose SQLite", text)
        self.assertNotIn("$", text)

    def test_no_git_and_clean_tree(self):
        self.assertIn("not a git repository", handoff.render_handoff(plan(), {"commit": None, "dirty": None}))
        text = handoff.render_handoff(plan(), {"commit": None, "dirty": []})
        self.assertIn("working tree is clean", text)
        self.assertIn("**Last commit:** none", text)

    def test_plan_complete(self):
        p = plan(statuses=("done",) * 5)
        self.assertIn("all releases in the plan are done", handoff.resume_line(p, {}))
        self.assertIn("the plan is complete", handoff.render_handoff(p, {"dirty": []}))


class Project(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Proje ÜNSAL"
        self.nav = self.root / ".navitok"
        self.nav.mkdir(parents=True)
        self.write_plan(plan())

    def tearDown(self):
        self._tmp.cleanup()

    def write_plan(self, p):
        (self.nav / "plan.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_write_and_summary_in_git_repo(self):
        if not HAS_GIT:
            self.skipTest("git not available")
        self.git("init", "-q")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                 "--allow-empty", "-m", "feat: first")
        (self.root / "çalışma.py").write_text("x = 1\n", encoding="utf-8")
        path, text = handoff.write_handoff(self.root, ["half-way through the parser"], NOW)
        self.assertEqual(path, self.nav / "HANDOFF.md")
        self.assertIn("feat: first", text)
        self.assertIn("`çalışma.py`", text)
        self.assertNotIn(".navitok/", text.split("## Half-edited")[1].split("## Notes")[0])
        s = handoff.summary(self.root)
        self.assertTrue(s.startswith("navitok handoff (2026-01-05T12:00:00Z): continuing v0.2 (Sync), task 3 of 5"))
        self.assertIn("1 uncommitted file.", s)
        self.assertNotIn("plan.json now says", s)
        self.assertLessEqual(len(s), handoff.SUMMARY_MAX)

    def test_write_outside_git(self):
        _, text = handoff.write_handoff(self.root, [], NOW)
        self.assertIn("not a git repository", text)

    def test_summary_notes_plan_moved_on(self):
        handoff.write_handoff(self.root, [], NOW)
        self.write_plan(plan(statuses=("done", "done", "done", "todo", "todo")))
        self.assertIn("plan.json now says: continuing v0.2 (Sync), task 4 of 5", handoff.summary(self.root))

    def test_summary_of_hand_written_handoff(self):
        (self.nav / "HANDOFF.md").write_text("# Notes\n\nWe stopped in the parser.\n", encoding="utf-8")
        self.assertIn("We stopped in the parser.", handoff.summary(self.root))

    def test_summary_is_capped(self):
        (self.nav / "HANDOFF.md").write_text("> Resume: " + "x" * 5000 + "\n", encoding="utf-8")
        self.assertEqual(len(handoff.summary(self.root)), handoff.SUMMARY_MAX)

    def test_no_handoff(self):
        self.assertIsNone(handoff.summary(self.root))

    def hook(self, payload):
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            rc = handoff.hook_main(stdin)
        finally:
            sys.stdout = old
        return rc, out.getvalue()

    def test_hook_sources(self):
        self.assertEqual(self.hook({"cwd": str(self.root), "source": "startup"}), (0, ""))  # no handoff
        handoff.write_handoff(self.root, [], NOW)
        for src in ("startup", "clear", "compact"):
            rc, out = self.hook({"cwd": str(self.root), "source": src})
            self.assertEqual(rc, 0)
            self.assertIn("continuing v0.2", out)
            self.assertEqual(out.count("\n"), 1)
        self.assertEqual(self.hook({"cwd": str(self.root), "source": "resume"}), (0, ""))

    def test_hook_never_fails(self):
        stdin = io.TextIOWrapper(io.BytesIO(b"\xff not json"), encoding="utf-8")
        self.assertEqual(handoff.hook_main(stdin), 0)

    def test_cli_fit_exit_codes(self):
        def fit(used):
            (self.nav / "schedule.json").write_text(json.dumps(sched(used)), encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "handoff.py"), "fit",
                                "--project-dir", str(self.root)], capture_output=True, timeout=30)
            return r.returncode, r.stdout.decode("utf-8")
        self.assertEqual(fit(10)[0], 0)
        self.assertEqual(fit(89)[0], 1)
        self.assertEqual(fit(None)[0], 3)

    def test_run_sh_start_records_and_prints(self):
        if not HAS_SH:
            self.skipTest("sh not available")
        handoff.write_handoff(self.root, [], NOW)
        payload = json.dumps({"cwd": str(self.root), "session_id": "s-1", "source": "startup",
                              "hook_event_name": "SessionStart"}, ensure_ascii=False).encode("utf-8")
        r = subprocess.run(["sh", str(ROOT / "hooks" / "run.sh"), "start"], input=payload,
                           capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        out = r.stdout.decode("utf-8")
        self.assertIn("navitok handoff", out)
        self.assertEqual(out.strip().count("\n"), 0)
        self.assertTrue((self.nav / "sessions" / "s-1.json").is_file())  # recorder still ran


class PluginFiles(unittest.TestCase):
    def test_checkpoint_command(self):
        text = (ROOT / "commands" / "checkpoint.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ndescription:"))
        self.assertIn("Checkpoint flow", text)
        self.assertIn("## Checkpoint flow", (ROOT / "skills" / "navitok" / "SKILL.md").read_text(encoding="utf-8"))

    def test_skill_has_fit_rule(self):
        text = (ROOT / "skills" / "navitok" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("handoff.py\" fit", text)
        self.assertIn("NO-FIT", text)

    def test_session_start_runs_handoff(self):
        text = (ROOT / "hooks" / "run.sh").read_text(encoding="utf-8")
        self.assertIn('handoff.py" hook 2>/dev/null', text)


if __name__ == "__main__":
    unittest.main()
