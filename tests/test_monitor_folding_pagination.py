"""Comprehensive tests for:
1-5: AA pagination, multi-page, page 3 discovery, deduplication, mid-fetch failure safety
6-10: Release family folding (GPT-6 Astra effort variants, compare preservation, Flash vs Vision, date version -0731, Preview vs Stable)
11-15: Lifecycle (bootstrap OBSERVED_ONLY -> SEEN, post-bootstrap OBSERVED_ONLY -> OBSERVED, OBSERVED upgrade to TRUSTED recent, OBSERVED upgrade past 60d, already evaluated family variant ignored)
16-17: Migration baseline safety & DeepSeek V4.1 Flash repeat suppression
18: CLI --force semantics
"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from model_watcher.aggregator import ModelAggregator
from model_watcher.cli import run_watcher
from model_watcher.config import initialize_profile_interactive
from model_watcher.family import (
    get_effort_priority,
    get_release_family_id,
    group_candidates_by_family,
    select_family_representative,
)
from model_watcher.sources.artificial_analysis import ArtificialAnalysisSource
import model_watcher.sources.artificial_analysis as aa_module
from model_watcher.state import WatcherState, load_state, save_state
from model_watcher.types import (
    ModelLifecycleStatus,
    ModelMetadata,
    ReleaseEvidenceLevel,
    Role,
)


class TestAAPaginationAndDeduplication(unittest.TestCase):
    def setUp(self):
        aa_module._GLOBAL_AA_MODELS = None

    def tearDown(self):
        aa_module._GLOBAL_AA_MODELS = None

    def test_01_aa_single_page(self):
        """1. AA 1 page pagination works correctly."""
        page_1_data = {
            "status": 200,
            "page": 1,
            "total_pages": 1,
            "has_more": False,
            "data": [
                {"id": "m1", "name": "Model 1", "creator": "Vendor A", "release_date": "2026-08-01"},
                {"id": "m2", "name": "Model 2", "creator": "Vendor B", "release_date": "2026-08-10"},
            ],
        }
        with patch("model_watcher.sources.artificial_analysis.http_get_json", return_value=page_1_data) as mock_get:
            source = ArtificialAnalysisSource(api_key="test-key")
            models = source.discover_models()
            self.assertEqual(len(models), 2)
            self.assertTrue(source.is_complete)
            self.assertEqual(mock_get.call_count, 1)

    def test_02_aa_multiple_pages(self):
        """2. AA multiple pages (e.g. 4 pages) iterates and aggregates all data."""
        def mock_fetch(url, headers=None, timeout=10):
            if "page=1" in url:
                return {"page": 1, "total_pages": 4, "has_more": True, "data": [{"id": "m1", "name": "M1"}]}
            elif "page=2" in url:
                return {"page": 2, "total_pages": 4, "has_more": True, "data": [{"id": "m2", "name": "M2"}]}
            elif "page=3" in url:
                return {"page": 3, "total_pages": 4, "has_more": True, "data": [{"id": "m3", "name": "M3"}]}
            elif "page=4" in url:
                return {"page": 4, "total_pages": 4, "has_more": False, "data": [{"id": "m4", "name": "M4"}]}
            return None

        with patch("model_watcher.sources.artificial_analysis.http_get_json", side_effect=mock_fetch) as mock_get:
            source = ArtificialAnalysisSource(api_key="test-key")
            models = source.discover_models()
            self.assertEqual(len(models), 4)
            self.assertTrue(source.is_complete)
            self.assertEqual(mock_get.call_count, 4)

    def test_03_aa_page_3_discovery(self):
        """3. Models appearing only on page 3 are properly discovered."""
        def mock_fetch(url, headers=None, timeout=10):
            if "page=1" in url:
                return {"page": 1, "total_pages": 3, "has_more": True, "data": [{"id": "m1", "name": "M1"}]}
            elif "page=2" in url:
                return {"page": 2, "total_pages": 3, "has_more": True, "data": [{"id": "m2", "name": "M2"}]}
            elif "page=3" in url:
                return {
                    "page": 3,
                    "total_pages": 3,
                    "has_more": False,
                    "data": [
                        {
                            "id": "deepseek-v4-1-flash",
                            "slug": "deepseek-v4-1-flash",
                            "name": "DeepSeek V4.1 Flash (Reasoning, Max Effort)",
                            "creator": "DeepSeek",
                            "release_date": "2026-09-10",
                        }
                    ],
                }
            return None

        with patch("model_watcher.sources.artificial_analysis.http_get_json", side_effect=mock_fetch):
            source = ArtificialAnalysisSource(api_key="test-key")
            models = source.discover_models()
            found = [m for m in models if m.canonical_id == "deepseek-v4-1-flash"]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].release_date, "2026-09-10")

    def test_04_aa_deduplication(self):
        """4. AA pagination duplicate entries across pages are deduplicated."""
        def mock_fetch(url, headers=None, timeout=10):
            if "page=1" in url:
                return {"page": 1, "total_pages": 2, "has_more": True, "data": [{"id": "dup-id", "name": "Model Dup"}]}
            elif "page=2" in url:
                return {"page": 2, "total_pages": 2, "has_more": False, "data": [{"id": "dup-id", "name": "Model Dup"}]}
            return None

        with patch("model_watcher.sources.artificial_analysis.http_get_json", side_effect=mock_fetch):
            source = ArtificialAnalysisSource(api_key="test-key")
            models = source.discover_models()
            self.assertEqual(len(models), 1)

    def test_05_aa_midway_failure_safety(self):
        """5. Mid-pagination network failure does NOT mark fetch as complete or cache partial data."""
        call_count = 0
        def mock_fetch(url, headers=None, timeout=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"page": 1, "total_pages": 3, "has_more": True, "data": [{"id": "m1", "name": "M1"}]}
            raise RuntimeError("Network disconnected on page 2")

        with patch("model_watcher.sources.artificial_analysis.http_get_json", side_effect=mock_fetch):
            source = ArtificialAnalysisSource(api_key="test-key")
            models = source.discover_models()
            self.assertEqual(models, [])
            self.assertFalse(source.is_complete)
            self.assertIsNone(aa_module._GLOBAL_AA_MODELS)

    def test_05b_aa_max_pages_reached_while_has_more_true_is_incomplete(self):
        """MAX_PAGES reached while has_more=true -> treated as incomplete and not cached."""
        def mock_fetch(url, headers=None, timeout=10):
            return {
                "page": 1,
                "total_pages": 100,
                "has_more": True,
                "data": [{"id": "m1", "name": "M1"}],
            }

        with patch("model_watcher.sources.artificial_analysis.http_get_json", side_effect=mock_fetch):
            source = ArtificialAnalysisSource(api_key="test-key")
            source.MAX_PAGES = 3
            models = source.discover_models()
            self.assertEqual(models, [])
            self.assertFalse(source.is_complete)
            self.assertIsNone(aa_module._GLOBAL_AA_MODELS)


class TestReleaseFamilyFolding(unittest.TestCase):
    def test_06_gpt6_astra_effort_variants_fold_to_one_family(self):
        """6. GPT-6 Astra low/medium/high/xhigh/max fold into 1 family and max is selected as rep."""
        cands = [
            ModelMetadata("gpt-6-astra-low", "GPT-6 Astra (low)", "OpenAI", release_date="2026-09-01"),
            ModelMetadata("gpt-6-astra-medium", "GPT-6 Astra (medium)", "OpenAI", release_date="2026-09-01"),
            ModelMetadata("gpt-6-astra-high", "GPT-6 Astra (high)", "OpenAI", release_date="2026-09-01"),
            ModelMetadata("gpt-6-astra-xhigh", "GPT-6 Astra (xhigh)", "OpenAI", release_date="2026-09-01"),
            ModelMetadata("gpt-6-astra-max", "GPT-6 Astra (max)", "OpenAI", release_date="2026-09-01"),
        ]
        groups = group_candidates_by_family(cands)
        self.assertEqual(len(groups), 1)
        fam_id = list(groups.keys())[0]
        self.assertEqual(fam_id, "gpt-6-astra")

        rep = select_family_representative(cands)
        self.assertEqual(rep.canonical_id, "gpt-6-astra-max")
        self.assertEqual(get_effort_priority(rep.canonical_id, rep.display_name), 5)

    def test_07_compare_preserves_specific_effort_configuration(self):
        """7. Compare mode still resolves and preserves specific effort configuration."""
        cands = [
            ModelMetadata("gpt-6-astra-low", "GPT-6 Astra (low)", "OpenAI"),
            ModelMetadata("gpt-6-astra-medium", "GPT-6 Astra (medium)", "OpenAI"),
            ModelMetadata("gpt-6-astra-high", "GPT-6 Astra (high)", "OpenAI"),
        ]
        agg = ModelAggregator()
        resolved = agg.resolve_model("gpt-6-astra-medium", candidates=cands)
        self.assertEqual(resolved.canonical_id, "gpt-6-astra-medium")
        self.assertEqual(resolved.display_name, "GPT-6 Astra (medium)")

    def test_08_flash_vs_vision_do_not_fold(self):
        """8. Flash and Flash Vision variants do not fold into the same family."""
        fam1 = get_release_family_id("deepseek-v4-flash", "DeepSeek V4 Flash")
        fam2 = get_release_family_id("deepseek-v4-flash-vision-exp", "DeepSeek V4 Flash Vision Exp")
        fam3 = get_release_family_id("deepseek-v4-flash-vision", "DeepSeek V4 Flash Vision (Reasoning, Max Effort)")

        self.assertNotEqual(fam1, fam2)
        self.assertNotEqual(fam1, fam3)

    def test_09_dated_version_does_not_fold_with_undated(self):
        """9. -0731 dated version does not fold with undated version."""
        fam_dated = get_release_family_id("deepseek-v4-flash-0731", "DeepSeek V4 Flash (0731)")
        fam_undated = get_release_family_id("deepseek-v4-flash", "DeepSeek V4 Flash")
        self.assertNotEqual(fam_dated, fam_undated)
        self.assertEqual(fam_dated, "deepseek-v4-flash-0731")
        self.assertEqual(fam_undated, "deepseek-v4-flash")

    def test_10_preview_vs_stable_do_not_fold(self):
        """10. Preview and Stable versions do not fold into the same family."""
        fam_preview = get_release_family_id("gpt-5-preview", "GPT-5 Preview")
        fam_stable = get_release_family_id("gpt-5", "GPT-5")
        self.assertNotEqual(fam_preview, fam_stable)

        fam_nova_prev = get_release_family_id("nova-2.0-pro-preview", "Nova 2.0 Pro Preview")
        fam_nova_stable = get_release_family_id("nova-2.0-pro", "Nova 2.0 Pro")
        self.assertNotEqual(fam_nova_prev, fam_nova_stable)


class TestModelLifecycleAndObservedState(unittest.TestCase):
    def test_11_bootstrap_observed_only_to_seen(self):
        """11. Bootstrap discovery records existing OBSERVED_ONLY models as SEEN."""
        state = WatcherState()
        agg = ModelAggregator()
        cands = [
            ModelMetadata("hist-1", "Historical 1", "Vendor", release_evidence_level=ReleaseEvidenceLevel.OBSERVED_ONLY.value),
        ]
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending = agg.get_pending_models(state, is_bootstrap=True)
            self.assertEqual(pending, [])
            self.assertIn("hist-1", state.models)
            self.assertEqual(state.models["hist-1"].status, ModelLifecycleStatus.SEEN.value)

    def test_12_post_bootstrap_new_observed_only_to_observed(self):
        """12. Post-bootstrap new discovery with only OBSERVED_ONLY evidence transitions to OBSERVED."""
        state = WatcherState()
        state.last_run = "2026-09-01T00:00:00Z"
        state.record_seen("existing", "Existing", "Vendor")

        agg = ModelAggregator()
        cands = [
            ModelMetadata(
                "new-hf-repo",
                "New HF Repo",
                "Vendor",
                release_date=None,
                release_evidence_level=ReleaseEvidenceLevel.OBSERVED_ONLY.value,
            )
        ]
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(pending, [])
            self.assertIn("new-hf-repo", state.models)
            self.assertEqual(state.models["new-hf-repo"].status, ModelLifecycleStatus.OBSERVED.value)

    def test_13_observed_upgrade_to_trusted_recent_triggers_eval(self):
        """13. An OBSERVED model upgraded with TRUSTED recent release triggers evaluation."""
        state = WatcherState()
        state.record_observed("candidate-x", "Candidate X", "Vendor")
        self.assertEqual(state.models["candidate-x"].status, ModelLifecycleStatus.OBSERVED.value)

        # Receives official release date 2 days ago
        should_eval = state.should_evaluate(
            "candidate-x",
            release_date="2026-09-09",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
        )
        self.assertTrue(should_eval)

    def test_14_observed_upgrade_past_60d_transitions_to_seen_without_eval(self):
        """14. An OBSERVED model upgraded with TRUSTED release date > 60 days transitions to SEEN without alert."""
        state = WatcherState()
        state.record_observed("candidate-old", "Candidate Old", "Vendor")

        # Receives release date 100 days ago
        should_eval = state.should_evaluate(
            "candidate-old",
            release_date="2026-05-01",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
        )
        self.assertFalse(should_eval)
        self.assertEqual(state.models["candidate-old"].status, ModelLifecycleStatus.SEEN.value)

    def test_15_evaluated_family_ignores_new_effort_variant(self):
        """15. Already evaluated family ignores subsequent effort variants."""
        state = WatcherState()
        state.record_evaluation(
            canonical_id="deepseek-v4-1-flash",
            display_name="DeepSeek V4.1 Flash (Reasoning, Max Effort)",
            provider="DeepSeek",
            report_ref="reports/2026-09-11_deepseek-v4-1-flash.md",
            release_date="2026-09-10",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
            family_id="deepseek-v4.1-flash",
        )

        should_eval = state.should_evaluate(
            canonical_id="deepseek-v4.1-flash-max",
            release_date="2026-09-10",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
            family_id="deepseek-v4.1-flash",
        )
        self.assertFalse(should_eval, "New effort variant of already evaluated family must NOT trigger evaluation")

    def test_15b_historical_seen_family_suppresses_later_effort_sibling(self):
        """Historical SEEN family suppresses later new effort sibling -> no unsolicited report."""
        state = WatcherState()
        state.record_seen(
            canonical_id="gpt-6-astra-high",
            display_name="GPT-6 Astra (high)",
            provider="OpenAI",
            release_date="2026-08-01",
            family_id="gpt-6-astra",
        )
        self.assertTrue(state.is_family_seen("gpt-6-astra"))
        self.assertTrue(state.is_family_suppressed("gpt-6-astra"))

        # Later, gpt-6-astra-max appears with recent TRUSTED release date
        should_eval = state.should_evaluate(
            canonical_id="gpt-6-astra-max",
            release_date="2026-09-08",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
            family_id="gpt-6-astra",
        )
        self.assertFalse(should_eval, "New effort sibling of historical SEEN family must NOT trigger evaluation")

        # In aggregator, get_pending_models must return 0 pending models
        agg = ModelAggregator()
        cands = [
            ModelMetadata(
                "gpt-6-astra-max",
                "GPT-6 Astra (max)",
                "OpenAI",
                release_date="2026-09-08",
                release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
                release_confirmed=True,
            )
        ]
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending), 0, "No unsolicited report should be generated for sibling of SEEN family")
            self.assertIn("gpt-6-astra-max", state.models)
            self.assertEqual(state.models["gpt-6-astra-max"].status, ModelLifecycleStatus.SEEN.value)

    def test_15c_observed_alias_does_not_suppress_trusted_sibling_eval(self):
        """OBSERVED alias A does NOT suppress TRUSTED alias B -> triggers initial evaluation."""
        state = WatcherState()
        state.record_observed(
            canonical_id="alias-a",
            display_name="Model Alias A",
            provider="Vendor",
            family_id="fam-test",
        )
        self.assertEqual(state.models["alias-a"].status, ModelLifecycleStatus.OBSERVED.value)
        self.assertFalse(state.is_family_suppressed("fam-test"))

        should_eval = state.should_evaluate(
            canonical_id="alias-b",
            release_date="2026-09-09",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
            family_id="fam-test",
        )
        self.assertTrue(should_eval, "TRUSTED sibling must NOT be blocked by OBSERVED alias")

        agg = ModelAggregator()
        cands = [
            ModelMetadata(
                "alias-b",
                "Model Alias B",
                "Vendor",
                release_date="2026-09-09",
                release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
                release_confirmed=True,
            )
        ]
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].canonical_id, "alias-b")

    def test_15d_crash_window_before_eval_does_not_suppress_rep_on_second_run(self):
        """Family has max/high/medium -> first run selects max -> simulate interruption before record_evaluation -> second run max still evaluated, not suppressed by siblings."""
        state = WatcherState()
        agg = ModelAggregator()
        cands = [
            ModelMetadata("gpt-6-astra-medium", "GPT-6 Astra (medium)", "OpenAI", release_date="2026-09-08", release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value, release_confirmed=True),
            ModelMetadata("gpt-6-astra-high", "GPT-6 Astra (high)", "OpenAI", release_date="2026-09-08", release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value, release_confirmed=True),
            ModelMetadata("gpt-6-astra-max", "GPT-6 Astra (max)", "OpenAI", release_date="2026-09-08", release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value, release_confirmed=True),
        ]

        # First run:
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending1 = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending1), 1)
            self.assertEqual(pending1[0].canonical_id, "gpt-6-astra-max")

            # Verify siblings were NOT prematurely marked as SEEN in state
            self.assertNotIn("gpt-6-astra-medium", state.models)
            self.assertNotIn("gpt-6-astra-high", state.models)
            self.assertFalse(state.is_family_suppressed("gpt-6-astra"))

        # Simulate crash/interruption: evaluation did NOT complete, state.record_evaluation was NOT called.

        # Second run:
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending2 = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending2), 1, "Representative max must still be evaluated on second run")
            self.assertEqual(pending2[0].canonical_id, "gpt-6-astra-max")

        # Now simulate successful evaluation of max
        state.record_evaluation(
            canonical_id="gpt-6-astra-max",
            display_name="GPT-6 Astra (max)",
            provider="OpenAI",
            report_ref="reports/2026-09-11_gpt-6-astra-max.md",
            release_date="2026-09-08",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
            family_id="gpt-6-astra",
        )
        self.assertTrue(state.is_family_suppressed("gpt-6-astra"))

        # Third run: family already has PROVISIONAL record -> siblings are silently absorbed as SEEN
        with patch.object(agg, "discover_all_candidates", return_value=cands):
            pending3 = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending3), 0, "No pending models on third run")
            self.assertIn("gpt-6-astra-medium", state.models)
            self.assertEqual(state.models["gpt-6-astra-medium"].status, ModelLifecycleStatus.SEEN.value)
            self.assertIn("gpt-6-astra-high", state.models)
            self.assertEqual(state.models["gpt-6-astra-high"].status, ModelLifecycleStatus.SEEN.value)


class TestMigrationAndRepeatSuppression(unittest.TestCase):
    def test_16_migration_baseline_absorbs_candidates_without_unsolicited_alerts(self):
        """16. First full-pagination migration baseline generates 0 unsolicited reports."""
        state = WatcherState()
        state.last_run = "2026-09-03T09:43:00Z"
        for i in range(343):
            state.record_seen(f"baseline-{i}", f"Baseline {i}", "Vendor")

        newly_visible = [
            ModelMetadata(f"new-model-{i}", f"New Model {i}", "Vendor", release_date="2026-09-01", release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value)
            for i in range(50)
        ]

        # Migration: record all newly visible models as SEEN baseline
        for m in newly_visible:
            if m.canonical_id not in state.models:
                fam = get_release_family_id(m.canonical_id, m.display_name)
                state.record_seen(
                    canonical_id=m.canonical_id,
                    display_name=m.display_name,
                    provider=m.provider,
                    release_date=m.release_date,
                    release_evidence_level=m.release_evidence_level,
                    release_confirmed=m.release_confirmed,
                    family_id=fam,
                )

        agg = ModelAggregator()
        with patch.object(agg, "discover_all_candidates", return_value=newly_visible):
            pending = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending), 0, "Migration must ensure 0 unsolicited reports on subsequent run")

    def test_17_deepseek_v4_1_flash_handled_no_repeat_on_next_cron(self):
        """17. DeepSeek V4.1 Flash processed -> next normal cron does not repeat alert."""
        state = WatcherState()
        state.record_evaluation(
            canonical_id="deepseek-v4-1-flash",
            display_name="DeepSeek V4.1 Flash (Reasoning, Max Effort)",
            provider="DeepSeek",
            report_ref="reports/2026-09-11_deepseek-v4-1-flash.md",
            release_date="2026-09-10",
            release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
            release_confirmed=True,
            family_id="deepseek-v4.1-flash",
        )

        agg = ModelAggregator()
        cron_candidates = [
            ModelMetadata("deepseek-v4-1-flash", "DeepSeek V4.1 Flash (Reasoning, Max Effort)", "DeepSeek", release_date="2026-09-10", release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value),
            ModelMetadata("deepseek-v4.1-flash-max", "DeepSeek V4.1 Flash (max)", "DeepSeek", release_date="2026-09-10", release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value),
        ]
        with patch.object(agg, "discover_all_candidates", return_value=cron_candidates):
            pending = agg.get_pending_models(state, is_bootstrap=False)
            self.assertEqual(len(pending), 0, "DeepSeek V4.1 Flash must not trigger repeated alerts on subsequent cron")


class TestForceCliSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.profile_path = self.tmp_path / "profile.yaml"
        self.state_path = self.tmp_path / "state.json"
        self.reports_dir = self.tmp_path / "reports"

        initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)

        state = WatcherState()
        state.record_seen("existing-m", "Existing Model", "Vendor")
        save_state(state, self.state_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_18_bare_force_is_rejected_with_exit_code_1(self):
        """18a. Bare 'run --force' is rejected with exit code 1."""
        code = run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model=None,
            force=True,
        )
        self.assertEqual(code, 1)

    def test_18_model_force_succeeds(self):
        """18b. 'run --model <M> --force' succeeds and forces evaluation of model in state."""
        with patch("model_watcher.aggregator.ModelAggregator.collect_role_evidence", return_value=[]):
            with patch("model_watcher.aggregator.ModelAggregator.resolve_model") as mock_resolve:
                mock_resolve.return_value = ModelMetadata(
                    canonical_id="existing-m",
                    display_name="Existing Model",
                    provider="Vendor",
                    release_date="2026-09-01",
                    release_evidence_level=ReleaseEvidenceLevel.TRUSTED.value,
                )
                code = run_watcher(
                    profile_path=self.profile_path,
                    state_path=self.state_path,
                    reports_dir=self.reports_dir,
                    target_model="existing-m",
                    force=True,
                )
                self.assertEqual(code, 0)
                loaded = load_state(self.state_path)
                self.assertIsNotNone(loaded.models["existing-m"].evaluated_at)
                self.assertIn(loaded.models["existing-m"].status, (ModelLifecycleStatus.MATURE.value, ModelLifecycleStatus.PROVISIONAL.value))


if __name__ == "__main__":
    unittest.main()
