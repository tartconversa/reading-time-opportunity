"""覆盖、冲突与争议处理的单元测试（使用保留无法判定情形的合成资料）。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp import coverage as cov  # noqa: E402
from timeopp.model import load_materials  # noqa: E402
from timeopp.synth import write_dataset  # noqa: E402


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)
        cls.diary_by_person = cls.materials.diary_by_person()
        cls.clar = cls.materials.clarifications_by_diary()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _days(self, pid):
        return cov.diagnose_person(
            self.diary_by_person[pid], self.materials.activities, self.clar)

    def test_unexplained_overlap_stays_open_and_minutes_not_double_counted(self):
        days = {d.day: d for d in self._days("A1")}
        d = days["2026-05-04"]
        open_disputes = [x for x in d.disputes if x.resolution == "open"]
        self.assertEqual(len(open_disputes), 1)
        self.assertEqual(open_disputes[0].reason, "incompatible_overlap")
        self.assertEqual(d.disputed_minutes, 30.0)
        # 重叠的 30 分钟不能重复占用：作业 120 分钟里有 30 分钟处于争议
        self.assertEqual(d.primary_minutes["homework"], 90.0)
        self.assertEqual(d.primary_minutes["reading"], 60.0)
        # 时间轴并集不超过 1440
        self.assertLessEqual(d.timeline_minutes, 1440.0)
        self.assertEqual(d.quality, "partial")

    def test_approved_clarification_deducts_earlier_interval(self):
        days = {d.day: d for d in self._days("A1")}
        d = days["2026-05-05"]
        approved = [x for x in d.disputes
                    if x.resolution == "approved_adjustment"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(d.disputed_minutes, 0.0)
        # 当天两段睡眠：00:00-07:00 共 420 分钟，
        # 加上 22:00-24:00 的 120 分钟扣掉重叠 30 分钟，合计 510 分钟
        self.assertEqual(d.primary_minutes["sleep"], 510.0)
        # 阅读跨午夜：当天落 30 分钟，次日落 30 分钟
        self.assertEqual(d.primary_minutes["reading"], 30.0)
        next_day = days["2026-05-06"]
        self.assertEqual(next_day.primary_minutes["reading"], 30.0)
        # 次日睡眠：00:30-07:00 的 390 分钟 + 22:00-24:00 的 120 分钟。
        # A1D11 从 00:30 起，与 DX1 端点相接（左闭右开），次日不存在重叠，
        # 30 分钟争议扣减全部落在 5/5 当晚的睡眠段
        self.assertEqual(next_day.primary_minutes["sleep"], 510.0)
        self.assertEqual(next_day.disputes, [])

    def test_audio_secondary_never_counts_as_focused_reading(self):
        days = {d.day: d for d in self._days("A2")}
        d = days["2026-05-04"]
        self.assertEqual(d.audio_secondary_minutes, 60.0)
        self.assertEqual(d.reading_minutes, 0.0)
        self.assertTrue(d.zero_reading_observed)
        self.assertEqual(d.secondary_minutes["audio"], 60.0)
        self.assertNotIn("reading", d.primary_minutes)
        # 未记录区间显式计量，不等于零阅读的原因解释
        self.assertEqual(d.unknown_minutes, 60.0)

    def test_true_gap_distinguished_from_unknown(self):
        days = {d.day: d for d in self._days("B1")}
        d = days["2026-05-04"]
        # 刻意缺口 16:00-18:00 共 120 分钟；另有 19:00-22:00 之后才到睡眠，
        # 22:00 前已由 free 覆盖，因此缺口正好 120 分钟
        self.assertEqual(d.gap_minutes, 120.0)
        self.assertEqual(d.quality, "incomplete")
        # 待审争议：重叠分钟不分配
        pending = [x for x in d.disputes if x.reason == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(d.disputed_minutes, 30.0)
        self.assertEqual(d.primary_minutes["homework"], 30.0)

    def test_no_diary_person_handled_explicitly(self):
        self.assertNotIn("C1", self.diary_by_person)
        summary = cov.coverage_summary([])
        self.assertEqual(summary["diary_days"], 0)
        self.assertEqual(summary["coverage_ratio"], 0.0)

    def test_compatible_secondary_pair_is_not_a_dispute(self):
        # A2 的 chores+audio 是字典声明的兼容对，不应产生争议
        days = {d.day: d for d in self._days("A2")}
        d = days["2026-05-04"]
        self.assertEqual(d.disputes, [])
        self.assertEqual(d.primary_minutes["chores"], 60.0)


if __name__ == "__main__":
    unittest.main()
