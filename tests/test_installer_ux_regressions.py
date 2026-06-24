import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_stack_bootstrap.bootstrap_skill_packs import install_optional_skills
from hermes_stack_bootstrap.bootstrap_prompts import prompt_yes_no
from hermes_stack_bootstrap.cli import InstallerOptions
from hermes_stack_bootstrap.bootstrap_data import HMX_KNOWLEDGE_SKILL_PACK, SkillPackSpec
from hermes_stack_bootstrap.bootstrap_skill_packs import stage_skill_pack
from hermes_stack_bootstrap.provider_setup import default_hashmicro_context_length
from tests.helpers import FakeTui


class InstallerUxRegressionTests(unittest.TestCase):
    def test_prompt_yes_no_uses_select_choices_not_raw_confirm(self):
        tui = FakeTui(["Yes"])

        self.assertTrue(prompt_yes_no("Install Ponytail?", False, tui))

        self.assertEqual(tui.events, [("select", "Install Ponytail?", ("Yes", "No"), "No")])



    def test_existing_direct_skill_install_is_replaced_by_vendor_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "repo" / "skills" / "hmx"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text("---\nname: hmx\n---\nnew\n", encoding="utf-8")
            direct = root / "home" / "skills" / "hmx"
            direct.mkdir(parents=True)
            direct.joinpath("SKILL.md").write_text("---\nname: hmx\n---\nold\n", encoding="utf-8")
            dest = root / "home" / "skills" / "vendor" / "hmx-knowledge"

            stage_skill_pack(root / "repo", dest, HMX_KNOWLEDGE_SKILL_PACK)

            self.assertFalse(direct.exists())
            self.assertIn("new", (dest / "hmx" / "SKILL.md").read_text(encoding="utf-8"))

    def test_existing_skill_with_same_manifest_name_in_any_folder_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "repo" / "plugin" / "skills" / "impeccable"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text("---\nname: impeccable\n---\nnew\n", encoding="utf-8")
            existing = root / "home" / "skills" / "custom-impeccable"
            existing.mkdir(parents=True)
            existing.joinpath("SKILL.md").write_text("---\nname: impeccable\n---\nold\n", encoding="utf-8")
            dest = root / "home" / "skills" / "vendor" / "impeccable"

            stage_skill_pack(
                root / "repo",
                dest,
                SkillPackSpec(
                    name="impeccable",
                    repo_url="https://example.invalid/impeccable",
                    source_subdir="plugin/skills",
                ),
            )

            self.assertFalse(existing.exists())
            self.assertIn("new", (dest / "impeccable" / "SKILL.md").read_text(encoding="utf-8"))
            backups = list((root / "home" / "backups").glob("impeccable-skill-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn("old", (backups[0] / "SKILL.md").read_text(encoding="utf-8"))

    def test_existing_duplicate_skills_with_same_manifest_name_are_all_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "repo" / "skills" / "ponytail"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text("---\nname: ponytail\n---\nnew\n", encoding="utf-8")
            for folder in ("ponytail", "old/ponytail-copy"):
                existing = root / "home" / "skills" / folder
                existing.mkdir(parents=True)
                existing.joinpath("SKILL.md").write_text("---\nname: ponytail\n---\nold\n", encoding="utf-8")
            dest = root / "home" / "skills" / "vendor" / "ponytail"

            stage_skill_pack(
                root / "repo",
                dest,
                SkillPackSpec(
                    name="ponytail",
                    repo_url="https://example.invalid/ponytail",
                    source_subdir="skills",
                ),
            )

            self.assertFalse((root / "home" / "skills" / "ponytail").exists())
            self.assertFalse((root / "home" / "skills" / "old" / "ponytail-copy").exists())
            self.assertTrue((dest / "ponytail" / "SKILL.md").exists())
            backups = list((root / "home" / "backups").glob("ponytail-skill-backup-*"))
            self.assertEqual(len(backups), 2)

    def test_optional_skill_pack_failure_does_not_abort_remaining_packs(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            install_superpowers=True,
            install_hmx_knowledge=True,
            install_ponytail=True,
        )
        plan = SimpleNamespace(options=options, target_home=Path("/tmp/hermes"))
        calls = []

        def fake_install(spec, dest, *, dry_run, gitlab_token=""):
            calls.append(spec.name)
            if spec.name == "hmx-knowledge":
                raise subprocess.CalledProcessError(128, ["git", "clone"])

        with patch("hermes_stack_bootstrap.bootstrap_skill_packs.install_skill_pack", side_effect=fake_install):
            install_optional_skills(plan)

        self.assertEqual(calls, ["obra-superpowers", "hmx-knowledge", "ponytail"])

    def test_hashmicro_gpt55_reasoning_context_default_is_272k_even_with_live_metadata(self):
        self.assertEqual(default_hashmicro_context_length("gpt-5.5-xhigh"), 272000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.5-medium"), 272000)

        from hermes_stack_bootstrap.bootstrap_option_flow import _context_default_for_model

        self.assertEqual(_context_default_for_model("gpt-5.5-xhigh", {"gpt-5.5-xhigh": 400000}), 272000)


if __name__ == "__main__":
    unittest.main()
