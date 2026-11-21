"""时间区间运算的单元测试。"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp import timeio  # noqa: E402

TZ = timezone(timedelta(hours=8))


def t(day, h, m=0):
    return datetime(2026, 5, day, h, m, tzinfo=TZ)


class TimeIOTests(unittest.TestCase):
    def test_parse_requires_timezone(self):
        with self.assertRaises(ValueError):
            timeio.parse_dt("2026-05-04T00:00:00")

    def test_split_cross_midnight(self):
        pieces = timeio.split_by_local_day(t(4, 23, 30), t(5, 0, 30))
        self.assertEqual(len(pieces), 2)
        self.assertEqual(pieces[0][0], pieces[1][0] - timedelta(days=1))
        self.assertEqual(timeio.minutes(pieces[0][1], pieces[0][2]), 30.0)
        self.assertEqual(timeio.minutes(pieces[1][1], pieces[1][2]), 30.0)

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError):
            timeio.split_by_local_day(t(4, 10), t(4, 9))

    def test_overlap_minutes_half_open(self):
        self.assertEqual(timeio.overlap_minutes(t(4, 10), t(4, 11),
                                                t(4, 11), t(4, 12)), 0.0)
        self.assertEqual(timeio.overlap_minutes(t(4, 10), t(4, 12),
                                                t(4, 11), t(4, 13)), 60.0)

    def test_subtract_and_intersect(self):
        base = [(t(4, 10), t(4, 12))]
        remain = timeio.subtract_intervals(base, [(t(4, 11), t(4, 11, 30))])
        self.assertEqual(timeio.total_minutes(remain), 90.0)
        inter = timeio.intersect_interval_sets(
            [(t(4, 10), t(4, 12))], [(t(4, 11, 30), t(4, 13))])
        self.assertEqual(timeio.total_minutes(inter), 30.0)

    def test_clock_window_cross_midnight(self):
        ws, we = timeio.clock_window_on_day(
            t(4, 0).date(), TZ,
            timeio.parse_clock("23:00"), timeio.parse_clock("01:00"))
        self.assertEqual(timeio.minutes(ws, we), 120.0)


if __name__ == "__main__":
    unittest.main()
