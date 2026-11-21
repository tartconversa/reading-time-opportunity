"""生成保留"无法判定情形"的小型合成日记资料，用于边缘情形验证。

与 materials/ 中的正式演练资料分开存放，默认输出到独立目录，
绝不覆盖原始资料。覆盖的情形：
1. 无法解释的重叠（无说明、待审、被拒）——争议保留，重叠分钟不分配；
2. 审核通过的重叠——按说明扣减较早区间；
3. 同步听读——单独计量，不默认并入专注阅读；
4. 真实时间缺口（一天没有被任何区间覆盖的片段）；
5. 整层无有效回收——不可代表，禁止大权重补救；
6. 跨午夜区间；
7. 零阅读日（区分未记录与真零）；
8. 同家庭两名学生（聚类方差需要）。
"""
from __future__ import annotations

import json
from pathlib import Path

TZ = "+08:00"


def _row(rid, pid, start, end, activity, secondary=None, received=None):
    day = start[:10]
    return {
        "id": rid, "person_id": pid,
        "start": f"{start}T00:00:00{TZ}" if "T" not in start else start,
        "end": f"{end}T00:00:00{TZ}" if "T" not in end else end,
        "activity_id": activity, "secondary": secondary,
        "received_on": received or day,
    }


def build_dataset() -> dict:
    schools = [
        {"id": "S1", "area": "城区", "devices": 5},
        {"id": "S2", "area": "乡村", "devices": 5},
    ]
    people = [
        {"id": "A1", "school_id": "S1", "household": "HH1", "grade": 4,
         "access_need": "text", "sample_weight": 2.0},
        {"id": "A2", "school_id": "S1", "household": "HH1", "grade": 5,
         "access_need": "audio", "sample_weight": 2.0},
        {"id": "B1", "school_id": "S1", "household": "HH2", "grade": 4,
         "access_need": "text", "sample_weight": 2.0},
        {"id": "C1", "school_id": "S2", "household": "HH3", "grade": 6,
         "access_need": "text", "sample_weight": 3.0},
        {"id": "C2", "school_id": "S2", "household": "HH3", "grade": 6,
         "access_need": "text", "sample_weight": 3.0},
    ]
    frame = [
        {"id": f"N{i+1}", "person_id": p["id"], "invited": True,
         "boarder": p["id"] in {"C1", "C2"},
         "stratum": f'{p["school_id"]}-{p["grade"]}'}
        for i, p in enumerate(people)
    ]
    activities = [
        {"id": "sleep", "label": "睡眠", "can_secondary": []},
        {"id": "school", "label": "课堂", "can_secondary": []},
        {"id": "homework", "label": "作业", "can_secondary": ["audio"]},
        {"id": "chores", "label": "家务", "can_secondary": ["audio"]},
        {"id": "reading", "label": "文本阅读", "can_secondary": []},
        {"id": "audio", "label": "听读", "can_secondary": ["chores", "homework"]},
        {"id": "free", "label": "未安排时间", "can_secondary": []},
        {"id": "unknown", "label": "未记录", "can_secondary": []},
    ]
    diary = []

    # A1：2026-05-04，含无法解释的重叠（reading vs homework 同时段，无说明）
    diary += [
        _row("A1D1", "A1", "2026-05-04T00:00:00+08:00", "2026-05-04T07:00:00+08:00", "sleep"),
        _row("A1D2", "A1", "2026-05-04T07:00:00+08:00", "2026-05-04T16:00:00+08:00", "school"),
        _row("A1D3", "A1", "2026-05-04T16:00:00+08:00", "2026-05-04T18:00:00+08:00", "homework"),
        # 17:00-17:30 与 homework 无法解释地重叠
        _row("A1D4", "A1", "2026-05-04T17:00:00+08:00", "2026-05-04T17:30:00+08:00", "reading"),
        _row("A1D5", "A1", "2026-05-04T18:00:00+08:00", "2026-05-04T19:00:00+08:00", "chores"),
        _row("A1D5B", "A1", "2026-05-04T19:00:00+08:00", "2026-05-04T20:00:00+08:00", "reading"),
        _row("A1D5C", "A1", "2026-05-04T20:00:00+08:00", "2026-05-04T22:00:00+08:00", "free"),
        _row("A1D6", "A1", "2026-05-04T22:00:00+08:00", "2026-05-05T00:00:00+08:00", "sleep"),
    ]
    # A1：2026-05-05，跨午夜阅读 + 审核通过扣减睡眠
    diary += [
        _row("A1D7", "A1", "2026-05-05T00:00:00+08:00", "2026-05-05T07:00:00+08:00", "sleep"),
        _row("A1D8", "A1", "2026-05-05T07:00:00+08:00", "2026-05-05T16:00:00+08:00", "school"),
        _row("A1D8B", "A1", "2026-05-05T16:00:00+08:00", "2026-05-05T18:00:00+08:00", "homework"),
        _row("A1D9", "A1", "2026-05-05T18:00:00+08:00", "2026-05-05T20:00:00+08:00", "free"),
        _row("A1D9B", "A1", "2026-05-05T20:00:00+08:00", "2026-05-05T22:00:00+08:00", "chores"),
        _row("A1DX", "A1", "2026-05-05T23:30:00+08:00", "2026-05-06T00:30:00+08:00",
             "reading", received="2026-05-08"),
        _row("A1D10", "A1", "2026-05-05T22:00:00+08:00", "2026-05-06T00:00:00+08:00", "sleep"),
    ]
    # A1：2026-05-06，承接跨午夜段后补满全天
    diary += [
        _row("A1D11", "A1", "2026-05-06T00:30:00+08:00", "2026-05-06T07:00:00+08:00", "sleep"),
        _row("A1D12", "A1", "2026-05-06T07:00:00+08:00", "2026-05-06T16:00:00+08:00", "school"),
        _row("A1D13", "A1", "2026-05-06T16:00:00+08:00", "2026-05-06T22:00:00+08:00", "free"),
        _row("A1D14", "A1", "2026-05-06T22:00:00+08:00", "2026-05-07T00:00:00+08:00", "sleep"),
    ]
    # A2：同步听读（做家务时听读）+ 一段明确未记录；当天零专注阅读
    diary += [
        _row("A2D1", "A2", "2026-05-04T00:00:00+08:00", "2026-05-04T07:00:00+08:00", "sleep"),
        _row("A2D2", "A2", "2026-05-04T07:00:00+08:00", "2026-05-04T16:00:00+08:00", "school"),
        _row("A2D2B", "A2", "2026-05-04T16:00:00+08:00", "2026-05-04T18:00:00+08:00", "homework"),
        _row("A2D3", "A2", "2026-05-04T18:00:00+08:00", "2026-05-04T19:00:00+08:00",
             "chores", secondary="audio"),
        _row("A2D4", "A2", "2026-05-04T19:00:00+08:00", "2026-05-04T20:00:00+08:00", "unknown"),
        _row("A2D5", "A2", "2026-05-04T20:00:00+08:00", "2026-05-04T22:00:00+08:00", "free"),
        _row("A2D6", "A2", "2026-05-04T22:00:00+08:00", "2026-05-05T00:00:00+08:00", "sleep"),
    ]
    # B1：真实缺口日（16:00-18:00 完全没有区间）+ 待审争议
    diary += [
        _row("B1D1", "B1", "2026-05-04T00:00:00+08:00", "2026-05-04T07:00:00+08:00", "sleep"),
        _row("B1D2", "B1", "2026-05-04T07:00:00+08:00", "2026-05-04T16:00:00+08:00", "school"),
        # 刻意缺口 16:00-18:00（120 分钟，时间轴上无任何区间）
        _row("B1D3", "B1", "2026-05-04T18:00:00+08:00", "2026-05-04T19:00:00+08:00", "homework"),
        # 待审争议：18:30-19:00 阅读与作业重叠
        _row("B1D4", "B1", "2026-05-04T18:30:00+08:00", "2026-05-04T19:00:00+08:00", "reading"),
        _row("B1D5", "B1", "2026-05-04T19:00:00+08:00", "2026-05-04T22:00:00+08:00", "free"),
        _row("B1D6", "B1", "2026-05-04T22:00:00+08:00", "2026-05-05T00:00:00+08:00", "sleep"),
    ]
    # A1：2026-05-11（周一），用于让 PT3 具备前期与后期的同星期观测
    diary += [
        _row("A1D15", "A1", "2026-05-11T00:00:00+08:00", "2026-05-11T07:00:00+08:00", "sleep"),
        _row("A1D16", "A1", "2026-05-11T07:00:00+08:00", "2026-05-11T16:00:00+08:00", "school"),
        _row("A1D17", "A1", "2026-05-11T16:00:00+08:00", "2026-05-11T18:00:00+08:00", "homework"),
        _row("A1D18", "A1", "2026-05-11T18:00:00+08:00", "2026-05-11T20:00:00+08:00", "free"),
        _row("A1D19", "A1", "2026-05-11T20:00:00+08:00", "2026-05-11T22:00:00+08:00", "reading"),
        _row("A1D20", "A1", "2026-05-11T22:00:00+08:00", "2026-05-12T00:00:00+08:00", "sleep"),
    ]
    # C1/C2：S2 整层无日记（模拟整层无有效回收）

    clarifications = [
        {"id": "K1", "diary_id": "A1DX", "submitted_on": "2026-05-09",
         "decision": "approved", "decided_on": "2026-05-10",
         "explanation": "跨午夜阅读应从睡眠段扣除"},
        {"id": "K2", "diary_id": "B1D4", "submitted_on": "2026-05-09",
         "decision": "pending", "decided_on": None,
         "explanation": "学生称该时段确实在阅读，待学校审核"},
    ]
    calendar = [
        {"id": "CAL1", "school_id": "S1", "from_on": "2026-05-18",
         "to_on": "2026-05-22", "kind": "exam",
         "open_start": "12:00", "open_end": "13:00"},
        {"id": "CAL2", "school_id": "S2", "from_on": "2026-05-18",
         "to_on": "2026-05-22", "kind": "exam",
         "open_start": "12:00", "open_end": "13:00"},
    ]
    pilots = [
        {"id": "PT1", "school_id": "S1", "from_on": "2026-05-11",
         "to_on": "2026-05-17", "time_start": "12:00", "time_end": "12:30",
         "displaces": "free", "status": "executed"},
        {"id": "PT2", "school_id": "S2", "from_on": "2026-05-11",
         "to_on": "2026-05-17", "time_start": "19:00", "time_end": "19:30",
         "displaces": "homework", "status": "confirmed"},
        # PT3 与前期 5/4（周一）共享星期，后期为 5/11（周一）
        {"id": "PT3", "school_id": "S1", "from_on": "2026-05-11",
         "to_on": "2026-05-11", "time_start": "18:00", "time_end": "19:00",
         "displaces": "free", "status": "executed"},
    ]
    return {
        "schools": schools, "people": people, "sample_frame": frame,
        "activities": activities, "diary": diary,
        "clarifications": clarifications, "calendar": calendar, "pilots": pilots,
    }


def write_dataset(directory) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "data.json"
    path.write_text(json.dumps(build_dataset(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path
