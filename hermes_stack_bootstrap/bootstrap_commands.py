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
    timeout: float | None = 300,
) -> None:
    if dry_run:
        print(f"DRY-RUN $ {render_command(command, env=env)}")
        return
    merged_env = None
    if env:
        merged_env = os.environ.copy()
        merged_env.update(env)
    try:
        if isinstance(command, str):
            subprocess.run(command, shell=True, check=True, env=merged_env, timeout=timeout)
        else:
            subprocess.run([str(part) for part in command], check=True, env=merged_env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        rendered = render_command(command, env=env)
        print(
            f"Command timed out after {exc.timeout:g} seconds: {rendered}\n"
            "Network installs can occasionally hang. Retry the bootstrap, or skip the step "
            "with the matching --skip flag (for example --skip-lcm, --skip-mnemosyne, "
            "--skip-progress-tail, or optional skill-pack skip flags) and install it manually."
        )
        raise RuntimeError(f"Command timed out after {exc.timeout:g} seconds") from exc
