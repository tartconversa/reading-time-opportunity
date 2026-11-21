"""命令行入口：调查员与学校的操作方式。

子命令：
  inspect       资料结构与指纹（沿用原 inspect_materials 口径）
  coverage      每个人一天的覆盖、未记录、冲突与争议
  disputes      列出未解决争议，支持登记审核意见
  review        登记学校对补充说明的审核决定（留痕，不改原始资料）
  estimate      群体估计：加权阅读量分布、适用范围、有界区间
  gaps          机会缺口：可用时段、连续性、家庭共同时间、挤压线索
  pilot-check   试行方案适用性、受益群体与被挤占活动比较
  pilot-register登记/暂停/改换试行，记录实际执行
  effects       试行前后观测比较（星期匹配、考试周、家庭聚类、归因标注）
  revisions     日记订正影响：区分重算结论与不可改写的已执行安排
  trace         从群体缺口一路追到方案与观测证据
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import effects, gaps, pilots, pipeline, timeio
from .model import load_materials
from .persons import MIN_COVERAGE_RATIO_DEFAULT, MIN_VALID_DAYS_DEFAULT
from .workflow import WorkStore


def _print(payload, as_json: bool):
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if as_json:
        print(text)
    else:
        print(_human_summary(payload))


def _human_summary(payload) -> str:
    """轻量中文摘要；完整机读结果以 --json 输出。"""
    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = []
    def put(k, v, indent=0):
        pad = "  " * indent
        lines.append(f"{pad}{k}: {v}")
    if "materials_digest" in payload:
        put("资料指纹", payload["materials_digest"])
    if "scope" in payload:
        scope = payload["scope"]
        put("可估计人数", scope["estimable_persons"])
        put("名册人数", scope["frame_persons"])
        put("不可代表层", scope["representability"]["unsupported_strata"])
        put("薄弱层(<2回收)", scope["representability"]["thin_strata"])
        put("权重极端标记", scope["concentration"]["extreme_flag"])
    if "overall" in payload and payload["overall"].get("estimable"):
        o = payload["overall"]
        put("日均专注阅读(分钟)", o["focused_reading"]["mean_daily_minutes"])
        put("阅读中位数", o["focused_reading"]["median_daily_minutes"])
        put("零阅读日比例", o["zero_reading_day_rate"])
        b = o["bounds_due_to_unknown"]
        put("未记录导致的有界区间",
            f"[{b['lower_mean_daily_minutes']}, {b['upper_if_all_unknown_is_reading']}]")
        put("日均同步听读(分钟，不默认计入)",
            o["audio_secondary"]["mean_daily_minutes"])
    if "coverage_overview" in payload:
        co = payload["coverage_overview"]
        put("无日记人数", co["people_without_diary"])
        put("未解决争议数", co["open_disputes"])
        put("完整/部分/不完整人日",
            f"{co['complete_person_days']}/{co['partial_person_days']}/{co['incomplete_person_days']}")
        put("未记录分钟合计", co["unknown_minutes_total"])
    if "applicability" in payload:
        a = payload["applicability"]
        put("方案", a["pilot_id"])
        put("场景", a["setting"])
        put("适用人数", len(a["eligible_persons"]))
        put("不适用人数", len(a["ineligible_persons"]))
        for w in a["applicability_warnings"]:
            put("告警", w)
    if "did" in payload:
        d = payload["did"]
        put("DiD(分钟/日)", d["minutes_per_day"])
        put("聚类稳健SE", d["cluster_robust_se"])
        put("归因标注", d["attribution"])
        put("计划释放分钟(不等于增长)", payload["planned_release_minutes"])
    if not lines:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines.append("（完整结果请加 --json）")
    return "\n".join(lines)


def _load(args):
    """装载资料，并叠加工作目录中已登记的学校审核留痕。"""
    store = WorkStore(args.workdir)
    overlay = store.load_reviews()["reviews"]
    return load_materials(args.materials, review_overlay=overlay or None)


def cmd_inspect(args):
    materials = _load(args)
    payload = {
        "materials_digest": materials.digest,
        "tables": {name: len(rows) for name, rows in materials.raw.items()},
        "schools": len(materials.schools),
        "people": len(materials.people),
        "diary_rows": len(materials.diary),
        "pilots": [
            {"id": p.id, "school": p.school_id, "status": p.status,
             "dates": [p.from_on.isoformat(), p.to_on.isoformat()]}
            for p in materials.pilots],
    }
    _print(payload, args.json)


def cmd_coverage(args):
    materials = _load(args)
    store = WorkStore(args.workdir)
    diag = pipeline.run_diagnostics(materials)
    open_disputes = [d for d in diag["disputes"] if d["resolution"] == "open"]
    overview = {
        "people_without_diary": sum(
            1 for pid, c in diag["coverage"].items() if c["diary_days"] == 0),
        "open_disputes": len(open_disputes),
        "complete_person_days": sum(c["complete_days"]
                                    for c in diag["coverage"].values()),
        "partial_person_days": sum(c["partial_days"]
                                   for c in diag["coverage"].values()),
        "incomplete_person_days": sum(c["incomplete_days"]
                                      for c in diag["coverage"].values()),
        "unknown_minutes_total": round(sum(
            c["total_unknown_minutes"] for c in diag["coverage"].values()), 3),
        "disputed_minutes_total": round(sum(
            c["total_disputed_minutes"] for c in diag["coverage"].values()), 3),
    }
    payload = {
        "materials_digest": materials.digest,
        "coverage_overview": overview,
        "open_disputes": open_disputes,
        "person_coverage": diag["coverage"],
    }
    if args.person:
        payload["person_days"] = diag["person_days"].get(args.person, [])
    run = store.record_run("coverage", vars(args), materials.digest,
                           result_ref="(inline)")
    path = store.write_result(run["run_id"], "coverage.json", payload)
    run["result_ref"] = str(path)
    _print({**payload, "run_id": run["run_id"], "result_path": str(path)},
           args.json)


def cmd_disputes(args):
    materials = _load(args)
    diag = pipeline.run_diagnostics(materials)
    open_disputes = [d for d in diag["disputes"] if d["resolution"] == "open"]
    if args.person:
        open_disputes = [d for d in open_disputes
                         if args.person in d["diary_ids"]
                         or d["id"].find(args.person) >= 0]
    payload = {"open_disputes": open_disputes,
               "count": len(open_disputes),
               "instruction": "用 review 子命令登记学校审核；待审/被拒争议的"
                              "重叠分钟不进入估计"}
    _print(payload, args.json)


def cmd_review(args):
    materials = _load(args)
    diary_ids = {r.id for r in materials.diary}
    if args.diary_id not in diary_ids:
        raise SystemExit(f"日记编号不存在：{args.diary_id}")
    if args.decision not in {"approved", "pending", "rejected"}:
        raise SystemExit("decision 必须是 approved/pending/rejected")
    if args.authoritative_diary_id is not None \
            and args.authoritative_diary_id not in diary_ids:
        raise SystemExit(
            f"权威日记行不存在：{args.authoritative_diary_id}")
    store = WorkStore(args.workdir)
    review = {
        "diary_id": args.diary_id, "decision": args.decision,
        "explanation": args.explanation, "recorded_on": args.recorded_on,
        "operator": args.operator,
        "authoritative_diary_id": args.authoritative_diary_id,
        "note": "审核留痕写入工作目录；原始 clarifications 表不被改写。"
                "approved 后下次 coverage/estimate 自动采用新解释；"
                "同日收到的重叠若不指定权威日记行，仍保留为未解决争议",
    }
    store.append_review(review)
    _print({"review_recorded": review}, args.json)


def cmd_estimate(args):
    materials = _load(args)
    store = WorkStore(args.workdir)
    diag = pipeline.run_diagnostics(
        materials, args.min_valid_days, args.min_coverage_ratio)
    weighting = pipeline.run_weighting(materials, diag["person_records"],
                                       args.max_weight_ratio, args.trim_weights)
    payload = pipeline.run_population_estimates(
        materials, diag["person_records"], weighting, args.audio_credit)
    payload["materials_digest"] = materials.digest
    run = store.record_run("estimate", vars(args), materials.digest,
                           result_ref="(pending)")
    path = store.write_result(run["run_id"], "estimate.json", payload)
    _print({**payload, "run_id": run["run_id"], "result_path": str(path)},
           args.json)


def cmd_gaps(args):
    materials = _load(args)
    store = WorkStore(args.workdir)
    diag = pipeline.run_diagnostics(materials)
    profiles = pipeline.run_gap_profiles(materials, diag, args.min_block)
    # 家庭共同时间示例（指定家庭时计算）
    shared = None
    if args.household:
        members = profiles["households"].get(args.household)
        if not members:
            raise SystemExit(f"家庭编号不存在：{args.household}")
        diary_by_person = materials.diary_by_person()
        any_day = next(iter({p.day for p in
                             diag["person_days_objects"][members[0]]}))
        shared = gaps.household_shared_time(
            diary_by_person, members, timeio.parse_day(any_day),
            args.min_block)
        shared["day"] = any_day
    squeeze = None
    if args.person:
        pdays = diag["person_days_objects"].get(args.person, [])
        squeeze = gaps.squeeze_profile(
            pdays, diag["person_records"].get(args.person))
    payload = {"materials_digest": materials.digest,
               "min_block_minutes": args.min_block,
               "person_profiles": profiles["person_profiles"],
               "household_shared_time": shared,
               "squeeze_profile": squeeze}
    run = store.record_run("gaps", vars(args), materials.digest,
                           result_ref="(pending)")
    path = store.write_result(run["run_id"], "gaps.json", payload)
    _print({**payload, "run_id": run["run_id"], "result_path": str(path)},
           args.json)


def _find_pilot(materials, pilot_id):
    for pilot in materials.pilots:
        if pilot.id == pilot_id:
            return pilot
    raise SystemExit(f"方案不存在：{pilot_id}")


def cmd_pilot_check(args):
    materials = _load(args)
    pilot = _find_pilot(materials, args.pilot_id)
    applicability = pilots.check_applicability(materials, pilot)
    exposure = pilots.exposure_days(
        materials, pilot, applicability["eligible_persons"])
    payload = {"materials_digest": materials.digest,
               "applicability": applicability, "exposure": exposure}
    _print(payload, args.json)


def cmd_pilot_register(args):
    materials = _load(args)
    pilot = _find_pilot(materials, args.pilot_id)
    applicability = pilots.check_applicability(materials, pilot)
    store = WorkStore(args.workdir)
    registration = {
        "pilot_id": pilot.id, "school_id": pilot.school_id,
        "scope_note": args.scope_note, "setting": applicability["setting"],
        "applies_to_boarder": args.applies_to_boarder,
        "status": args.action,
        "registered_on": args.recorded_on,
        "history": [{
            "from": None, "to": args.action,
            "reason": "initial_registration",
            "recorded_on": args.recorded_on,
        }],
        "applicability_snapshot": {
            "eligible_persons": applicability["eligible_persons"],
            "ineligible_persons": applicability["ineligible_persons"],
            "warnings": applicability["applicability_warnings"],
        },
    }
    store.upsert_registration(registration)
    _print({"registered": registration}, args.json)


def cmd_pilot_status(args):
    store = WorkStore(args.workdir)
    updated = store.change_status(args.pilot_id, args.new_status,
                                  args.reason, args.recorded_on)
    _print({"status_changed": updated,
            "rule": "暂停/改换只影响后续日期；旧方案已实际覆盖的日期仍保留"},
           args.json)


def cmd_effects(args):
    materials = _load(args)
    store = WorkStore(args.workdir)
    pilot = _find_pilot(materials, args.pilot_id)
    applicability = pilots.check_applicability(materials, pilot)
    treatment = applicability["eligible_persons"]
    comparison = [
        pid for pid in materials.people
        if materials.people[pid]["school_id"] != pilot.school_id
    ]
    diag = pipeline.run_diagnostics(
        materials, args.min_valid_days, args.min_coverage_ratio)
    weighting = pipeline.run_weighting(materials, diag["person_records"])
    result = effects.difference_in_differences(
        materials, pilot, treatment, comparison, weighting["weights"],
        exclude_exam=not args.keep_exam)
    result["materials_digest"] = materials.digest
    result["pilot_id"] = pilot.id
    run = store.record_run("effects", vars(args), materials.digest,
                           result_ref="(pending)")
    path = store.write_result(run["run_id"], "effects.json", result)
    _print({**result, "run_id": run["run_id"], "result_path": str(path)},
           args.json)


def cmd_revisions(args):
    materials = _load(args)
    store = WorkStore(args.workdir)
    impact = store.revision_impact(materials.digest)
    registry = store.load_registry()
    registered_ids = {reg["pilot_id"] for reg in registry["registrations"]}
    # 已执行安排不可改写；未开始安排需复议
    locked, review_needed = [], []
    for reg in registry["registrations"]:
        pilot = next((p for p in materials.pilots
                      if p.id == reg["pilot_id"]), None)
        if pilot is not None and pilot.status == "executed":
            locked.append({
                "pilot_id": reg["pilot_id"],
                "reason": "已有实际执行日期，重算不改写校内安排",
                "history": reg["history"],
            })
        else:
            review_needed.append({
                "pilot_id": reg["pilot_id"],
                "reason": "尚未开始执行，资料订正后须带着新诊断复议范围",
            })
    # 原始资料中存在、但从未登记的未执行方案，同样提示需要复议，
    # 避免"未登记即被遗忘"
    for pilot in materials.pilots:
        if pilot.id not in registered_ids and pilot.status != "executed":
            review_needed.append({
                "pilot_id": pilot.id,
                "reason": "未登记且未执行，资料订正后须先确认范围再试行",
            })
    impact["locked_decisions"] = locked
    impact["review_needed"] = review_needed
    _print(impact, args.json)


def cmd_trace(args):
    """从一个群体的时间缺口追到调整后的观测证据。"""
    materials = _load(args)
    store = WorkStore(args.workdir)
    diag = pipeline.run_diagnostics(
        materials, args.min_valid_days, args.min_coverage_ratio)
    weighting = pipeline.run_weighting(materials, diag["person_records"])
    estimates = pipeline.run_population_estimates(
        materials, diag["person_records"], weighting)
    chain = {
        "materials_digest": materials.digest,
        "step1_population_gap": {
            "scope": estimates["scope"],
            "overall": estimates["overall"],
        },
        "step2_pilots": [],
    }
    for pilot in materials.pilots:
        applicability = pilots.check_applicability(materials, pilot)
        exposure = pilots.exposure_days(
            materials, pilot, applicability["eligible_persons"])
        effect = effects.difference_in_differences(
            materials, pilot, applicability["eligible_persons"],
            [pid for pid in materials.people
             if materials.people[pid]["school_id"] != pilot.school_id],
            weighting["weights"])
        chain["step2_pilots"].append({
            "pilot_id": pilot.id,
            "applicability": {
                "setting": applicability["setting"],
                "eligible_n": len(applicability["eligible_persons"]),
                "warnings": applicability["applicability_warnings"],
            },
            "exposure": exposure,
            "observed_effect": effect,
        })
    chain["step3_attribution_guard"] = (
        "只有 executed 且窗口内有实际阅读的方案才可能贡献阅读机会证据；"
        "confirmed 未执行方案无效果可评；DiD 仍是观察性关联")
    run = store.record_run("trace", vars(args), materials.digest,
                           result_ref="(pending)")
    path = store.write_result(run["run_id"], "trace.json", chain)
    _print({**chain, "run_id": run["run_id"], "result_path": str(path)},
           args.json)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m timeopp",
        description="青少年阅读时间机会分析与试行跟踪（合成演练工具）")
    parser.add_argument("--materials", default="materials",
                        help="资料目录（默认 materials）")
    parser.add_argument("--workdir", default="workdir",
                        help="派生状态输出目录（默认 workdir）")
    parser.add_argument("--json", action="store_true",
                        help="输出完整机读 JSON")
    parser.add_argument("--min-valid-days", type=int,
                        default=MIN_VALID_DAYS_DEFAULT,
                        help="有效回收要求的最少个人日数（默认 7）")
    parser.add_argument("--min-coverage-ratio", type=float,
                        default=MIN_COVERAGE_RATIO_DEFAULT,
                        help="有效回收要求的时间轴覆盖率（默认 0.9）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inspect").set_defaults(func=cmd_inspect)

    p = sub.add_parser("coverage", help="个人日覆盖与冲突诊断")
    p.add_argument("--person", help="只输出指定学生的个人日明细")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("disputes", help="列出未解决争议")
    p.add_argument("--person")
    p.set_defaults(func=cmd_disputes)

    p = sub.add_parser("review", help="登记学校审核决定")
    p.add_argument("--diary-id", required=True)
    p.add_argument("--decision", required=True,
                   choices=["approved", "pending", "rejected"])
    p.add_argument("--explanation", required=True)
    p.add_argument("--authoritative-diary-id", default=None,
                   help="approved 时显式指定保留的权威日记行（其余重叠行扣减）")
    p.add_argument("--operator", default="investigator")
    p.add_argument("--recorded-on", default=date.today().isoformat())
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("estimate", help="群体加权估计")
    p.add_argument("--audio-credit", type=float, default=0.0,
                   help="同步听读折算比例[0,1]，默认0即全不算专注阅读")
    p.add_argument("--max-weight-ratio", type=float, default=10.0)
    p.add_argument("--trim-weights", action="store_true")
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("gaps", help="机会缺口诊断")
    p.add_argument("--min-block", type=int, default=20)
    p.add_argument("--person")
    p.add_argument("--household")
    p.set_defaults(func=cmd_gaps)

    p = sub.add_parser("pilot-check", help="方案适用性与挤占比较")
    p.add_argument("--pilot-id", required=True)
    p.set_defaults(func=cmd_pilot_check)

    p = sub.add_parser("pilot-register", help="登记试行")
    p.add_argument("--pilot-id", required=True)
    p.add_argument("--scope-note", required=True)
    p.add_argument("--applies-to-boarder", choices=["true", "false", "any"],
                   default="any")
    p.add_argument("--action", default="planned",
                   choices=["planned", "active", "paused", "replaced", "closed"])
    p.add_argument("--recorded-on", default=date.today().isoformat())
    p.set_defaults(func=cmd_pilot_register)

    p = sub.add_parser("pilot-status", help="暂停/改换/关闭方案")
    p.add_argument("--pilot-id", required=True)
    p.add_argument("--new-status", required=True,
                   choices=["planned", "active", "paused", "replaced", "closed"])
    p.add_argument("--reason", required=True)
    p.add_argument("--recorded-on", default=date.today().isoformat())
    p.set_defaults(func=cmd_pilot_status)

    p = sub.add_parser("effects", help="试行前后观测比较")
    p.add_argument("--pilot-id", required=True)
    p.add_argument("--keep-exam", action="store_true",
                   help="保留考试周（默认排除）")
    p.set_defaults(func=cmd_effects)

    sub.add_parser("revisions").set_defaults(func=cmd_revisions)
    sub.add_parser("trace").set_defaults(func=cmd_trace)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "applies_to_boarder"):
        mapping = {"true": True, "false": False, "any": None}
        args.applies_to_boarder = mapping[args.applies_to_boarder]
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
