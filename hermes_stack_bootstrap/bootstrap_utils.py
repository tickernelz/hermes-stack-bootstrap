"""Small filesystem helpers for installer side effects."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text via a sibling temp file and atomic replace.

    ``Path.replace`` maps to an atomic rename on POSIX when source and target are
    on the same filesystem. The temp path intentionally lives next to the target.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(text, encoding=encoding)
    temp_path.replace(path)


def retry_with_backoff(
    func: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ),
    label: str = "operation",
) -> T:
    """Retry a callable with exponential backoff on transient failures.

    Delays between attempts: base_delay, base_delay*2, base_delay*4, ...
    On the final attempt, the original exception is re-raised.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return func()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            print(
                f"Warning: {label} attempt {attempt + 1}/{max_attempts} failed ({exc}); retrying in {delay:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError(f"{label} failed after {max_attempts} attempts") from last_exc
