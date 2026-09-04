"""Tests for 7-role evaluation logic, legal verdicts, and replacement rules."""
import tempfile
import unittest
from pathlib import Path

from model_watcher.config import initialize_profile_interactive
from model_watcher.evaluator import ModelEvaluator
from model_watcher.types import (
    BenchmarkEvidence,
    CapabilityVerdict,
    ModelMetadata,
    ReplaceVerdict,
    Role,
)


class TestEvaluator(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        profile_path = Path(self.tmp_dir.name) / "profile.yaml"
        self.profile = initialize_profile_interactive(target_path=profile_path, use_defaults=True)
        self.evaluator = ModelEvaluator(self.profile)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_reviewer_golden_rule_missing_evidence(self):
        """Reviewer 在缺证据时能返回 Insufficient evidence，不要猜"""
        challenger = ModelMetadata(canonical_id="challenger-x", display_name="Challenger X", provider="Org")
        non_review_evidence = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Coding)",
                version="2026_06_25",
                score_challenger=95.0,
                score_incumbent=80.0,
            )
        ]

        res = self.evaluator.evaluate_role(Role.REVIEWER, challenger, non_review_evidence)
        self.assertEqual(res.capability, CapabilityVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(res.replace, ReplaceVerdict.NO)
        self.assertIn("审查角色要求严格直接的代码审查与缺陷挖掘证据", res.replace_rationale)

    def test_multimodal_audit_missing_evidence(self):
        """Test Issue #2: Multimodal 在缺乏可靠结构化结果时必须返回 ? Insufficient evidence"""
        challenger = ModelMetadata(canonical_id="challenger-x", display_name="Challenger X", provider="Org")
        # No verified machine-readable multimodal leaderboard data
        res = self.evaluator.evaluate_role(Role.MULTIMODAL, challenger, [])
        self.assertEqual(res.capability, CapabilityVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(res.replace, ReplaceVerdict.NO)

    def test_all_seven_roles_produce_legal_verdicts(self):
        """七个角色都能产生合法 verdict"""
        challenger = ModelMetadata(canonical_id="challenger-x", display_name="Challenger X", provider="Org")
        legal_caps = {v.value for v in CapabilityVerdict}
        legal_reps = {v.value for v in ReplaceVerdict}

        for role in Role:
            res = self.evaluator.evaluate_role(role, challenger, [])
            self.assertIn(res.capability.value, legal_caps)
            self.assertIn(res.replace.value, legal_reps)

    def test_capability_superiority_does_not_force_replacement(self):
        """Capability: ↑ Clearly better, Replace: No is legal when harness or access differs."""
        challenger = ModelMetadata(canonical_id="challenger-x", display_name="Challenger X", provider="Org")
        evidence = [
            BenchmarkEvidence(
                source="SWE-bench",
                benchmark="SWE-bench Verified",
                version="v1",
                score_challenger=88.0,
                score_incumbent=80.0,
                known_uncertainty="Harness difference: Agent A vs Agent B",
            )
        ]

        res = self.evaluator.evaluate_role(Role.CODER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.CLEARLY_BETTER)
        self.assertEqual(res.replace, ReplaceVerdict.NO)

    def test_marginal_superiority_does_not_trigger_replacement(self):
        """Slight lead (e.g. 82.0 vs 80.0) should NOT trigger replacement."""
        challenger = ModelMetadata(canonical_id="challenger-x", display_name="Challenger X", provider="Org")
        evidence = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Reasoning)",
                version="2026_06_25",
                score_challenger=82.0,
                score_incumbent=80.0,
            )
        ]

        res = self.evaluator.evaluate_role(Role.REASONER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.PROBABLY_BETTER)
        self.assertEqual(res.replace, ReplaceVerdict.NO)

    def test_clearly_better_inaccessible_triggers_replace_yes_and_unconfigured_availability(self):
        """Clearly Better + inaccessible → Replace Yes + 当前可用性=未配置"""
        from model_watcher.reporter import MarkdownReporter
        reporter = MarkdownReporter(reports_dir=Path(self.tmp_dir.name) / "reports")

        challenger = ModelMetadata(
            canonical_id="inaccessible-strong-model",
            display_name="Inaccessible Strong Model",
            provider="FutureAI",
            input_price_per_m=2.5,
            output_price_per_m=10.0,
        )
        self.assertFalse(self.profile.is_accessible(challenger.canonical_id))

        evidence = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Coding)",
                version="2026_06_25",
                score_challenger=92.0,
                score_incumbent=80.0,
                display_metric="%",
                harness="official public leaderboard",
                confidence=0.9,
            )
        ]

        res = self.evaluator.evaluate_role(Role.CODER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.CLEARLY_BETTER)
        self.assertEqual(res.replace, ReplaceVerdict.YES)
        self.assertFalse(res.is_accessible)
        self.assertIn("该模型尚未列入当前 Calibration 的可用模型，若需要新增订阅/API，请结合价格", res.replace_rationale)

        report = self.evaluator.build_report(challenger, {Role.CODER: res})
        md = reporter.format_report(report)

        self.assertIn("**当前可用性：** 未配置（未列入当前 Calibration）", md)
        self.assertIn("| 角色 | 当前模型 | 候选模型 | 能力判断 | 是否替换？ |", md)
        self.assertIn("| 编码 / 构建 | claude-3-7-sonnet | Inaccessible Strong Model | ↑ 明显更强 | 是 |", md)
        self.assertIn("该模型尚未列入当前 Calibration 的可用模型，若需要新增订阅/API，请结合价格", md)

    def test_probably_better_inaccessible_triggers_replace_no(self):
        """Probably Better + inaccessible → Replace No with subscription rationale"""
        challenger = ModelMetadata(
            canonical_id="inaccessible-marginal-model",
            display_name="Inaccessible Marginal Model",
            provider="FutureAI",
        )
        self.assertFalse(self.profile.is_accessible(challenger.canonical_id))

        evidence = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Coding)",
                version="2026_06_25",
                score_challenger=83.0,
                score_incumbent=80.0,
                display_metric="%",
                confidence=0.85,
            )
        ]

        res = self.evaluator.evaluate_role(Role.CODER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.PROBABLY_BETTER)
        self.assertEqual(res.replace, ReplaceVerdict.NO)
        self.assertIn("优势不足以支持为了它新增订阅", res.replace_rationale)

    def test_clearly_better_accessible_triggers_replace_yes(self):
        """Clearly Better + accessible → Replace Yes"""
        from model_watcher.reporter import MarkdownReporter
        reporter = MarkdownReporter(reports_dir=Path(self.tmp_dir.name) / "reports")

        # gpt-4o is in self.profile.accessible_models by default
        challenger = ModelMetadata(
            canonical_id="gpt-4o",
            display_name="GPT-4o",
            provider="OpenAI",
        )
        self.assertTrue(self.profile.is_accessible(challenger.canonical_id))

        evidence = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Coding)",
                version="2026_06_25",
                score_challenger=92.0,
                score_incumbent=80.0,
                display_metric="%",
                harness="official public leaderboard",
                confidence=0.9,
            )
        ]

        res = self.evaluator.evaluate_role(Role.CODER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.CLEARLY_BETTER)
        self.assertEqual(res.replace, ReplaceVerdict.YES)
        self.assertTrue(res.is_accessible)

        report = self.evaluator.build_report(challenger, {Role.CODER: res})
        md = reporter.format_report(report)

        self.assertIn("**当前可用性：** 已配置", md)
        self.assertIn("| 角色 | 当前模型 | 候选模型 | 能力判断 | 是否替换？ |", md)
        self.assertIn("| 编码 / 构建 | claude-3-7-sonnet | GPT-4o | ↑ 明显更强 | 是 |", md)

    def test_accessibility_does_not_alter_capability_verdict(self):
        """accessibility 不得改变 Capability Verdict"""
        accessible_model = ModelMetadata(canonical_id="gpt-4o", display_name="GPT-4o", provider="OpenAI")
        inaccessible_model = ModelMetadata(canonical_id="future-model", display_name="Future Model", provider="FutureOrg")

        # Score delta +8 (clearly better)
        ev_clearly = [BenchmarkEvidence(source="S", benchmark="B", version="v1", score_challenger=88.0, score_incumbent=80.0)]
        res_acc_clear = self.evaluator.evaluate_role(Role.CODER, accessible_model, ev_clearly)
        res_inacc_clear = self.evaluator.evaluate_role(Role.CODER, inaccessible_model, ev_clearly)
        self.assertEqual(res_acc_clear.capability, res_inacc_clear.capability)
        self.assertEqual(res_acc_clear.capability, CapabilityVerdict.CLEARLY_BETTER)

        # Score delta +3 (probably better)
        ev_prob = [BenchmarkEvidence(source="S", benchmark="B", version="v1", score_challenger=83.0, score_incumbent=80.0)]
        res_acc_prob = self.evaluator.evaluate_role(Role.CODER, accessible_model, ev_prob)
        res_inacc_prob = self.evaluator.evaluate_role(Role.CODER, inaccessible_model, ev_prob)
        self.assertEqual(res_acc_prob.capability, res_inacc_prob.capability)
        self.assertEqual(res_acc_prob.capability, CapabilityVerdict.PROBABLY_BETTER)

    def test_missing_incumbent_score_yields_insufficient_evidence(self):
        """Regression 1: challenger score exists + incumbent score missing → Insufficient evidence (never infer from absolute score)"""
        challenger = ModelMetadata(canonical_id="challenger-solo", display_name="Challenger Solo", provider="Org")
        evidence = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Coding)",
                version="2026_06_25",
                score_challenger=96.0,
                score_incumbent=None,
                display_metric="%",
            )
        ]
        res = self.evaluator.evaluate_role(Role.CODER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(res.replace, ReplaceVerdict.NO)
        self.assertIn("当前主力模型在相同基准上缺少直接可比得分", res.replace_rationale)

    def test_aa_composite_uncertainty_semantics_not_harness_incompatibility(self):
        """Regression 3: Artificial Analysis composite index uncertainty must NOT output '测试环境不兼容'"""
        challenger = ModelMetadata(canonical_id="challenger-comp", display_name="Challenger Comp", provider="Org")
        evidence = [
            BenchmarkEvidence(
                source="Artificial Analysis",
                benchmark="Quality Index",
                version="v1",
                score_challenger=92.0,
                score_incumbent=80.0,
                display_metric=" Index",
                known_uncertainty="Composite index computed across independent test harness runs",
            )
        ]
        res = self.evaluator.evaluate_role(Role.CODER, challenger, evidence)
        self.assertEqual(res.capability, CapabilityVerdict.CLEARLY_BETTER)
        self.assertEqual(res.replace, ReplaceVerdict.NO)
        self.assertNotIn("测试环境不兼容", res.replace_rationale)
        self.assertIn("属于跨多个独立评测形成的综合指数", res.replace_rationale)

    def test_probably_better_or_composite_coder_does_not_generate_specialist_use_case(self):
        """Regression 5: Probably Better coder or composite index does NOT generate '针对高难代码难题的专有构建模型'"""
        challenger = ModelMetadata(canonical_id="challenger-pb", display_name="Challenger PB", provider="Org")

        # 1. Probably better
        ev_pb = [
            BenchmarkEvidence(
                source="LiveBench",
                benchmark="LiveBench (Coding)",
                version="2026_06_25",
                score_challenger=83.0,
                score_incumbent=80.0,
                display_metric="%",
            )
        ]
        res_pb = self.evaluator.evaluate_role(Role.CODER, challenger, ev_pb)
        self.assertEqual(res_pb.capability, CapabilityVerdict.PROBABLY_BETTER)
        report_pb = self.evaluator.build_report(challenger, {Role.CODER: res_pb})
        self.assertNotIn("针对高难代码难题的专有构建模型", report_pb.new_use_cases)

        # 2. Clearly better but composite index
        ev_comp = [
            BenchmarkEvidence(
                source="Artificial Analysis",
                benchmark="Coding Index",
                version="v1",
                score_challenger=90.0,
                score_incumbent=80.0,
                display_metric=" Index",
                known_uncertainty="Composite index computed across independent test harness runs",
            )
        ]
        res_comp = self.evaluator.evaluate_role(Role.CODER, challenger, ev_comp)
        self.assertEqual(res_comp.capability, CapabilityVerdict.CLEARLY_BETTER)
        report_comp = self.evaluator.build_report(challenger, {Role.CODER: res_comp})
        self.assertNotIn("针对高难代码难题的专有构建模型", report_comp.new_use_cases)


if __name__ == "__main__":
    unittest.main()
