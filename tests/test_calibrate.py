"""Tests for calibrate.py and external.py (synthetic history + the real dogfood ledger)."""

import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate  # noqa: E402
import estimate  # noqa: E402
import external  # noqa: E402
import handoff  # noqa: E402
import hook_session  # noqa: E402
import ledger  # noqa: E402
import plan as planmod  # noqa: E402
import schedule as sch  # noqa: E402

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)  # a Sunday
PPT = 1e-5  # true % per weighted token in the synthetic world
LEDGER = ROOT / "docs" / "dogfood" / "ledger.jsonl"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(i, local, ext=0.0, n=20, model="claude-opus-5-5", plan="pro", tokens=True, weekly=None,
        tasks=None, outlier=False, start_pct=10.0):
    """Session i of n (the last one ends 1 h before NOW, one per 6 h)."""
    end = NOW - timedelta(hours=1 + 6 * (n - 1 - i))
    r = ledger.new_record(
        ts_start=iso(end - timedelta(hours=1)), ts_end=iso(end), source="manual", model=model, plan=plan,
        account_session_pct_start=start_pct, account_session_pct_end=start_pct + local + ext,
        local_tokens={"input": 0, "output": round(local / (5 * PPT)), "cache_read": 0, "cache_write": 0}
        if tokens else None,
        tasks=tasks if tasks is not None else [
            {"id": f"s{i}-t{k}", "type": "feature", "size": "S", "est_pct": [1, 3]} for k in range(3)],
        outlier=outlier)
    if weekly:
        r["account_weekly_pct_start"], r["account_weekly_pct_end"] = weekly
    return r


def history(locals_, exts=None):
    n = len(locals_)
    return [rec(i, v, (exts or {}).get(i, 0.0), n) for i, v in enumerate(locals_)]


LOW = [5.8, 6.2] * 10      # estimate midpoint is 6 per session
HIGH = [2.0, 10.0] * 10


class Acceptance(unittest.TestCase):
    def test_low_variance_raises_threshold(self):
        cal = calibrate.calibrate(history(LOW), NOW)
        self.assertEqual(cal["n"], 20)
        self.assertTrue(cal["learned"])
        self.assertGreater(cal["threshold"], 90)
        self.assertLessEqual(cal["threshold"], 98)
        self.assertGreater(cal["confidence"], 80)

    def test_high_variance_stays_low(self):
        cal = calibrate.calibrate(history(HIGH), NOW)
        self.assertGreaterEqual(cal["threshold"], 90)
        self.assertLessEqual(cal["threshold"], 92)
        self.assertLess(cal["confidence"], 70)

    def test_never_above_98(self):
        cal = calibrate.calibrate(history([0.5] * 30), NOW)
        self.assertEqual(cal["threshold"], 98)
        self.assertEqual(calibrate.threshold_from(50, 0, 0), 98)

    def test_web_usage_is_external_not_error(self):
        base = calibrate.calibrate(history(LOW), NOW)
        web = {i: 10.0 for i in (3, 8, 13, 18)}
        cal = calibrate.calibrate(history(LOW, web), NOW)
        self.assertAlmostEqual(cal["pct_per_token"], PPT, places=12)
        self.assertEqual(cal["sigma_err"], base["sigma_err"])
        self.assertEqual(cal["threshold"], base["threshold"])
        for i in web:
            self.assertAlmostEqual(cal["sessions"][i]["external_pct"], 10.0, places=1)
            self.assertAlmostEqual(cal["sessions"][i]["error"], base["sessions"][i]["error"], places=6)
        self.assertEqual(cal["sessions"][0]["external_pct"], 0.0)

    def test_cold_start_below_five(self):
        cal = calibrate.calibrate(history(LOW[:4]), NOW)
        self.assertFalse(cal["learned"])
        self.assertEqual(cal["threshold"], 90)
        self.assertIsNone(cal["pct_per_token"])
        self.assertFalse(cal["external"]["known"])
        self.assertIsNone(cal["external"]["reserve_pct"])
        self.assertTrue(all(v["est_pct"] is None for v in cal["types"].values()))


class OutliersAndWeights(unittest.TestCase):
    def test_outlier_reasons(self):
        recs = history(LOW[:8])
        recs.append(rec(8, 6.0, n=12, tokens=False))                 # missing data
        recs.append(rec(9, 30.0, n=12))                              # spiral: 30 > 2 x 9
        recs.append(rec(10, 1.0, ext=20.0, n=12))                    # unexplained external
        recs.append(rec(11, 6.0, n=12, outlier=True))                # flagged by hand
        rows = {r["ts_end"]: r for r in calibrate.calibrate(recs, NOW)["sessions"]}
        reasons = [rows[r["ts_end"]]["outlier"] for r in recs[8:]]
        self.assertIn("missing data", reasons[0])
        self.assertIn("debugging spiral", reasons[1])
        self.assertIn("large unexplained external usage", reasons[2])
        self.assertIn("flagged", reasons[3])
        cal = calibrate.calibrate(recs, NOW)
        self.assertEqual(cal["n"], 8)  # outliers are not counted
        self.assertLess(rows[recs[9]["ts_end"]]["weight"], 0.25)

    def test_recorded_external_is_explained(self):
        r = rec(0, 2.0, ext=20.0, n=1)
        r["external_pct"] = 20.0
        row = calibrate.session_rows([r], PPT)[0]
        self.assertEqual(row["outlier"], [])
        self.assertAlmostEqual(row["external_pct"], 20.0)

    def test_recency_and_model_change(self):
        recs = [rec(i, 6.0, n=12, model="old-model") for i in range(6)] + \
               [rec(i, 6.0, n=12) for i in range(6, 12)]
        rows = calibrate.calibrate(recs, NOW)["sessions"]
        self.assertEqual(rows[-1]["weight"], 1.0)
        self.assertGreater(rows[-1]["weight"], rows[6]["weight"])           # recency
        self.assertLess(rows[5]["weight"], rows[6]["weight"] * calibrate.CHANGE_WEIGHT + 1e-9)

    def test_learned_types_and_size_normalisation(self):
        recs = history(LOW)
        recs[0]["tasks"] = [{"id": "m", "type": "docs", "size": "M", "est_pct": [2.5, 5]}]
        cal = calibrate.calibrate(recs, NOW)
        feat = cal["types"]["feature"]
        self.assertAlmostEqual(feat["mean"], 2.0, places=1)
        lo, hi = feat["est_pct"]
        self.assertLess(lo, 2.0)
        self.assertGreater(hi, 2.0)
        self.assertIsNone(cal["types"]["docs"]["est_pct"])  # one sample is not enough
        self.assertAlmostEqual(cal["types"]["docs"]["mean"], 5.8 / 2.5, places=2)


class External(unittest.TestCase):
    def test_weighted_tokens_and_parts(self):
        r = {"local_tokens": {"input": 10, "output": 2, "cache_read": 100, "cache_write": 4}}
        self.assertAlmostEqual(external.weighted_tokens(r), 10 + 10 + 10 + 5)
        parts = {"parts": [{"account_session_pct_start": 30, "account_session_pct_end": 31},
                           {"account_session_pct_start": 0, "account_session_pct_end": 3}]}
        self.assertEqual(external.account_delta(parts), 4)
        self.assertIsNone(external.account_delta({"account_session_pct_start": 50,
                                                  "account_session_pct_end": 3}))  # unexplained reset

    def test_weekly_profile_and_reserve(self):
        recs = history([6.0] * 10, {9: 10.0})
        for i, r in enumerate(recs):  # weekly rises 1 per session, plus a 3-point gap before #5
            base = i + (3 if i >= 5 else 0)
            r["account_weekly_pct_start"], r["account_weekly_pct_end"] = base, base + 1
        prof = external.profile(recs, now=NOW, ratio=0.1)
        self.assertTrue(prof["known"])
        self.assertIn("Sun", prof["per_weekday"])
        wk = prof["weekly"]
        # in-session external 10 x 0.1 = 1, plus the 3-point gap
        self.assertAlmostEqual(sum([wk["this_week"]]), 4.0, places=2)
        self.assertGreaterEqual(prof["reserve_pct"], 0)

    def test_weekly_ratio_learned(self):
        recs = history([10.0] * 6)
        for r in recs:
            r["account_weekly_pct_start"], r["account_weekly_pct_end"] = 0, 2
        ratio, learned = external.weekly_ratio(recs)
        self.assertTrue(learned)
        self.assertAlmostEqual(ratio, 0.2)
        self.assertEqual(external.weekly_ratio(recs[:3]), (external.WEEKLY_PER_SESSION, False))

    def test_quantile(self):
        self.assertEqual(external.quantile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(external.quantile([0, 10], 0.8), 8)
        self.assertIsNone(external.quantile([], 0.5))


class RealLedger(unittest.TestCase):
    def test_dogfood_ledger_calibrates(self):
        recs = ledger.read_all(LEDGER)
        self.assertGreaterEqual(len(recs), 7)
        cal = calibrate.calibrate(recs)
        self.assertGreaterEqual(cal["n"], 5)
        self.assertIsNotNone(cal["pct_per_token"])
        self.assertTrue(90 <= cal["threshold"] <= 98)
        self.assertTrue(0 <= cal["confidence"] <= 100)
        # The maintainer's sprints were overestimated: learned feature cost is below the cold start.
        self.assertLess(cal["types"]["feature"]["mean"], estimate.BASE["feature"][1])
        # Local usage explains most of the account delta: external stays small per session.
        exts = [s["external_pct"] for s in cal["sessions"] if s["external_pct"] is not None]
        self.assertTrue(exts and max(exts) < 5)


class Integration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Proje ÜNSAL"
        self.nav = self.root / ".navitok"
        self.nav.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_history(self, recs):
        for r in recs:
            ledger.append(r, self.nav / "history.jsonl")

    def test_config_threshold_and_pricing(self):
        self.write_history(history([0.5] * 20))
        calibrate.update(self.root, NOW)
        cfg = planmod.load_config(self.root)
        self.assertEqual(planmod.threshold_for(cfg), 98)
        self.assertEqual(planmod.threshold_for(dict(cfg, threshold_override=93)), 93)
        planmod.write_config(self.root, plan="pro")
        self.assertNotIn("calibration", json.loads((self.nav / "config.json").read_text(encoding="utf-8")))
        learned = planmod.learned_types(cfg)
        row = estimate.estimate_task({"type": "feature", "size": "S"}, "pro", learned)
        self.assertEqual(row["est_pct"], learned["feature"]["est_pct"])
        self.assertIn("learned from history", row["notes"])
        self.assertEqual(estimate.estimate_task({"type": "docs", "size": "S"}, "pro", learned)["est_pct"],
                         list(estimate.BASE["docs"]))  # unlearned type keeps the cold start

    def test_cold_start_threshold_unchanged(self):
        self.write_history(history(HIGH[:3]))
        calibrate.update(self.root, NOW)
        self.assertEqual(planmod.threshold_for(planmod.load_config(self.root)), 90)

    def test_schedule_reserves_external(self):
        plan = {"schema": 1, "project": "x", "plan": "pro", "mode": "strict", "releases": [
            {"id": "v0.1", "title": "a", "tasks": [{"id": "v0.1-t1", "title": "a", "type": "feature",
                                                    "size": "S", "status": "todo", "est_pct": [5, 20]}]}]}
        reading = {"source": "manual", "session_pct": 0, "weekly_pct": 80, "stale": False,
                   "session_resets_at": None, "weekly_resets_at": None}
        cfg = {"plan": "pro", "mode": "strict", "weekly_per_session": 0.5}
        free = sch.compute(plan, cfg, reading, now=NOW)
        self.assertEqual(free["placement"][0]["week"], 1)          # 80 + 10 <= 90
        self.assertIsNone(free["week"]["external_reserved_pct"])
        cfg["calibration"] = {"learned": True, "external": {"known": True, "reserve_pct": 5}}
        held = sch.compute(plan, cfg, reading, now=NOW)
        self.assertEqual(held["week"]["external_reserved_pct"], 5)
        self.assertEqual(held["placement"][0]["week"], 2)          # 80 + 10 > 90 - 5
        self.assertIn("5% of the week is reserved", sch.render_section(held))

    def test_fit_check_uses_learned_max_step(self):
        plan = {"schema": 1, "project": "x", "plan": "pro", "mode": "strict", "releases": [
            {"id": "v0.1", "title": "a", "tasks": [{"id": "v0.1-t1", "title": "a", "type": "feature",
                                                    "size": "S", "status": "todo", "est_pct": [1, 3]}]}]}
        cfg = {"plan": "pro", "calibration": {"learned": True, "max_step": 6}}
        r = handoff.fit_check(plan, cfg, {"threshold": 90, "session": {"used_pct": 82}})
        self.assertEqual(r["buffer"], 6)
        self.assertEqual(r["verdict"], "NO-FIT")  # 8 left < 3 + 6

    def test_recorder_attaches_finished_tasks(self):
        def write_plan(status):
            (self.nav / "plan.json").write_text(json.dumps({"releases": [{"id": "v0.1", "tasks": [
                {"id": "v0.1-t1", "type": "feature", "size": "S", "files": 2, "status": "done", "est_pct": [1, 3]},
                {"id": "v0.1-t2", "type": "test", "size": "S", "status": status, "est_pct": [0.5, 2]}]}]}),
                encoding="utf-8")
        write_plan("todo")
        missing = self.root / "no-cache.json"
        payload = {"session_id": "s-1", "cwd": str(self.root)}
        hook_session.on_start(payload, self.nav, NOW, missing)
        write_plan("done")
        hook_session.on_stop(payload, self.nav, NOW, missing)
        hook_session.on_end(payload, self.nav, NOW + timedelta(minutes=5), missing)
        rec_ = ledger.read_all(self.nav / "history.jsonl")[-1]
        self.assertEqual([t["id"] for t in rec_["tasks"]], ["v0.1-t2"])
        self.assertEqual(rec_["tasks"][0]["est_pct"], [0.5, 2])
        self.assertEqual(rec_["release"], "v0.1")

    def test_hook_writes_calibration_silently(self):
        self.write_history(history(LOW[:6]))
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({"cwd": str(self.root)}).encode("utf-8")),
                                 encoding="utf-8")
        out, old = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            self.assertEqual(calibrate.hook_main(stdin), 0)
        finally:
            sys.stdout = old
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(calibrate.load(self.root)["learned"])
        bad = io.TextIOWrapper(io.BytesIO(b"\xff"), encoding="utf-8")
        self.assertEqual(calibrate.hook_main(bad), 0)

    def test_status_text(self):
        cold = calibrate.status_text(self.root)
        self.assertIn("cold start (0 of 5", cold)
        self.assertIn("external usage unknown", cold)
        self.write_history(history(LOW))
        calibrate.update(self.root, NOW)
        (self.nav / "schedule.json").write_text(json.dumps(
            {"threshold": 95, "session": {"used_pct": 40}, "week": {"used_pct": 20}}), encoding="utf-8")
        text = calibrate.status_text(self.root)
        self.assertIn("40% used, 55% left before the 95% threshold", text)
        self.assertIn("20 learned sessions", text)
        self.assertIn("Next: no plan", text)

    def test_plugin_files(self):
        cmd = (ROOT / "commands" / "status.md").read_text(encoding="utf-8")
        self.assertTrue(cmd.startswith("---\ndescription:"))
        self.assertIn("calibrate.py\" status", cmd)
        self.assertIn('calibrate.py" hook >/dev/null 2>&1', (ROOT / "hooks" / "run.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
