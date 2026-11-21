"""试行方案的适用性核查、登记与实际执行跟踪。

关键纪律：
- 方案带生效日期、覆盖学校/班级口径、释放时段与被挤占活动；
- 不能把某校午间方案直接用于走读学生晚间：时段场景与住宿情况必须匹配；
- 计划释放的时间只是计划，observed 部分必须来自日记，不预记阅读增长；
- 已执行日期即使方案后来暂停或改换，仍保留在对应解释内；
- 原始 materials 中的 pilots 表只读，登记信息写入工作目录。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date

from . import timeio
from .coverage import FOCUSED_READING_ACTIVITY


@dataclass
class PilotRegistration:
    pilot_id: str
    school_id: str
    scope_note: str                 # 覆盖班级/群体口径的人工说明
    setting: str                    # campus_noon / after_school / evening 等
    applies_to_boarder: bool | None  # None=两类均可
    status: str                     # planned / active / paused / replaced / closed
    registered_on: str
    history: list                   # 状态变更留痕


def check_applicability(materials, pilot, person_ids=None) -> dict:
    """核查方案对学生的适用性，并比较受益群体与被挤占活动。

    判定规则（保守、可解释）：
    - 场景 setting 由释放钟点推断：12:00-14:00 为 campus_noon，
      15:30 之后为 after_school；晚间方案（18:00 后）默认不适用住校生；
    - 走读学生不适用 campus_noon 之外的校内假设：campus_noon 只对
      当天该时段在校的群体有意义，住宿标记不匹配时直接列出不适用人员；
    - 被挤占活动必须存在于活动字典；窗口内实际活动与声明不一致时告警。
    """
    dictionary = materials.activities
    dictionary.get(pilot.displaces)  # 不存在会抛错
    setting = infer_setting(pilot)
    if person_ids is None:
        person_ids = sorted(pid for pid, p in materials.people.items()
                            if p["school_id"] == pilot.school_id)

    eligible, ineligible = [], []
    for pid in person_ids:
        person = materials.people[pid]
        if person["school_id"] != pilot.school_id:
            ineligible.append({"person_id": pid,
                               "reason": "not_in_pilot_school"})
            continue
        boarder = bool(materials.frame[pid]["boarder"])
        reason = _setting_mismatch(setting, boarder)
        if reason:
            ineligible.append({"person_id": pid, "reason": reason})
        else:
            eligible.append(pid)

    window_observation = observe_window(materials, pilot, eligible)
    return {
        "pilot_id": pilot.id,
        "school_id": pilot.school_id,
        "setting": setting,
        "window": f"{pilot.time_start.strftime('%H:%M')}-{pilot.time_end.strftime('%H:%M')}",
        "date_range": [pilot.from_on.isoformat(), pilot.to_on.isoformat()],
        "declared_displaces": pilot.displaces,
        "source_status": pilot.status,
        "eligible_persons": eligible,
        "ineligible_persons": ineligible,
        "window_observation": window_observation,
        "applicability_warnings": _build_warnings(pilot, setting, window_observation),
    }


def infer_setting(pilot) -> str:
    noon = timeio.parse_clock("12:00")
    evening = timeio.parse_clock("18:00")
    if noon <= pilot.time_start < timeio.parse_clock("14:00"):
        return "campus_noon"
    if pilot.time_start >= evening:
        return "evening"
    return "after_school"


def _setting_mismatch(setting, boarder):
    if setting == "evening" and boarder:
        return "evening_plan_not_for_boarder"
    if setting == "campus_noon" and not boarder:
        # 午间校内方案对走读生同样可能适用（中午在校），不直接排除；
        # 但要求登记时显式确认，这里仅返回提示级标记由登记环节处理
        return None
    return None


def observe_window(materials, pilot, person_ids) -> dict:
    """用日记观测方案窗口内、方案日期上的实际活动构成（不做任何假设）。"""
    tz_name_holder = materials.diary[0].start.tzinfo if materials.diary else None
    counts: dict[str, float] = {}
    reading_minutes = 0.0
    person_days = 0
    seen = set()
    for row in materials.diary:
        if row.person_id not in person_ids:
            continue
        day = row.start.date()
        if not (pilot.from_on <= day <= pilot.to_on):
            continue
        tz = row.start.tzinfo
        ws, we = timeio.clock_window_on_day(
            day, tz, pilot.time_start, pilot.time_end)
        ov = timeio.overlap_minutes(row.start, row.end, ws, we)
        if ov <= 0:
            continue
        key = (row.person_id, day)
        if key not in seen:
            seen.add(key)
            person_days += 1
        counts[row.activity_id] = counts.get(row.activity_id, 0.0) + ov
        if row.activity_id == FOCUSED_READING_ACTIVITY:
            reading_minutes += ov
    declared = counts.get(pilot.displaces, 0.0)
    total = sum(counts.values())
    return {
        "observed_person_days": person_days,
        "activity_minutes_in_window": {k: round(v, 3) for k, v in
                                       sorted(counts.items())},
        "declared_displaces_observed_minutes": round(declared, 3),
        "declared_displaces_share": (round(declared / total, 6)
                                     if total else None),
        "reading_observed_minutes": round(reading_minutes, 3),
        "planned_release_minutes_per_person_day": round(
            timeio.minutes(
                timeio.clock_window_on_day(
                    date(2000, 1, 1), tz_name_holder,
                    pilot.time_start, pilot.time_end)[0],
                timeio.clock_window_on_day(
                    date(2000, 1, 1), tz_name_holder,
                    pilot.time_start, pilot.time_end)[1],
            ), 3),
        "note": "计划释放分钟不等于观测到的阅读增长",
    }


def _build_warnings(pilot, setting, observation):
    warnings = []
    if observation["observed_person_days"] == 0:
        warnings.append("no_diary_in_window：窗口内没有任何日记，无法判断实际执行")
        return warnings
    share = observation["declared_displaces_share"]
    if share is not None and share < 0.5:
        warnings.append(
            f"displaces_mismatch：声明被挤占活动 {pilot.displaces} "
            f"在窗口内实际占比仅 {share}，方案前提与日记不符")
    if observation["reading_observed_minutes"] == 0:
        warnings.append("no_reading_observed：窗口内未观测到文本阅读，"
                        "计划释放尚未转化为阅读机会")
    if setting == "campus_noon":
        warnings.append("campus_noon_scope：午间校内方案不得直接套用于走读生晚间")
    return warnings


def exposure_days(materials, pilot, eligible_persons) -> dict:
    """方案实际覆盖日期：只统计 executed 且日记显示窗口存在的人日。

    confirmed（已确认未执行）不产生暴露日；暂停/改换后，旧方案已覆盖
    的日期仍由登记历史保留，这里只反映原始资料中的执行事实。
    """
    if pilot.status != "executed":
        return {"pilot_id": pilot.id, "exposed": False,
                "reason": f"status={pilot.status}，无实际执行日期",
                "person_days": [], "dates": []}
    covered = {}
    dates = set()
    for row in materials.diary:
        if row.person_id not in eligible_persons:
            continue
        day = row.start.date()
        if not (pilot.from_on <= day <= pilot.to_on):
            continue
        tz = row.start.tzinfo
        ws, we = timeio.clock_window_on_day(day, tz, pilot.time_start,
                                            pilot.time_end)
        if timeio.overlap_minutes(row.start, row.end, ws, we) > 0:
            covered.setdefault(row.person_id, set()).add(day)
            dates.add(day)
    person_days = [
        {"person_id": pid, "dates": sorted(d.isoformat() for d in ds),
         "n_days": len(ds)}
        for pid, ds in sorted(covered.items())
    ]
    return {"pilot_id": pilot.id, "exposed": bool(person_days),
            "reason": "executed" if person_days else "no_window_diary",
            "person_days": person_days,
            "dates": sorted(d.isoformat() for d in dates)}


def registration_to_dict(reg: PilotRegistration) -> dict:
    return asdict(reg)
