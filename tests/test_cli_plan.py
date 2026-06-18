import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap.cli import (
    PROGRESS_TAIL_REF,
    InstallerOptions,
    base_home_from_config_path,
    build_plan,
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
            patch("builtins.input", side_effect=["/opt/hermes", "work"]),
        ):
            options = wizard([])

        self.assertEqual(options.base_home, Path("/opt/hermes"))
        self.assertEqual(options.profile, "work")

    def test_progress_tail_ref_defaults_to_latest_release(self):
        self.assertEqual(PROGRESS_TAIL_REF, "latest")

    def test_build_plan_targets_default_home_and_uses_upstream_install_commands(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            summary_model="lokal_sub2api/gpt-5.4-mini",
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


if __name__ == "__main__":
    unittest.main()
