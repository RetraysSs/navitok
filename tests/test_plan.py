"""Tests for scripts/plan.py (synthetic data only)."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import plan as planmod  # noqa: E402


def sample(plan="pro", mode="strict", tasks=None):
    return {"schema": 1, "project": "Ünïcode app", "plan": plan, "mode": mode, "releases": [
        {"id": "v0.1", "title": "Skeleton", "tasks": tasks or [
            {"id": "v0.1-t1", "title": "Scaffold", "type": "scaffold", "size": "S", "files": 4},
            {"id": "v0.1-t2", "title": "Wrap up", "type": "wrapup", "size": "S"}]},
        {"id": "v0.2", "title": "Login", "tasks": [
            {"id": "v0.2-t1", "title": "Login form", "type": "feature", "size": "M", "files": 3}]}]}


class Validate(unittest.TestCase):
    def test_valid_sample(self):
        self.assertEqual(planmod.validate(sample()), [])

    def test_structural_errors(self):
        p = sample()
        p["schema"] = 2
        p["mode"] = "yolo"
        p["releases"][1]["id"] = "v0.1"
        p["releases"][1]["tasks"][0]["id"] = "v0.1-t1"
        p["releases"][0]["tasks"][1]["status"] = "maybe"
        p["releases"][0]["tasks"][1]["files"] = -1
        errs = " | ".join(planmod.validate(p))
        for needle in ("schema", "mode", "duplicate release", "duplicate task", "status", "files"):
            self.assertIn(needle, errs)

    def test_empty_and_wrong_shapes(self):
        self.assertTrue(planmod.validate([]))
        p = sample()
        p["releases"] = []
        self.assertIn("releases must be a non-empty list", planmod.validate(p))
        p = sample()
        p["releases"][0]["tasks"] = []
        self.assertTrue(planmod.validate(p))
        p = sample(plan="team")
        self.assertTrue(planmod.validate(p))


class Price(unittest.TestCase):
    def test_fills_estimates(self):
        p, over = planmod.price(sample())
        self.assertEqual(over, [])
        t1 = p["releases"][0]["tasks"][0]
        self.assertEqual(t1["est_pct"], [0.33, 1.65])  # scaffold S, 4 files -> x1.1
        self.assertEqual(t1["status"], "todo")
        self.assertIsNone(t1["suggested_model"])
        self.assertEqual(p["releases"][0]["est_pct"], [0.83, 3.15])
        self.assertEqual(p["releases"][1]["est_pct"], [2.5, 7.5])

    def test_plan_alias_normalized(self):
        p, _ = planmod.price(sample(plan="Max 5x"))
        self.assertEqual(p["plan"], "max5x")

    def test_unknown_type_note(self):
        tasks = [{"id": "a", "title": "x", "type": "spike", "size": "S"}]
        p, _ = planmod.price(sample(tasks=tasks))
        self.assertIn("unknown type: widest range", p["releases"][0]["tasks"][0]["est_notes"])

    def test_over_threshold_boundary(self):
        five = [{"id": f"t{i}", "title": "x", "type": "feature", "size": "L"} for i in range(5)]
        _, over = planmod.price(sample(tasks=five))          # high exactly 90 -> fits
        self.assertEqual(over, [])
        six = five + [{"id": "t5", "title": "x", "type": "docs", "size": "S"}]
        _, over = planmod.price(sample(tasks=six))
        self.assertEqual(over, [("v0.1", 91.0)])
        _, over = planmod.price(sample(tasks=copy.deepcopy(six)), threshold=80)
        self.assertEqual(len(over), 1)

    def test_api_never_over(self):
        many = [{"id": f"t{i}", "title": "x", "type": "bugfix", "size": "L"} for i in range(10)]
        _, over = planmod.price(sample(plan="api", tasks=many))
        self.assertEqual(over, [])

    def test_invalid_plan_raises(self):
        with self.assertRaises(planmod.PlanError):
            planmod.price({"schema": 1})


class Threshold(unittest.TestCase):
    def test_override_only_lowers(self):
        self.assertEqual(planmod.threshold_for({"threshold_override": None}), 90.0)
        self.assertEqual(planmod.threshold_for({"threshold_override": 80}), 80.0)
        self.assertEqual(planmod.threshold_for({"threshold_override": 97}), 90.0)
        self.assertEqual(planmod.threshold_for({"threshold_override": True}), 90.0)
        self.assertEqual(planmod.threshold_for({"threshold_override": 0}), 90.0)


class Render(unittest.TestCase):
    def test_render_contents(self):
        p, _ = planmod.price(sample())
        text = planmod.render(p)
        self.assertIn("# Ünïcode app — Roadmap", text)
        self.assertIn("| v0.1 | Skeleton | 2 | 0.8–3.1% |", text)
        self.assertIn("### v0.2 — Login", text)
        self.assertIn("| v0.2-t1 | Login form | feature | M | 2.5–7.5% | todo |", text)
        self.assertIn("Stop threshold: **90%**", text)
        self.assertNotIn("$", text)

    def test_dollar_in_title_kept_literally(self):
        p = sample()
        p["project"] = "Cost $savings"
        p, _ = planmod.price(p)
        self.assertIn("# Cost $savings — Roadmap", planmod.render(p))

    def test_api_unit(self):
        p, _ = planmod.price(sample(plan="api"))
        self.assertIn("no session limit", planmod.render(p))


class Cli(unittest.TestCase):
    def run_cli(self, d, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/plan.py"), *args, "--project-dir", d],
                              capture_output=True, text=True, encoding="utf-8")

    def test_config_price_render_flow(self):
        with tempfile.TemporaryDirectory() as d:
            d = str(Path(d) / "prøject")
            Path(d).mkdir()
            p = self.run_cli(d, "config", "--plan", "max20x", "--mode", "flex")
            self.assertEqual(p.returncode, 0, p.stderr)
            cfg = json.loads((Path(d) / ".navitok/config.json").read_text(encoding="utf-8"))
            self.assertEqual((cfg["plan"], cfg["mode"], cfg["statusline"]), ("max20x", "flex", False))
            p = self.run_cli(d, "config", "--mode", "strict")      # keeps plan
            cfg = json.loads((Path(d) / ".navitok/config.json").read_text(encoding="utf-8"))
            self.assertEqual((cfg["plan"], cfg["mode"]), ("max20x", "strict"))

            self.assertEqual(self.run_cli(d, "price").returncode, 2)   # no plan.json yet
            (Path(d) / ".navitok/plan.json").write_text(json.dumps(sample()), encoding="utf-8")
            p = self.run_cli(d, "price")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("All releases fit", p.stdout)
            self.assertIn("All releases together: 3.3–", p.stdout)
            saved = json.loads((Path(d) / ".navitok/plan.json").read_text(encoding="utf-8"))
            self.assertIn("est_pct", saved["releases"][0])
            self.assertTrue((Path(d) / ".navitok/ROADMAP.md").exists())
            self.assertEqual(self.run_cli(d, "render").returncode, 0)

    def test_price_over_threshold_exit_1_no_roadmap(self):
        with tempfile.TemporaryDirectory() as d:
            big = [{"id": f"t{i}", "title": "x", "type": "bugfix", "size": "L"} for i in range(4)]
            nav = Path(d) / ".navitok"
            nav.mkdir()
            (nav / "plan.json").write_text(json.dumps(sample(tasks=big)), encoding="utf-8")
            p = self.run_cli(d, "price")
            self.assertEqual(p.returncode, 1)
            self.assertIn("OVER: v0.1", p.stdout)
            self.assertFalse((nav / "ROADMAP.md").exists())

    def test_malformed_plan_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            nav = Path(d) / ".navitok"
            nav.mkdir()
            (nav / "plan.json").write_text("{bad", encoding="utf-8")
            p = self.run_cli(d, "price")
            self.assertEqual(p.returncode, 2)
            self.assertIn("plan:", p.stderr)
            self.assertEqual(self.run_cli(d, "config", "--plan", "team").returncode, 2)


class PluginFiles(unittest.TestCase):
    def test_command_and_skill_reference_scripts(self):
        cmd = (ROOT / "commands/plan.md").read_text(encoding="utf-8")
        self.assertTrue(cmd.startswith("---\ndescription:"))
        self.assertIn("$ARGUMENTS", cmd)
        skill = (ROOT / "skills/navitok/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/plan.py", skill)
        for t in planmod.estimate.BASE:
            self.assertIn(f"`{t}`", skill)


if __name__ == "__main__":
    unittest.main()
