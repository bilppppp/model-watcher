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
        self.assertIn("Reviewer requires strict direct evidence", res.replace_rationale)

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


if __name__ == "__main__":
    unittest.main()
