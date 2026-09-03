"""Integration tests with live structured data sources and end-to-end dry run."""
import os
import tempfile
import unittest
from pathlib import Path
import yaml

from model_watcher.cli import run_watcher
from model_watcher.config import initialize_profile_interactive, load_profile
from model_watcher.sources.livebench import LiveBenchSource
from model_watcher.sources.swebench import SWEBenchSource
from model_watcher.state import load_state
from model_watcher.types import Role


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.profile_path = self.tmp_path / "profile.yaml"
        self.state_path = self.tmp_path / "state.json"
        self.reports_dir = self.tmp_path / "reports"

        # Initialize profile
        initialize_profile_interactive(target_path=self.profile_path, use_defaults=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_skill_runtime_manifest_and_skill_md(self):
        """Test #1: Skill 本身能够被当前本地 Skill runtime 正确加载"""
        skill_file = Path("SKILL.md")
        self.assertTrue(skill_file.exists(), "SKILL.md must exist in skill root")

        with open(skill_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertTrue(content.startswith("---"), "SKILL.md must start with YAML frontmatter")
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "YAML frontmatter must be delimited by '---'")

        frontmatter = yaml.safe_load(parts[1])
        self.assertEqual(frontmatter.get("name"), "model-watcher")
        self.assertTrue(bool(frontmatter.get("description")))

        # Verify discovery symlink in ~/.gemini/config/skills/model-watcher
        global_skill = Path(os.path.expanduser("~/.gemini/config/skills/model-watcher/SKILL.md"))
        self.assertTrue(global_skill.exists(), "Skill must be resolvable via ~/.gemini/config/skills/model-watcher")

    def test_live_structured_source_reading(self):
        """Test #4 & #12: 至少一个真实结构化数据源成功读取，不是 mock-only"""
        # Test LiveBench real source
        livebench = LiveBenchSource()
        models = livebench.discover_models()
        self.assertGreater(len(models), 0, "LiveBench must discover at least 1 real model from official repo")

        # Verify scores are real floats
        first_model = models[0]
        self.assertTrue(bool(first_model.canonical_id))
        self.assertGreater(len(first_model.headline_indices), 0)

        # Test SWE-bench real source
        swebench = SWEBenchSource()
        swe_models = swebench.discover_models()
        self.assertGreater(len(swe_models), 0, "SWE-bench must discover verified entries from official repo")

    def test_end_to_end_frontier_model_dry_run(self):
        """Test #5: 至少对一个真实现存 frontier model 完成端到端 dry run"""
        frontier_model = "claude-opus-4-7-xhigh-effort"

        ret_code = run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model=frontier_model,
            dry_run=True,
            force=True,
            quiet_on_empty=False,
        )
        self.assertEqual(ret_code, 0)

        # In dry run, state should not be saved to disk
        self.assertFalse(self.state_path.exists())

        # But report was generated and saved
        report_files = list(self.reports_dir.glob("*.md"))
        self.assertEqual(len(report_files), 1)

        with open(report_files[0], "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("本次改变：", content)
        self.assertIn("| Role | Current | Challenger | Capability | Replace? |", content)
        self.assertIn("## Evidence / Confidence", content)

    def test_end_to_end_persistence_and_idempotency(self):
        """Test #3 & #9: 真实运行后更新状态，第二次运行幂等且不再重复处理"""
        frontier_model = "gemini-3.1-pro-preview-high"

        # First run (non-dry-run)
        ret1 = run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model=frontier_model,
            dry_run=False,
            force=True,
            quiet_on_empty=False,
        )
        self.assertEqual(ret1, 0)
        self.assertTrue(self.state_path.exists())

        state_after_first = load_state(self.state_path)
        self.assertIn(frontier_model, state_after_first.models)

        # Count reports generated
        report_count_1 = len(list(self.reports_dir.glob("*.md")))
        self.assertGreaterEqual(report_count_1, 1)

        # Second run without force: should detect that it's already evaluated and do nothing
        ret2 = run_watcher(
            profile_path=self.profile_path,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            target_model=frontier_model,
            dry_run=False,
            force=False,
            quiet_on_empty=False,
        )
        self.assertEqual(ret2, 0)
        report_count_2 = len(list(self.reports_dir.glob("*.md")))
        self.assertEqual(report_count_1, report_count_2, "No duplicate reports should be created")


if __name__ == "__main__":
    unittest.main()
