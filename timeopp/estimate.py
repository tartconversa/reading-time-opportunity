"""群体估计：加权阅读量分布、有界估计与家庭聚类稳健标准误。

口径纪律：
- 只对"有效回收者"估计；无法代表的层在适用范围中显式声明；
- 同步听读（audio 次活动）单独报告，不默认并入专注阅读；
- 未记录分钟不等于零：给出有界区间而不是猜测；
- 同一家庭的学生不是独立观测，方差按家庭聚类计算；
- 估计值附带有效样本量与权重集中度，避免看似精确的结论。
"""
from __future__ import annotations


def weighted_mean(values: list[float], weights: list[float]) -> float:
    w_sum = sum(weights)
    if w_sum <= 0:
        raise ValueError("权重之和非正，无法计算加权均值")
    return sum(v * w for v, w in zip(values, weights)) / w_sum


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """加权分位数（线性插值，与 numpy 默认口径一致）。"""
    if not 0 <= q <= 1:
        raise ValueError("分位数 q 必须位于 [0, 1]")
    order = sorted(range(len(values)), key=lambda i: values[i])
    sv = [values[i] for i in order]
    sw = [weights[i] for i in order]
    total = sum(sw)
    if total <= 0:
        raise ValueError("权重之和非正，无法计算加权分位数")
    target = q * total
    cum = 0.0
    for i, (v, w) in enumerate(zip(sv, sw)):
        if cum + w >= target:
            if i == 0 or cum + w == target:
                return v
            prev_v = sv[i - 1]
            return prev_v + (v - prev_v) * ((target - cum) / w)
        cum += w
    return sv[-1]


def cluster_robust_se(person_values: dict[str, float], weights: dict[str, float],
                      households: dict[str, str]) -> dict:
    """按家庭聚类的加权均值线性化稳健标准误。

    估计量为加权均值 Y = Σ w_i y_i / Σ w_i。
    聚类（家庭）层面的影响函数求和后做三明治方差，
    并做有限总体校正 sqrt(G/(G-1))；G 为聚类数。
    """
    ids = [pid for pid in person_values if pid in weights]
    if not ids:
        return {"se": None, "clusters": 0, "note": "无有效样本"}
    w_sum = sum(weights[pid] for pid in ids)
    y_bar = weighted_mean([person_values[pid] for pid in ids],
                          [weights[pid] for pid in ids])
    # 每个聚类的影响函数之和
    cluster_scores: dict[str, float] = {}
    for pid in ids:
        hh = households.get(pid, pid)
        score = weights[pid] * (person_values[pid] - y_bar) / w_sum
        cluster_scores[hh] = cluster_scores.get(hh, 0.0) + score
    g = len(cluster_scores)
    if g < 2:
        return {"se": None, "clusters": g,
                "note": "有效聚类少于 2，无法估计抽样方差"}
    meat = sum(s * s for s in cluster_scores.values())
    variance = (g / (g - 1)) * meat
    return {"se": round(variance ** 0.5, 6), "clusters": g,
            "note": "家庭聚类稳健标准误（线性化）"}


def estimate_group(person_records: dict[str, dict], weights: dict[str, float],
                   materials, person_ids=None,
                   audio_credit: float = 0.0) -> dict:
    """对一组学生估计阅读量分布与机会指标。

    audio_credit：同步听读折算为专注阅读的比例，默认 0（全不算专注阅读）。
    该参数只影响"含听读口径"的衍生指标，专注阅读与听读分钟始终分开报告。
    """
    if not 0 <= audio_credit <= 1:
        raise ValueError("audio_credit 必须位于 [0, 1]")
    if person_ids is None:
        person_ids = sorted(weights)
    ids = [pid for pid in person_ids if pid in weights and pid in person_records]
    if not ids:
        return {"estimable": False, "reason": "组内没有任何有效回收者",
                "persons_requested": len(person_ids or [])}

    w = [weights[pid] for pid in ids]
    reading = [person_records[pid]["mean_daily_reading"] for pid in ids]
    audio = [person_records[pid]["total_audio_secondary_minutes"]
             / person_records[pid]["diary_days"] for pid in ids]
    unknown = [person_records[pid]["total_unknown_minutes"]
               / person_records[pid]["diary_days"] for pid in ids]
    zero_rates = [person_records[pid]["zero_reading_day_ratio"] for pid in ids]
    combined = [r + audio_credit * a for r, a in zip(reading, audio)]

    households = {pid: materials.people[pid]["household"] for pid in ids}
    se_reading = cluster_robust_se(dict(zip(ids, reading)),
                                   dict(zip(ids, w)), households)

    # 有界估计：未记录分钟若全部用于阅读为上界，全部不用于阅读为下界
    lower = reading
    upper = [r + u for r, u in zip(reading, unknown)]
    disputed = [person_records[pid]["total_disputed_minutes"]
                / person_records[pid]["diary_days"] for pid in ids]
    upper_with_dispute = [r + u + dp for r, u, dp in zip(reading, unknown, disputed)]

    w_total = sum(w)
    ess = w_total * w_total / sum(x * x for x in w)
    return {
        "estimable": True,
        "n_persons": len(ids),
        "weight_sum": round(w_total, 3),
        "effective_sample_size": round(ess, 3),
        "focused_reading": {
            "mean_daily_minutes": round(weighted_mean(reading, w), 3),
            "median_daily_minutes": round(weighted_quantile(reading, w, 0.5), 3),
            "p25": round(weighted_quantile(reading, w, 0.25), 3),
            "p75": round(weighted_quantile(reading, w, 0.75), 3),
            "se_mean": se_reading["se"],
            "se_detail": se_reading,
        },
        "audio_secondary": {
            "mean_daily_minutes": round(weighted_mean(audio, w), 3),
            "credit_ratio_used": audio_credit,
        },
        "combined_reading_with_credit": {
            "mean_daily_minutes": round(weighted_mean(combined, w), 3),
        },
        "zero_reading_day_rate": round(weighted_mean(zero_rates, w), 6),
        "bounds_due_to_unknown": {
            "lower_mean_daily_minutes": round(weighted_mean(lower, w), 3),
            "upper_if_all_unknown_is_reading": round(weighted_mean(upper, w), 3),
            "upper_also_counting_disputed": round(
                weighted_mean(upper_with_dispute, w), 3),
            "interpretation": "未记录与争议分钟不猜成零；区间宽度即不可消除的无知",
        },
        "mean_unknown_minutes_daily": round(weighted_mean(unknown, w), 3),
        "mean_disputed_minutes_daily": round(weighted_mean(disputed, w), 3),
    }


def domain_estimates(materials, person_records, weights, domains,
                     audio_credit=0.0) -> dict:
    """按年级、住宿、城乡、学校等域分别估计，并标注不可估计的域。"""
    out = {}
    for domain_name, key_func in domains.items():
        groups: dict[str, list[str]] = {}
        for pid in weights:
            groups.setdefault(str(key_func(materials, pid)), []).append(pid)
        result = {}
        for key, members in sorted(groups.items()):
            result[key] = estimate_group(
                person_records, weights, materials, members,
                audio_credit=audio_credit)
        out[domain_name] = result
    return out


def default_domains() -> dict:
    return {
        "grade": lambda m, pid: m.people[pid]["grade"],
        "boarder": lambda m, pid: ("boarder" if m.frame[pid]["boarder"] else "day"),
        "area": lambda m, pid: m.schools[m.people[pid]["school_id"]]["area"],
        "school": lambda m, pid: m.people[pid]["school_id"],
        "access_need": lambda m, pid: m.people[pid]["access_need"],
    }
