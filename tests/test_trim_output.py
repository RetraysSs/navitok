"""Tests for scripts/trim_output.py (v0.12) and its coexistence with Graphify's hook.

The long test run is real: a generated unittest module with many verbose
tests and one failure is run in a temp directory. The coexistence test runs
Graphify's real PreToolUse hook (`graphify hook-guard search`) when the
`graphify` CLI is installed, and is skipped otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import trim_output as tr  # noqa: E402

RUN_SH = ROOT / "hooks" / "run.sh"
GRAPHIFY = shutil.which("graphify")
ERROR_MSG = "AssertionError: 41 != 42 : invoice total off by one (Ünïcode)"

GEN = '''import unittest

class Many(unittest.TestCase):
{tests}
    def test_zz_invoice(self):
        self.assertEqual(41, 42, "invoice total off by one (Ünïcode)")

if __name__ == "__main__":
    unittest.main(verbosity=2)
'''


def project(tmp, trim=True, **opts):
    d = Path(tmp) / "prój ÜNSAL"
    (d / ".navitok").mkdir(parents=True)
    cfg = {"schema": 1, "plan": "pro", "mode": "strict",
           "trim_output": ({"enabled": True, **opts} if opts else True) if trim else False}
    (d / ".navitok" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return d


def long_test_run(d, n=400):
    src = GEN.format(tests="\n".join(f"    def test_{i:04d}(self):\n        pass" for i in range(n)))
    (d / "test_gen.py").write_text(src, encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "test_gen.py"], cwd=d, capture_output=True, text=True,
                       encoding="utf-8", env=env)
    return r.stdout, r.stderr


def payload(d, stdout="", stderr="", event="PostToolUse", tool="Bash"):
    return {"hook_event_name": event, "tool_name": tool, "cwd": str(d), "session_id": "s",
            "tool_use_id": "toolu_01", "tool_input": {"command": "python test_gen.py"},
            "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False}}


class Settings(unittest.TestCase):
    def test_off_by_default(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(tr.settings(t))                       # no .navitok
            d = project(t, trim=False)
            self.assertIsNone(tr.settings(d))
            self.assertIsNone(tr.handle(payload(d, stdout="x\n" * 1000)))

    def test_true_and_object(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(tr.settings(project(t)), tr.DEFAULTS)
        with tempfile.TemporaryDirectory() as t:
            opt = tr.settings(project(t, max_lines=50, tail=5, head=-1))
            self.assertEqual((opt["max_lines"], opt["tail"], opt["head"]), (50, 5, tr.DEFAULTS["head"]))

    def test_plan_default_is_off(self):
        import plan as planmod
        self.assertIs(planmod.CONFIG_DEFAULTS["trim_output"], False)


class Trim(unittest.TestCase):
    opt = dict(tr.DEFAULTS, max_lines=20, head=2, tail=3, context=1)

    def test_short_untouched(self):
        self.assertIsNone(tr.trim_text("a\nb\n", self.opt))

    def test_collapse_and_keep_errors(self):
        lines = ["start", "header"] + [f"noise {chr(97 + i % 26)}{i * 7 % 13}" for i in range(60)] + \
                ["ERROR: disk full", "detail"] + [f"more {chr(97 + i % 26)}x" for i in range(40)] + \
                [f"Downloading {i}/500" for i in range(500)] + ["done"]
        text, before, after = tr.trim_text("\n".join(lines), self.opt)
        self.assertEqual(before, len(lines))
        self.assertLess(after, 40)
        self.assertIn("similar lines", text)
        self.assertIn("ERROR: disk full", text)
        self.assertIn("detail", text)                 # context after an error line
        self.assertTrue(text.rstrip().endswith("done"))
        self.assertIn("lines omitted", text)

    def test_traceback_kept_whole(self):
        tb = ["Traceback (most recent call last):", '  File "a.py", line 3, in <module>',
              "    f()", '  File "a.py", line 2, in f', "    1/0", "ZeroDivisionError: division by zero"]
        lines = [f"line {chr(97 + i % 26)}" for i in range(100)] + tb + [f"tail {chr(97 + i % 26)}" for i in range(50)]
        text, _, _ = tr.trim_text("\n".join(lines), self.opt)
        self.assertIn("\n".join(tb), text)


class Acceptance(unittest.TestCase):
    """Accept: a long test run is trimmed without losing the error message."""

    def test_long_failing_test_run(self):
        with tempfile.TemporaryDirectory() as t:
            d = project(t)
            out, err = long_test_run(d)
            self.assertGreater(len(err.splitlines()), tr.DEFAULTS["max_lines"])
            res = tr.handle(payload(d, out, err))
            new = res["hookSpecificOutput"]["updatedToolOutput"]
            self.assertEqual(res["hookSpecificOutput"]["hookEventName"], "PostToolUse")
            self.assertIn(ERROR_MSG, new["stderr"])
            self.assertIn("FAIL: test_zz_invoice", new["stderr"])
            self.assertIn("FAILED (failures=1)", new["stderr"])
            self.assertLess(len(new["stderr"].splitlines()), 80)
            self.assertEqual((new["interrupted"], new["isImage"]), (False, False))
            self.assertIn(".navitok/logs/", new["stderr"].splitlines()[0])
            logs = list((d / ".navitok" / "logs").glob("*.log"))
            self.assertEqual(len(logs), 1)
            full = logs[0].read_text(encoding="utf-8")
            self.assertIn("test_0399", full)
            self.assertIn(ERROR_MSG, full)

    def test_run_sh_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            d = project(t)
            out, err = long_test_run(d)
            r = subprocess.run(["sh", str(RUN_SH), "trim"], input=json.dumps(payload(d, out, err)).encode("utf-8"),
                               capture_output=True)
            self.assertEqual(r.returncode, 0)
            res = json.loads(r.stdout.decode("utf-8"))
            self.assertIn(ERROR_MSG, res["hookSpecificOutput"]["updatedToolOutput"]["stderr"])
            short = subprocess.run(["sh", str(RUN_SH), "trim"], input=json.dumps(payload(d, "ok\n")).encode("utf-8"),
                                   capture_output=True)
            self.assertEqual((short.returncode, short.stdout), (0, b""))   # silent

    def test_other_events_and_tools_silent(self):
        with tempfile.TemporaryDirectory() as t:
            d = project(t)
            big = "x\n" * 1000
            self.assertIsNone(tr.handle(payload(d, big, event="PreToolUse")))
            self.assertIsNone(tr.handle(payload(d, big, tool="Read")))
            bad = payload(d)
            bad["tool_response"] = "not a dict"
            self.assertIsNone(tr.handle(bad))
            self.assertEqual(tr.hook_main(b"{broken"), 0)

    def test_log_rotation(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as t:
            d = project(t, keep_logs=3)
            t0 = datetime(2026, 11, 26, tzinfo=timezone.utc)
            for i in range(5):
                tr.handle(payload(d, "ERROR x\n" + "y\n" * 300), now=t0 + timedelta(seconds=i))
            self.assertEqual(len(list((d / ".navitok" / "logs").glob("*.log"))), 3)


@unittest.skipUnless(GRAPHIFY, "graphify CLI not installed")
class GraphifyCoexistence(unittest.TestCase):
    """Accept: Graphify's hook still works. Its real PreToolUse hook and navitok's
    PostToolUse hook run on the same Bash call (concurrently, as Claude Code runs
    matching hooks in parallel) and neither changes the other's result."""

    def graphify_hook(self, d, result):
        p = payload(d, event="PreToolUse")
        p["tool_input"] = {"command": "grep -rn invoice ."}
        p.pop("tool_response")
        r = subprocess.run([GRAPHIFY, "hook-guard", "search"], input=json.dumps(p).encode("utf-8"),
                           capture_output=True, cwd=d)
        result["graphify"] = r

    def test_both_hooks_on_one_call(self):
        with tempfile.TemporaryDirectory() as t:
            d = project(t)
            out, err = long_test_run(d)
            (d / "graphify-out").mkdir()
            (d / "graphify-out" / "graph.json").write_text(json.dumps(
                {"directed": False, "multigraph": False, "graph": {}, "nodes": [
                    {"id": "a", "label": "invoice_total()", "source_file": "app.py", "source_location": "L1"}],
                 "links": []}), encoding="utf-8")
            result = {}
            th = threading.Thread(target=self.graphify_hook, args=(d, result))
            th.start()
            ours = subprocess.run(["sh", str(RUN_SH), "trim"], input=json.dumps(payload(d, out, err)).encode("utf-8"),
                                  capture_output=True)
            th.join(30)
            g = result["graphify"]
            self.assertEqual(g.returncode, 0, g.stderr)
            if g.stdout.strip():
                spec = json.loads(g.stdout.decode("utf-8"))["hookSpecificOutput"]
                self.assertEqual(spec["hookEventName"], "PreToolUse")
                self.assertNotIn("updatedInput", spec)          # nothing for us to race with
                self.assertIn("graphify", spec.get("additionalContext", ""))
            self.assertEqual(ours.returncode, 0)
            new = json.loads(ours.stdout.decode("utf-8"))["hookSpecificOutput"]["updatedToolOutput"]
            self.assertIn(ERROR_MSG, new["stderr"])
            self.assertEqual(json.loads((d / "graphify-out" / "graph.json").read_text(encoding="utf-8"))["nodes"][0]["id"], "a")
            # navitok's trimmer ignores the PreToolUse event Graphify handles.
            self.assertIsNone(tr.handle(payload(d, out, err, event="PreToolUse")))


if __name__ == "__main__":
    unittest.main()
