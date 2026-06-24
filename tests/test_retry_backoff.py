"""Tests for retry_with_backoff helper."""

from __future__ import annotations

import subprocess
import unittest
from io import StringIO
from unittest.mock import patch

from hermes_stack_bootstrap.bootstrap_utils import retry_with_backoff


class RetryWithBackoffTests(unittest.TestCase):
    def test_success_on_first_attempt(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        with patch("time.sleep"):
            result = retry_with_backoff(func, label="test")

        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 1)

    def test_success_after_transient_failures(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("network down")
            return "recovered"

        with patch("time.sleep"):
            result = retry_with_backoff(func, max_attempts=3, label="test")

        self.assertEqual(result, "recovered")
        self.assertEqual(call_count, 3)

    def test_raises_after_max_attempts(self):
        def func():
            raise ConnectionError("permanent failure")

        with patch("time.sleep"):
            with self.assertRaises(ConnectionError):
                retry_with_backoff(func, max_attempts=3, label="test")

    def test_non_retryable_exception_propagates_immediately(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with patch("time.sleep"):
            with self.assertRaises(ValueError):
                retry_with_backoff(func, label="test")

        self.assertEqual(call_count, 1)

    def test_retries_on_called_process_error(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.CalledProcessError(1, "git clone")
            return "ok"

        with patch("time.sleep"):
            result = retry_with_backoff(func, label="git clone")

        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 2)

    def test_retries_on_timeout_expired(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.TimeoutExpired("git", 300)
            return "ok"

        with patch("time.sleep"):
            result = retry_with_backoff(func, label="git clone")

        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 2)

    def test_prints_warning_to_stderr(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return "ok"

        buf = StringIO()
        with patch("time.sleep"), patch("sys.stderr", buf):
            retry_with_backoff(func, label="git clone")

        output = buf.getvalue()
        self.assertIn("attempt 1/3 failed", output)
        self.assertIn("git clone", output)
        self.assertIn("retrying in 2s", output)

    def test_custom_retryable_exceptions(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("custom retryable")
            return "ok"

        with patch("time.sleep"):
            result = retry_with_backoff(func, retryable_exceptions=(RuntimeError,), label="test")

        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
