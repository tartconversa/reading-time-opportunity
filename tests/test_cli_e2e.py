"""命令行端到端测试：在小型合成资料上走完整操作链。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run_tool.py"


class CliEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mat_tmp = tempfile.TemporaryDirectory()
        cls.work_tmp = tempfile.TemporaryDirectory()
        sys.path.insert(0, str(ROOT))
        from timeopp.synth import write_dataset  # noqa: E402
        write_dataset(cls.mat_tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.mat_tmp.cleanup()
        cls.work_tmp.cleanup()

    def _run(self, *args, expect_zero=True):
        proc = subprocess.run(
            [sys.executable, "-I", str(RUNNER),
             "--materials", self.mat_tmp.name,
             "--workdir", self.work_tmp.name,
             "--min-valid-days", "1", "--min-coverage-ratio", "0",
             "--json", *args],
            capture_output=True, text=True, check=False)
        if expect_zero and proc.returncode != 0:
            self.fail(f"命令失败：{args}\n{proc.stderr}")
        return proc

    def test_01_inspect_and_coverage(self):
        out = self._run("inspect")
        payload = json.loads(out.stdout)
        self.assertEqual(len(payload["materials_digest"]), 64)
        out = self._run("coverage")
        payload = json.loads(out.stdout)
        self.assertEqual(payload["coverage_overview"]["people_without_diary"], 2)
        self.assertGreaterEqual(
            payload["coverage_overview"]["open_disputes"], 1)

    def test_02_disputes_review_workflow(self):
        out = self._run("disputes")
        payload = json.loads(out.stdout)
        self.assertGreater(payload["count"], 0)
        # 登记一条审核（留痕，不改原始资料）
        out = self._run("review", "--diary-id", "B1D4",
                        "--decision", "rejected",
                        "--explanation", "重叠时段无法确认")
        self.assertTrue(json.loads(out.stdout)["review_recorded"])

    def test_03_estimate_reports_bounds_and_scope(self):
        out = self._run("estimate")
        payload = json.loads(out.stdout)
        self.assertIn("overall", payload)
        # S2-6 整层无回收，必须出现在不可代表声明中
        self.assertIn(
            "S2-6", payload["scope"]["representability"]["unsupported_strata"])
        bounds = payload["overall"]["bounds_due_to_unknown"]
        self.assertLess(bounds["lower_mean_daily_minutes"],
                        bounds["upper_if_all_unknown_is_reading"])

    def test_04_pilot_check_warns_and_register_pause(self):
        out = self._run("pilot-check", "--pilot-id", "PT2")
        payload = json.loads(out.stdout)
        self.assertEqual(
            payload["exposure"]["reason"],
            "status=confirmed，无实际执行日期")
        self._run("pilot-register", "--pilot-id", "PT1",
                  "--scope-note", "午间阅读角", "--action", "planned")
        out = self._run("pilot-status", "--pilot-id", "PT1",
                        "--new-status", "paused", "--reason", "演练暂停")
        self.assertEqual(
            json.loads(out.stdout)["status_changed"]["status"], "paused")

    def test_05_effects_and_trace_chain(self):
        out = self._run("effects", "--pilot-id", "PT3")
        payload = json.loads(out.stdout)
        self.assertIn("attribution", payload["did"])
        out = self._run("trace")
        chain = json.loads(out.stdout)
        self.assertEqual(len(chain["step2_pilots"]), 3)
        self.assertIn("step3_attribution_guard", chain)

    def test_06_revisions_flags_review_needed(self):
        out = self._run("revisions")
        payload = json.loads(out.stdout)
        # PT1 已登记且原始状态 executed -> 锁定；PT2 未执行 -> 需复议
        locked = {x["pilot_id"] for x in payload["locked_decisions"]}
        review = {x["pilot_id"] for x in payload["review_needed"]}
        self.assertIn("PT1", locked)
        self.assertIn("PT2", review)

    def test_07_bad_inputs_rejected(self):
        # 不存在的方案
        proc = self._run("pilot-check", "--pilot-id", "NOPE",
                         expect_zero=False)
        self.assertNotEqual(proc.returncode, 0)
        # 非法审核决定
        proc = self._run("review", "--diary-id", "A1D1",
                         "--decision", "maybe", "--explanation", "x",
                         expect_zero=False)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
