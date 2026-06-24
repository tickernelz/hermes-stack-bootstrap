"""Small filesystem helpers for installer side effects."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar

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


@contextmanager
def spinner(message: str = "Working") -> Iterator[None]:
    """Show a threaded spinner during long operations in interactive mode.

    Only activates when stdout is a TTY. In non-interactive mode (piped,
    redirected, or dry-run), yields silently without output.
    """
    if not sys.stdout.isatty():
        yield
        return

    stop_event = threading.Event()
    chars = "|/-\\"

    def _spin() -> None:
        i = 0
        while not stop_event.is_set():
            sys.stdout.write(f"\r{message} {chars[i % len(chars)]}")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1

    thread = threading.Thread(target=_spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=2)
        sys.stdout.write("\r" + " " * (len(message) + 4) + "\r")
        sys.stdout.flush()
