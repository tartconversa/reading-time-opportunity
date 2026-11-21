"""试行前后的观测比较与可归因性纪律。

- 比较按星期构成匹配，避免把周一-周四和周末结构混在一起；
- 考试周可以整体排除或单独标记；
- 同一家庭的关联通过聚类稳健标准误处理；
- 差分中的差（DiD）只是观测差异，是否可归因取决于暴露、平行趋势等条件；
- 计划释放时间绝不直接记成阅读增长；结果同时给出窗口内实际阅读。
"""
from __future__ import annotations

from datetime import timedelta, timezone

from . import timeio
from .coverage import AUDIO_ACTIVITY, FOCUSED_READING_ACTIVITY
from .estimate import weighted_mean, cluster_robust_se


def _day_period(day, pilot):
    if pilot.from_on <= day <= pilot.to_on:
        return "post"
    if day < pilot.from_on:
        return "pre"
    return "after"


def matched_weekday_sets(materials, pilot, eligible_persons,
                         exclude_exam=True) -> dict:
    """取前后期星期构成一致的日期集合（同 weekday 才进入比较）。"""
    diary_days = sorted({
        row.start.date() for row in materials.diary
        if row.person_id in eligible_persons
    })
    pre_days, post_days = [], []
    for day in diary_days:
        period = _day_period(day, pilot)
        if period not in {"pre", "post"}:
            continue
        if exclude_exam and materials.is_exam_day(pilot.school_id, day):
            continue
        (pre_days if period == "pre" else post_days).append(day)
    pre_wd = {timeio.weekday(d) for d in pre_days}
    post_wd = {timeio.weekday(d) for d in post_days}
    common = pre_wd & post_wd
    return {
        "pre_days": [d.isoformat() for d in pre_days
                     if timeio.weekday(d) in common],
        "post_days": [d.isoformat() for d in post_days
                      if timeio.weekday(d) in common],
        "excluded_weekdays_absent_in_one_period": sorted(
            pre_wd.symmetric_difference(post_wd)),
        "exam_excluded": exclude_exam,
    }


def person_day_reading(materials, person_id, day, pilot_window=True,
                       pilot=None) -> dict:
    """某人某天的阅读结果（专注阅读、听读、窗口内阅读）。"""
    tz = None
    focused = audio = window_reading = 0.0
    for row in materials.diary:
        if row.person_id != person_id:
            continue
        s, e = row.start, row.end
        day0 = s.date()
        if day0 != day:
            # 跨午夜段落在该日的部分
            t0, t1 = timeio.day_bounds(day, s.tzinfo)
            ss, ee = max(s, t0), min(e, t1)
            if ss >= ee:
                continue
            s, e = ss, ee
        if s.date() != day:
            continue
        minutes = timeio.minutes(s, e)
        if row.activity_id == FOCUSED_READING_ACTIVITY:
            focused += minutes
        if row.secondary == AUDIO_ACTIVITY:
            audio += minutes
        if pilot_window and pilot is not None:
            ws, we = timeio.clock_window_on_day(day, s.tzinfo,
                                                pilot.time_start, pilot.time_end)
            if row.activity_id == FOCUSED_READING_ACTIVITY:
                window_reading += timeio.overlap_minutes(s, e, ws, we)
        tz = s.tzinfo
    return {"focused": focused, "audio": audio,
            "window_reading": window_reading}


def _period_person_means(materials, pilot, persons, days, use_window):
    """每个学生在给定日期集合上的日均阅读（及窗口内阅读）。"""
    result = {}
    for pid in persons:
        vals, window_vals = [], []
        for day_text in days:
            day = timeio.parse_day(day_text)
            r = person_day_reading(materials, pid, day,
                                   pilot_window=use_window, pilot=pilot)
            vals.append(r["focused"])
            window_vals.append(r["window_reading"])
        if vals:
            result[pid] = {
                "mean_focused": sum(vals) / len(vals),
                "mean_window_reading": sum(window_vals) / len(window_vals),
                "n_days": len(vals),
            }
    return result


def difference_in_differences(materials, pilot, treatment_persons,
                              comparison_persons, weights,
                              exclude_exam=True) -> dict:
    """带对照组的 DiD；无对照组时退化为组内前后差并显式标注。"""
    matched = matched_weekday_sets(materials, pilot, treatment_persons,
                                   exclude_exam)
    use_window = True
    pre_t = _period_person_means(materials, pilot, treatment_persons,
                                 matched["pre_days"], use_window)
    post_t = _period_person_means(materials, pilot, treatment_persons,
                                  matched["post_days"], use_window)
    common_t = sorted(set(pre_t) & set(post_t) & set(weights))
    if not common_t:
        return {"estimable": False,
                "reason": "处理组没有同时具备前期与后期日记的合格学生"}

    def wmean(means_map, ids, key):
        ids = [p for p in ids if p in means_map and p in weights]
        if not ids:
            return None
        return weighted_mean([means_map[p][key] for p in ids],
                             [weights[p] for p in ids])

    pre_mean = wmean(pre_t, common_t, "mean_focused")
    post_mean = wmean(post_t, common_t, "mean_focused")
    within_change = post_mean - pre_mean
    pre_window = wmean(pre_t, common_t, "mean_window_reading")
    post_window = wmean(post_t, common_t, "mean_window_reading")

    out = {
        "estimable": True,
        "matched_days": matched,
        "treatment": {
            "n_persons": len(common_t),
            "pre_mean_focused_minutes": round(pre_mean, 3),
            "post_mean_focused_minutes": round(post_mean, 3),
            "within_change": round(within_change, 3),
            "pre_window_reading_minutes": round(pre_window, 3),
            "post_window_reading_minutes": round(post_window, 3),
            "window_change": round(post_window - pre_window, 3),
        },
    }

    pre_c = _period_person_means(materials, pilot, comparison_persons,
                                 matched["pre_days"], use_window)
    post_c = _period_person_means(materials, pilot, comparison_persons,
                                  matched["post_days"], use_window)
    common_c = sorted(set(pre_c) & set(post_c) & set(weights))
    if common_c:
        pre_cm = wmean(pre_c, common_c, "mean_focused")
        post_cm = wmean(post_c, common_c, "mean_focused")
        control_change = post_cm - pre_cm
        did = within_change - control_change
        # DiD 的聚类稳健 SE：以个人层面的前后差为观测值；
        # 无有效日记/无权重的人员在 common_* 阶段已被排除
        delta_t = {p: post_t[p]["mean_focused"] - pre_t[p]["mean_focused"]
                   for p in common_t if p in weights}
        delta_c = {p: post_c[p]["mean_focused"] - pre_c[p]["mean_focused"]
                   for p in common_c}
        households = {p: materials.people[p]["household"]
                      for p in set(delta_t) | set(delta_c)}
        se_t = cluster_robust_se(delta_t, {p: weights[p] for p in delta_t},
                                 households)
        se_c = cluster_robust_se(delta_c, {p: weights[p] for p in delta_c},
                                 households)
        se = None
        if se_t["se"] is not None and se_c["se"] is not None:
            se = round((se_t["se"] ** 2 + se_c["se"] ** 2) ** 0.5, 6)
        out["comparison"] = {
            "n_persons": len(common_c),
            "pre_mean_focused_minutes": round(pre_cm, 3),
            "post_mean_focused_minutes": round(post_cm, 3),
            "within_change": round(control_change, 3),
        }
        out["did"] = {
            "minutes_per_day": round(did, 3),
            "cluster_robust_se": se,
            "attribution": _attribution_label(pilot, post_window, did),
        }
    else:
        out["comparison"] = None
        out["did"] = {
            "minutes_per_day": None,
            "cluster_robust_se": None,
            "attribution": "uncontrolled_pre_post_only：无合格对照组，"
                           "观测变化不能归因于方案",
        }
    out["planned_release_minutes"] = _planned_minutes(pilot)
    out["attribution_guard"] = (
        "计划释放分钟仅为方案声明；只有窗口内实际阅读变化可计入观测证据，"
        "且 DiD 在平行趋势等假设成立时才可谨慎归因")
    return out


def _planned_minutes(pilot):
    # 方案窗口的钟点长度；所有合成资料统一为 +08:00
    tz = timezone(timedelta(hours=8))
    ws, we = timeio.clock_window_on_day(
        pilot.from_on, tz, pilot.time_start, pilot.time_end)
    return round(timeio.minutes(ws, we), 3)


def _attribution_label(pilot, post_window, did):
    if pilot.status != "executed":
        return "not_attributable：方案未实际执行"
    if post_window == 0:
        return "not_observed_in_window：窗口内无阅读，差异不能归因于释放时段"
    return "observational_did：关联证据，需平行趋势假设，非实验因果"
