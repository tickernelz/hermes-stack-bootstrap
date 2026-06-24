"""Small filesystem helpers for installer side effects."""

from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text via a sibling temp file and atomic replace.

    ``Path.replace`` maps to an atomic rename on POSIX when source and target are
    on the same filesystem. The temp path intentionally lives next to the target.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(text, encoding=encoding)
    temp_path.replace(path)
