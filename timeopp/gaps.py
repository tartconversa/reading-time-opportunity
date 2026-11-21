"""机会缺口诊断。

阅读量分布之外，同时考察：
1. 完整可用时段：扣除睡眠、课堂、作业、家务、未记录与争议后，
   连续空闲块的数量与长度（短块难以承载深度阅读）；
2. 连续性：阅读事件自身的连续长度与被打断情况；
3. 家庭共同时间：同一家庭两名学生本地时间轴上空闲区间的交集；
4. 挤压因素：各类活动与阅读在个人日间的共变描述，只做诊断不做因果裁决。
"""
from __future__ import annotations

from . import timeio
from .coverage import (
    FREE_ACTIVITY,
    FOCUSED_READING_ACTIVITY,
    UNKNOWN_ACTIVITY,
)

# 默认可支配时段需要扣除的活动（未记录/争议另走显式处理）
OBLIGATION_ACTIVITIES = ("sleep", "school", "homework", "chores")
MIN_BLOCK_MINUTES_DEFAULT = 20


def _day_intervals(rows, day, excluded_activities):
    """取指定日本地日、活动不在排除集合内的已解释区间（先按行裁剪）。"""
    tz = rows[0].start.tzinfo
    t0, t1 = timeio.day_bounds(day, tz)
    keep, excluded = [], []
    for row in rows:
        s, e = max(row.start, t0), min(row.end, t1)
        if s >= e:
            continue
        if row.activity_id in excluded_activities or row.activity_id == UNKNOWN_ACTIVITY:
            excluded.append((s, e))
        else:
            keep.append((s, e))
    return timeio.subtract_intervals(keep, excluded), t0, t1


def usable_blocks(person_day_rows, day, min_minutes=MIN_BLOCK_MINUTES_DEFAULT):
    """完整可用时段：空闲（free）为主、且未被义务活动/未记录侵蚀的连续块。"""
    free_intervals, _, _ = _day_intervals(
        person_day_rows, day, OBLIGATION_ACTIVITIES)
    # 只保留实际标记为 free 的部分（reading 等不算"待使用的空闲"）
    tz = person_day_rows[0].start.tzinfo
    t0, t1 = timeio.day_bounds(day, tz)
    free_only = []
    for row in person_day_rows:
        s, e = max(row.start, t0), min(row.end, t1)
        if s < e and row.activity_id == FREE_ACTIVITY:
            free_only.append((s, e))
    blocks = timeio.intersect_interval_sets(free_intervals, free_only)
    return [
        {"start": s.isoformat(), "end": e.isoformat(),
         "minutes": timeio.total_minutes([(s, e)])}
        for s, e in blocks
        if timeio.total_minutes([(s, e)]) >= min_minutes
    ]


def reading_continuity(rows, day):
    """阅读事件连续性：主活动 reading 的连续段及相邻间隔。"""
    tz = rows[0].start.tzinfo
    t0, t1 = timeio.day_bounds(day, tz)
    reading_ivs = []
    for row in rows:
        s, e = max(row.start, t0), min(row.end, t1)
        if s < e and row.activity_id == FOCUSED_READING_ACTIVITY:
            reading_ivs.append((s, e))
    merged = timeio.merge_intervals(reading_ivs)
    lengths = [timeio.total_minutes([iv]) for iv in merged]
    gaps = [
        timeio.total_minutes([(merged[i][1], merged[i + 1][0])])
        for i in range(len(merged) - 1)
    ]
    return {
        "reading_events": len(merged),
        "event_minutes": [round(x, 3) for x in lengths],
        "longest_event_minutes": round(max(lengths), 3) if lengths else 0.0,
        "interruption_gap_minutes": [round(x, 3) for x in gaps],
        "total_reading_minutes": round(sum(lengths), 3),
    }


def household_shared_time(rows_by_person, household_members, day,
                          min_minutes=MIN_BLOCK_MINUTES_DEFAULT):
    """同一家庭两名学生当天可支配空闲区间的交集（家庭共同时间）。"""
    member_free = []
    for pid in household_members:
        rows = rows_by_person.get(pid, [])
        if not rows:
            return {"estimable": False, "reason": f"{pid} 当天无日记"}
        days_covered = {d for r in rows for d, _, _
                        in timeio.split_by_local_day(r.start, r.end)}
        if day not in days_covered:
            return {"estimable": False, "reason": f"{pid} 当天无日记"}
        blocks, _, _ = _day_intervals(rows, day, OBLIGATION_ACTIVITIES)
        tz = rows[0].start.tzinfo
        t0, t1 = timeio.day_bounds(day, tz)
        free_only = []
        for row in rows:
            s, e = max(row.start, t0), min(row.end, t1)
            if s < e and row.activity_id == FREE_ACTIVITY:
                free_only.append((s, e))
        member_free.append(timeio.intersect_interval_sets(blocks, free_only))
    if len(member_free) != 2:
        return {"estimable": False, "reason": "家庭共同时间需要两名成员资料"}
    shared = timeio.intersect_interval_sets(member_free[0], member_free[1])
    pieces = [
        {"start": s.isoformat(), "end": e.isoformat(),
         "minutes": timeio.total_minutes([(s, e)])}
        for s, e in shared if timeio.total_minutes([(s, e)]) >= min_minutes
    ]
    return {
        "estimable": True,
        "members": sorted(household_members),
        "shared_blocks": pieces,
        "shared_minutes": round(sum(b["minutes"] for b in pieces), 3),
    }


def squeeze_profile(person_days, person_records):
    """挤压因素诊断：各活动分钟与零阅读日的描述性共变。

    输出按零阅读/有阅读天分组的活动均值差异。这是诊断信号，
    不是因果效应；相关不代表该活动"导致"不阅读。
    """
    zero_days, read_days = [], []
    for pd_obj in person_days:
        row = {
            FOCUSED_READING_ACTIVITY: pd_obj.reading_minutes,
            UNKNOWN_ACTIVITY: pd_obj.unknown_minutes,
            "disputed": pd_obj.disputed_minutes,
            **{k: v for k, v in pd_obj.primary_minutes.items()
               if k not in (FOCUSED_READING_ACTIVITY, UNKNOWN_ACTIVITY)},
        }
        (zero_days if pd_obj.zero_reading_observed else read_days).append(row)

    def mean(rows_, key):
        vals = [r.get(key, 0.0) for r in rows_]
        return round(sum(vals) / len(vals), 3) if vals else None

    keys = sorted({k for r in zero_days + read_days for k in r})
    diffs = []
    for key in keys:
        if key == FOCUSED_READING_ACTIVITY:
            continue
        m0, m1 = mean(zero_days, key), mean(read_days, key)
        if m0 is not None and m1 is not None:
            diffs.append({
                "activity": key,
                "mean_minutes_on_zero_reading_days": m0,
                "mean_minutes_on_reading_days": m1,
                "difference": round(m0 - m1, 3),
            })
    diffs.sort(key=lambda x: abs(x["difference"]), reverse=True)
    return {
        "zero_reading_days": len(zero_days),
        "reading_days": len(read_days),
        "activity_differences": diffs,
        "caveat": "分组均值差异仅用于定位挤压线索，不能作因果归因",
    }


def person_gap_profile(person_id, rows_by_person, days, min_minutes):
    """单个学生的机会缺口汇总。"""
    rows = rows_by_person.get(person_id, [])
    block_counts, block_minutes, continuity = [], [], []
    for day in days:
        blocks = usable_blocks(rows, day, min_minutes)
        block_counts.append(len(blocks))
        block_minutes.append(sum(b["minutes"] for b in blocks))
        continuity.append(reading_continuity(rows, day))
    n = len(days) or 1
    no_block_days = sum(1 for c in block_counts if c == 0)
    return {
        "person_id": person_id,
        "days_analyzed": len(days),
        "days_without_qualifying_free_block": no_block_days,
        "mean_free_block_count": round(sum(block_counts) / n, 3),
        "mean_usable_free_minutes": round(sum(block_minutes) / n, 3),
        "mean_longest_reading_event_minutes": round(
            sum(c["longest_event_minutes"] for c in continuity) / n, 3),
        "mean_reading_events_per_day": round(
            sum(c["reading_events"] for c in continuity) / n, 3),
    }
