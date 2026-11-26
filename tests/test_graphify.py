"""Tests for scripts/integrations/graphify.py and helper-group calibration (v0.11).

The graph below is synthetic, written by hand in the node-link shape that
Graphify 0.9.x writes to graphify-out/graph.json (checked against a graph
built locally with `graphify update`). No Graphify code or output is copied.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate  # noqa: E402
import estimate  # noqa: E402
import graphify as gf  # noqa: E402
import hook_session  # noqa: E402
import plan as planmod  # noqa: E402
from test_calibrate import LOW, NOW, history, rec  # noqa: E402

SCRIPT = ROOT / "scripts" / "integrations" / "graphify.py"
TS = "2026-11-26T12:00:00Z"


def node(nid, label, src, line):
    return {"id": nid, "label": label, "norm_label": label.lower(), "source_file": src,
            "source_location": f"L{line}", "file_type": "code", "community": 0}


GRAPH = {
    "directed": False, "multigraph": False,
    "graph": {"schema_version": 1, "graphify_version": "0.9.120"},
    "nodes": [
        node("billing_invoice", "Invoice", "app/billing.py", 10),
        node("billing_total", "invoice_total()", "app/billing.py", 40),
        node("billing_tax", "apply_tax()", "app/billing.py", 70),
        node("mail_send", "send_receipt()", "app/mailer.py", 5),
        node("auth_login", "login()", "app/auth.py", 1),
        node("auth_logout", "logout()", "app/auth.py", 30),
    ],
    "links": [
        {"source": "billing_total", "target": "billing_tax", "relation": "calls"},
        {"source": "mail_send", "target": "billing_total", "relation": "calls"},
    ],
    "hyperedges": [],
}


def write_graph(project, graph=GRAPH, report=True):
    out = Path(project) / gf.OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / gf.GRAPH_FILE).write_text(json.dumps(graph), encoding="utf-8")
    if report:
        (out / gf.REPORT_FILE).write_text("# Graph Report\n", encoding="utf-8")
    return out / gf.GRAPH_FILE


def sample_plan(helpers=None):
    p = {"schema": planmod.SCHEMA, "project": "Ünïcode shop", "plan": "pro", "mode": "strict",
         "releases": [{"id": "v0.1", "title": "Billing", "tasks": [
             {"id": "v0.1-t1", "title": "Fix invoice total rounding", "type": "bugfix", "size": "S"},
             {"id": "v0.1-t2", "title": "Logout redirect", "type": "feature", "size": "S", "files": 1},
             {"id": "v0.1-t3", "title": "Zzz unrelated quux", "type": "feature", "size": "S"},
             {"id": "v0.1-t4", "title": "Wrap up", "type": "wrapup", "size": "S"}]}]}
    if helpers is not None:
        p["helpers"] = helpers
    return p


class Detect(unittest.TestCase):
    def test_absent_and_present(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(gf.present(d))
            self.assertFalse(gf.detect(d)["present"])
            write_graph(d)
            info = gf.detect(d)
            self.assertTrue(info["present"])
            self.assertEqual((info["nodes"], info["edges"], info["version"]), (6, 2, "0.9.120"))
            self.assertIsNotNone(info["report"])

    def test_unreadable_graph_counts_as_absent(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / gf.OUT_DIR
            out.mkdir()
            (out / gf.GRAPH_FILE).write_text("{not json", encoding="utf-8")
            self.assertFalse(gf.detect(d)["present"])

    def test_edges_key_accepted(self):
        g = dict(GRAPH)
        g["edges"] = g.pop("links")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(gf.load_graph(write_graph(d, g))["links"]), 2)


class Scope(unittest.TestCase):
    def setUp(self):
        self.idx = gf.index({"nodes": GRAPH["nodes"], "links": GRAPH["links"]})

    def test_spans(self):
        self.assertEqual(self.idx["span"]["billing_invoice"], 30)
        self.assertEqual(self.idx["span"]["billing_tax"], gf.DEFAULT_SPAN)  # last in its file

    def test_title_matches_nodes_and_neighbours(self):
        sc = gf.scope({"title": "Fix invoice total rounding"}, self.idx)
        self.assertEqual(sc["source"], "graphify")
        self.assertIn("app/billing.py", sc["paths"])
        self.assertIn("app/mailer.py", sc["paths"])      # caller of invoice_total()
        self.assertNotIn("app/auth.py", sc["paths"])
        self.assertEqual(sc["files"], 2)
        self.assertGreater(sc["lines"], 0)

    def test_no_match(self):
        self.assertIsNone(gf.scope({"title": "Zzz unrelated quux"}, self.idx))

    def test_explicit_paths(self):
        sc = gf.scope({"title": "Zzz", "paths": ["app\\auth.py"]}, self.idx)
        self.assertEqual(sc["paths"], ["app/auth.py"])

    def test_annotate_feeds_estimate_and_keeps_hand_counts(self):
        p = sample_plan(helpers=["superpowers"])
        n = gf.annotate(p, GRAPH)
        t1, t2, t3, t4 = p["releases"][0]["tasks"]
        self.assertEqual(n, 1)
        self.assertEqual(t1["files"], 2)
        self.assertEqual(t1["scope"]["source"], "graphify")
        self.assertEqual(t2["files"], 1)                 # set by hand: kept
        self.assertNotIn("scope", t2)
        self.assertNotIn("files", t3)                    # nothing matched
        self.assertNotIn("scope", t4)                    # wrapup is never scoped
        self.assertEqual(p["helpers"], ["superpowers", "graphify"])
        gf.annotate(p, GRAPH)
        self.assertEqual(p["helpers"].count("graphify"), 1)
        priced, _ = planmod.price(p)
        self.assertEqual(planmod.validate(priced), [])

    def test_more_files_raise_the_estimate(self):
        many = {"nodes": [node(f"n{i}", f"report_{i}()", f"r/report{i}.py", 1) for i in range(12)],
                "links": []}
        p = sample_plan()
        p["releases"][0]["tasks"][0]["title"] = "Report export"
        before = estimate.estimate_task(dict(p["releases"][0]["tasks"][0]))["est_pct"]
        gf.annotate(p, many)
        after = estimate.estimate_task(p["releases"][0]["tasks"][0])["est_pct"]
        self.assertEqual(p["releases"][0]["tasks"][0]["files"], 12)
        self.assertGreater(after[1], before[1])


class MapRelease(unittest.TestCase):
    def test_corpus_skips_output_and_hidden_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in ("a.py", "b.ts", "README.md", "img.png", "notes.txt",
                        ".git/x.md", "graphify-out/y.md", "node_modules/z.js"):
                f = Path(d) / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("x", encoding="utf-8")
            self.assertEqual(gf.corpus(d), {"code": 2, "other": 3})

    def test_code_only_is_cheap_and_docs_scale(self):
        code = gf.map_release({"code": 50, "other": 0})["tasks"][0]
        self.assertEqual((code["type"], code["size"], code["execution"]), ("config", "S", "inline"))
        sizes = [gf.map_release({"code": 0, "other": k})["tasks"][0]["size"] for k in (5, 50, 500)]
        self.assertEqual(sizes, ["S", "M", "L"])
        costs = [estimate.estimate(gf.map_release({"code": 0, "other": k})["tasks"])["total_pct"][1]
                 for k in (0, 5, 500)]
        self.assertEqual(costs, sorted(costs))


class Groups(unittest.TestCase):
    """Accept: synthetic history with and without Graphify stays separate;
    estimates come from the right group."""

    def helped(self, n=10):
        out = []
        for i in range(n):
            r = rec(i, 3.0, n=n)      # 1% per task, half the plain cost
            r["helpers"] = ["superpowers", "graphify"]
            r["ts_end"] = r["ts_end"].replace("2026-", "2025-")  # older, distinct ids
            out.append(r)
        return out

    def test_groups_stay_separate(self):
        cal = calibrate.calibrate(history(LOW) + self.helped(), NOW)
        plain = cal["helper_groups"]["plain"]
        helped = cal["helper_groups"]["graphify"]
        self.assertEqual((plain["n"], helped["n"]), (20, 10))
        self.assertAlmostEqual(plain["types"]["feature"]["mean"], 2.0, places=1)
        self.assertAlmostEqual(helped["types"]["feature"]["mean"], 1.0, places=1)
        self.assertEqual(cal["types"], plain["types"])
        self.assertTrue(all(s["group"] in ("plain", "graphify") for s in cal["sessions"]))

    def test_superpowers_alone_does_not_split(self):
        recs = history(LOW)
        for r in recs:
            r["helpers"] = ["superpowers"]
        cal = calibrate.calibrate(recs, NOW)
        self.assertEqual(list(cal["helper_groups"]), ["plain"])

    def test_estimates_come_from_the_right_group(self):
        cfg = {planmod.CALIBRATION_KEY: calibrate.calibrate(history(LOW) + self.helped(), NOW)}
        plain = planmod.learned_types(cfg)["feature"]["est_pct"]
        helped = planmod.learned_types(cfg, ["graphify"])["feature"]["est_pct"]
        self.assertLess(helped[1], plain[1])
        p_plain, p_help = sample_plan(), sample_plan(helpers=["graphify"])
        a = planmod.price(p_plain, learned=planmod.learned_types(cfg, p_plain.get("helpers")))[0]
        b = planmod.price(p_help, learned=planmod.learned_types(cfg, p_help.get("helpers")))[0]
        self.assertLess(b["releases"][0]["tasks"][2]["est_pct"][1], a["releases"][0]["tasks"][2]["est_pct"][1])

    def test_unlearned_group_falls_back_to_cold_start(self):
        cfg = {planmod.CALIBRATION_KEY: calibrate.calibrate(history(LOW) + self.helped(3), NOW)}
        self.assertFalse(cfg[planmod.CALIBRATION_KEY]["helper_groups"]["graphify"]["learned"])
        self.assertIsNone(planmod.learned_types(cfg, ["graphify"]))   # not the plain group's ranges
        self.assertIsNotNone(planmod.learned_types(cfg))


class Hook(unittest.TestCase):
    def test_session_records_graphify_helper(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(hook_session.helpers_for(Path(d)), [])
            write_graph(d)
            self.assertEqual(hook_session.helpers_for(Path(d)), ["graphify"])
        r = hook_session.build_record({"session_id": "s", "start": {}, "helpers": ["graphify"]})
        self.assertEqual(r["helpers"], ["graphify"])
        self.assertEqual(hook_session.build_record({"session_id": "s", "start": {}})["helpers"], [])


class PredictedScope(unittest.TestCase):
    """v0.12: Graphify's predicted scope is recorded next to the actuals."""

    def test_finished_tasks_carry_predicted_scope(self):
        with tempfile.TemporaryDirectory() as d:
            nav = Path(d) / ".navitok"
            nav.mkdir()
            p = sample_plan()
            gf.annotate(p, GRAPH)
            (nav / "plan.json").write_text(json.dumps(p), encoding="utf-8")
            before = hook_session.plan_tasks(nav)
            p["releases"][0]["tasks"][0]["status"] = "done"
            p["releases"][0]["tasks"][1]["status"] = "done"
            (nav / "plan.json").write_text(json.dumps(p), encoding="utf-8")
            done = {t["id"]: t for t in hook_session.finished_tasks(before, hook_session.plan_tasks(nav))}
        self.assertEqual(done["v0.1-t1"]["files_predicted"], 2)
        self.assertGreater(done["v0.1-t1"]["lines_predicted"], 0)
        self.assertIsNone(done["v0.1-t2"]["files_predicted"])    # hand-set count, no scope
        r = hook_session.ledger.new_record(ts_start=TS, ts_end=TS, tasks=list(done.values()))
        self.assertEqual(hook_session.ledger.validate(r), [])

    def test_ledger_rejects_bad_counts(self):
        led = hook_session.ledger
        for bad in (-1, 1.5, True, "3"):
            r = led.new_record(ts_start=TS, ts_end=TS, tasks=[{"id": "x", "files_predicted": bad}])
            self.assertTrue(any("files_predicted" in e for e in led.validate(r)), bad)
        self.assertEqual(led.validate(led.new_record(ts_start=TS, ts_end=TS, tasks=[{"id": "x", "files_predicted": None,
                                                             "files_touched": 3}])), [])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                              text=True, encoding="utf-8")

    def test_apply_end_to_end_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "prój ÜNSAL"
            nav = d / ".navitok"
            nav.mkdir(parents=True)
            (nav / "plan.json").write_text(json.dumps(sample_plan()), encoding="utf-8")
            graph = write_graph(d)
            before = (graph.read_bytes(), os.stat(graph).st_mtime_ns)
            r = self.run_cli("apply", "--project-dir", str(d))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Scoped 1 task", r.stdout)
            saved = json.loads((nav / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["helpers"], ["graphify"])
            self.assertEqual(saved["releases"][0]["tasks"][0]["files"], 2)
            self.assertTrue((nav / "ROADMAP.md").exists())
            self.assertEqual((graph.read_bytes(), os.stat(graph).st_mtime_ns), before)
            r = self.run_cli("scope", "--project-dir", str(d), "--title", "invoice total")
            self.assertIn("app/billing.py", r.stdout)

    def test_map_and_missing_graph(self):
        with tempfile.TemporaryDirectory() as d:
            nav = Path(d) / ".navitok"
            nav.mkdir()
            (nav / "plan.json").write_text(json.dumps(sample_plan()), encoding="utf-8")
            (Path(d) / "a.py").write_text("x", encoding="utf-8")
            self.assertEqual(self.run_cli("apply", "--project-dir", d).returncode, 2)
            r = self.run_cli("map", "--project-dir", d, "--apply")
            self.assertEqual(r.returncode, 0, r.stderr)
            saved = json.loads((nav / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["releases"][0]["id"], "map")
            self.assertIsInstance(saved["releases"][0]["est_pct"], list)
            self.assertIn("already has", self.run_cli("map", "--project-dir", d, "--apply").stdout)
            write_graph(d)
            self.assertIn("already exists", self.run_cli("map", "--project-dir", d).stdout)


if __name__ == "__main__":
    unittest.main()
