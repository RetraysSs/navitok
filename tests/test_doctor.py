"""Tests for scripts/doctor.py (v0.13). Synthetic home and project folders only."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import doctor  # noqa: E402

NO_CLI = lambda name: None  # noqa: E731


def files(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home Ü"
        self.proj = base / "proj Ü"
        self.home.mkdir()
        self.proj.mkdir()
        env = mock.patch.dict("os.environ")
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CODE_GIT_BASH_PATH", None)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        return {r["key"]: r for r in doctor.run_checks(self.proj, home=self.home, which=NO_CLI)}

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")


class CleanMachine(Base):
    def test_reports_every_gap_and_changes_nothing(self):
        before = files(self.home), files(self.proj)
        rows = self.rows()
        self.assertEqual(list(rows), ["python", "shell", "project", "usage", "statusline", "trimming",
                                      "superpowers", "graphify"])
        self.assertTrue(rows["python"]["ok"])
        for key in ("shell", "project", "usage", "statusline", "trimming", "superpowers", "graphify"):
            self.assertFalse(rows[key]["ok"], key)
            self.assertTrue(rows[key]["fix"], key)
        self.assertIn("no .navitok/", rows["project"]["detail"])
        self.assertIn("no reading", rows["usage"]["detail"])
        self.assertEqual(rows["statusline"]["detail"], "no statusline configured")
        self.assertIn("run.py", rows["trimming"]["detail"])
        self.assertIn("not installed", rows["superpowers"]["detail"])
        self.assertIn("$ /plugin install superpowers@claude-plugins-official", rows["superpowers"]["fix"])
        self.assertIn("$ uv tool install graphifyy", rows["graphify"]["fix"])
        self.assertTrue(any("graphify update ." in c for c in rows["graphify"]["fix"]))
        text = doctor.render(list(rows.values()))
        self.assertEqual(text.count(doctor.GAP), 7)
        self.assertIn("Required: missing POSIX shell (sh)", text)
        self.assertIn("Nothing was installed or changed", text)
        self.assertIn("`uv tool install graphifyy`<br>or: pipx install graphifyy", text)
        self.assertEqual((files(self.home), files(self.proj)), before)  # read-only

    def test_old_python_is_a_required_gap(self):
        r = doctor.check_python((3, 9, 1), "py")
        self.assertFalse(r["ok"])
        self.assertTrue(r["required"])
        self.assertIn("Required: missing Python", doctor.render([r]))

    def test_cli_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(doctor.main(["check", "--json", "--project-dir", str(self.proj)]), 0)
        self.assertEqual(len(json.loads(buf.getvalue())), 8)


class Shell(unittest.TestCase):
    def make(self, root, rel):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        return str(p)

    def test_windows_without_git_bash_shows_how_to_install(self):
        r = doctor.check_shell(which=NO_CLI, run=lambda sh: True, env={}, nt=True)
        self.assertFalse(r["ok"])
        self.assertTrue(r["required"])
        self.assertEqual(r["detail"], "no Git Bash found")
        self.assertIn("$ winget install --id Git.Git -e", r["fix"])
        self.assertTrue(any("git-scm.com" in c for c in r["fix"]))
        self.assertIn("Required: missing POSIX shell", doctor.render([r]))

    def test_wsl_bash_in_system32_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            wsl = self.make(d, "Windows/System32/bash.exe")
            which = lambda n: wsl if n == "bash" else None  # noqa: E731
            self.assertIsNone(doctor.find_shell(which, env={}, nt=True))

    def test_git_bash_found_next_to_git_exe(self):
        with tempfile.TemporaryDirectory() as d:
            git = self.make(d, "Program Files Ü/Git/mingw64/bin/git.exe")
            bash = self.make(d, "Program Files Ü/Git/bin/bash.exe")
            which = lambda n: git if n == "git" else None  # noqa: E731
            self.assertEqual(doctor.find_shell(which, env={}, nt=True), bash)
            r = doctor.check_shell(which, run=lambda sh: True, env={}, nt=True)
            self.assertTrue(r["ok"])
            self.assertEqual(r["fix"], [])

    def test_env_override_and_failing_shell(self):
        with tempfile.TemporaryDirectory() as d:
            bash = self.make(d, "tools/bash.exe")
            env = {"CLAUDE_CODE_GIT_BASH_PATH": bash}
            self.assertEqual(doctor.find_shell(NO_CLI, env=env, nt=True), bash)
            r = doctor.check_shell(NO_CLI, run=lambda sh: False, env=env, nt=True)
            self.assertFalse(r["ok"])
            self.assertIn("failed", r["detail"])

    def test_raising_probe_is_a_gap(self):
        def boom(sh):
            raise OSError("no exec")
        r = doctor.check_shell(lambda n: "/bin/sh" if n == "sh" else None, run=boom, env={}, nt=False)
        self.assertFalse(r["ok"])

    def test_this_machine_has_a_working_shell(self):
        r = doctor.check_shell()
        if not r["ok"]:
            self.skipTest("no POSIX shell here: " + r["detail"])
        self.assertIn("works", r["detail"])


class Detected(Base):
    def test_set_up_project(self):
        nav = self.proj / ".navitok"
        self.write(nav / "config.json", {"plan": "max5x", "mode": "flex", "trim_output": {"enabled": True}})
        self.write(nav / "plan.json", {})
        self.write(nav / "usage_snapshot.json", {"schema": 1, "captured_at": time.time(), "rate_limits": {
            "five_hour": {"used_percentage": 12.5}, "seven_day": {"used_percentage": 30}}})
        self.write(self.home / ".claude" / "plugins" / "installed_plugins.json",
                   {"version": 2, "plugins": {"superpowers@x": [{"version": "7.0.2"}]}})
        self.write(self.proj / "graphify-out" / "graph.json",
                   {"nodes": [{"id": "a"}], "links": [], "graph": {"graphify_version": "0.9"}})
        rows = {r["key"]: r for r in doctor.run_checks(self.proj, self.home, which=lambda n: "/bin/graphify")}
        for key in ("project", "usage", "trimming", "superpowers", "graphify"):
            self.assertTrue(rows[key]["ok"], key)
            self.assertEqual(rows[key]["fix"], [], key)
        self.assertIn("plan max5x, mode flex", rows["project"]["detail"])
        self.assertIn("statusline (fresh", rows["usage"]["detail"])
        self.assertIn("1 nodes", rows["graphify"]["detail"])

    def test_custom_statusline_is_wrapped_not_replaced(self):
        self.write(self.home / ".claude" / "settings.json", {"statusLine": {"type": "command", "command": "my-line"}})
        r = self.rows()["statusline"]
        self.assertFalse(r["ok"])
        self.assertIn("your own statusline", r["detail"])
        self.assertIn("wraps yours", r["fix"][1])

    def test_project_local_scope_wins(self):
        self.write(self.home / ".claude" / "settings.json", {"statusLine": {"command": "my-line"}})
        cmd = doctor.statusline.navitok_command()
        self.write(self.proj / ".claude" / "settings.local.json", {"statusLine": {"command": cmd}})
        state, f = doctor.statusline_state(self.proj, self.home)
        self.assertEqual(state, "navitok")
        self.assertEqual(f.name, "settings.local.json")


class Wizard(Base):
    def test_writes_answers_and_keeps_other_keys(self):
        self.write(self.proj / ".navitok" / "config.json",
                   {"plan": "pro", "threshold_override": 85, "trim_output": {"enabled": False, "tail": 5}})
        lines = doctor.wizard(self.proj, plan="max 5x", mode="flex", trim=True, statusline_on=False,
                              home=self.home)
        cfg = json.loads((self.proj / ".navitok" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["plan"], "max5x")
        self.assertEqual(cfg["mode"], "flex")
        self.assertEqual(cfg["threshold_override"], 85)
        self.assertEqual(cfg["trim_output"], {"enabled": True, "tail": 5})
        self.assertFalse(cfg["statusline"])
        self.assertIn("trimming on", lines[0])
        self.assertTrue(any("run.py" in l and "PostToolUse" in l for l in lines))  # both paths explained

    def test_statusline_is_only_proposed(self):
        lines = doctor.wizard(self.proj, trim=False, statusline_on=True, home=self.home)
        self.assertFalse((self.home / ".claude" / "settings.json").exists())  # never written
        text = "\n".join(lines)
        self.assertIn("proposed, not made", text)
        self.assertIn("Nothing written", text)
        self.assertNotIn("run.py", text)  # trimming off: no trimming text

    def test_bad_plan_is_an_error(self):
        self.assertEqual(doctor.main(["wizard", "--plan", "gold", "--project-dir", str(self.proj)]), 2)


if __name__ == "__main__":
    unittest.main()
