"""run.sh fast off path for the trim hook (v1.0): "off" is decided in the shell,
before any Python starts. Every config layout that turns trimming on must still
reach trim_output.py. Synthetic data only."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_SH = ROOT / "hooks" / "run.sh"

OFF = [
    None,  # no config.json
    "{}",
    '{"plan": "pro"}',
    '{"trim_output": false}',
    '{\n  "plan": "pro",\n  "trim_output"  :\tfalse,\n  "statusline": true\n}',  # plan.py layout
]
ON = [
    '{"trim_output": true}',
    '{"trim_output": {"enabled": true, "tail": 5}}',
    '{\n  "trim_output": {\n    "enabled": true\n  }\n}',
    '{"trim_output":\n true}',
]


class FastOffPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "proj Ü"
        (self.d / ".navitok").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, cfg_text, project_env=True, cwd=None):
        cfg = self.d / ".navitok" / "config.json"
        if cfg_text is None:
            cfg.unlink(missing_ok=True)
        else:
            cfg.write_text(cfg_text, encoding="utf-8")
        big = "".join(f"line {i} FAILED\n" if i == 150 else f"line {i}\n" for i in range(300))
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": str(self.d),
                   "tool_input": {"command": "x"},
                   "tool_response": {"stdout": big, "stderr": "", "interrupted": False, "isImage": False}}
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        if project_env:
            env["CLAUDE_PROJECT_DIR"] = str(self.d)  # Claude Code sets it for hook commands
        r = subprocess.run(["sh", str(RUN_SH), "trim"], env=env, cwd=cwd or ROOT,
                           input=json.dumps(payload).encode("utf-8"), capture_output=True)
        self.assertEqual(r.returncode, 0)
        return r.stdout

    def test_off_layouts_are_silent(self):
        for cfg in OFF:
            self.assertEqual(self.hook(cfg), b"", cfg)

    def test_on_layouts_still_trim(self):
        for cfg in ON:
            self.assertIn(b"[navitok: stdout trimmed", self.hook(cfg), cfg)

    def test_hook_cwd_is_also_checked(self):
        out = self.hook('{"trim_output": true}', project_env=False, cwd=self.d)
        self.assertIn(b"[navitok: stdout trimmed", out)


if __name__ == "__main__":
    unittest.main()
