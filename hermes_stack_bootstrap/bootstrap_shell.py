"""Shell rendering helpers."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Mapping, Sequence

_WINDOWS_DRIVE_PATH_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def path_for_shell(value: str | Path) -> str:
    """Return a POSIX-shell-friendly display/execution path for Git Bash plans.

    The installer can run under Windows Python while the visible terminal is Git
    Bash. Native Windows paths like C:\\Users\\... must not be emitted into bash
    snippets as-is; Git Bash expects /c/Users/....
    """
    text = str(value)
    match = _WINDOWS_DRIVE_PATH_RE.match(text)
    if not match:
        return text
    drive, rest = match.groups()
    normalized_rest = rest.replace("\\", "/")
    return f"/{drive.lower()}/{normalized_rest}"


def shell_quote(value: str | Path) -> str:
    return shlex.quote(path_for_shell(value))


def shell_join(args: Sequence[str | Path]) -> str:
    return " ".join(shell_quote(arg) for arg in args)


def env_prefix_for_shell(env: Mapping[str, str] | None) -> str:
    if not env:
        return ""
    return " ".join(f"{key}={shell_quote(value)}" for key, value in env.items())


def render_command(command: str | Sequence[str | Path], *, env: Mapping[str, str] | None = None) -> str:
    command_text = command if isinstance(command, str) else shell_join(command)
    env_prefix = env_prefix_for_shell(env)
    return f"{env_prefix} {command_text}" if env_prefix else command_text
