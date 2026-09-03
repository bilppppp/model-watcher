"""Tests for 30-second markdown report generation."""
import tempfile
import unittest
from pathlib import Path

from model_watcher.config import initialize_profile_interactive
from model_watcher.evaluator import ModelEvaluator
from model_watcher.reporter import MarkdownReporter
from model_watcher.types import (
    BenchmarkEvidence,
    CapabilityVerdict,
    ModelMetadata,
    ReplaceVerdict,
    Role,
    RoleEvaluation,
)


class TestReporter(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        profile_path = Path(self.tmp_dir.name) / "profile.yaml"
        self.profile = initialize_profile_interactive(target_path=profile_path, use_defaults=True)
        self.evaluator = ModelEvaluator(self.profile)
        self.reporter = MarkdownReporter(reports_dir=Path(self.tmp_dir.name) / "reports")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_report_zero_out_of_seven_format(self):
        """Test #8 & #10: 0/7 routes changed generates official quote."""
        challenger = ModelMetadata(canonical_id="gpt-test", display_name="GPT-Test", provider="OpenAI")
        role_evals = {}
        for r in Role:
            role_evals[r] = RoleEvaluation(
                role=r,
                incumbent_model="claude-3-7-sonnet",
                challenger_model="gpt-test",
                capability=CapabilityVerdict.NO_ADVANTAGE,
                replace=ReplaceVerdict.NO,
                replace_rationale="No meaningful advantage.",
            )

        report = self.evaluator.build_report(challenger, role_evals)
        md = self.reporter.format_report(report)

        self.assertIn("# 🆕 GPT-Test", md)
        self.assertIn("本次改变：0/7 个当前模型路由", md)
        self.assertIn("> 已完成评估，没有任何维度足以改变当前模型组合，可以忽略这次发布。", md)
        self.assertIn("## 保持不动", md)
        self.assertIn("## Evidence / Confidence", md)

    def test_evidence_traceability_in_report(self):
        """Test #8: report 中 source/provenance 可追溯"""
        challenger = ModelMetadata(canonical_id="model-y", display_name="Model Y", provider="Provider")
        ev = BenchmarkEvidence(
            source="SWE-bench",
            benchmark="SWE-bench Verified",
            version="verified-v1",
            score_challenger=89.5,
            score_incumbent=80.2,
            harness="SWE-agent-harness",
            url="https://www.swebench.com/results",
            confidence=0.90,
            known_uncertainty="Verified benchmark run",
        )

        role_evals = {}
        for r in Role:
            role_evals[r] = RoleEvaluation(
                role=r,
                incumbent_model="incumbent",
                challenger_model="model-y",
                capability=CapabilityVerdict.CLEARLY_BETTER if r == Role.CODER else CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                replace=ReplaceVerdict.YES if r == Role.CODER else ReplaceVerdict.NO,
                replace_rationale="Clear advantage",
                primary_evidence=ev if r == Role.CODER else None,
            )

        report = self.evaluator.build_report(challenger, role_evals)
        md = self.reporter.format_report(report)

        self.assertIn("Source:** SWE-bench", md)
        self.assertIn("Benchmark:** SWE-bench Verified", md)
        self.assertIn("Score:** Challenger: 89.5% vs Incumbent: 80.2%", md)
        self.assertIn("Harness:** SWE-agent-harness", md)
        self.assertIn("URL:** https://www.swebench.com/results", md)
        self.assertIn("Confidence:** 90%", md)


if __name__ == "__main__":
    unittest.main()
