"""Tests for state persistence, lifecycle, bootstrap, and release provenance hierarchy."""
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
from model_watcher.types import ModelLifecycleStatus, ReleaseEvidenceLevel


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp_dir.name) / "state.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_bootstrap_records_models_as_seen_without_evaluation(self):
        state = WatcherState()
        rec = state.record_seen("claude-3-7-sonnet", "Claude 3.7 Sonnet", "Anthropic", release_date="2025-02-24", release_confirmed=True)

        self.assertEqual(rec.status, ModelLifecycleStatus.SEEN.value)
        self.assertIsNone(rec.evaluated_at)
        self.assertIsNone(rec.report_ref)
        self.assertFalse(state.should_evaluate("claude-3-7-sonnet", release_date="2025-02-24", release_confirmed=True))

    def test_release_evidence_levels(self):
        """Test provenance hierarchy: CONFIRMED, TRUSTED, INFERRED, OBSERVED_ONLY."""
        state = WatcherState()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")

        # 1. CONFIRMED / TRUSTED: qualified for evaluation
        self.assertTrue(
            state.should_evaluate("m1", release_date=recent_date, release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value, release_confirmed=True),
            "CONFIRMED recent release must qualify"
        )
        self.assertTrue(
            state.should_evaluate("m2", release_date=recent_date, release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value, release_confirmed=True),
            "TRUSTED recent release must qualify"
        )

        # 2. INFERRED: qualified for provisional evaluation
        self.assertTrue(
            state.should_evaluate("m3", release_date=recent_date, release_evidence_level=ReleaseEvidenceLevel.INFERRED.value, release_confirmed=False),
            "INFERRED recent release must qualify for provisional evaluation"
        )

        # 3. OBSERVED_ONLY (e.g. HF createdAt or benchmark date): must NOT qualify on its own
        self.assertFalse(
            state.should_evaluate("m4", release_date=recent_date, release_evidence_level=ReleaseEvidenceLevel.OBSERVED_ONLY.value, release_confirmed=False),
            "OBSERVED_ONLY must not qualify as new model release"
        )

    def test_provisional_re_eval_after_7_days(self):
        state = WatcherState()
        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-08-25_gpt-5.5.md",
            release_date="2026-08-20",
            release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value,
            release_confirmed=True,
        )
        eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
        state.models["gpt-5.5"].evaluated_at = eight_days_ago.isoformat()

        self.assertTrue(state.should_evaluate("gpt-5.5", release_date="2026-08-20", release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value, release_confirmed=True))

        state.record_evaluation(
            canonical_id="gpt-5.5",
            display_name="GPT-5.5",
            provider="OpenAI",
            report_ref="reports/2026-09-03_gpt-5.5.md",
            release_date="2026-08-20",
            release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value,
            release_confirmed=True,
        )
        self.assertEqual(state.models["gpt-5.5"].status, ModelLifecycleStatus.MATURE.value)
        self.assertFalse(state.should_evaluate("gpt-5.5", release_date="2026-08-20", release_evidence_level=ReleaseEvidenceLevel.CONFIRMED.value, release_confirmed=True))

    def test_atomic_write_and_corruption_safety(self):
        state = WatcherState()
        state.record_seen("test-model", "Test Model", "Provider")
        save_state(state, self.state_path)

        with open(self.state_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        recovered = load_state(self.state_path)
        self.assertIsInstance(recovered, WatcherState)
        backup = self.state_path.with_suffix(".corrupted.bak")
        self.assertTrue(backup.exists())


class TestReleaseConfirmationFallback(unittest.TestCase):
    def test_hf_created_at_stored_strictly_as_repository_first_seen(self):
        """HF createdAt 只能作为 repository_first_seen (OBSERVED_ONLY)，不能作为 release_date 或 release_confirmed"""
        from model_watcher.aggregator import confirm_release_fallback
        from model_watcher.types import ModelMetadata

        m = ModelMetadata(
            canonical_id="community-user-custom-model",
            display_name="Custom Model",
            provider="Community User",
            repository_first_seen="2026-08-15",
            release_date=None,
            release_evidence_level=ReleaseEvidenceLevel.OBSERVED_ONLY.value,
            release_confirmed=False,
        )
        confirm_release_fallback(m)

        # Must NOT convert to confirmed release
        self.assertFalse(m.release_confirmed)
        self.assertIsNone(m.release_date)
        self.assertEqual(m.release_evidence_level, ReleaseEvidenceLevel.OBSERVED_ONLY.value)
        self.assertEqual(m.repository_first_seen, "2026-08-15")

    def test_trusted_provider_date_inferred(self):
        """Trusted provider with explicit version date in canonical name is marked INFERRED"""
        from model_watcher.aggregator import confirm_release_fallback
        from model_watcher.types import ModelMetadata

        m = ModelMetadata(
            canonical_id="claude-opus-4-5-20251101-thinking-64k-high-effort",
            display_name="Claude Opus 4.5",
            provider="Anthropic",
            release_date=None,
            release_evidence_level=ReleaseEvidenceLevel.OBSERVED_ONLY.value,
            release_confirmed=False,
        )
        confirm_release_fallback(m)
        self.assertEqual(m.release_evidence_level, ReleaseEvidenceLevel.INFERRED.value)
        self.assertEqual(m.release_date, "2025-11-01")
        self.assertFalse(m.release_confirmed, "Inferred date is not confirmed")

    def test_untrusted_third_party_name_date_not_inferred(self):
        """Third-party repo/model slug with date is NOT inferred as official release date"""
        from model_watcher.aggregator import confirm_release_fallback
        from model_watcher.types import ModelMetadata

        m = ModelMetadata(
            canonical_id="random-third-party-2026-08-01-lora",
            display_name="Random Third Party LoRA",
            provider="Random Dev",
            release_date=None,
            release_evidence_level=ReleaseEvidenceLevel.OBSERVED_ONLY.value,
            release_confirmed=False,
        )
        confirm_release_fallback(m)
        self.assertEqual(m.release_evidence_level, ReleaseEvidenceLevel.OBSERVED_ONLY.value)
        self.assertIsNone(m.release_date)
        self.assertFalse(m.release_confirmed)


if __name__ == "__main__":
    unittest.main()
