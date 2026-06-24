#!/usr/bin/env python3
"""Fail when checked files exceed a small line-count budget."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_MAX_LINES = 600


@dataclass(frozen=True)
class LineLimitViolation:
    path: Path
    lines: int
    max_lines: int


def count_text_lines(path: Path) -> int | None:
    """Return line count for text files; skip missing or binary-ish files."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError):
        return None
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def check_paths(paths: Iterable[Path | str], *, max_lines: int = DEFAULT_MAX_LINES) -> list[LineLimitViolation]:
    violations: list[LineLimitViolation] = []
    for raw_path in paths:
        path = Path(raw_path)
        lines = count_text_lines(path)
        if lines is not None and lines > max_lines:
            violations.append(LineLimitViolation(path=path, lines=lines, max_lines=max_lines))
    return violations


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument("paths", nargs="*")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    violations = check_paths(args.paths, max_lines=args.max_lines)
    for violation in violations:
        print(f"{violation.path}: {violation.lines} lines > {violation.max_lines} max")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
