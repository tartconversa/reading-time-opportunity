"""人员层面的汇总：把个人日诊断聚合为可加权的人员记录。"""
from __future__ import annotations

from .coverage import PersonDay

MIN_VALID_DAYS_DEFAULT = 7
MIN_COVERAGE_RATIO_DEFAULT = 0.90


def aggregate_person(person_id: str, person_days: list[PersonDay],
                     min_valid_days: int = MIN_VALID_DAYS_DEFAULT,
                     min_coverage_ratio: float = MIN_COVERAGE_RATIO_DEFAULT) -> dict:
    """把一个学生的多个个人日聚合成人员记录。

    有效回收判定同时要求：
    - 个人日数量达到 min_valid_days；
    - 时间轴覆盖率达到 min_coverage_ratio。
    未记录（unknown）是明确填报的一部分，不直接拉低覆盖率；
    真实缺口（gap）才影响覆盖率。
    """
    n_days = len(person_days)
    timeline = sum(p.timeline_minutes for p in person_days)
    coverage_ratio = timeline / (1440.0 * n_days) if n_days else 0.0
    valid = n_days >= min_valid_days and coverage_ratio >= min_coverage_ratio

    zero_reading_days = sum(1 for p in person_days if p.zero_reading_observed)
    daily_reading = [p.reading_minutes for p in person_days]
    daily_audio = [p.audio_secondary_minutes for p in person_days]
    daily_unknown = [p.unknown_minutes for p in person_days]

    return {
        "person_id": person_id,
        "diary_days": n_days,
        "coverage_ratio": coverage_ratio,
        "valid_respondent": valid,
        "incomplete_days": sum(1 for p in person_days if p.quality == "incomplete"),
        "partial_days": sum(1 for p in person_days if p.quality == "partial"),
        "total_reading_minutes": round(sum(daily_reading), 3),
        "total_audio_secondary_minutes": round(sum(daily_audio), 3),
        "total_unknown_minutes": round(sum(daily_unknown), 3),
        "total_disputed_minutes": round(
            sum(p.disputed_minutes for p in person_days), 3),
        "mean_daily_reading": (round(sum(daily_reading) / n_days, 3)
                               if n_days else None),
        "zero_reading_days": zero_reading_days,
        "zero_reading_day_ratio": (round(zero_reading_days / n_days, 6)
                                   if n_days else None),
        "daily_reading_minutes": daily_reading,
        "daily_audio_minutes": daily_audio,
        "daily_unknown_minutes": daily_unknown,
        "days": [p.day for p in person_days],
    }
