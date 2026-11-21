"""审核裁决三情形的单元测试：权威行、收到日先后、无法判定保留。"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp import coverage as cov  # noqa: E402
from timeopp.model import Clarification, load_materials  # noqa: E402
from timeopp.synth import write_dataset  # noqa: E402


class AdjudicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_dataset(cls.tmp.name)
        cls.materials = load_materials(cls.tmp.name)
        cls.rows = cls.materials.diary_by_person()["B1"]
        cls.day = date(2026, 5, 4)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _build(self, clar):
        return cov.build_person_day(
            "B1", self.day, self.rows, self.materials.activities,
            {clar.diary_id: clar} if clar else {})

    def test_pending_review_keeps_dispute_open(self):
        cla = Clarification("K", "B1D4", "2026-05-09", "pending",
                            None, "待审")
        d = self._build(cla)
        self.assertEqual(d.disputed_minutes, 30.0)
        self.assertEqual(d.disputes[0].reason, "pending")

    def test_approved_same_day_without_authority_stays_unresolved(self):
        # B1D3 与 B1D4 同日收到；approved 但无权威行 -> 无法判定
        cla = Clarification("K", "B1D4", "2026-05-09", "approved",
                            "2026-05-09", "学校口头确认", None)
        d = self._build(cla)
        self.assertEqual(d.disputes[0].reason, "approved_unresolved")
        self.assertEqual(d.disputes[0].resolution, "open")
        self.assertEqual(d.disputed_minutes, 30.0)

    def test_approved_with_authority_allocates_to_named_row(self):
        # 指定 B1D4（阅读）为权威行：作业扣 30，阅读保留 30
        cla = Clarification("K", "B1D4", "2026-05-09", "approved",
                            "2026-05-09", "核实为阅读", "B1D4")
        d = self._build(cla)
        self.assertEqual(d.disputes[0].resolution, "approved_adjustment")
        self.assertEqual(d.primary_minutes["reading"], 30.0)
        self.assertEqual(d.primary_minutes["homework"], 30.0)
        self.assertEqual(d.disputed_minutes, 0.0)

    def test_approved_authority_on_homework_row_cuts_reading(self):
        # 指定 B1D3（作业）为权威行：阅读扣 30，作业保留 60
        cla = Clarification("K", "B1D4", "2026-05-09", "approved",
                            "2026-05-09", "核实为作业", "B1D3")
        d = self._build(cla)
        self.assertEqual(d.primary_minutes["homework"], 60.0)
        self.assertNotIn("reading", d.primary_minutes)

    def test_review_overlay_does_not_mutate_source(self):
        # 叠加层只在内存生效，原始资料保持 pending
        source = json_load(self.tmp.name)
        self.assertEqual(
            [c["decision"] for c in source["clarifications"]
             if c["diary_id"] == "B1D4"], ["pending"])


def json_load(directory):
    import json
    return json.loads(Path(directory, "data.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
