"""个人一天的时间覆盖、冲突与争议诊断。

处理顺序（先看清每个人，再进入群体估计）：
1. 把跨午夜日记切到本地自然日；
2. 找出同一天所有时间重叠，按活动字典判断是否为已声明的主次兼容；
3. 无法解释的重叠保留为争议；学生补充说明经学校审核通过后，
   才改变用于估计的解释；待审/被拒/无说明的重叠分钟一律不分配；
4. 明确的未记录区间（unknown）与真正的时间缺口分开报告，
   绝不把未记录或零阅读自动解释为"没有空闲"。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import timedelta

from . import timeio

UNKNOWN_ACTIVITY = "unknown"
FREE_ACTIVITY = "free"
# 专注阅读只认 reading；audio 是次活动，单独计量，不默认并入专注阅读
FOCUSED_READING_ACTIVITY = "reading"
AUDIO_ACTIVITY = "audio"


@dataclass(frozen=True)
class Segment:
    start: str
    end: str
    minutes: float


@dataclass(frozen=True)
class Dispute:
    id: str
    day: str
    reason: str                       # incompatible_overlap / pending / rejected
    diary_ids: tuple[str, ...]
    activities: tuple[str, ...]
    overlap: Segment
    explanation: str | None
    decision: str | None
    resolution: str                   # open / approved_adjustment

    def to_dict(self) -> dict:
        d = asdict(self)
        d["overlap"] = asdict(self.overlap)
        return d


@dataclass
class PersonDay:
    person_id: str
    day: str
    tz_offset: str
    raw_minutes: float                # 日记区间（含重叠、含 unknown）覆盖的原始分钟
    timeline_minutes: float = 0.0     # 时间轴并集覆盖
    unknown_minutes: float = 0.0      # 明确标记为未记录的分钟
    gap_minutes: float = 0.0          # 时间轴上真正没有任何区间的分钟
    disputed_minutes: float = 0.0     # 存在争议、未分配解释的分钟
    primary_minutes: dict = field(default_factory=dict)
    secondary_minutes: dict = field(default_factory=dict)   # 按次活动代码
    audio_secondary_minutes: float = 0.0
    reading_minutes: float = 0.0      # 主活动=文本阅读（已通过审核的扣减会反映在此）
    disputes: list = field(default_factory=list)
    has_diary: bool = True

    @property
    def known_minutes(self) -> float:
        """已解释、无争议的分钟 = 并集 - 未记录 - 缺口 - 争议。"""
        return max(
            0.0,
            self.timeline_minutes - self.unknown_minutes
            - self.gap_minutes - self.disputed_minutes,
        )

    @property
    def quality(self) -> str:
        """complete 完整 / partial 有未记录或争议 / incomplete 存在真实缺口。"""
        if self.gap_minutes > 0:
            return "incomplete"
        if self.unknown_minutes > 0 or self.disputed_minutes > 0:
            return "partial"
        return "complete"

    @property
    def zero_reading_observed(self) -> bool:
        """当天在已解释时间里没有观测到任何文本阅读（不解释原因）。"""
        return self.reading_minutes == 0

    def to_dict(self) -> dict:
        return {
            "person_id": self.person_id,
            "day": self.day,
            "tz_offset": self.tz_offset,
            "raw_minutes": round(self.raw_minutes, 3),
            "timeline_minutes": round(self.timeline_minutes, 3),
            "known_minutes": round(self.known_minutes, 3),
            "unknown_minutes": round(self.unknown_minutes, 3),
            "gap_minutes": round(self.gap_minutes, 3),
            "disputed_minutes": round(self.disputed_minutes, 3),
            "reading_minutes": round(self.reading_minutes, 3),
            "audio_secondary_minutes": round(self.audio_secondary_minutes, 3),
            "zero_reading_observed": self.zero_reading_observed,
            "quality": self.quality,
            "primary_minutes": {k: round(v, 3) for k, v in self.primary_minutes.items()},
            "secondary_minutes": {k: round(v, 3) for k, v in self.secondary_minutes.items()},
            "disputes": [dp.to_dict() for dp in self.disputes],
        }


def _seg(start, end) -> Segment:
    return Segment(
        start=start.isoformat(), end=end.isoformat(),
        minutes=timeio.minutes(start, end),
    )


def _clipped_rows(rows, day):
    """把跨午夜日记切到指定本地日，返回 [(row, seg_start, seg_end), ...]。"""
    out = []
    for row in rows:
        t0, t1 = timeio.day_bounds(day, row.start.tzinfo)
        s, e = max(row.start, t0), min(row.end, t1)
        if s < e:
            out.append((row, s, e))
    return out


def _approved_ruling(clarification, row_a, row_b):
    """审核通过后的可执行裁决。

    返回 (被扣减行, 保留行, 裁决依据)；没有可执行口径时返回 None。
    优先级：
    1. 审核显式指定的权威日记行 authoritative_diary_id；
    2. 收到日不同：较晚收到的视为订正，保留较晚者；
    3. 收到日相同且未指定权威行：无法判定，保留争议。
    """
    pair = {row_a.id: row_a, row_b.id: row_b}
    authority = clarification.authoritative_diary_id
    if authority in pair:
        keep = pair[authority]
        cut = row_b if keep is row_a else row_a
        return cut, keep, "authoritative_diary_id"
    if row_a.received_on != row_b.received_on:
        if row_a.received_on > row_b.received_on:
            return row_b, row_a, "later_received_on"
        return row_a, row_b, "later_received_on"
    return None


def _is_compatible_pair(row_a, row_b, dictionary) -> tuple[bool, str | None]:
    """两个重叠区间是否构成字典声明的主次兼容对。

    返回 (是否兼容, 次活动代码或 None)。兼容要求次活动确实挂在主活动区间上，
    且主活动字典声明了该次活动可同时出现。
    """
    a_sec, b_sec = row_a.secondary, row_b.secondary
    if a_sec == row_b.activity_id and b_sec is None:
        if dictionary.compatible(row_a.activity_id, row_b.activity_id):
            return True, row_b.activity_id
    if b_sec == row_a.activity_id and a_sec is None:
        if dictionary.compatible(row_b.activity_id, row_a.activity_id):
            return True, row_a.activity_id
    return False, None


def build_person_day(person_id, day, rows, dictionary, clarifications_by_diary):
    """构造单个学生单个本地日的覆盖诊断。"""
    clipped = _clipped_rows(rows, day)
    if not clipped:
        return None
    tz = clipped[0][0].start.tzinfo
    t0, t1 = timeio.day_bounds(day, tz)
    pd_obj = PersonDay(
        person_id=person_id, day=day.isoformat(),
        tz_offset=str(tz.utcoffset(None)),
        raw_minutes=sum(timeio.minutes(s, e) for _, s, e in clipped),
    )

    # 时间轴并集（所有区间，含 unknown 与争议）
    pd_obj.timeline_minutes = timeio.total_minutes(
        timeio.merge_intervals([(s, e) for _, s, e in clipped])
    )
    pd_obj.gap_minutes = 1440.0 - pd_obj.timeline_minutes

    # 每个重叠对逐一裁决
    open_disputes = []          # (row_ids, activities, seg, reason, clarification)
    approved_cuts = []          # (diary_id, cut_segments) 审核通过后的扣减
    for i in range(len(clipped)):
        row_a, sa, ea = clipped[i]
        for j in range(i + 1, len(clipped)):
            row_b, sb, eb = clipped[j]
            os_, oe = max(sa, sb), min(ea, eb)
            if os_ >= oe:
                continue
            compatible, _ = _is_compatible_pair(row_a, row_b, dictionary)
            if compatible:
                continue
            seg = _seg(os_, oe)
            cla_a = clarifications_by_diary.get(row_a.id)
            cla_b = clarifications_by_diary.get(row_b.id)
            cla = cla_a or cla_b
            if cla is not None and cla.decision == "approved":
                ruling = _approved_ruling(cla, row_a, row_b)
                if ruling is not None:
                    # 有可执行的机器口径：从非权威/较早区间扣减重叠分钟
                    cut_row, keep_row, basis = ruling
                    approved_cuts.append((cut_row.id, [(os_, oe)]))
                    pd_obj.disputes.append(Dispute(
                        id=f"DP:{person_id}:{day.isoformat()}:{row_a.id}:{row_b.id}",
                        day=day.isoformat(), reason="approved_clarification",
                        diary_ids=(row_a.id, row_b.id),
                        activities=(row_a.activity_id, row_b.activity_id),
                        overlap=seg,
                        explanation=f"{cla.explanation}｜裁决依据：{basis}",
                        decision="approved",
                        resolution="approved_adjustment",
                    ))
                    continue
                # 审核虽通过，但没有可执行的分配口径（同日收到且未指定权威行）：
                # 保留为未解决争议，重叠分钟不分配
                dispute = Dispute(
                    id=f"DP:{person_id}:{day.isoformat()}:{row_a.id}:{row_b.id}",
                    day=day.isoformat(), reason="approved_unresolved",
                    diary_ids=(row_a.id, row_b.id),
                    activities=(row_a.activity_id, row_b.activity_id),
                    overlap=seg,
                    explanation=(f"{cla.explanation}｜审核通过但无法从说明"
                                 "确定权威区间，需补登 authoritative_diary_id"),
                    decision="approved", resolution="open",
                )
                pd_obj.disputes.append(dispute)
                open_disputes.append(dispute)
                continue
            if cla is None:
                reason = "incompatible_overlap"
                decision = None
                explanation = None
            else:
                reason = "pending" if cla.decision == "pending" else "rejected"
                decision = cla.decision
                explanation = cla.explanation
            dispute = Dispute(
                id=f"DP:{person_id}:{day.isoformat()}:{row_a.id}:{row_b.id}",
                day=day.isoformat(), reason=reason,
                diary_ids=(row_a.id, row_b.id),
                activities=(row_a.activity_id, row_b.activity_id),
                overlap=seg, explanation=explanation,
                decision=decision, resolution="open",
            )
            pd_obj.disputes.append(dispute)
            open_disputes.append(dispute)

    # 未解决争议覆盖的分钟（并集，避免多重重叠重复计）
    open_segments = merge_dispute_segments(open_disputes, tz)
    pd_obj.disputed_minutes = timeio.total_minutes(open_segments)

    # 按行分配主/次活动分钟；未解决争议段与审核扣减段不参与分配
    cut_by_row: dict[str, list] = {}
    for diary_id, segs in approved_cuts:
        cut_by_row.setdefault(diary_id, []).extend(segs)
    open_cut = [(timeio.parse_dt(dp.overlap.start),
                 timeio.parse_dt(dp.overlap.end)) for dp in open_disputes]

    for row, s, e in clipped:
        own_segments = timeio.subtract_intervals(
            [(s, e)],
            (cut_by_row.get(row.id, []) + open_cut),
        )
        own_minutes = timeio.total_minutes(own_segments)
        if own_minutes <= 0:
            continue
        pd_obj.primary_minutes[row.activity_id] = (
            pd_obj.primary_minutes.get(row.activity_id, 0.0) + own_minutes
        )
        if row.secondary is not None:
            pd_obj.secondary_minutes[row.secondary] = (
                pd_obj.secondary_minutes.get(row.secondary, 0.0) + own_minutes
            )
            if row.secondary == AUDIO_ACTIVITY:
                pd_obj.audio_secondary_minutes += own_minutes

    pd_obj.unknown_minutes = pd_obj.primary_minutes.get(UNKNOWN_ACTIVITY, 0.0)
    pd_obj.reading_minutes = pd_obj.primary_minutes.get(
        FOCUSED_READING_ACTIVITY, 0.0)
    return pd_obj


def merge_dispute_segments(disputes, tz):
    intervals = [
        (timeio.parse_dt(dp.overlap.start), timeio.parse_dt(dp.overlap.end))
        for dp in disputes
    ]
    return timeio.merge_intervals(intervals)


def diagnose_person(rows, dictionary, clarifications_by_diary):
    """对一个学生的全部日记生成按本地日排序的 PersonDay 列表。"""
    by_day = {}
    for row in rows:
        for day, _, _ in timeio.split_by_local_day(row.start, row.end):
            by_day.setdefault(day, []).append(row)
    result = []
    for day in sorted(by_day):
        pd_obj = build_person_day(
            rows[0].person_id, day, rows, dictionary, clarifications_by_diary
        )
        if pd_obj is not None:
            result.append(pd_obj)
    return result


def coverage_summary(person_days) -> dict:
    """个人层面的覆盖汇总，供群体阶段判断有效回收。"""
    n_days = len(person_days)
    if n_days == 0:
        return {
            "diary_days": 0, "complete_days": 0, "partial_days": 0,
            "incomplete_days": 0, "coverage_ratio": 0.0,
            "total_unknown_minutes": 0.0, "total_disputed_minutes": 0.0,
            "total_gap_minutes": 0.0, "open_disputes": 0,
        }
    q = {"complete": 0, "partial": 0, "incomplete": 0}
    for pd_obj in person_days:
        q[pd_obj.quality] += 1
    timeline = sum(p.timeline_minutes for p in person_days)
    return {
        "diary_days": n_days,
        "complete_days": q["complete"],
        "partial_days": q["partial"],
        "incomplete_days": q["incomplete"],
        "coverage_ratio": round(timeline / (1440.0 * n_days), 6),
        "total_unknown_minutes": round(sum(p.unknown_minutes for p in person_days), 3),
        "total_disputed_minutes": round(sum(p.disputed_minutes for p in person_days), 3),
        "total_gap_minutes": round(sum(p.gap_minutes for p in person_days), 3),
        "open_disputes": sum(1 for p in person_days for d in p.disputes
                             if d.resolution == "open"),
    }
