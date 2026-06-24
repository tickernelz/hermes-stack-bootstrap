import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap import wizard_flow
from hermes_stack_bootstrap.cli import main
from hermes_stack_bootstrap.wizard_flow import parse_cli_flags, run_wizard_v2
from hermes_stack_bootstrap.wizard_tui import FakeWizardTui


class EntrypointRegressionTests(unittest.TestCase):
    def test_help_returns_usage_without_entering_wizard(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(["--help"])

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("usage:", stdout.getvalue().lower())
        self.assertIn("--quick", stdout.getvalue())
        self.assertNotIn("Hermes Stack Bootstrap Wizard", stdout.getvalue())

    def test_final_review_plan_action_returns_dry_run_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            ui = FakeWizardTui(
                select=[
                    "full",
                    str(hermes_home),
                    "default",
                    "skip",
                    "skip",
                    "manual",
                    "272000",
                    "same",
                    "same",
                    "plan",
                    "",
                ],
                text=["gpt-5.5"],
            )
            with patch.object(wizard_flow, "CHOICES_DIR", Path(tmp) / "profiles"):
                options = run_wizard_v2(
                    env={"HERMES_HOME": str(hermes_home), "HOME": tmp}, ui=ui, execute=False, argv=[]
                )

        self.assertTrue(options.dry_run)

    def test_parse_cli_flags_accepts_documented_flags_and_human_context_lengths(self):
        flags = parse_cli_flags(
            [
                "--yes",
                "--generate-soul",
                "--soul-overwrite",
                "--soul-agent-name",
                "Gatot",
                "--soul-user-name",
                "Zhafron",
                "--soul-communication",
                "direct",
                "--soul-language",
                "id",
                "--mnemosyne-mode",
                "full-online",
                "--progress-tail-ref",
                "v0.1.99",
                "--hermes-bin",
                "/opt/hermes/bin/hermes",
                "--hermes-python",
                "/opt/hermes/bin/python",
                "--main-context-length",
                "400K",
                "--delegation-context-length",
                "272_000",
                "--aux-all-context-length",
                "409,600",
            ]
        )

        self.assertTrue(flags["generate_soul"])
        self.assertTrue(flags["soul_overwrite"])
        self.assertEqual(flags["soul_communication"], "direct")
        self.assertEqual(flags["soul_language"], "id")
        self.assertEqual(flags["mnemosyne_mode"], "full-online")
        self.assertEqual(flags["progress_tail_ref"], "v0.1.99")
        self.assertEqual(flags["hermes_bin"], "/opt/hermes/bin/hermes")
        self.assertEqual(flags["hermes_python"], "/opt/hermes/bin/python")
        self.assertEqual(flags["main_context_length"], 400000)
        self.assertEqual(flags["delegation_context_length"], 272000)
        self.assertEqual(flags["aux_all_context_length"], 409600)

    def test_noninteractive_hashmicro_context_flags_preserve_route_specific_lengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            options = run_wizard_v2(
                env={"HERMES_HOME": str(hermes_home), "HOME": tmp, "XAI_HASHMICRO_API_KEY": "sk-test"},
                ui=FakeWizardTui(),
                execute=False,
                argv=[
                    "--yes",
                    "--dry-run",
                    "--home",
                    str(hermes_home),
                    "--setup-hashmicro-provider",
                    "--main-model",
                    "gpt-5.5",
                    "--main-context-length",
                    "111000",
                    "--delegation-model",
                    "gpt-5.5-mini",
                    "--delegation-context-length",
                    "222000",
                    "--aux-all-model",
                    "gpt-5.4-mini",
                    "--aux-all-context-length",
                    "333000",
                ],
            )

        self.assertEqual(options.hashmicro_main_context_length, 111000)
        self.assertEqual(options.hashmicro_delegation_context_length, 222000)
        self.assertEqual(set(options.hashmicro_auxiliary_context_lengths.values()), {333000})

    def test_unknown_cli_flag_fails_loudly(self):
        with self.assertRaises(SystemExit):
            parse_cli_flags(["--definitely-not-a-real-flag"])


if __name__ == "__main__":
    unittest.main()
