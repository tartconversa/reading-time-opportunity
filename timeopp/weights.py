"""抽样权重与有效回收的衔接。

区分两层事实：
- sample_weight 是抽样基础权重，回应"被抽中概率"；
- 日记有效回收是另一回事，无日记或覆盖不合格的人不进入估计，
  其基础权重只在同一抽样层内、有合格回收时才能重新分摊。

禁止靠极大权重制造精确：默认对权重集中度给出告警与可选截尾，
截尾只改变估计用权重并完整留痕，不改原始基础权重。
"""
from __future__ import annotations

MAX_WEIGHT_RATIO_DEFAULT = 10.0


def build_weights(materials, person_records: dict[str, dict],
                  max_weight_ratio: float = MAX_WEIGHT_RATIO_DEFAULT,
                  trim: bool = False) -> dict:
    """生成估计用权重表与适用范围诊断。

    返回结构：
    - weights: person_id -> 估计用权重（仅有效回收者）
    - base_weights: person_id -> 基础权重（全体名册）
    - strata: 每层的回收、分摊因子、权重集中度
    - nonresponse: 无日记/无效回收人员清单及所属层
    - representability: 无法代表的层及原因
    - trimming: 截尾留痕（未截尾时为空记录）
    """
    frame = materials.frame
    base = {pid: row["sample_weight"] for pid, row in materials.people.items()}

    strata_ids = sorted({r["stratum"] for r in frame.values()})
    strata_detail = {}
    weights: dict[str, float] = {}
    nonresponse = []

    for stratum in strata_ids:
        members = [pid for pid, r in frame.items() if r["stratum"] == stratum]
        base_total = sum(base[pid] for pid in members)
        respondents = [
            pid for pid in members
            if pid in person_records and person_records[pid]["valid_respondent"]
        ]
        resp_base_total = sum(base[pid] for pid in respondents)
        for pid in members:
            if pid not in respondents:
                rec = person_records.get(pid)
                if rec is None or rec.get("diary_days", 0) == 0:
                    reason = "no_diary"
                elif not rec["valid_respondent"]:
                    reason = "insufficient_coverage"
                else:
                    reason = "unexpected"
                nonresponse.append({
                    "person_id": pid, "stratum": stratum,
                    "boarder": frame[pid]["boarder"], "reason": reason,
                })
        if respondents and resp_base_total > 0:
            factor = base_total / resp_base_total
            for pid in respondents:
                weights[pid] = base[pid] * factor
        else:
            factor = None
        strata_detail[stratum] = {
            "frame_persons": len(members),
            "valid_respondents": len(respondents),
            "base_weight_total": round(base_total, 6),
            "respondent_base_weight_total": round(resp_base_total, 6),
            "nonresponse_adjustment_factor": (round(factor, 6)
                                              if factor is not None else None),
            "response_rate_persons": round(len(respondents) / len(members), 6),
        }

    valid_persons = set(weights)
    representability = assess_representability(strata_detail, frame, valid_persons)
    concentration = weight_concentration(weights)
    trimming = {"applied": False, "cap_ratio": max_weight_ratio, "records": []}
    if trim and weights:
        weights, trimming = apply_trimming(weights, max_weight_ratio)

    return {
        "weights": weights,
        "base_weights": base,
        "strata": strata_detail,
        "nonresponse": nonresponse,
        "representability": representability,
        "concentration": concentration,
        "trimming": trimming,
    }


def assess_representability(strata_detail: dict, frame: dict,
                            valid_persons: set[str]) -> dict:
    """覆盖不足时明确指出无法代表哪些群体。"""
    unsupported_strata = [
        s for s, d in strata_detail.items()
        if d["nonresponse_adjustment_factor"] is None
    ]
    thin_strata = [
        s for s, d in strata_detail.items()
        if d["nonresponse_adjustment_factor"] is not None
        and d["valid_respondents"] < 2
    ]
    # 住宿/走读维度：某类在全体名册中存在、却没有任何有效回收则不可代表
    boarder_groups = {True: set(), False: set()}
    for pid, row in frame.items():
        boarder_groups[bool(row["boarder"])].add(pid)
    unsupported_boarder_groups = [
        "boarder" if boarder else "day"
        for boarder, members in boarder_groups.items()
        if members and not (members & valid_persons)
    ]
    return {
        "unsupported_strata": unsupported_strata,
        "thin_strata": thin_strata,
        "unsupported_boarder_groups": unsupported_boarder_groups,
        "note": ("unsupported_strata 中的层没有任何有效回收，"
                 "该层不进入群体估计，也不以零值或大权重替代"),
    }


def weight_concentration(weights: dict[str, float]) -> dict:
    if not weights:
        return {"max_weight": None, "min_weight": None, "max_to_min_ratio": None,
                "effective_sample_size": 0, "design_effect": None,
                "extreme_flag": False}
    values = list(weights.values())
    w_sum = sum(values)
    w_sq = sum(v * v for v in values)
    ess = (w_sum * w_sum / w_sq) if w_sq > 0 else 0.0
    deff = (len(values) / ess) if ess > 0 else None
    ratio = max(values) / min(values) if min(values) > 0 else None
    return {
        "max_weight": round(max(values), 6),
        "min_weight": round(min(values), 6),
        "max_to_min_ratio": (round(ratio, 6) if ratio is not None else None),
        "effective_sample_size": round(ess, 3),
        "design_effect": round(deff, 6) if deff is not None else None,
        "extreme_flag": ratio is not None and ratio > MAX_WEIGHT_RATIO_DEFAULT,
    }


def apply_trimming(weights: dict[str, float], cap_ratio: float):
    """以最小权重的 cap_ratio 倍为上限截尾，超出部分按比例再分摊。"""
    if not weights:
        return {}, {"applied": False, "cap_ratio": cap_ratio,
                    "cap_value": None, "records": []}
    floor = min(weights.values())
    cap = floor * cap_ratio
    records = []
    capped = dict(weights)
    for pid, w in list(capped.items()):
        if w > cap:
            records.append({"person_id": pid, "before": round(w, 6),
                            "after": round(cap, 6)})
            capped[pid] = cap
    # 把截掉的权重按截后权重比例再分配，保持总权重不变
    excess = sum(weights[p] - capped[p] for p in weights)
    base_sum = sum(capped.values())
    if excess > 0 and base_sum > 0:
        capped = {p: w + excess * w / base_sum for p, w in capped.items()}
    return capped, {"applied": True, "cap_ratio": cap_ratio,
                    "cap_value": round(cap, 6), "records": records}
