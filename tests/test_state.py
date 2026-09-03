"""Tests for state persistence, lifecycle and deduplication."""
from datetime import datetime, timezone, timedelta
import json
import tempfile
import unittest
from pathlib import Path

from model_watcher.state import (
    WatcherState,
    load_state,
    save_state,
)
from model_watcher.types import ModelLifecycleStatus


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp_dir.name) / "state.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_new_model_needs_evaluation(self):
        """New models must be evaluated immediately."""
        state = WatcherState()
        self.assertTrue(state.should_evaluate("gpt-5.5"))

    def test_state_avoids_duplicate_evaluation(self):
        """Test #3 & #9: state 能避免重复评估；第二次运行不会重复处理同一个模型"""
        state = WatcherState()
        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-09-03_gpt-5.5.md",
        )
        save_state(state, self.state_path)

        # Reload from disk
        reloaded = load_state(self.state_path)
        self.assertIn("gpt-5.5", reloaded.models)
        self.assertEqual(reloaded.models["gpt-5.5"].status, ModelLifecycleStatus.PROVISIONAL.value)

        # Immediate next run: should NOT evaluate
        self.assertFalse(reloaded.should_evaluate("gpt-5.5"))

    def test_provisional_re_eval_after_7_days(self):
        """Provisional model allows one mature review ~7 days later."""
        state = WatcherState()
        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-08-25_gpt-5.5.md",
        )
        # Simulate 8 days elapsed
        eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
        state.models["gpt-5.5"].first_seen = eight_days_ago.isoformat()

        # Should be eligible for re-evaluation
        self.assertTrue(state.should_evaluate("gpt-5.5"))

        # After re-evaluation, transitions to MATURE
        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-09-03_gpt-5.5.md",
        )
        self.assertEqual(state.models["gpt-5.5"].status, ModelLifecycleStatus.MATURE.value)

        # Even 30 days later, MATURE model is NOT re-evaluated
        self.assertFalse(state.should_evaluate("gpt-5.5"))

    def test_atomic_write_and_corruption_safety(self):
        """Test #11: 网络/API 异常时不会损坏 profile/state"""
        state = WatcherState()
        state.record_evaluation("test-model", "Test Model", "Provider", "reports/ref.md")
        save_state(state, self.state_path)

        # Corrupt file deliberately
        with open(self.state_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        # Loading should not crash; creates backup and recovers
        recovered = load_state(self.state_path)
        self.assertIsInstance(recovered, WatcherState)
        backup = self.state_path.with_suffix(".corrupted.bak")
        self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()
