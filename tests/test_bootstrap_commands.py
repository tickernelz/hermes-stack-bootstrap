from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap.bootstrap_commands import run_command


class RunCommandTests(unittest.TestCase):
    def test_passes_default_timeout_to_subprocess(self):
        with patch("subprocess.run") as subprocess_run:
            run_command(["python", "-V"], dry_run=False)

        self.assertEqual(subprocess_run.call_args.kwargs["timeout"], 300)

    def test_passes_custom_timeout_to_subprocess(self):
        with patch("subprocess.run") as subprocess_run:
            run_command(["git", "clone", "repo", Path("dest")], dry_run=False, timeout=600)

        self.assertEqual(subprocess_run.call_args.kwargs["timeout"], 600)

    def test_dry_run_does_not_pass_timeout_to_subprocess(self):
        with patch("subprocess.run") as subprocess_run:
            run_command(["python", "-V"], dry_run=True, timeout=1)

        subprocess_run.assert_not_called()

    def test_timeout_prints_actionable_message_and_raises_runtime_error(self):
        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git", "clone", "repo"], 12)),
            patch("builtins.print") as print_mock,
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_command(["git", "clone", "repo"], dry_run=False, timeout=12)

        message = print_mock.call_args.args[0]
        self.assertIn("Command timed out after 12 seconds", message)
        self.assertIn("git clone repo", message)
        self.assertIn("Retry the bootstrap", message)
        self.assertIn("--skip-lcm", message)
        self.assertIn("--skip-mnemosyne", message)
        self.assertIsInstance(raised.exception.__cause__, subprocess.TimeoutExpired)


if __name__ == "__main__":
    unittest.main()
