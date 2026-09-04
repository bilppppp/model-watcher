"""Tests for SWE-bench data source, anti-ensemble pollution, and matching accuracy."""
import unittest
from model_watcher.sources.swebench import SWEBenchSource


class TestSWEBenchAntiPollution(unittest.TestCase):
    def setUp(self):
        self.source = SWEBenchSource()
        # Mock leaderboard data with both single model and ensemble entries
        self.source._verified_results = [
            # Ensemble entry 1: model_display == 'Multiple' with many models in tags
            {
                "model_display": "Multiple",
                "name": "TRAE",
                "resolved": 75.2,
                "agent": "TRAE",
                "tags": [
                    "Model: claude-4-sonnet-20250522",
                    "Model: claude-3-7-sonnet-20250219",
                    "Model: gemini-2.5-pro-preview-06-05",
                ],
            },
            # Ensemble entry 2: Multiple models listed in tags with generic name
            {
                "model_display": "Ensemble-Agent",
                "name": "ACoder",
                "resolved": 76.4,
                "agent": "ACoder",
                "tags": [
                    "Model: claude-4-sonnet",
                    "Model: gpt-5-0807-global",
                    "Model: target-ensemble-only",
                ],
            },
            # Real standalone entry: Claude 3.7 Sonnet
            {
                "model_display": "Claude 3.7 Sonnet",
                "name": "Claude 3.7 Sonnet",
                "resolved": 66.4,
                "agent": "ByteDance DevInfra",
                "tags": ["Model: claude-3-7-sonnet-20250219"],
            },
            # Real standalone entry: Gemini 2.5 Pro
            {
                "model_display": "Gemini 2.5 Pro",
                "name": "Gemini 2.5 Pro",
                "resolved": 53.6,
                "agent": "Google DeepMind",
                "tags": ["Model: gemini-2.5-pro"],
            },
        ]

    def test_target_model_in_multiple_tags_without_standalone_returns_none(self):
        """target model 出现在 Multiple entry tags 中但无独立 entry → 不得匹配，返回 None"""
        # 'target-ensemble-only' only appears in Ensemble-Agent tags
        res = self.source._find_best_result("target-ensemble-only")
        self.assertIsNone(res, "Model appearing only in ensemble tags must NOT match ensemble entry!")

    def test_target_model_with_standalone_entry_prioritizes_real_entry(self):
        """target model 出现在 Multiple entry tags 中但有真实独立 entry → 必须优先真实独立 entry"""
        # Claude 3.7 Sonnet is in TRAE ensemble (75.2) and standalone (66.4)
        res = self.source._find_best_result("claude-3-7-sonnet")
        self.assertIsNotNone(res)
        self.assertEqual(res.get("model_display"), "Claude 3.7 Sonnet")
        self.assertEqual(res.get("resolved"), 66.4, "Must pick standalone 66.4% instead of ensemble 75.2%!")

        # Gemini 2.5 Pro is in TRAE ensemble (75.2) and standalone (53.6)
        res_gemini = self.source._find_best_result("gemini-2.5-pro")
        self.assertIsNotNone(res_gemini)
        self.assertEqual(res_gemini.get("model_display"), "Gemini 2.5 Pro")
        self.assertEqual(res_gemini.get("resolved"), 53.6, "Must pick standalone 53.6% instead of ensemble 75.2%!")

    def test_querying_multiple_returns_none(self):
        """Directly querying 'Multiple' or 'ensemble' must not return an ensemble score."""
        self.assertIsNone(self.source._find_best_result("multiple"))
        self.assertIsNone(self.source._find_best_result("ensemble"))


if __name__ == "__main__":
    unittest.main()
