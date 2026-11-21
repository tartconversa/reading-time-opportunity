"""把装载、覆盖诊断、人员汇总、权重与群体估计串成可复用流水线。"""
from __future__ import annotations

from datetime import date

from . import coverage as cov
from . import estimate as est
from . import gaps
from . import persons as persons_mod
from . import weights as weights_mod
from .model import Materials


def run_diagnostics(materials: Materials,
                    min_valid_days=persons_mod.MIN_VALID_DAYS_DEFAULT,
                    min_coverage_ratio=persons_mod.MIN_COVERAGE_RATIO_DEFAULT):
    """第一步：每个人一天的覆盖与冲突，再聚合成人员记录。"""
    dictionary = materials.activities
    clar = materials.clarifications_by_diary()
    diary_by_person = materials.diary_by_person()

    person_days_all: dict[str, list[cov.PersonDay]] = {}
    person_days_payload: dict[str, list[dict]] = {}
    all_disputes = []
    for pid in sorted(materials.people):
        rows = diary_by_person.get(pid, [])
        if not rows:
            person_days_all[pid] = []
            person_days_payload[pid] = []
            continue
        pdays = cov.diagnose_person(rows, dictionary, clar)
        person_days_all[pid] = pdays
        person_days_payload[pid] = [p.to_dict() for p in pdays]
        all_disputes.extend(d for p in pdays for d in p.disputes)

    person_records = {}
    coverage = {}
    for pid, pdays in person_days_all.items():
        coverage[pid] = cov.coverage_summary(pdays)
        if pdays:
            person_records[pid] = persons_mod.aggregate_person(
                pid, pdays, min_valid_days, min_coverage_ratio)
        else:
            person_records[pid] = {
                "person_id": pid, "diary_days": 0, "coverage_ratio": 0.0,
                "valid_respondent": False, "incomplete_days": 0,
                "partial_days": 0, "total_reading_minutes": 0.0,
                "total_audio_secondary_minutes": 0.0,
                "total_unknown_minutes": 0.0, "total_disputed_minutes": 0.0,
                "mean_daily_reading": None, "zero_reading_days": 0,
                "zero_reading_day_ratio": None,
                "daily_reading_minutes": [], "daily_audio_minutes": [],
                "daily_unknown_minutes": [], "days": [],
            }
    return {
        "person_days": person_days_payload,
        "person_days_objects": person_days_all,
        "person_records": person_records,
        "coverage": coverage,
        "disputes": [d.to_dict() for d in all_disputes],
    }


def run_weighting(materials: Materials, person_records: dict,
                  max_weight_ratio=weights_mod.MAX_WEIGHT_RATIO_DEFAULT,
                  trim=False):
    return weights_mod.build_weights(materials, person_records,
                                     max_weight_ratio, trim)


def run_population_estimates(materials: Materials, person_records: dict,
                             weighting: dict, audio_credit: float = 0.0):
    weights = weighting["weights"]
    overall = est.estimate_group(person_records, weights, materials,
                                 audio_credit=audio_credit)
    domains = est.domain_estimates(materials, person_records, weights,
                                   est.default_domains(), audio_credit)
    return {
        "scope": {
            "estimable_persons": len(weights),
            "frame_persons": len(materials.frame),
            "representability": weighting["representability"],
            "concentration": weighting["concentration"],
            "trimming": weighting["trimming"],
            "strata": weighting["strata"],
            "nonresponse": weighting["nonresponse"],
        },
        "overall": overall,
        "domains": domains,
    }


def run_gap_profiles(materials: Materials, diagnostics: dict,
                     min_block_minutes: int = gaps.MIN_BLOCK_MINUTES_DEFAULT):
    diary_by_person = materials.diary_by_person()
    profiles = []
    for pid, pdays in diagnostics["person_days_objects"].items():
        if not pdays:
            continue
        days = sorted({date.fromisoformat(p.day) for p in pdays})
        profiles.append(gaps.person_gap_profile(
            pid, diary_by_person, days, min_block_minutes))
    households: dict[str, list[str]] = {}
    for pid, person in materials.people.items():
        households.setdefault(person["household"], []).append(pid)
    return {
        "person_profiles": profiles,
        "households": {hh: sorted(members) for hh, members in households.items()},
    }
