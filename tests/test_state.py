"""Tests for state persistence, lifecycle, bootstrap, and release date separation."""
from datetime import datetime, timezone, timedelta
import json
import tempfile
import unittest
from pathlib import Path

from model_watcher.state import (
    WatcherState,
    is_recent_date,
    load_state,
    parse_date,
    save_state,
)
from model_watcher.types import ModelLifecycleStatus


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp_dir.name) / "state.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_bootstrap_records_models_as_seen_without_evaluation(self):
        """Test Issue #1: 首次建立 discovery state 时，把已有模型记录为已知/SEEN，不当成新发布"""
        state = WatcherState()
        rec = state.record_seen("claude-3-7-sonnet", "Claude 3.7 Sonnet", "Anthropic", release_date="2025-02-24", release_confirmed=True)

        self.assertEqual(rec.status, ModelLifecycleStatus.SEEN.value)
        self.assertIsNone(rec.evaluated_at)
        self.assertIsNone(rec.report_ref)
        # It must NOT qualify for automatic evaluation
        self.assertFalse(state.should_evaluate("claude-3-7-sonnet", release_date="2025-02-24", release_confirmed=True))

    def test_distinguish_benchmark_entry_and_release_date(self):
        """Test Issue #3: 分离 'benchmark 新 entry' 和 '新模型发布'"""
        state = WatcherState()

        # Case A: Old model appearing in benchmark for the first time
        # Release date was 180 days ago
        old_release = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
        should_eval_old = state.should_evaluate("old-model-v1", release_date=old_release, release_confirmed=True)
        self.assertFalse(should_eval_old, "Old model newly added to benchmark must not be evaluated as new release")

        # Case B: Model with unconfirmed release date
        should_eval_unconfirmed = state.should_evaluate("unconfirmed-model", release_date=None, release_confirmed=False)
        self.assertFalse(should_eval_unconfirmed, "Unconfirmed release date must not trigger unsolicited alert")

        # Case C: Genuine recent release (e.g. released 10 days ago)
        recent_release = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        should_eval_recent = state.should_evaluate("fresh-frontier-model", release_date=recent_release, release_confirmed=True)
        self.assertTrue(should_eval_recent, "Confirmed recent release must trigger evaluation")

    def test_provisional_re_eval_after_7_days(self):
        """Provisional model allows one mature review ~7 days later."""
        state = WatcherState()
        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-08-25_gpt-5.5.md",
            release_date="2026-08-20",
            release_confirmed=True,
        )
        # Simulate 8 days elapsed since evaluation
        eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
        state.models["gpt-5.5"].evaluated_at = eight_days_ago.isoformat()

        # Should be eligible for re-evaluation
        self.assertTrue(state.should_evaluate("gpt-5.5", release_date="2026-08-20", release_confirmed=True))

        # After re-evaluation, transitions to MATURE
        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-09-03_gpt-5.5.md",
            release_date="2026-08-20",
            release_confirmed=True,
        )
        self.assertEqual(state.models["gpt-5.5"].status, ModelLifecycleStatus.MATURE.value)

        # Even later, MATURE model is NOT re-evaluated
        self.assertFalse(state.should_evaluate("gpt-5.5", release_date="2026-08-20", release_confirmed=True))

    def test_atomic_write_and_corruption_safety(self):
        """Network/API error or corrupted file does not crash state loading."""
        state = WatcherState()
        state.record_seen("test-model", "Test Model", "Provider")
        save_state(state, self.state_path)

        # Corrupt file deliberately
        with open(self.state_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        recovered = load_state(self.state_path)
        self.assertIsInstance(recovered, WatcherState)
        backup = self.state_path.with_suffix(".corrupted.bak")
        self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()


class TestReleaseConfirmationFallback(unittest.TestCase):
    def test_fallback_extracts_date_from_model_name(self):
        """Test Issue #2: 无 AA Key 时，通过名称版本标识或官方来源确认发布时间"""
        from model_watcher.aggregator import confirm_release_fallback
        from model_watcher.types import ModelMetadata

        m = ModelMetadata(
            canonical_id="claude-opus-4-5-20251101-thinking-64k-high-effort",
            display_name="Claude Opus 4.5",
            provider="Anthropic",
            release_date=None,
            release_confirmed=False,
        )
        confirm_release_fallback(m)
        self.assertTrue(m.release_confirmed)
        self.assertEqual(m.release_date, "2025-11-01")

    def test_fallback_recent_date_qualifies_for_evaluation(self):
        """Recent date confirmed via fallback is not swallowed."""
        from model_watcher.aggregator import confirm_release_fallback
        from model_watcher.types import ModelMetadata

        recent_tag = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        m = ModelMetadata(
            canonical_id=f"frontier-model-{recent_tag}",
            display_name="Frontier Model",
            provider="Vendor",
            release_date=None,
            release_confirmed=False,
        )
        confirm_release_fallback(m)
        self.assertTrue(m.release_confirmed)

        state = WatcherState()
        self.assertTrue(state.should_evaluate(m.canonical_id, release_date=m.release_date, release_confirmed=m.release_confirmed))
