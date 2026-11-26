"""Tests for scripts/integrations/superpowers.py (synthetic data only).

The sample plan below is written by hand in the shape Superpowers'
writing-plans skill documents (v7.0.2). No Superpowers code or real plan is
copied here.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "integrations"))
import estimate  # noqa: E402
import plan as planmod  # noqa: E402
import superpowers as sp  # noqa: E402

SCRIPT = ROOT / "scripts" / "integrations" / "superpowers.py"

SAMPLE = """# Ünïcode Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A small notes CLI.

**Architecture:** One module, one store.

**Tech Stack:** Python 3.10

---

### Task 1: Note store

**Files:**
- Create: `notes/store.py`
- Test: `tests/test_store.py`

- [x] **Step 1: Write the failing test**

```python
def test_add():
    # - [ ] a checkbox inside a code block is not a step
    assert True
```

- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Implement `add(text: str) -> int`**
- [x] **Step 4: Run test to verify it passes**
- [x] **Step 5: Commit**

### Task 2: Fix crash on empty title

**Files:**
- Modify: `notes/store.py:10-20`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run it**
- [ ] **Step 3: Fix**
- [ ] **Step 4: Run it**
- [ ] **Step 5: Commit**

### Task 3: CLI with many commands

**Files:**
- Create: `notes/cli.py`
- Create: `notes/commands/add.py`
- Create: `notes/commands/list.py`
- Create: `notes/commands/rm.py`
- Create: `notes/commands/edit.py`
- Test: `tests/test_cli.py`

""" + "\n".join(f"- [ ] **Step {i}: step {i}**" for i in range(1, 15)) + """

### Task 4: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document usage**
- [ ] **Step 2: Commit**
"""


def write_sample(project, name="2026-11-26-notes.md", text=SAMPLE):
    d = Path(project) / "docs" / "superpowers" / "plans"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(text.encode("utf-8"))
    return p


class Detect(unittest.TestCase):
    def test_installed_from_plugin_registry(self):
        with tempfile.TemporaryDirectory() as home:
            reg = Path(home) / ".claude" / "plugins" / "installed_plugins.json"
            reg.parent.mkdir(parents=True)
            reg.write_text(json.dumps({"version": 2, "plugins": {
                "superpowers@superpowers-marketplace": [
                    {"scope": "user", "installPath": "/x/superpowers/7.0.2", "version": "7.0.2"}],
                "other@m": [{"version": "1"}]}}), encoding="utf-8")
            info = sp.detect(home=home, project_dir=home)
            self.assertTrue(info["installed"])
            self.assertEqual(info["version"], "7.0.2")

    def test_not_installed_missing_or_broken_registry(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertFalse(sp.detect(home=home, project_dir=home)["installed"])
            reg = Path(home) / ".claude" / "plugins" / "installed_plugins.json"
            reg.parent.mkdir(parents=True)
            reg.write_text("{not json", encoding="utf-8")
            self.assertFalse(sp.detect(home=home, project_dir=home)["installed"])

    def test_lists_plan_files(self):
        with tempfile.TemporaryDirectory() as proj:
            write_sample(proj, "2026-11-27-b.md")
            write_sample(proj, "2026-11-26-a.md")
            info = sp.detect(home=proj, project_dir=proj)
            self.assertEqual([Path(p).name for p in info["plans"]], ["2026-11-26-a.md", "2026-11-27-b.md"])


class Parse(unittest.TestCase):
    def setUp(self):
        self.parsed = sp.parse_plan(SAMPLE)

    def test_header(self):
        self.assertEqual(self.parsed["title"], "Ünïcode Notes")
        self.assertEqual(self.parsed["goal"], "A small notes CLI.")
        self.assertTrue(self.parsed["recommends_subagents"])

    def test_tasks(self):
        tasks = self.parsed["tasks"]
        self.assertEqual([t["number"] for t in tasks], [1, 2, 3, 4])
        self.assertEqual(tasks[0]["title"], "Note store")
        self.assertEqual(tasks[0]["files"], 2)
        self.assertEqual(tasks[1]["files"], 2)  # path suffix :10-20 is the same file
        self.assertEqual(tasks[2]["files"], 6)
        self.assertEqual(tasks[0]["steps"], 5)  # the checkbox in the code block is ignored
        self.assertEqual(tasks[0]["done_steps"], 5)
        self.assertEqual(tasks[2]["steps"], 14)

    def test_inferred_type_size_status(self):
        t = self.parsed["tasks"]
        self.assertEqual([x["type"] for x in t], ["feature", "bugfix", "feature", "docs"])
        self.assertEqual([x["size"] for x in t], ["S", "S", "L", "S"])
        self.assertEqual([x["status"] for x in t], ["done", "todo", "todo", "todo"])

    def test_no_tasks(self):
        self.assertEqual(sp.parse_plan("# Empty Implementation Plan\n\nNothing.\n")["tasks"], [])


class ToPlan(unittest.TestCase):
    def build(self, execution="auto", plan="pro", mode="strict", threshold=90.0):
        parsed = [("docs/superpowers/plans/2026-11-26-notes.md", sp.parse_plan(SAMPLE))]
        return sp.to_plan(parsed, plan=plan, mode=mode, execution=execution, threshold=threshold)

    def test_valid_versioned_plan(self):
        out, rec = self.build()
        self.assertEqual(planmod.validate(out), [])
        self.assertEqual(out["project"], "Ünïcode Notes")
        ids = [r["id"] for r in out["releases"]]
        self.assertEqual(ids[0], "v0.1")
        for r in out["releases"]:
            self.assertEqual(r["tasks"][-1]["type"], "wrapup")
            self.assertLessEqual(len(r["tasks"]), 5)
        src = out["releases"][0]["tasks"][0]["source"]
        self.assertEqual(src, {"superpowers_plan": "docs/superpowers/plans/2026-11-26-notes.md", "task": 1})

    def test_every_release_fits_the_threshold(self):
        out, _ = self.build(threshold=40.0)  # task 3 alone is ~36.6% with its wrapup
        priced, over = planmod.price(out, 40.0)
        self.assertEqual(over, [])
        self.assertGreater(len(priced["releases"]), 1)

    def test_auto_uses_subagents_and_recommends_inline_on_pro_strict(self):
        out, rec = self.build()
        tasks = [t for r in out["releases"] for t in r["tasks"] if "source" in t]
        self.assertTrue(all(t["execution"] == "subagent" for t in tasks))
        self.assertIn("inline", rec)

    def test_no_recommendation_on_flex_or_inline(self):
        self.assertIsNone(self.build(mode="flex")[1])
        out, rec = self.build(execution="inline")
        self.assertIsNone(rec)
        self.assertTrue(all(t.get("execution", "inline") == "inline"
                            for r in out["releases"] for t in r["tasks"]))

    def test_subagent_costs_more_than_inline(self):
        sub, _ = self.build(execution="subagent")
        inl, _ = self.build(execution="inline")
        hi = lambda p: sum(r["est_pct"][1] for r in planmod.price(p)[0]["releases"])  # noqa: E731
        self.assertAlmostEqual(hi(sub) / hi(inl), estimate.EXECUTION["subagent"], delta=0.35)
        self.assertGreater(hi(sub), hi(inl))

    def test_task_too_big_alone_gets_its_own_release(self):
        out, _ = self.build(threshold=3.0)
        self.assertTrue(any(len(r["tasks"]) == 2 for r in out["releases"]))  # task + wrapup


class Cli(unittest.TestCase):
    def run_cli(self, *args, home=None):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        if home:
            env["HOME"] = env["USERPROFILE"] = home
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                              text=True, encoding="utf-8", env=env)

    def test_acceptance_plan_to_roadmap_and_schedule(self):
        with tempfile.TemporaryDirectory() as proj:
            src = write_sample(proj)
            before = (src.read_bytes(), os.stat(src).st_mtime_ns)
            r = self.run_cli("ingest", "--project-dir", proj, home=proj)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("v0.1", r.stdout)
            self.assertEqual((src.read_bytes(), os.stat(src).st_mtime_ns), before)  # never modified
            nv = Path(proj) / ".navitok"
            self.assertTrue((nv / "plan.json").exists())
            self.assertTrue((nv / "ROADMAP.md").exists())
            s = subprocess.run([sys.executable, str(ROOT / "scripts" / "schedule.py"), "recompute",
                                "--project-dir", proj, "--session-pct", "10", "--weekly-pct", "20"],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(s.returncode, 0, s.stderr)
            sched = json.loads((nv / "schedule.json").read_text(encoding="utf-8"))
            self.assertTrue(sched)
            self.assertEqual(list(Path(proj, "docs", "superpowers", "plans").iterdir()), [src])

    def test_refuses_to_overwrite_plan_without_force(self):
        with tempfile.TemporaryDirectory() as proj:
            write_sample(proj)
            self.assertEqual(self.run_cli("ingest", "--project-dir", proj, home=proj).returncode, 0)
            r = self.run_cli("ingest", "--project-dir", proj, home=proj)
            self.assertEqual(r.returncode, 2)
            self.assertIn("--force", r.stderr)
            self.assertEqual(self.run_cli("ingest", "--project-dir", proj, "--force", home=proj).returncode, 0)

    def test_no_plans_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as proj:
            r = self.run_cli("ingest", "--project-dir", proj, home=proj)
            self.assertEqual(r.returncode, 2)
            self.assertIn("no Superpowers plan", r.stderr)

    def test_detect_without_superpowers(self):
        with tempfile.TemporaryDirectory() as proj:
            r = self.run_cli("detect", "--project-dir", proj, home=proj)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("not installed", r.stdout)


class WithoutSuperpowers(unittest.TestCase):
    def test_v04_flow_still_works(self):
        with tempfile.TemporaryDirectory() as proj:
            nv = Path(proj) / ".navitok"
            nv.mkdir()
            (nv / "plan.json").write_text(json.dumps({
                "schema": 1, "project": "p", "plan": "pro", "mode": "strict", "releases": [
                    {"id": "v0.1", "title": "A", "tasks": [
                        {"id": "v0.1-t1", "title": "x", "type": "feature", "size": "S"}]}]}),
                encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan.py"), "price",
                                "--project-dir", proj], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((Path(proj) / "docs").exists())


if __name__ == "__main__":
    unittest.main()
