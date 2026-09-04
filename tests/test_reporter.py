"""Tests for 30-second markdown report generation and cross-model summary resolution."""
import tempfile
import unittest
from pathlib import Path

from model_watcher.config import initialize_profile_interactive
from model_watcher.evaluator import ModelEvaluator
from model_watcher.reporter import MarkdownReporter
from model_watcher.types import (
    BenchmarkEvidence,
    CapabilityVerdict,
    EvaluationReport,
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
        """0/7 routes changed generates official quote."""
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
        self.assertIn("> 没有发现足以改变当前工作流的信号，可以忽略本次发布。", md)
        self.assertIn("## 保持不动", md)
        self.assertIn("## 证据 / 置信度", md)

    def test_evidence_traceability_in_report(self):
        """Report 中 source/provenance 可追溯"""
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
                all_evidence=[ev] if r == Role.CODER else [],
            )

        report = self.evaluator.build_report(challenger, role_evals)
        md = self.reporter.format_report(report)

        self.assertIn("来源：** SWE-bench", md)
        self.assertIn("基准：** SWE-bench Verified", md)
        self.assertIn("得分：** Challenger: 89.5% vs Incumbent: 80.2%", md)
        self.assertIn("评测环境：** SWE-agent-harness", md)
        self.assertIn("URL：** https://www.swebench.com/results", md)
        self.assertIn("置信度：** 90%", md)

    def _create_dummy_report(self, model_id: str, display_name: str, coder_replace: bool, coder_score: float, benchmark_name: str, harness: str = "official"):
        challenger = ModelMetadata(canonical_id=model_id, display_name=display_name, provider="Provider")
        ev = BenchmarkEvidence(
            source="LiveBench" if "LiveBench" in benchmark_name else "SWE-bench",
            benchmark=benchmark_name,
            version="2026_06_25",
            score_challenger=coder_score,
            score_incumbent=75.0,
            display_metric="%",
            harness=harness,
            confidence=0.85,
        )
        role_evals = {}
        for r in Role:
            if r == Role.CODER:
                role_evals[r] = RoleEvaluation(
                    role=r,
                    incumbent_model="claude-3-7-sonnet",
                    challenger_model=display_name,
                    capability=CapabilityVerdict.CLEARLY_BETTER if coder_replace else CapabilityVerdict.NO_ADVANTAGE,
                    replace=ReplaceVerdict.YES if coder_replace else ReplaceVerdict.NO,
                    replace_rationale="Replace coder",
                    primary_evidence=ev,
                    all_evidence=[ev],
                )
            else:
                # Reviewer and other roles
                role_evals[r] = RoleEvaluation(
                    role=r,
                    incumbent_model="claude-3-7-sonnet" if r != Role.REASONER else "o3-mini",
                    challenger_model=display_name,
                    capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                    replace=ReplaceVerdict.NO,
                    replace_rationale="Retain incumbent",
                )
        return self.evaluator.build_report(challenger, role_evals)

    def test_cross_model_order_invariance_abc_vs_cba(self):
        """Test #6: compare A B C 与 compare C B A 必须产生相同推荐结论"""
        rep_a = self._create_dummy_report("model-a", "Model A", True, 85.0, "LiveBench (Coding)")
        rep_b = self._create_dummy_report("model-b", "Model B", True, 89.0, "LiveBench (Coding)")
        rep_c = self._create_dummy_report("model-c", "Model C", True, 82.0, "LiveBench (Coding)")

        summary_abc = self.reporter.format_multi_compare_summary([rep_a, rep_b, rep_c])
        summary_cba = self.reporter.format_multi_compare_summary([rep_c, rep_b, rep_a])
        summary_bac = self.reporter.format_multi_compare_summary([rep_b, rep_a, rep_c])

        # Both must recommend Model B as the clear winner on LiveBench (Coding)
        expected_rec = "**Model B**（在 LiveBench (Coding) 上取得最高分 89.0%）"
        self.assertIn(expected_rec, summary_abc)
        self.assertIn(expected_rec, summary_cba)
        self.assertIn(expected_rec, summary_bac)

        # Reviewer must retain claude-3-7-sonnet across all permutations
        self.assertIn("| 审查 | claude-3-7-sonnet |", summary_abc)
        self.assertIn("保留 claude-3-7-sonnet", summary_abc)
        self.assertIn("保留 claude-3-7-sonnet", summary_cba)

    def test_multiple_replace_yes_without_common_benchmark_outputs_unrankable(self):
        """Test #7a: 多个 Replace Yes + 无共同可比 benchmark → 不选假 winner，输出 unrankable 提示"""
        rep_a = self._create_dummy_report("model-a", "Model A", True, 85.0, "LiveBench (Coding)")
        rep_b = self._create_dummy_report("model-b", "Model B", True, 80.0, "SWE-bench Verified")

        summary_ab = self.reporter.format_multi_compare_summary([rep_a, rep_b])
        summary_ba = self.reporter.format_multi_compare_summary([rep_b, rep_a])

        expected_text = "Model A / Model B 均优于当前模型；但缺乏足够的直接可比证据，无法可靠排序。"
        self.assertIn(expected_text, summary_ab)
        self.assertIn(expected_text, summary_ba)

    def test_multiple_replace_yes_with_common_benchmark_picks_highest_score(self):
        """Test #7b: 多个 Replace Yes + 有共同同版本同 harness benchmark → 正确选择真实最高分"""
        rep_x = self._create_dummy_report("model-x", "Model X", True, 91.5, "LiveBench (Coding)")
        rep_y = self._create_dummy_report("model-y", "Model Y", True, 88.0, "LiveBench (Coding)")

        summary_xy = self.reporter.format_multi_compare_summary([rep_x, rep_y])
        summary_yx = self.reporter.format_multi_compare_summary([rep_y, rep_x])

        self.assertIn("**Model X**（在 LiveBench (Coding) 上取得最高分 91.5%）", summary_xy)
        self.assertIn("**Model X**（在 LiveBench (Coding) 上取得最高分 91.5%）", summary_yx)

    def test_multiple_replace_yes_tie_outputs_tie_sorted_alphabetically(self):
        """Test #7c: 同分 → 明确 tie，按字母升序排序，不随输入顺序变化"""
        rep_alpha = self._create_dummy_report("model-alpha", "Model Alpha", True, 88.0, "LiveBench (Coding)")
        rep_beta = self._create_dummy_report("model-beta", "Model Beta", True, 88.0, "LiveBench (Coding)")

        summary_ab = self.reporter.format_multi_compare_summary([rep_alpha, rep_beta])
        summary_ba = self.reporter.format_multi_compare_summary([rep_beta, rep_alpha])

        expected_tie = "并列：Model Alpha / Model Beta（在 LiveBench (Coding) 上同得 88.0%）"
        self.assertIn(expected_tie, summary_ab)
        self.assertIn(expected_tie, summary_ba)

    def test_simplified_chinese_report_structure(self):
        """Test #10: Raw generated Markdown is natively in Simplified Chinese."""
        challenger = ModelMetadata(canonical_id="gpt-5-mini", display_name="GPT-5-Mini", provider="OpenAI")
        ev = BenchmarkEvidence(
            source="LiveBench",
            benchmark="LiveBench (Coding)",
            version="2026_06_25",
            score_challenger=92.0,
            score_incumbent=80.0,
            display_metric="%",
            harness="official public leaderboard",
            confidence=0.88,
        )
        role_evals = {}
        for r in Role:
            role_evals[r] = RoleEvaluation(
                role=r,
                incumbent_model="claude-3-7-sonnet",
                challenger_model="GPT-5-Mini",
                capability=CapabilityVerdict.CLEARLY_BETTER if r == Role.CODER else CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                replace=ReplaceVerdict.YES if r == Role.CODER else ReplaceVerdict.NO,
                replace_rationale="在 LiveBench (Coding) 上具备经确证的明显能力优势（+12.0%），建议进行路由迁移。" if r == Role.CODER else "该角色暂无可验证的直接对比基准证据，继续保留当前模型。",
                primary_evidence=ev if r == Role.CODER else None,
                all_evidence=[ev] if r == Role.CODER else [],
            )

        report = self.evaluator.build_report(challenger, role_evals)
        md = self.reporter.format_report(report)

        # 1. Chinese Table headers
        self.assertIn("| 角色 | 当前模型 | 候选模型 | 能力判断 | 是否替换？ |", md)
        self.assertIn("**当前可用性：** 未配置（未列入当前 Calibration）", md)
        # 2. Chinese Role display names
        self.assertIn("| 编码 / 构建 | claude-3-7-sonnet | GPT-5-Mini |", md)
        self.assertIn("| 规划 |", md)
        self.assertIn("| 审查 |", md)
        self.assertIn("| 推理 |", md)
        self.assertIn("| 分析 / 研究 |", md)
        self.assertIn("| Agent / 工具执行 |", md)
        self.assertIn("| 多模态 |", md)
        # 3. Chinese Capability display
        self.assertIn("↑ 明显更强", md)
        self.assertIn("? 证据不足", md)
        # 4. Chinese Replace display
        self.assertIn("| 是 |", md)
        self.assertIn("| 否 |", md)
        # 5. Baseline Calibration
        self.assertIn("当前校准基线：", md)
        self.assertIn("Revision", md)
        # 6. Untranslated technical items
        self.assertIn("GPT-5-Mini", md)
        self.assertIn("LiveBench", md)
        self.assertIn("LiveBench (Coding)", md)
        self.assertIn("official public leaderboard", md)

    def test_zero_out_of_seven_worth_watching_disclaimer_no_contradiction(self):
        """Regression 2: 0/7 + 值得关注 must NOT contain '可以忽略' and must output correct prompt."""
        challenger = ModelMetadata(canonical_id="gpt-watch", display_name="GPT-Watch", provider="OpenAI", input_price_per_m=0.5)
        role_evals = {}
        for r in Role:
            role_evals[r] = RoleEvaluation(
                role=r,
                incumbent_model="claude-3-7-sonnet",
                challenger_model="gpt-watch",
                capability=CapabilityVerdict.CLEARLY_BETTER if r == Role.CODER else CapabilityVerdict.NO_ADVANTAGE,
                replace=ReplaceVerdict.NO,
                replace_rationale="Composite index, retain incumbent.",
            )

        report = self.evaluator.build_report(challenger, role_evals)
        self.assertEqual(report.routes_changed, 0)
        self.assertEqual(report.overall_verdict, "值得关注")

        md = self.reporter.format_report(report)
        self.assertIn("**结论：** 值得关注", md)
        self.assertIn("> 暂不调整当前路由，但存在值得继续观察的能力或价格信号。", md)
        self.assertNotIn("可以忽略本次发布", md)
        self.assertNotIn("可以忽略这次发布", md)

    def test_missing_evidence_does_not_claim_current_combo_optimal(self):
        """Regression 4: When no route adjustments are suggested, do NOT claim '当前组合保持最优'."""
        challenger = ModelMetadata(canonical_id="model-sparse", display_name="Model Sparse", provider="Provider")
        role_evals = {}
        for r in Role:
            role_evals[r] = RoleEvaluation(
                role=r,
                incumbent_model="incumbent",
                challenger_model="model-sparse",
                capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                replace=ReplaceVerdict.NO,
                replace_rationale="No benchmark data.",
            )

        report = self.evaluator.build_report(challenger, role_evals)
        md = self.reporter.format_report(report)

        self.assertIn("暂无足够证据支持调整当前路由。", md)
        self.assertNotIn("当前组合保持最优", md)

    def test_complete_chinese_ui_labels_in_evidence_and_header(self):
        """Regression 6: Chinese UI labels are complete in report header, table, and evidence sections."""
        challenger = ModelMetadata(
            canonical_id="model-cn-ui",
            display_name="Model CN UI",
            provider="Provider",
            input_price_per_m=0.5,
            output_price_per_m=1.5,
        )
        ev = BenchmarkEvidence(
            source="LiveBench",
            benchmark="LiveBench (Coding)",
            version="2026_06_25",
            score_challenger=95.0,
            score_incumbent=80.0,
            display_metric="%",
            harness="official",
            url="https://livebench.ai",
            confidence=0.9,
            known_uncertainty="Verified run",
        )
        role_evals = {
            Role.CODER: RoleEvaluation(
                role=Role.CODER,
                incumbent_model="claude-3-7-sonnet",
                challenger_model="Model CN UI",
                capability=CapabilityVerdict.CLEARLY_BETTER,
                replace=ReplaceVerdict.YES,
                replace_rationale="Clear advantage",
                primary_evidence=ev,
                all_evidence=[ev],
            )
        }
        for r in Role:
            if r != Role.CODER:
                role_evals[r] = RoleEvaluation(
                    role=r,
                    incumbent_model="claude-3-7-sonnet",
                    challenger_model="Model CN UI",
                    capability=CapabilityVerdict.INSUFFICIENT_EVIDENCE,
                    replace=ReplaceVerdict.NO,
                    replace_rationale="No evidence",
                )

        report = self.evaluator.build_report(challenger, role_evals)
        md = self.reporter.format_report(report)

        # Header labels
        self.assertIn("**结论：**", md)
        self.assertIn("**本次改变：", md)
        self.assertIn("**当前可用性：**", md)
        self.assertIn("**当前校准基线：**", md)

        # Table header
        self.assertIn("| 角色 | 当前模型 | 候选模型 | 能力判断 | 是否替换？ |", md)

        # Section labels
        self.assertIn("## 建议调整", md)
        self.assertIn("## 保持不动", md)
        self.assertIn("## 新用途", md)
        self.assertIn("## 最值得知道的一点", md)
        self.assertIn("## 证据 / 置信度", md)

        # Evidence field labels
        self.assertIn("- **来源：** LiveBench", md)
        self.assertIn("**基准：** LiveBench (Coding)", md)
        self.assertIn("- **得分：**", md)
        self.assertIn("- **评测环境：** official", md)
        self.assertIn("- **URL：** https://livebench.ai", md)
        self.assertIn("- **置信度：** 90%", md)
        self.assertIn("- **不确定性：** Verified run", md)


if __name__ == "__main__":
    unittest.main()
