"""权重、有效回收与群体估计的单元测试。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp import estimate as est  # noqa: E402
from timeopp import pipeline, weights as weights_mod  # noqa: E402
from timeopp.model import load_materials  # noqa: E402
from timeopp.synth import write_dataset  # noqa: E402


class WeightTests(unittest.TestCase):
    # 小型合成资料每人只有 1-3 天日记，使用与样本匹配的宽松有效门槛
    MIN_DAYS = 1
    MIN_COVERAGE = 0.0

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)
        cls.diag = pipeline.run_diagnostics(
            cls.materials, min_valid_days=cls.MIN_DAYS,
            min_coverage_ratio=cls.MIN_COVERAGE)
        cls.weighting = weights_mod.build_weights(
            cls.materials, cls.diag["person_records"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_nonrespondents_listed_with_reason(self):
        reasons = {r["person_id"]: r["reason"]
                   for r in self.weighting["nonresponse"]}
        # C1/C2 完全无日记
        self.assertEqual(reasons["C1"], "no_diary")
        self.assertEqual(reasons["C2"], "no_diary")

    def test_unsupported_stratum_not_represented(self):
        rep = self.weighting["representability"]
        unsupported = set(rep["unsupported_strata"])
        # S2-6 层没有任何有效回收
        self.assertIn("S2-6", unsupported)
        # 该层学生不在估计权重中，禁止用大权重"造"出估计
        self.assertNotIn("C1", self.weighting["weights"])
        self.assertNotIn("C2", self.weighting["weights"])

    def test_nonresponse_adjustment_preserves_stratum_weight_total(self):
        for stratum, detail in self.weighting["strata"].items():
            if detail["nonresponse_adjustment_factor"] is None:
                continue
            members = [pid for pid, row in self.materials.frame.items()
                       if row["stratum"] == stratum]
            base_total = sum(self.weighting["base_weights"][pid]
                             for pid in members)
            adj_total = sum(self.weighting["weights"].get(pid, 0.0)
                            for pid in members)
            self.assertAlmostEqual(base_total, adj_total, places=6)

    def test_weight_trimming_keeps_total_and_logs(self):
        unequal = {"X1": 1.0, "X2": 1.0, "X3": 5.0}
        new_weights, trimming = weights_mod.apply_trimming(
            unequal, cap_ratio=2.0)
        self.assertAlmostEqual(sum(new_weights.values()),
                               sum(unequal.values()), places=6)
        self.assertTrue(trimming["applied"])
        self.assertEqual([r["person_id"] for r in trimming["records"]],
                         ["X3"])
        # 空权重表不报错
        empty_w, empty_t = weights_mod.apply_trimming({}, cap_ratio=2.0)
        self.assertEqual(empty_w, {})
        self.assertFalse(empty_t["applied"])

    def test_boarder_group_unsupported_when_no_respondent(self):
        # 合成资料里仅有的 boarder 是 C1/C2，且都无日记
        groups = self.weighting["representability"]["unsupported_boarder_groups"]
        self.assertIn("boarder", groups)


class EstimateTests(unittest.TestCase):
    MIN_DAYS = 1
    MIN_COVERAGE = 0.0

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)
        cls.diag = pipeline.run_diagnostics(
            cls.materials, min_valid_days=cls.MIN_DAYS,
            min_coverage_ratio=cls.MIN_COVERAGE)
        cls.weighting = weights_mod.build_weights(
            cls.materials, cls.diag["person_records"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_group_estimate_excludes_unsupported(self):
        result = est.estimate_group(
            self.diag["person_records"], self.weighting["weights"],
            self.materials)
        self.assertTrue(result["estimable"])
        # 只有 A1/A2/B1 三人进入估计
        self.assertEqual(result["n_persons"], 3)

    def test_audio_credit_does_not_change_focused_reading(self):
        no_credit = est.estimate_group(
            self.diag["person_records"], self.weighting["weights"],
            self.materials, audio_credit=0.0)
        full_credit = est.estimate_group(
            self.diag["person_records"], self.weighting["weights"],
            self.materials, audio_credit=1.0)
        self.assertEqual(
            no_credit["focused_reading"]["mean_daily_minutes"],
            full_credit["focused_reading"]["mean_daily_minutes"])
        self.assertGreater(
            full_credit["combined_reading_with_credit"]["mean_daily_minutes"],
            no_credit["combined_reading_with_credit"]["mean_daily_minutes"])

    def test_unknown_minutes_produce_bounds_not_point_guess(self):
        result = est.estimate_group(
            self.diag["person_records"], self.weighting["weights"],
            self.materials)
        b = result["bounds_due_to_unknown"]
        self.assertLess(b["lower_mean_daily_minutes"],
                        b["upper_if_all_unknown_is_reading"])
        self.assertGreaterEqual(result["mean_unknown_minutes_daily"], 0.0)

    def test_invalid_credit_rejected(self):
        with self.assertRaises(ValueError):
            est.estimate_group(
                self.diag["person_records"], self.weighting["weights"],
                self.materials, audio_credit=1.5)

    def test_empty_group_not_estimable(self):
        result = est.estimate_group(
            self.diag["person_records"], self.weighting["weights"],
            self.materials, person_ids=["C1", "C2"])
        self.assertFalse(result["estimable"])

    def test_household_cluster_se_uses_households(self):
        records = {pid: self.diag["person_records"][pid]
                   for pid in self.weighting["weights"]}
        values = {pid: records[pid]["mean_daily_reading"]
                  for pid in records}
        households = {pid: self.materials.people[pid]["household"]
                      for pid in values}
        se = est.cluster_robust_se(values, self.weighting["weights"],
                                   households)
        # A1/A2 同属 HH1，聚类数少于人数
        self.assertLess(se["clusters"], len(values))
        self.assertIsNotNone(se["se"])


if __name__ == "__main__":
    unittest.main()
