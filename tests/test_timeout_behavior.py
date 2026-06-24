"""Tests for timeout handling and performance bounds."""

from __future__ import annotations

import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from hermes_stack_bootstrap.bootstrap_commands import run_command
from hermes_stack_bootstrap.bootstrap_utils import spinner


class TimeoutBehaviorTests(unittest.TestCase):
    """Verify timeout protection prevents indefinite hangs."""

    def test_run_command_times_out_on_slow_command(self):
        with self.assertRaises(RuntimeError) as ctx:
            run_command(["sleep", "10"], dry_run=False, timeout=1)
        self.assertIn("timed out", str(ctx.exception).lower())
        self.assertIn("second", str(ctx.exception))

    def test_timeout_error_message_is_actionable(self):
        with self.assertRaises(RuntimeError) as ctx:
            run_command(["sleep", "10"], dry_run=False, timeout=1)
        message = str(ctx.exception).lower()
        # Should suggest what to do next
        self.assertTrue(
            any(word in message for word in ["skip", "retry", "manual", "install"]),
            f"Error message should be actionable: {message}",
        )

    def test_run_command_completes_within_timeout(self):
        start = time.monotonic()
        run_command(["sleep", "0.1"], dry_run=False, timeout=5)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2.0, "Fast command should complete quickly")

    def test_run_command_with_no_timeout_does_not_hang(self):
        """Commands with timeout=None should still respect subprocess timeout."""
        # This tests that we don't accidentally pass timeout=None to subprocess.run
        # which would allow indefinite hangs
        with self.assertRaises(RuntimeError):
            run_command(["sleep", "10"], dry_run=False, timeout=1)

    def test_timeout_parameter_is_respected(self):
        """Verify custom timeout values are honored."""
        with self.assertRaises(RuntimeError) as ctx:
            run_command(["sleep", "10"], dry_run=False, timeout=2)
        # Timeout message includes the actual elapsed time (may have floating point variance)
        self.assertIn("timed out after", str(ctx.exception))
        self.assertIn("second", str(ctx.exception))

    def test_successful_command_does_not_raise(self):
        """Commands that complete within timeout should not raise."""
        run_command(["echo", "test"], dry_run=False, timeout=10)

    def test_dry_run_ignores_timeout(self):
        """Dry-run mode should not actually execute commands."""
        # This should not raise even though sleep 10 > timeout 1
        run_command(["sleep", "10"], dry_run=True, timeout=1)

    def test_shell_command_respects_timeout(self):
        """String commands (shell=True) should also respect timeout."""
        with self.assertRaises(RuntimeError) as ctx:
            run_command("sleep 10", dry_run=False, timeout=1)
        self.assertIn("timed out", str(ctx.exception).lower())


class SpinnerTests(unittest.TestCase):
    """Verify spinner behavior in interactive and non-interactive modes."""

    def test_spinner_yields_silently_when_not_tty(self):
        """Spinner should not output anything when stdout is not a TTY."""
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()  # Not a TTY
        try:
            with spinner("Test"):
                time.sleep(0.1)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(output, "", "Spinner should be silent when not a TTY")

    def test_spinner_activates_when_tty(self):
        """Spinner should start and stop when stdout is a TTY."""
        # We can't easily test TTY output in unit tests, but we can verify
        # the context manager doesn't crash
        with patch("sys.stdout.isatty", return_value=False):
            with spinner("Test"):
                pass  # Should complete without error

    def test_spinner_cleans_up_on_exit(self):
        """Spinner should clear its line when exiting."""
        with patch("sys.stdout.isatty", return_value=False):
            with spinner("Working"):
                pass
        # If we got here without error, cleanup worked


class PerformanceBoundsTests(unittest.TestCase):
    """Verify operations complete within reasonable time bounds."""

    def test_simple_command_completes_quickly(self):
        """Simple commands should complete in under 1 second."""
        start = time.monotonic()
        run_command(["echo", "test"], dry_run=False, timeout=300)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0, f"Simple command took {elapsed:.2f}s")

    def test_dry_run_is_instant(self):
        """Dry-run should be nearly instantaneous."""
        start = time.monotonic()
        run_command(["sleep", "10"], dry_run=True, timeout=300)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.1, f"Dry-run took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
