import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_stack_bootstrap.bootstrap_skill_packs import install_optional_skills
from hermes_stack_bootstrap.cli import InstallerOptions, prompt_yes_no, wizard
from hermes_stack_bootstrap.bootstrap_data import HMX_KNOWLEDGE_SKILL_PACK, SkillPackSpec
from hermes_stack_bootstrap.bootstrap_prompts import prompt_missing_runtime_python
from hermes_stack_bootstrap.bootstrap_skill_packs import stage_skill_pack
from hermes_stack_bootstrap.hermes_discovery import HermesRuntime
from hermes_stack_bootstrap.provider_setup import default_hashmicro_context_length


class FakeTui:
    def __init__(self, answers):
        self.answers = list(answers)
        self.events = []

    def _pop(self):
        if not self.answers:
            raise AssertionError("FakeTui ran out of answers")
        return self.answers.pop(0)

    def banner(self, title: str, subtitle: str) -> None:
        self.events.append(("banner", title, subtitle))

    def step(self, title: str) -> None:
        self.events.append(("step", title))

    def text(self, prompt: str, default: str = "") -> str:
        self.events.append(("text", prompt, default))
        answer = self._pop()
        return default if answer is None else answer

    def confirm(self, prompt: str, default: bool = False) -> bool:
        self.events.append(("confirm", prompt, default))
        answer = self._pop()
        return default if answer is None else bool(answer)

    def select(self, prompt: str, choices, default: str = "") -> str:
        self.events.append(("select", prompt, tuple(choices), default))
        answer = self._pop()
        return default if answer is None else answer

    def multi_select(self, prompt: str, choices, defaults=()):
        self.events.append(("multi_select", prompt, tuple(choices), tuple(defaults)))
        answer = self._pop()
        return tuple(defaults) if answer is None else tuple(answer)

    def password(self, prompt: str) -> str:
        self.events.append(("password", prompt))
        return self._pop()

    def runtime_summary(self, runtime) -> None:
        self.events.append(("runtime", runtime.hermes_bin, runtime.hermes_python))


class InstallerUxRegressionTests(unittest.TestCase):
    def test_prompt_yes_no_uses_select_choices_not_raw_confirm(self):
        tui = FakeTui(["Yes"])

        self.assertTrue(prompt_yes_no("Install Ponytail?", False, tui))

        self.assertEqual(tui.events, [("select", "Install Ponytail?", ("Yes", "No"), "No")])

    def test_missing_runtime_skip_uses_select_not_confirm(self):
        runtime = HermesRuntime(
            hermes_bin="hermes",
            hermes_bin_source="test",
            hermes_python=None,
            hermes_python_source="missing",
        )
        tui = FakeTui(["Skip Mnemosyne"])

        _runtime, skip = prompt_missing_runtime_python(runtime, tui)

        self.assertTrue(skip)
        self.assertFalse(any(event[0] == "confirm" for event in tui.events))

    def test_wizard_uses_saved_skill_defaults_but_still_prompts_as_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_home = Path(tmp)
            (base_home / ".hermes-stack-bootstrap.json").write_text(
                '{"install_superpowers": true, "install_hmx_knowledge": true, "install_impeccable": false, "install_ponytail": true}',
                encoding="utf-8",
            )
            tui = FakeTui(
                [
                    "Plugin & skill only",
                    None,
                    ["default"],
                    "Yes",
                    "Yes",
                    "glpat-old",
                    "No",
                    "Yes",
                ]
            )
            with (
                patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=base_home),
                patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
            ):
                options = wizard([], env={}, ui=tui)

        self.assertTrue(options.install_superpowers)
        self.assertTrue(options.install_hmx_knowledge)
        self.assertFalse(options.install_impeccable)
        self.assertTrue(options.install_ponytail)
        self.assertFalse(any(event[0] == "confirm" for event in tui.events))
        prompts = [event[1] for event in tui.events if event[0] == "select"]
        self.assertIn("Install Obra Superpowers skill pack?", prompts)
        self.assertIn("Install HMX knowledge skill pack?", prompts)
        self.assertIn("Install Impeccable design skill?", prompts)
        self.assertIn("Install strongly recommended Ponytail skill pack?", prompts)

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
