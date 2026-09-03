"""Tests for user baseline profile, configuration, and calibration lifecycle."""
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

from model_watcher.config import (
    UserProfile,
    initialize_profile_interactive,
    load_profile,
    recalibrate_profile_interactive,
)
from model_watcher.types import NeedsCalibrationError, Role


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.tmp_dir.name) / "profile.yaml"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_first_use_non_interactive_without_profile_raises_needs_calibration(self):
        """Test #6: 首次无 profile + 非交互运行返回 NEEDS_CALIBRATION，不自动创建默认 profile"""
        self.assertFalse(self.profile_path.exists())

        # When sys.stdin.isatty() is False (default in tests) and use_defaults=False:
        with self.assertRaises(NeedsCalibrationError):
            initialize_profile_interactive(target_path=self.profile_path, use_defaults=False)

        # Ensure no file was created on disk
        self.assertFalse(self.profile_path.exists())

    def test_first_use_defaults_for_testing(self):
        """Explicit use_defaults=True allows fixture setup with revision 1."""
        profile = initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)
        self.assertTrue(self.profile_path.exists())
        self.assertEqual(profile.revision, 1)
        self.assertTrue(bool(profile.calibrated_at))
        self.assertEqual(len(profile.routing), 7)

    def test_first_use_interactive_creates_profile_with_revision_and_calibrated_at(self):
        """Test #7: 首次交互 calibration 能建立完整七角色 baseline，记录 revision 和 calibrated_at"""
        inputs = [
            "claude-3-7-sonnet, gpt-4o, o3-mini",  # Q1
            "y",  # Q2
            "claude-3-7-sonnet", "",  # coder
            "claude-3-7-sonnet", "",  # planner
            "claude-3-7-sonnet", "",  # reviewer
            "o3-mini", "",            # reasoner
            "claude-3-7-sonnet", "",  # analyst
            "claude-3-7-sonnet", "",  # agent
            "gemini-2.5-pro", "",     # multimodal
        ]
        input_iter = iter(inputs)

        # Mock sys.stdin.isatty to True
        old_isatty = sys.stdin.isatty
        sys.stdin.isatty = lambda: True
        try:
            profile = initialize_profile_interactive(
                target_path=self.profile_path,
                use_defaults=False,
                input_func=lambda prompt: next(input_iter),
            )
        finally:
            sys.stdin.isatty = old_isatty

        self.assertTrue(self.profile_path.exists())
        self.assertEqual(profile.revision, 1)
        self.assertTrue(bool(profile.calibrated_at))
        self.assertEqual(profile.get_incumbent(Role.REASONER), "o3-mini")
        self.assertEqual(profile.get_incumbent(Role.MULTIMODAL), "gemini-2.5-pro")

    def test_recalibration_unconfirmed_leaves_profile_byte_for_byte_identical(self):
        """Test #9: recalibration 未确认时 profile byte-for-byte 不变"""
        initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)
        with open(self.profile_path, "rb") as f:
            original_bytes = f.read()

        # Simulate user entering changes but typing 'n' at confirmation
        recal_inputs = [
            "claude-opus-4-6, o3-mini",  # new models
            "claude-opus-4-6", "",      # coder
            "", "",                     # planner
            "", "",                     # reviewer
            "", "",                     # reasoner
            "", "",                     # analyst
            "", "",                     # agent
            "", "",                     # multimodal
            "n",                        # CONFIRMATION: NO!
        ]
        input_iter = iter(recal_inputs)

        recalibrate_profile_interactive(
            target_path=self.profile_path,
            input_func=lambda prompt: next(input_iter),
        )

        with open(self.profile_path, "rb") as f:
            after_bytes = f.read()

        self.assertEqual(original_bytes, after_bytes, "Profile must remain byte-for-byte identical when not confirmed")

    def test_recalibration_confirmed_increments_revision_and_updates_calibrated_at(self):
        """Test #8 & #10: 确认后 revision +1、calibrated_at 更新"""
        init_prof = initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)
        orig_revision = init_prof.revision
        orig_calibrated_at = init_prof.calibrated_at

        # Simulate user updating coder to claude-opus-4-6 and confirming 'y'
        recal_inputs = [
            "claude-opus-4-6, o3-mini",  # Q1 new models
            "claude-opus-4-6", "",      # coder primary & fallback
            "", "",                     # planner
            "", "",                     # reviewer
            "", "",                     # reasoner
            "", "",                     # analyst
            "", "",                     # agent
            "", "",                     # multimodal
            "y",                        # CONFIRMATION: YES!
        ]
        input_iter = iter(recal_inputs)

        updated_prof = recalibrate_profile_interactive(
            target_path=self.profile_path,
            input_func=lambda prompt: next(input_iter),
        )

        self.assertEqual(updated_prof.revision, orig_revision + 1)
        self.assertNotEqual(updated_prof.calibrated_at, orig_calibrated_at)
        self.assertEqual(updated_prof.get_incumbent(Role.CODER), "claude-opus-4-6")

        # Reload from disk to verify persistence
        reloaded = load_profile(self.profile_path)
        self.assertEqual(reloaded.revision, orig_revision + 1)
        self.assertEqual(reloaded.get_incumbent(Role.CODER), "claude-opus-4-6")


if __name__ == "__main__":
    unittest.main()
