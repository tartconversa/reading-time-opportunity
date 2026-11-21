"""资料装载与活动字典。

原始资料只读：本模块不修改 data.json，也不把任何派生解释写回。
活动字典的兼容关系只声明"哪些活动可以同时出现"，不规定阅读折算。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import timeio


@dataclass(frozen=True)
class Activity:
    id: str
    label: str
    can_secondary: frozenset[str]


class ActivityDictionary:
    """活动字典：主次活动与可兼容关系。"""

    def __init__(self, rows):
        self._activities = {
            r["id"]: Activity(r["id"], r["label"], frozenset(r["can_secondary"]))
            for r in rows
        }

    def get(self, activity_id: str) -> Activity:
        if activity_id not in self._activities:
            raise KeyError(f"活动代码不在字典中：{activity_id}")
        return self._activities[activity_id]

    def labels(self) -> dict[str, str]:
        return {a.id: a.label for a in self._activities.values()}

    def compatible(self, primary_id: str, secondary_id: str) -> bool:
        """secondary_id 是否被声明为可与 primary_id 同时出现的次活动。"""
        if primary_id not in self._activities or secondary_id not in self._activities:
            return False
        return secondary_id in self.get(primary_id).can_secondary

    def all_ids(self) -> frozenset[str]:
        return frozenset(self._activities)


@dataclass(frozen=True)
class DiaryRow:
    id: str
    person_id: str
    start: object          # datetime
    end: object            # datetime
    activity_id: str
    secondary: object      # str | None
    received_on: str       # ISO 日期字符串

    @property
    def duration_minutes(self) -> float:
        return timeio.minutes(self.start, self.end)


@dataclass(frozen=True)
class Clarification:
    id: str
    diary_id: str
    submitted_on: str
    decision: str          # approved / pending / rejected
    decided_on: object     # str | None
    explanation: str
    authoritative_diary_id: object = None  # 审核显式指定的权威日记行


@dataclass(frozen=True)
class Pilot:
    id: str
    school_id: str
    from_on: object        # date
    to_on: object
    time_start: object     # time
    time_end: object
    displaces: str
    status: str            # executed / confirmed


@dataclass(frozen=True)
class CalendarItem:
    id: str
    school_id: str
    from_on: object
    to_on: object
    kind: str
    open_start: object
    open_end: object


@dataclass
class Materials:
    raw: dict
    digest: str
    source_path: Path
    activities: ActivityDictionary
    people: dict
    frame: dict
    diary: list[DiaryRow]
    clarifications: list[Clarification]
    calendar: list[CalendarItem]
    pilots: list[Pilot]
    schools: dict

    def person(self, person_id: str) -> dict:
        return self.people[person_id]

    def diary_by_person(self) -> dict[str, list[DiaryRow]]:
        out: dict[str, list[DiaryRow]] = {}
        for row in self.diary:
            out.setdefault(row.person_id, []).append(row)
        for rows in out.values():
            rows.sort(key=lambda r: (r.start, r.end, r.id))
        return out

    def clarifications_by_diary(self) -> dict[str, list[Clarification]]:
        out: dict[str, Clarification] = {}
        for c in self.clarifications:
            # 同一日记若有多条说明，保留提交时间最新的一条作为当前审核事实
            old = out.get(c.diary_id)
            if old is None or c.submitted_on > old.submitted_on:
                out[c.diary_id] = c
        return out

    def calendar_for(self, school_id: str) -> list[CalendarItem]:
        return [c for c in self.calendar if c.school_id == school_id]

    def is_exam_day(self, school_id: str, day) -> bool:
        for item in self.calendar_for(school_id):
            if item.kind == "exam" and item.from_on <= day <= item.to_on:
                return True
        return False


def load_materials(directory, review_overlay=None) -> Materials:
    """读取并校验合成资料；返回不可变装载对象与原始资料指纹。

    review_overlay：可选的审核叠加记录列表（来自工作目录 review_log.json）。
    叠加只在内存中改变用于估计的解释，原始 data.json 与其中的
    clarifications 表保持不变；同一日记以记录时间最新的审核为准。
    """
    directory = Path(directory)
    raw_bytes = (directory / "data.json").read_bytes()
    data = json.loads(raw_bytes.decode("utf-8"))
    digest = hashlib.sha256(raw_bytes).hexdigest()

    required = {
        "schools", "people", "sample_frame", "activities", "diary",
        "clarifications", "calendar", "pilots",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(f"资料缺少必需表：{sorted(missing)}")

    if review_overlay:
        data = _apply_review_overlay(data, review_overlay)

    people = {r["id"]: r for r in data["people"]}
    schools = {r["id"]: r for r in data["schools"]}
    frame = {r["person_id"]: r for r in data["sample_frame"]}

    diary_rows = []
    for r in data["diary"]:
        start = timeio.parse_dt(r["start"])
        end = timeio.parse_dt(r["end"])
        if end <= start:
            raise ValueError(f"日记区间无效（止时不晚于起时）：{r['id']}")
        if str(start.utcoffset()) != str(end.utcoffset()):
            raise ValueError(f"日记区间起止时区不一致：{r['id']}")
        diary_rows.append(DiaryRow(
            id=r["id"], person_id=r["person_id"], start=start, end=end,
            activity_id=r["activity_id"], secondary=r["secondary"],
            received_on=r["received_on"],
        ))

    clarifications = [
        Clarification(
            id=r["id"], diary_id=r["diary_id"], submitted_on=r["submitted_on"],
            decision=r["decision"], decided_on=r["decided_on"],
            explanation=r["explanation"],
            authoritative_diary_id=r.get("authoritative_diary_id"),
        )
        for r in data["clarifications"]
    ]
    for c in clarifications:
        if c.decision not in {"approved", "pending", "rejected"}:
            raise ValueError(f"审核决定取值非法：{c.id} -> {c.decision}")

    calendar_items = [
        CalendarItem(
            id=r["id"], school_id=r["school_id"],
            from_on=timeio.parse_day(r["from_on"]),
            to_on=timeio.parse_day(r["to_on"]), kind=r["kind"],
            open_start=timeio.parse_clock(r["open_start"]),
            open_end=timeio.parse_clock(r["open_end"]),
        )
        for r in data["calendar"]
    ]
    pilots = [
        Pilot(
            id=r["id"], school_id=r["school_id"],
            from_on=timeio.parse_day(r["from_on"]),
            to_on=timeio.parse_day(r["to_on"]),
            time_start=timeio.parse_clock(r["time_start"]),
            time_end=timeio.parse_clock(r["time_end"]),
            displaces=r["displaces"], status=r["status"],
        )
        for r in data["pilots"]
    ]
    for pilot in pilots:
        if pilot.status not in {"executed", "confirmed"}:
            raise ValueError(f"方案状态取值非法：{pilot.id} -> {pilot.status}")

    materials = Materials(
        raw=data, digest=digest, source_path=directory,
        activities=ActivityDictionary(data["activities"]),
        people=people, frame=frame, diary=diary_rows,
        clarifications=clarifications, calendar=calendar_items,
        pilots=pilots, schools=schools,
    )
    _validate_references(materials)
    return materials


def _apply_review_overlay(data: dict, review_overlay: list[dict]) -> dict:
    """把工作目录的审核留痕叠加到资料副本上（不改原始 data）。

    每条 overlay 至少含 diary_id/decision/recorded_on/explanation。
    同一 diary_id 以 recorded_on 最新者为准；生成的合成说明编号加
    RV- 前缀，避免与原始 clarifications 的编号冲突。
    """
    merged = {key: list(rows) for key, rows in data.items()}
    existing_ids = {r["id"] for r in merged["clarifications"]}
    latest: dict[str, dict] = {}
    for review in review_overlay:
        diary_id = review["diary_id"]
        old = latest.get(diary_id)
        if old is None or review["recorded_on"] >= old["recorded_on"]:
            latest[diary_id] = review
    for idx, (diary_id, review) in enumerate(sorted(latest.items()), start=1):
        rid = f"RV-{idx:03d}"
        while rid in existing_ids:
            idx += 1
            rid = f"RV-{idx:03d}"
        existing_ids.add(rid)
        # 去掉同日记的原始说明，替换为当前审核事实
        merged["clarifications"] = [
            r for r in merged["clarifications"]
            if r["diary_id"] != diary_id
        ]
        merged["clarifications"].append({
            "id": rid, "diary_id": diary_id,
            "submitted_on": review["recorded_on"],
            "decision": review["decision"],
            "decided_on": review["recorded_on"],
            "explanation": review.get("explanation", ""),
            "authoritative_diary_id": review.get("authoritative_diary_id"),
        })
    return merged


def _validate_references(m: Materials) -> None:
    diary_ids = {r.id for r in m.diary}
    for c in m.clarifications:
        if c.diary_id not in diary_ids:
            raise ValueError(f"说明指向不存在的日记：{c.id} -> {c.diary_id}")
    for r in m.diary:
        if r.person_id not in m.people:
            raise ValueError(f"日记指向不存在的学生：{r.id}")
        m.activities.get(r.activity_id)
        if r.secondary is not None:
            m.activities.get(r.secondary)
    for person_id, row in m.frame.items():
        if person_id not in m.people:
            raise ValueError(f"抽样框指向不存在的学生：{row['id']}")
    for pilot in m.pilots:
        if pilot.school_id not in m.schools:
            raise ValueError(f"方案指向不存在的学校：{pilot.id}")
        m.activities.get(pilot.displaces)
