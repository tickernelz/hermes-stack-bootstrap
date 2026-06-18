import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap.cli import (
    PROGRESS_TAIL_REF,
    InstallerOptions,
    base_home_from_config_path,
    build_plan,
    build_plans,
    parse_profiles,
    wizard,
)


class CliPlanTests(unittest.TestCase):
    def test_base_home_from_config_path_supports_default_profile(self):
        self.assertEqual(
            base_home_from_config_path("/mnt/hermes-runtime/config.yaml"),
            Path("/mnt/hermes-runtime"),
        )

    def test_base_home_from_config_path_supports_named_profile(self):
        self.assertEqual(
            base_home_from_config_path("/srv/hermes/profiles/work/config.yaml"),
            Path("/srv/hermes"),
        )

    def test_wizard_uses_detected_base_home_noninteractive(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(["--yes"])

        self.assertEqual(options.base_home, Path("/srv/hermes"))
        self.assertEqual(options.profile, "default")

    def test_wizard_allows_manual_base_home_override(self):
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("builtins.input", side_effect=["/opt/hermes", "work", "", "", ""]),
        ):
            options = wizard([])

        self.assertEqual(options.base_home, Path("/opt/hermes"))
        self.assertEqual(options.profile, "work")

    def test_progress_tail_ref_defaults_to_latest_release(self):
        self.assertEqual(PROGRESS_TAIL_REF, "latest")

    def test_parse_profiles_accepts_repeated_and_comma_separated_values(self):
        self.assertEqual(
            parse_profiles(["default,work", "client", "work"]),
            ("default", "work", "client"),
        )

    def test_build_plans_targets_multiple_profiles(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default,work",
            yes=True,
            dry_run=True,
            skip_lcm=True,
            skip_mnemosyne=True,
            skip_progress_tail=True,
            install_superpowers=True,
        )

        plans = build_plans(options)

        self.assertEqual([plan.options.profile for plan in plans], ["default", "work"])
        self.assertEqual(plans[0].target_home, Path("/tmp/hermes"))
        self.assertEqual(plans[1].target_home, Path("/tmp/hermes/profiles/work"))
        default_commands = [step.command for step in plans[0].steps if step.command]
        work_commands = [step.command for step in plans[1].steps if step.command]
        self.assertIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/skills/vendor/obra-superpowers",
            default_commands,
        )
        self.assertIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/profiles/work/skills/vendor/obra-superpowers",
            work_commands,
        )

    def test_build_plan_targets_default_home_and_uses_upstream_install_commands(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            lcm_summary_model="lokal_sub2api/gpt-5.4-mini",
            lcm_expansion_model="lokal_sub2api/gpt-5.4-mini",
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "git clone https://github.com/stephenschoettler/hermes-lcm /tmp/hermes/plugins/hermes-lcm",
            commands,
        )
        self.assertIn(
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[all]' sqlite-vec",
            commands,
        )
        self.assertIn(
            "HERMES_HOME=/tmp/hermes /tmp/hermes/hermes-agent/venv/bin/python -m mnemosyne.install",
            commands,
        )
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-progress-tail/${LATEST_HERMES_PROGRESS_TAIL_TAG}/install.sh | env HPT_INTERACTIVE=0 HERMES_HOME=/tmp/hermes bash",
            commands,
        )

    def test_build_plan_uses_mode_specific_mnemosyne_install_commands(self):
        hybrid = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            mnemosyne_mode="hybrid",
        )
        online = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            mnemosyne_mode="full-online",
        )

        hybrid_commands = [step.command for step in build_plan(hybrid).steps if step.command]
        online_commands = [step.command for step in build_plan(online).steps if step.command]

        self.assertIn(
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[embeddings]' sqlite-vec",
            hybrid_commands,
        )
        self.assertIn(
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir mnemosyne-memory sqlite-vec numpy",
            online_commands,
        )

    def test_wizard_accepts_mnemosyne_and_lcm_model_options(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(
                [
                    "--yes",
                    "--mnemosyne-mode",
                    "hybrid",
                    "--mnemosyne-llm-provider",
                    "openrouter",
                    "--mnemosyne-llm-model",
                    "anthropic/claude-sonnet-4",
                    "--lcm-summary-model",
                    "openrouter/google/gemini-2.5-flash",
                    "--lcm-expansion-model",
                    "openrouter/anthropic/claude-sonnet-4",
                ]
            )

        self.assertEqual(options.mnemosyne_mode, "hybrid")
        self.assertEqual(options.mnemosyne_host_llm_provider, "openrouter")
        self.assertEqual(options.mnemosyne_host_llm_model, "anthropic/claude-sonnet-4")
        self.assertEqual(options.lcm_summary_model, "openrouter/google/gemini-2.5-flash")
        self.assertEqual(options.lcm_expansion_model, "openrouter/anthropic/claude-sonnet-4")

    def test_build_plan_targets_named_profile_for_progress_tail(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="work",
            yes=True,
            dry_run=True,
            summary_model="",
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "git clone https://github.com/stephenschoettler/hermes-lcm /tmp/hermes/profiles/work/plugins/hermes-lcm",
            commands,
        )
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-progress-tail/${LATEST_HERMES_PROGRESS_TAIL_TAG}/install.sh | env HPT_INTERACTIVE=0 HERMES_HOME=/tmp/hermes HPT_PROFILES=work bash",
            commands,
        )
        self.assertIn(
            "hermes -p work memory status && hermes -p work mnemosyne stats && hermes -p work plugins list --plain --no-bundled",
            commands,
        )

    def test_build_plan_can_include_optional_skill_repositories(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            install_superpowers=True,
            install_hmx_knowledge=True,
            install_impeccable=True,
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/skills/vendor/obra-superpowers",
            commands,
        )
        self.assertIn(
            "git clone --depth=1 git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git /tmp/hermes/skills/vendor/hmx-knowledge",
            commands,
        )
        self.assertIn(
            "git clone --depth=1 https://github.com/pbakaus/impeccable /tmp/hermes/skills/vendor/impeccable",
            commands,
        )


if __name__ == "__main__":
    unittest.main()
