"""Command execution helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from .bootstrap_shell import render_command


def run_command(
    command: str | Sequence[str | Path],
    *,
    dry_run: bool,
    env: Mapping[str, str] | None = None,
) -> None:
    if dry_run:
        print(f"DRY-RUN $ {render_command(command, env=env)}")
        return
    merged_env = None
    if env:
        merged_env = os.environ.copy()
        merged_env.update(env)
    if isinstance(command, str):
        subprocess.run(command, shell=True, check=True, env=merged_env)
    else:
        subprocess.run([str(part) for part in command], check=True, env=merged_env)
