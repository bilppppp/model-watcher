"""Tests for user baseline profile and configuration handling."""
import tempfile
import unittest
from pathlib import Path
import yaml

from model_watcher.config import (
    UserProfile,
    initialize_profile_interactive,
    load_profile,
)
from model_watcher.types import Role


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.tmp_dir.name) / "profile.yaml"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_initialize_profile_with_defaults(self):
        """Test #2: 首次初始化 profile 可工作 (automated/defaults mode)"""
        self.assertFalse(self.profile_path.exists())
        profile = initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)

        self.assertTrue(self.profile_path.exists())
        self.assertIsInstance(profile, UserProfile)
        self.assertEqual(len(profile.routing), 7)
        for role in Role:
            self.assertIn(role, profile.routing)
            self.assertTrue(bool(profile.get_incumbent(role)))

    def test_initialize_profile_interactive_mock_inputs(self):
        """Test interactive Q&A flow establishing profile."""
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

        profile = initialize_profile_interactive(
            target_path=self.profile_path,
            use_defaults=False,
            input_func=lambda prompt: next(input_iter),
        )
        self.assertTrue(self.profile_path.exists())
        self.assertEqual(profile.get_incumbent(Role.REASONER), "o3-mini")
        self.assertEqual(profile.get_incumbent(Role.MULTIMODAL), "gemini-2.5-pro")

    def test_baseline_not_modified_without_confirmation(self):
        """Test #10: baseline 不会未经确认自动修改"""
        # Create initial profile
        initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)
        with open(self.profile_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        # Load and verify it does not change file content
        profile = load_profile(self.profile_path)
        self.assertEqual(profile.get_incumbent(Role.CODER), "claude-3-7-sonnet")

        with open(self.profile_path, "r", encoding="utf-8") as f:
            new_content = f.read()
        self.assertEqual(original_content, new_content)


if __name__ == "__main__":
    unittest.main()
