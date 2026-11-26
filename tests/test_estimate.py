"""Tests for scripts/estimate.py (synthetic data only)."""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import estimate  # noqa: E402


def t(type_="feature", size="S", files=None, id_="t"):
    task = {"id": id_, "type": type_, "size": size}
    if files is not None:
        task["files"] = files
    return task


class TaskRanges(unittest.TestCase):
    def test_known_type_base_range(self):
        r = estimate.estimate_task(t("feature", "S"))
        self.assertEqual(r["est_pct"], [1.0, 3.0])
        self.assertEqual(r["confidence"], estimate.CONF_KNOWN)

    def test_ranges_are_ordered_and_positive(self):
        for ttype in estimate.BASE:
            for size in estimate.SIZE:
                lo, hi = estimate.estimate_task(t(ttype, size))["est_pct"]
                self.assertGreater(lo, 0)
                self.assertLess(lo, hi)

    def test_unknown_type_gets_widest_range(self):
        r = estimate.estimate_task(t("spike", "S"))
        lo, hi = r["est_pct"]
        self.assertEqual((lo, hi), estimate.widest_range())
        for blo, bhi in estimate.BASE.values():
            self.assertLessEqual(lo, blo)
            self.assertGreaterEqual(hi, bhi)
        self.assertEqual(r["confidence"], estimate.CONF_UNKNOWN_TYPE)
        self.assertTrue(r["notes"])

    def test_missing_type_is_unknown(self):
        self.assertEqual(estimate.estimate_task({"size": "S"})["confidence"],
                         estimate.CONF_UNKNOWN_TYPE)

    def test_type_and_size_are_case_insensitive(self):
        self.assertEqual(estimate.estimate_task(t("Feature", "m"))["est_pct"],
                         estimate.estimate_task(t("feature", "M"))["est_pct"])

    def test_unknown_size_priced_as_largest(self):
        r = estimate.estimate_task(t("docs", "XL"))
        self.assertEqual(r["size"], "L")
        self.assertEqual(r["est_pct"], estimate.estimate_task(t("docs", "L"))["est_pct"])
        self.assertEqual(r["confidence"], estimate.CONF_UNKNOWN_SIZE)
        self.assertEqual(estimate.estimate_task({"type": "docs"})["size"], "L")

    def test_sizes_increase(self):
        s, m, l = (estimate.estimate_task(t("test", z))["est_pct"][1] for z in "SML")
        self.assertLess(s, m)
        self.assertLess(m, l)


class FilesFactor(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(estimate.files_factor(None), 1.0)
        self.assertEqual(estimate.files_factor(0), 1.0)
        self.assertEqual(estimate.files_factor(estimate.FILES_FREE), 1.0)
        self.assertAlmostEqual(estimate.files_factor(estimate.FILES_FREE + 1), 1.1)
        self.assertEqual(estimate.files_factor(13), estimate.FILES_CAP)
        self.assertEqual(estimate.files_factor(10_000), estimate.FILES_CAP)

    def test_invalid_files_rejected(self):
        for bad in (-1, 2.5, "3", True):
            with self.assertRaises(estimate.EstimateError):
                estimate.files_factor(bad)


class Plans(unittest.TestCase):
    def test_multipliers_scale(self):
        pro = estimate.estimate_task(t(), "pro")["est_pct"]
        max5 = estimate.estimate_task(t(), "max5x")["est_pct"]
        self.assertAlmostEqual(max5[1], pro[1] * 0.2)

    def test_aliases_and_default(self):
        self.assertEqual(estimate.normalize_plan(None), "pro")
        self.assertEqual(estimate.normalize_plan("Max 20x"), "max20x")
        with self.assertRaises(estimate.EstimateError):
            estimate.normalize_plan("team")

    def test_api_has_no_fit_check(self):
        res = estimate.estimate([t()], "api")
        self.assertIsNone(res["fits_one_session"])
        self.assertIsNone(res["sessions_needed"])


class Totals(unittest.TestCase):
    def test_totals_are_sums(self):
        res = estimate.estimate([t("docs"), t("feature")])
        self.assertEqual(res["total_pct"], [1.3, 4.0])

    def test_empty_list(self):
        res = estimate.estimate([])
        self.assertEqual(res["total_pct"], [0, 0])
        self.assertEqual(res["confidence"], 0)
        self.assertTrue(res["fits_one_session"])

    def test_threshold_is_fixed_at_90(self):
        self.assertEqual(estimate.THRESHOLD, 90.0)

    def test_threshold_boundary(self):
        # feature L = 6..18 on Pro; 5 tasks -> high exactly 90.
        res = estimate.estimate([t("feature", "L")] * 5)
        self.assertEqual(res["total_pct"][1], 90.0)
        self.assertTrue(res["fits_one_session"])
        self.assertEqual(res["sessions_needed"], 1)
        res = estimate.estimate([t("feature", "L")] * 5 + [t("docs")])
        self.assertFalse(res["fits_one_session"])
        self.assertEqual(res["sessions_needed"], 2)

    def test_confidence_weighted_by_high(self):
        res = estimate.estimate([t("feature"), t("spike")])
        # (30*3 + 10*4) / 7 = 18.57 -> 19
        self.assertEqual(res["confidence"], 19)

    def test_bad_input(self):
        with self.assertRaises(estimate.EstimateError):
            estimate.estimate({"type": "docs"})
        with self.assertRaises(estimate.EstimateError):
            estimate.estimate(["docs"])


class Execution(unittest.TestCase):
    def test_subagent_multiplier(self):
        base = estimate.estimate_task({"type": "feature", "size": "S"})
        sub = estimate.estimate_task({"type": "feature", "size": "S", "execution": "subagent"})
        m = estimate.EXECUTION["subagent"]
        self.assertEqual(sub["est_pct"], [round(base["est_pct"][0] * m, 2), round(base["est_pct"][1] * m, 2)])
        self.assertTrue(any("subagent" in n for n in sub["notes"]))
        inline = estimate.estimate_task({"type": "feature", "size": "S", "execution": "inline"})
        self.assertEqual(inline["est_pct"], base["est_pct"])

    def test_unknown_execution_rejected(self):
        with self.assertRaises(estimate.EstimateError):
            estimate.estimate_task({"type": "feature", "size": "S", "execution": "swarm"})

    def test_heuristics_documents_the_multiplier(self):
        text = (ROOT / "skills/navitok/references/heuristics.md").read_text(encoding="utf-8")
        m = re.search(r"^\| subagent \| ×([\d.]+) \|", text, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(float(m.group(1)), estimate.EXECUTION["subagent"])


class DocsInSync(unittest.TestCase):
    def test_heuristics_table_matches_script(self):
        text = (ROOT / "skills/navitok/references/heuristics.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\w+) \| ([\d.]+) \| ([\d.]+) \|", text, re.M)
        self.assertEqual({r[0]: (float(r[1]), float(r[2])) for r in rows}, estimate.BASE)
        sizes = re.findall(r"^\| ([SML]) \| ([\d.]+) \|$", text, re.M)
        self.assertEqual({k: float(v) for k, v in sizes}, estimate.SIZE)

    def test_plans_table_matches_script(self):
        text = (ROOT / "skills/navitok/references/plans.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| [^|]+ \| `(\w+)` \| ([\d.]+)", text, re.M)
        self.assertEqual({k: float(v) for k, v in rows}, estimate.PLANS)
        self.assertNotRegex(text.lower(), r"\d[\d,.]*\s*k?\s*tokens")


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/estimate.py"), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_example_prints_table(self):
        p = self.run_cli(str(ROOT / "examples/tasks.json"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Task", p.stdout)
        self.assertIn("TOTAL", p.stdout)
        self.assertIn("unknown type: widest range", p.stdout)
        self.assertIn("Threshold: 90%", p.stdout)

    def test_json_and_plan_override(self):
        p = self.run_cli(str(ROOT / "examples/tasks.json"), "--plan", "api", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["plan"], "api")

    def test_bare_list_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "list.json"
            good.write_text(json.dumps([t("docs")]), encoding="utf-8")
            self.assertEqual(self.run_cli(str(good)).returncode, 0)
            bad = Path(d) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            p = self.run_cli(str(bad))
            self.assertEqual(p.returncode, 2)
            self.assertIn("estimate:", p.stderr)
            self.assertEqual(self.run_cli(str(good), "--plan", "team").returncode, 2)


if __name__ == "__main__":
    unittest.main()
