"""Tests for scripts/run.py (v0.12.1 command wrapper). Synthetic commands only."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "scripts" / "run.py"
sys.path.insert(0, str(ROOT / "scripts"))
import run as runmod  # noqa: E402

GEN = """import sys
for i in range({n}):
    print(f"test_case_{{i:03d}} ... ok")
print("FAIL: test_case_150 (tests.test_demo.Demo)", file=sys.stderr)
print("AssertionError: 41 != 42", file=sys.stderr)
print("FAILED (failures=1)")
sys.exit({code})
"""


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "proj Ü"  # non-ASCII path, as on the maintainer's machine
        self.dir.mkdir()
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.dir), PYTHONIOENCODING="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, n=300, code=1):
        p = self.dir / "gen.py"
        p.write_text(GEN.format(n=n, code=code), encoding="utf-8")
        return p

    def call(self, *args):
        return subprocess.run([sys.executable, str(RUN), *args], cwd=self.dir, env=self.env,
                              capture_output=True)

    def logs(self):
        return sorted((self.dir / ".navitok" / "logs").glob("*.log"))

    def test_failing_long_output_is_trimmed_and_exit_code_kept(self):
        r = self.call("--", sys.executable, str(self.gen(300, 1)))
        self.assertEqual(r.returncode, 1)
        out = r.stdout.decode("utf-8")
        err = r.stderr.decode("utf-8")
        self.assertTrue(out.startswith("[navitok: stdout trimmed 301 -> "), out[:200])
        self.assertIn(".navitok/logs/", out.splitlines()[0])
        self.assertLess(len(out.splitlines()), 80)
        self.assertIn("FAILED (failures=1)", out)
        # short stderr is passed through untouched
        self.assertEqual(err.replace("\r\n", "\n"),
                         "FAIL: test_case_150 (tests.test_demo.Demo)\nAssertionError: 41 != 42\n")
        logs = self.logs()
        self.assertEqual(len(logs), 1)
        body = logs[0].read_text(encoding="utf-8")
        self.assertIn("test_case_299 ... ok", body)
        self.assertIn("AssertionError: 41 != 42", body)

    def test_success_exit_code_zero(self):
        r = self.call("--", sys.executable, str(self.gen(300, 0)))
        self.assertEqual(r.returncode, 0)
        self.assertIn("[navitok: stdout trimmed", r.stdout.decode("utf-8"))

    def test_other_exit_codes_pass_through(self):
        r = self.call("--", sys.executable, "-c", "import sys; sys.exit(3)")
        self.assertEqual(r.returncode, 3)

    def test_short_output_untouched_no_log(self):
        r = self.call("--", sys.executable, "-c", "print('hello Ü')")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.decode("utf-8").replace("\r\n", "\n"), "hello Ü\n")
        self.assertEqual(self.logs(), [])

    def test_single_argument_runs_in_shell(self):
        gen = self.gen(300, 2)
        r = self.call("--", f'"{sys.executable}" "{gen}"')
        self.assertEqual(r.returncode, 2)
        self.assertIn("[navitok: stdout trimmed", r.stdout.decode("utf-8"))

    def test_missing_command_is_127(self):
        r = self.call("--", "navitok-no-such-command-xyz", "arg")
        self.assertEqual(r.returncode, 127)
        self.assertIn("cannot start", r.stderr.decode("utf-8"))

    def test_usage_errors(self):
        self.assertEqual(self.call().returncode, 2)
        self.assertEqual(self.call("--bogus", "--", "x").returncode, 2)

    def test_max_lines_flag_and_config_overrides(self):
        r = self.call("--max-lines", "1000", "--", sys.executable, str(self.gen(300, 1)))
        self.assertNotIn("[navitok:", r.stdout.decode("utf-8"))
        nav = self.dir / ".navitok"
        nav.mkdir(exist_ok=True)
        # the hook may be off; the wrapper still uses the overrides
        (nav / "config.json").write_text(json.dumps({"trim_output": {"enabled": False, "tail": 5}}),
                                         encoding="utf-8")
        opt = runmod.options(self.dir)
        self.assertEqual(opt["tail"], 5)
        self.assertEqual(opt["max_lines"], 120)
        r = self.call("--", sys.executable, str(self.gen(300, 1)))
        self.assertIn("last 5 lines kept", r.stdout.decode("utf-8"))

    def test_parse(self):
        self.assertEqual(runmod.parse(["--", "a", "b"]), (None, ["a", "b"]))
        self.assertEqual(runmod.parse(["--max-lines", "7", "--", "a"]), (7, ["a"]))
        with self.assertRaises(ValueError):
            runmod.parse(["--"])


if __name__ == "__main__":
    unittest.main()
