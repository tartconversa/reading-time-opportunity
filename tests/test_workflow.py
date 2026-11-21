"""工作流留痕、试行登记状态机与订正影响的单元测试。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timeopp.workflow import WorkStore  # noqa: E402


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_records_are_sequential_and_json_safe(self):
        r1 = self.store.record_run(
            "estimate", {"trim": False, "func": lambda x: x},
            "digest-A", "(pending)")
        r2 = self.store.record_run("coverage", {}, "digest-A", "(pending)")
        self.assertTrue(r1["run_id"].endswith("001"))
        self.assertTrue(r2["run_id"].endswith("002"))
        # 函数对象不会进入留痕文件
        loaded = self.store.list_runs()
        self.assertNotIn("func", loaded[0]["params"])

    def test_pilot_status_history_preserved_through_pause(self):
        self.store.upsert_registration({
            "pilot_id": "PT1", "school_id": "S1", "scope_note": "试行",
            "setting": "campus_noon", "applies_to_boarder": None,
            "status": "active", "registered_on": "2026-05-10",
            "history": [{"from": None, "to": "active",
                         "reason": "initial_registration",
                         "recorded_on": "2026-05-10"}],
        })
        updated = self.store.change_status(
            "PT1", "paused", "考试周暂停", "2026-05-18")
        self.assertEqual(updated["status"], "paused")
        self.assertEqual(len(updated["history"]), 2)
        # 再次读取仍能看到完整历史，旧执行日期不被抹掉
        registry = self.store.load_registry()
        self.assertEqual(registry["registrations"][0]["history"][1]["reason"],
                         "考试周暂停")

    def test_revision_impact_separates_digest_eras(self):
        self.store.record_run("estimate", {}, "digest-A", "(pending)")
        self.store.record_run("coverage", {}, "digest-B", "(pending)")
        impact = self.store.revision_impact("digest-B")
        self.assertEqual(
            [r["run_id"] for r in impact["runs_under_older_digest"]]
            and impact["runs_under_older_digest"][0]["digest_at_run"],
            "digest-A")
        self.assertEqual(
            impact["runs_under_current_digest"][0]["digest_at_run"],
            "digest-B")

    def test_review_log_appends_without_overwriting(self):
        self.store.append_review(
            {"diary_id": "D1", "decision": "pending",
             "explanation": "待审", "recorded_on": "2026-05-09"})
        self.store.append_review(
            {"diary_id": "D2", "decision": "approved",
             "explanation": "通过", "recorded_on": "2026-05-10"})
        self.assertEqual(len(self.store.load_reviews()["reviews"]), 2)

    def test_unknown_pilot_status_change_raises(self):
        with self.assertRaises(KeyError):
            self.store.change_status("NOPE", "paused", "x", "2026-05-18")


if __name__ == "__main__":
    unittest.main()
