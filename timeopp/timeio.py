"""带时区时间区间的基础运算。

口径：
- 区间一律左闭右开 [start, end)；
- 日记允许跨午夜，按区间自身携带的时区切到本地自然日；
- null/未记录不等于零，本模块只做几何运算，不做业务解释。
"""
from __future__ import annotations

from datetime import datetime, timedelta, date, time as dtime

ONE_DAY = timedelta(days=1)


def parse_dt(text: str) -> datetime:
    """解析 ISO 8601 带偏移时间（如 2026-05-04T23:30:00+08:00）。"""
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"时间缺少时区信息：{text}")
    return dt


def parse_day(text: str) -> date:
    return date.fromisoformat(text)


def parse_clock(text: str) -> dtime:
    h, m = text.split(":")
    return dtime(hour=int(h), minute=int(m))


def local_day(dt: datetime) -> date:
    """该时刻在其自身时区下的本地日期。"""
    return dt.date()


def day_bounds(day: date, tzinfo) -> tuple[datetime, datetime]:
    t0 = datetime.combine(day, dtime.min, tzinfo=tzinfo)
    return t0, t0 + ONE_DAY


def split_by_local_day(start: datetime, end: datetime):
    """把一个可能跨午夜的区间切成 (本地日期, 起, 止) 序列。

    切出的各段沿用原区间的时区，左闭右开且互不重叠。
    """
    if end <= start:
        raise ValueError(f"区间止时必须晚于起时：{start} -> {end}")
    tz = start.tzinfo
    day = start.date()
    pieces = []
    cursor = start
    while cursor < end:
        t0, t1 = day_bounds(day, tz)
        seg_end = min(end, t1)
        pieces.append((day, max(start, t0), seg_end))
        cursor = seg_end
        day = day + ONE_DAY
    return pieces


def overlap_minutes(a_start, a_end, b_start, b_end) -> float:
    """两个区间的重叠分钟数（左闭右开，无重叠返回 0）。"""
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    return max(0.0, (hi - lo).total_seconds() / 60.0)


def minutes(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 60.0


def merge_intervals(intervals):
    """合并相交或相邻（端点相接）的区间，返回排好序的 [(s, e), ...]。"""
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged_s, merged_e = ordered[0]
    out = []
    for s, e in ordered[1:]:
        if s <= merged_e:
            if e > merged_e:
                merged_e = e
        else:
            out.append((merged_s, merged_e))
            merged_s, merged_e = s, e
    out.append((merged_s, merged_e))
    return out


def subtract_intervals(base_intervals, cut_intervals):
    """从 base 区间集合中挖去 cut 区间集合，返回剩余区间列表。"""
    cuts = merge_intervals(list(cut_intervals))
    remain = []
    for bs, be in merge_intervals(list(base_intervals)):
        cursor = bs
        for cs, ce in cuts:
            if ce <= cursor:
                continue
            if cs >= be:
                break
            if cs > cursor:
                remain.append((cursor, min(cs, be)))
            cursor = max(cursor, ce)
            if cursor >= be:
                break
        if cursor < be:
            remain.append((cursor, be))
    return merge_intervals(remain)


def intersect_interval_sets(a_intervals, b_intervals):
    """两个区间集合的交集（分钟级几何交集）。"""
    out = []
    a = merge_intervals(list(a_intervals))
    b = merge_intervals(list(b_intervals))
    i = j = 0
    while i < len(a) and j < len(b):
        as_, ae = a[i]
        bs, be = b[j]
        lo, hi = max(as_, bs), min(ae, be)
        if lo < hi:
            out.append((lo, hi))
        if ae <= be:
            i += 1
        else:
            j += 1
    return out


def total_minutes(intervals) -> float:
    return sum((e - s).total_seconds() / 60.0 for s, e in intervals)


def clock_window_on_day(day: date, tzinfo, clock_start: dtime, clock_end: dtime):
    """某日本地钟点窗口对应的绝对区间；允许跨午夜的钟点窗口。"""
    t0 = datetime.combine(day, clock_start, tzinfo=tzinfo)
    t1 = datetime.combine(day, clock_end, tzinfo=tzinfo)
    if t1 <= t0:
        t1 = t1 + ONE_DAY
    return t0, t1


def weekday(day: date) -> int:
    """周一=0 ... 周日=6。"""
    return day.weekday()
