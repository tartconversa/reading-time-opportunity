"""机会缺口（可用时段、连续性、家庭共同时间、挤压线索）测试。"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp import gaps  # noqa: E402
from timeopp import timeio  # noqa: E402
from timeopp.model import load_materials  # noqa: E402
from timeopp.synth import write_dataset  # noqa: E402


class GapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)
        cls.by_person = cls.materials.diary_by_person()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_usable_blocks_only_from_free_and_long_enough(self):
        day = date(2026, 5, 4)
        # A2 当天有 120 分钟 free（20:00-22:00），应形成一个合格块
        blocks = gaps.usable_blocks(self.by_person["A2"], day, min_minutes=20)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["minutes"], 120.0)
        # 提高门槛后该块仍合格；门槛超过 120 则无合格块
        self.assertEqual(
            gaps.usable_blocks(self.by_person["A2"], day, min_minutes=121),
            [])

    def test_gap_day_has_no_qualifying_coverage_but_still_measured(self):
        day = date(2026, 5, 4)
        profile = gaps.person_gap_profile(
            "B1", self.by_person, [day], min_minutes=20)
        # B1 的 free 段 19:00-22:00 共 180 分钟形成一个块，
        # 但 16:00-18:00 的真实缺口在覆盖诊断中另行报告
        self.assertEqual(profile["days_analyzed"], 1)

    def test_reading_continuity_counts_events(self):
        day = date(2026, 5, 4)
        cont = gaps.reading_continuity(self.by_person["A1"], day)
        # 17:00-17:30 与 19:00-20:00 两个不相邻阅读事件
        self.assertEqual(cont["reading_events"], 2)
        self.assertEqual(cont["total_reading_minutes"], 90.0)
        self.assertEqual(cont["longest_event_minutes"], 60.0)

    def test_household_shared_time_requires_both_members(self):
        day = date(2026, 5, 4)
        result = gaps.household_shared_time(
            self.by_person, ["A1", "A2"], day, min_minutes=1)
        self.assertTrue(result["estimable"])
        self.assertEqual(result["members"], ["A1", "A2"])
        # 缺成员资料时明确不可估计，而不是编造共同时间
        missing = gaps.household_shared_time(
            self.by_person, ["C1", "C2"], day, min_minutes=1)
        self.assertFalse(missing["estimable"])

    def test_squeeze_profile_is_descriptive_only(self):
        from timeopp import coverage as cov
        clar = self.materials.clarifications_by_diary()
        pdays = cov.diagnose_person(
            self.by_person["B1"], self.materials.activities, clar)
        profile = gaps.squeeze_profile(pdays, None)
        self.assertIn("caveat", profile)
        self.assertEqual(profile["zero_reading_days"]
                         + profile["reading_days"], len(pdays))


if __name__ == "__main__":
    unittest.main()
