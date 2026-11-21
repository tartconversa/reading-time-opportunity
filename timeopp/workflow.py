"""工作流状态：运行留痕、试行登记、订正指纹与追溯链。

所有派生状态写入工作目录，原始 materials 永远只读。
每次分析运行记录资料指纹，使日记订正后可以区分：
- 重新分析得到的新诊断/新估计；
- 已经执行、不可改写的校内安排；
- 尚未开始、需要复议的安排。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path


class WorkStore:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.runs_dir = self.dir / "runs"
        self.registry_path = self.dir / "pilot_registry.json"
        self.reviews_path = self.dir / "review_log.json"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)

    # ---- 分析运行留痕 -------------------------------------------------
    @staticmethod
    def _jsonable_params(params: dict) -> dict:
        safe = {}
        for key, value in params.items():
            if key == "func" or callable(value):
                continue
            safe[key] = value
        return safe

    def record_run(self, command: str, params: dict, digest: str,
                   result_ref: str, notes: str = "") -> dict:
        today = date.today().isoformat()
        existing = sorted(p.name for p in self.runs_dir.glob("run-*.json"))
        seq = len(existing) + 1
        run_id = f"run-{today}-{seq:03d}"
        record = {
            "run_id": run_id,
            "command": command,
            "params": self._jsonable_params(params),
            "materials_digest": digest,
            "result_ref": result_ref,
            "notes": notes,
            "recorded_on": today,
        }
        (self.runs_dir / f"{run_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def list_runs(self) -> list[dict]:
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(self.runs_dir.glob("run-*.json"))
        ]

    def write_result(self, run_id: str, name: str, payload: dict) -> Path:
        out_dir = self.dir / "results" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    # ---- 试行登记（人工操作，区别于原始 pilots 表） -------------------
    def load_registry(self) -> dict:
        if not self.registry_path.exists():
            return {"registrations": []}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def save_registry(self, registry: dict) -> None:
        self.registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def upsert_registration(self, registration: dict) -> dict:
        registry = self.load_registry()
        items = registry["registrations"]
        for i, item in enumerate(items):
            if item["pilot_id"] == registration["pilot_id"]:
                items[i] = registration
                break
        else:
            items.append(registration)
        self.save_registry(registry)
        return registration

    def change_status(self, pilot_id: str, new_status: str,
                      reason: str, recorded_on: str) -> dict:
        registry = self.load_registry()
        for item in registry["registrations"]:
            if item["pilot_id"] == pilot_id:
                item["history"].append({
                    "from": item["status"], "to": new_status,
                    "reason": reason, "recorded_on": recorded_on,
                })
                item["status"] = new_status
                self.save_registry(registry)
                return item
        raise KeyError(f"登记中找不到方案：{pilot_id}")

    # ---- 审核操作留痕 -------------------------------------------------
    def load_reviews(self) -> dict:
        if not self.reviews_path.exists():
            return {"reviews": []}
        return json.loads(self.reviews_path.read_text(encoding="utf-8"))

    def append_review(self, review: dict) -> dict:
        log = self.load_reviews()
        log["reviews"].append(review)
        self.reviews_path.write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return review

    # ---- 订正影响分析 -------------------------------------------------
    def revision_impact(self, current_digest: str) -> dict:
        """对比历次运行所用指纹，标出受日记订正影响的产物。"""
        runs = self.list_runs()
        affected, unaffected = [], []
        for run in runs:
            target = affected if run["materials_digest"] != current_digest \
                else unaffected
            target.append({
                "run_id": run["run_id"], "command": run["command"],
                "digest_at_run": run["materials_digest"],
                "result_ref": run["result_ref"],
            })
        return {
            "current_digest": current_digest,
            "runs_under_older_digest": affected,
            "runs_under_current_digest": unaffected,
            "rule": "受影响的是诊断、估计与效果说明；已执行的校内安排"
                    "不随重算改写，未开始的安排需携带原因复议",
        }
