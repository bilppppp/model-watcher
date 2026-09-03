"""Integration tests for bootstrap behavior, incremental releases, compare, and calibration."""
from datetime import datetime, timezone, timedelta
import os
import tempfile
import unittest
from pathlib import Path
import yaml

from model_watcher.cli import run_compare, run_watcher
from model_watcher.config import initialize_profile_interactive, recalibrate_profile_interactive
from model_watcher.sources.livebench import LiveBenchSource
from model_watcher.sources.lmms_eval import LMMsEvalSource
from model_watcher.sources.swebench import SWEBenchSource
from model_watcher.state import load_state, save_state, WatcherState
from model_watcher.types import ModelMetadata, ReleaseEvidenceLevel, Role


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.profile_path = self.tmp_path / "profile.yaml"
        self.state_path = self.tmp_path / "state.json"
        self.reports_dir = self.tmp_path / "reports"

        # Initialize baseline profile
        initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_bootstrap_zero_unsolicited_reports(self):
        """Test #1: 首次初始化 N 个已有模型 → 0 个 unsolicited reports"""
        self.assertFalse(self.state_path.exists())

        ret = run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model=None,
            dry_run=False,
            force=False,
            quiet_on_empty=False,
        )
        self.assertEqual(ret, 0)
        self.assertTrue(self.state_path.exists())

        state = load_state(self.state_path)
        self.assertGreater(len(state.models), 50, "Bootstrap should discover existing historical models")

        report_files = list(self.reports_dir.glob("*.md"))
        self.assertEqual(len(report_files), 0, "Bootstrap must generate 0 unsolicited reports!")

    def test_simulated_n_plus_one_new_model_increment(self):
        """Test #1 & #3: N -> N+1 模拟加入一个新模型，只处理新增的一个候选"""
        run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model=None,
            dry_run=False,
            force=False,
            quiet_on_empty=True,
        )
        initial_reports = list(self.reports_dir.glob("*.md"))
        self.assertEqual(len(initial_reports), 0)

        state = load_state(self.state_path)
        initial_model_count = len(state.models)

        new_model_id = "test-new-frontier-2026"
        recent_release_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        new_candidate = ModelMetadata(
            canonical_id=new_model_id,
            display_name="Test New Frontier 2026",
            provider="TestLab",
            release_date=recent_release_date,
            release_confirmed=True,
            release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value,
            benchmark_first_seen=datetime.now(timezone.utc).isoformat(),
            raw_source="Test",
        )

        from model_watcher import cli
        real_discover = cli.ModelAggregator.discover_all_candidates

        def mocked_discover(self):
            candidates = real_discover(self)
            return candidates + [new_candidate]

        cli.ModelAggregator.discover_all_candidates = mocked_discover
        try:
            ret = run_watcher(
                profile_path=self.profile_path,
                state_path=self.state_path,
                reports_dir=self.reports_dir,
                target_model=None,
                dry_run=False,
                force=False,
                quiet_on_empty=True,
            )
            self.assertEqual(ret, 0)

            new_reports = list(self.reports_dir.glob("*.md"))
            self.assertEqual(len(new_reports), 1, "Only the single newly released candidate should produce a report")
            self.assertIn(new_model_id, new_reports[0].name)

            updated_state = load_state(self.state_path)
            self.assertEqual(len(updated_state.models), initial_model_count + 1)
            self.assertEqual(updated_state.models[new_model_id].status, "PROVISIONAL")
        finally:
            cli.ModelAggregator.discover_all_candidates = real_discover

    def test_compare_single_model_does_not_modify_state(self):
        """Test #1, #3, #4, #13: compare 单模型挑战当前七角色 baseline，不修改 state.json，报告记录 revision"""
        # Ensure state.json exists with initial state
        initial_state = WatcherState()
        initial_state.record_seen("baseline-model", "Baseline Model", "Anthropic")
        save_state(initial_state, self.state_path)
        with open(self.state_path, "rb") as f:
            state_before = f.read()

        ret = run_compare(
            profile_path=self.profile_path,
            model_queries=["claude-opus-4-7"],
            reports_dir=self.reports_dir,
            verbose=False,
        )
        self.assertEqual(ret, 0)

        # 1. Verify state.json was completely untouched
        with open(self.state_path, "rb") as f:
            state_after = f.read()
        self.assertEqual(state_before, state_after, "compare command must NOT modify state.json")

        # 2. Verify report was generated with baseline revision
        reports = list(self.reports_dir.glob("*.md"))
        self.assertGreaterEqual(len(reports), 1)
        content = reports[0].read_text()
        self.assertIn("Revision 1", content)
        self.assertIn("| 编码 / 构建 |", content)

    def test_compare_multi_model_generates_cross_model_summary(self):
        """Test #2: compare 多模型生成 cross-model role summary 表"""
        ret = run_compare(
            profile_path=self.profile_path,
            model_queries=["claude-opus-4-7", "gemini-3.1-pro-preview-high"],
            reports_dir=self.reports_dir,
            verbose=False,
        )
        self.assertEqual(ret, 0)

        summary_reports = list(self.reports_dir.glob("*compare*.md"))
        self.assertGreaterEqual(len(summary_reports), 1)
        summary_content = summary_reports[0].read_text()

        # Check cross-model summary table presence
        self.assertIn("# 📊 多模型比较总结", summary_content)
        self.assertIn("| 角色 | 当前模型 |", summary_content)
        self.assertIn("| 建议 |", summary_content)
        # Check Reviewer adheres to Insufficient evidence
        self.assertIn("| 审查 |", summary_content)

    def test_compare_unknown_model_returns_error_without_fake_provenance(self):
        """Test #5: targeted unknown model 不再伪造 CONFIRMED release provenance，返回错误"""
        ret = run_compare(
            profile_path=self.profile_path,
            model_queries=["nonexistent-model-xyz-12345"],
            reports_dir=self.reports_dir,
            verbose=False,
        )
        self.assertEqual(ret, 1)

    def test_recalibration_and_subsequent_compare_uses_latest_revision(self):
        """Test #10, #11, #12: recalibration 不清空 state，后续 compare 使用最新 revision 的 incumbents"""
        # Save initial state
        initial_state = WatcherState()
        initial_state.record_seen("some-model", "Some Model", "Provider")
        save_state(initial_state, self.state_path)

        # Recalibrate: change coder incumbent to gpt-4o
        recal_inputs = [
            "gpt-4o, o3-mini",  # models
            "gpt-4o", "",       # coder
            "", "",             # planner
            "", "",             # reviewer
            "", "",             # reasoner
            "", "",             # analyst
            "", "",             # agent
            "", "",             # multimodal
            "y",                # confirm
        ]
        input_iter = iter(recal_inputs)
        recalibrate_profile_interactive(target_path=self.profile_path, input_func=lambda p: next(input_iter))

        # Check state.json was NOT cleared
        st = load_state(self.state_path)
        self.assertIn("some-model", st.models)

        # Now run compare
        ret = run_compare(
            profile_path=self.profile_path,
            model_queries=["claude-opus-4-7"],
            reports_dir=self.reports_dir,
            verbose=False,
        )
        self.assertEqual(ret, 0)

        # Check that report contains Revision 2 and uses gpt-4o as Coder incumbent
        report_files = sorted(self.reports_dir.glob("*.md"))
        latest_report = report_files[-1].read_text()
        self.assertIn("Revision 2", latest_report)
        self.assertIn("| 编码 / 构建 | gpt-4o |", latest_report)


if __name__ == "__main__":
    unittest.main()
