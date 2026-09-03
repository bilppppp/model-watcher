"""Integration tests for bootstrap behavior, incremental new releases, and live benchmarks."""
from datetime import datetime, timezone, timedelta
import os
import tempfile
import unittest
from pathlib import Path
import yaml

from model_watcher.cli import run_watcher
from model_watcher.config import initialize_profile_interactive
from model_watcher.sources.livebench import LiveBenchSource
from model_watcher.sources.lmms_eval import LMMsEvalSource
from model_watcher.sources.swebench import SWEBenchSource
from model_watcher.state import load_state
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
        """Test Issue #1: 首次初始化 N 个已有模型 → 0 个 unsolicited reports"""
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
        """Test Issue #1 & #3: N -> N+1 模拟加入一个新模型，只处理新增的一个候选"""
        # Step 1: Bootstrap existing models
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

        # Step 2: Simulate a newly released model appearing in data sources
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
            # Step 3: Run incremental cycle
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

            # Step 4: Verify ONLY 1 new report was generated!
            new_reports = list(self.reports_dir.glob("*.md"))
            self.assertEqual(len(new_reports), 1, "Only the single newly released candidate should produce a report")
            self.assertIn(new_model_id, new_reports[0].name)

            updated_state = load_state(self.state_path)
            self.assertEqual(len(updated_state.models), initial_model_count + 1)
            self.assertEqual(updated_state.models[new_model_id].status, "PROVISIONAL")
        finally:
            cli.ModelAggregator.discover_all_candidates = real_discover

    def test_multimodal_audit_no_hardcoded_scores(self):
        """Test Issue #2: LMMs-Eval 数据审计，禁止静态分数表，缺失返回 ? Insufficient evidence"""
        source = LMMsEvalSource()
        self.assertFalse(hasattr(source, "MULTIMODAL_REFERENCE_BENCHMARKS"), "Static score table must be removed")

        ev = source.get_evidence("gemini-2.5-pro", "claude-3-7-sonnet", Role.MULTIMODAL)
        self.assertIsNone(ev, "LMMs-Eval must return None when no verified live results file exists")

    def test_explicit_targeted_dry_run(self):
        """Explicit run --model <name> --dry-run still evaluates targeted model on demand"""
        ret = run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model="claude-opus-4-7-xhigh-effort",
            dry_run=True,
            force=True,
            quiet_on_empty=False,
        )
        self.assertEqual(ret, 0)
        report_files = list(self.reports_dir.glob("*.md"))
        self.assertEqual(len(report_files), 1)


if __name__ == "__main__":
    unittest.main()
