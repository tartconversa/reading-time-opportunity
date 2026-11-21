"""试行方案适用性、暴露日与前后效果比较的单元测试。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp import effects, pipeline, pilots, weights as weights_mod  # noqa: E402
from timeopp.model import load_materials  # noqa: E402
from timeopp.synth import write_dataset  # noqa: E402


class PilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _pilot(self, pilot_id):
        return next(p for p in self.materials.pilots if p.id == pilot_id)

    def test_setting_inference_blocks_evening_plan_for_boarders(self):
        pt2 = self._pilot("PT2")
        self.assertEqual(pilots.infer_setting(pt2), "evening")
        result = pilots.check_applicability(self.materials, pt2)
        # S2 的 C1/C2 是住校生，晚间方案对他们不适用
        self.assertEqual(
            {x["reason"] for x in result["ineligible_persons"]},
            {"evening_plan_not_for_boarder"})
        self.assertEqual(result["eligible_persons"], [])

    def test_confirmed_pilot_has_no_exposure(self):
        pt2 = self._pilot("PT2")
        result = pilots.check_applicability(self.materials, pt2)
        exposure = pilots.exposure_days(
            self.materials, pt2, result["eligible_persons"])
        self.assertFalse(exposure["exposed"])
        self.assertIn("confirmed", exposure["reason"])

    def test_executed_pilot_records_actual_covered_dates(self):
        pt1 = self._pilot("PT1")
        result = pilots.check_applicability(self.materials, pt1)
        exposure = pilots.exposure_days(
            self.materials, pt1, result["eligible_persons"])
        # A1 在 5/11 的课堂段覆盖了 12:00-12:30 窗口
        self.assertTrue(exposure["exposed"])
        covered_dates = {
            d for item in exposure["person_days"] for d in item["dates"]}
        self.assertIn("2026-05-11", covered_dates)

    def test_planned_release_not_counted_as_reading(self):
        pt1 = self._pilot("PT1")
        result = pilots.check_applicability(self.materials, pt1)
        obs = result["window_observation"]
        self.assertEqual(obs["reading_observed_minutes"], 0.0)
        # 计划释放 30 分钟与实际阅读 0 分钟同时呈现
        self.assertEqual(
            obs["planned_release_minutes_per_person_day"], 30.0)
        self.assertTrue(
            any("no_reading_observed" in w
                for w in result["applicability_warnings"]))


class EffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)
        cls.diag = pipeline.run_diagnostics(
            cls.materials, min_valid_days=1, min_coverage_ratio=0.0)
        cls.weighting = weights_mod.build_weights(
            cls.materials, cls.diag["person_records"])
        cls.weights = cls.weighting["weights"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _pilot(self, pilot_id):
        return next(p for p in self.materials.pilots if p.id == pilot_id)

    def test_did_matches_weekdays_and_excludes_exam(self):
        pt3 = self._pilot("PT3")
        result = effects.difference_in_differences(
            self.materials, pt3, ["A1"], [], self.weights)
        self.assertTrue(result["estimable"])
        pre_days = result["matched_days"]["pre_days"]
        post_days = result["matched_days"]["post_days"]
        self.assertIn("2026-05-04", pre_days)
        self.assertIn("2026-05-11", post_days)
        # 无对照组：只能报告前后差，明确不可归因
        self.assertIsNone(result["comparison"])
        self.assertIn("uncontrolled_pre_post_only",
                      result["did"]["attribution"])

    def test_confirmed_pilot_not_attributable(self):
        pt2 = self._pilot("PT2")
        result = effects.difference_in_differences(
            self.materials, pt2, ["C1", "C2"], [], self.weights)
        self.assertFalse(result["estimable"])

    def test_attribution_guard_never_credits_planned_minutes(self):
        pt1 = self._pilot("PT1")
        result = effects.difference_in_differences(
            self.materials, pt1, ["A1"], ["A2", "B1"], self.weights)
        self.assertEqual(result["planned_release_minutes"], 30.0)
        # 窗口内无阅读，即使存在对照组也不能归因
        self.assertIn("not_observed_in_window",
                      result["did"]["attribution"])
        self.assertEqual(
            result["treatment"]["post_window_reading_minutes"], 0.0)


if __name__ == "__main__":
    unittest.main()
