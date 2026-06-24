"""Command-line entrypoint and compatibility exports for hermes-stack-bootstrap."""

from __future__ import annotations

import subprocess
import sys
from typing import Iterable

from . import bootstrap_apply as _apply
from . import bootstrap_option_flow as _option_flow
from . import bootstrap_skill_packs as _skill_packs
from . import wizard_flow as _wizard_flow
from .bootstrap_apply import (
    backup_files,
    backup_soul_file,
    hmx_env_values,
    merge_config_and_env,
    mnemosyne_packages_satisfied,
    mnemosyne_runtime_needs_sudo,
    resolve_soul_overwrite_before_apply,
    run_verification,
)
from .bootstrap_commands import run_command
from .bootstrap_data import *
from .bootstrap_option_flow import *
from .bootstrap_plan import *
from .bootstrap_runtime import *
from .bootstrap_shell import *
from .bootstrap_skill_packs import *
from .hermes_discovery import discover_hermes_runtime
from .hermes_models import provider_choices
from .provider_setup import fetch_openai_compatible_model_metadata
from .soul_generator import generate_soul_with_hermes
from .wizard_flow import cli_help, quick_install, run_wizard_v2 as run_wizard
from .wizard_state import profile_delete, profile_list, profile_show
from .wizard_tui import RichWizardTui as RichPromptTui
from .wizard_tui import TuiDependencyError, create_tui

_apply_install_lcm = _apply.install_lcm
_apply_install_mnemosyne = _apply.install_mnemosyne
_apply_install_progress_tail = _apply.install_progress_tail
_apply_apply_soul_generation = _apply.apply_soul_generation
_apply_apply_plan = _apply.apply_plan
_apply_apply_plans = _apply.apply_plans
_skill_install_skill_pack = _skill_packs.install_skill_pack
_skill_install_optional_skills = _skill_packs.install_optional_skills


def install_lcm(plan) -> None:
    _apply.run_command = run_command
    return _apply_install_lcm(plan)


def install_mnemosyne(plan) -> None:
    _apply.run_command = run_command
    _apply.mnemosyne_packages_satisfied = mnemosyne_packages_satisfied
    _apply.mnemosyne_runtime_needs_sudo = mnemosyne_runtime_needs_sudo
    return _apply_install_mnemosyne(plan)


def install_progress_tail(plan) -> None:
    _apply.run_command = run_command
    return _apply_install_progress_tail(plan)


def install_skill_pack(spec, dest, *, dry_run: bool, gitlab_token: str = "") -> None:
    _skill_packs.run_command = run_command
    _skill_packs.stage_skill_pack = stage_skill_pack
    return _skill_install_skill_pack(spec, dest, dry_run=dry_run, gitlab_token=gitlab_token)


def install_optional_skills(plan) -> None:
    _skill_packs.install_skill_pack = install_skill_pack
    return _skill_install_optional_skills(plan)


def apply_soul_generation(plan, ui=None) -> None:
    _apply.generate_soul_with_hermes = generate_soul_with_hermes
    return _apply_apply_soul_generation(plan, ui)


def _sync_apply_compat_globals() -> None:
    """Keep old `hermes_stack_bootstrap.cli.*` patch points working in tests/users."""
    _apply.install_lcm = install_lcm
    _apply.install_mnemosyne = install_mnemosyne
    _apply.install_progress_tail = install_progress_tail
    _apply.install_optional_skills = install_optional_skills
    _apply.merge_config_and_env = merge_config_and_env
    _apply.run_verification = run_verification
    _apply.apply_soul_generation = apply_soul_generation
    _apply.generate_soul_with_hermes = generate_soul_with_hermes


def _sync_wizard_compat_globals() -> None:
    _wizard_flow.discover_hermes_runtime = discover_hermes_runtime
    _option_flow.fetch_openai_compatible_model_metadata = fetch_openai_compatible_model_metadata


def apply_plan(plan, ui=None) -> None:
    _sync_apply_compat_globals()
    return _apply_apply_plan(plan, ui)


def apply_plans(plans, ui=None) -> None:
    _sync_apply_compat_globals()
    return _apply_apply_plans(plans, ui)


def wizard(argv: Iterable[str] | None = None, *, env=None, ui=None, execute: bool = False):
    _sync_wizard_compat_globals()

    argv_list = sys.argv[1:] if argv is None else list(argv)
    if "--quick" in argv_list:
        return quick_install(env=env, ui=ui)

    return run_wizard(env=env, ui=ui, argv=argv_list, execute=execute)


def main(argv: Iterable[str] | None = None) -> int:
    """Main entry point for hermes-stack-bootstrap CLI.

    Supports three modes:
    - Profile management: --profile list|delete|show [name]
    - Quick install: --quick (no wizard, use defaults)
    - Interactive wizard: all other invocations
    """
    # Parse profile management commands
    args = list(argv) if argv is not None else sys.argv[1:]

    if any(arg in {"--help", "-h"} for arg in args):
        print(cli_help(args), end="")
        return 0

    if args and args[0] == "--profile" and len(args) > 1 and args[1] in {"list", "delete", "show"}:
        if len(args) < 2:
            print("Usage: hermes-stack-bootstrap --profile <list|delete|show> [name]", file=sys.stderr)
            return 1

        cmd = args[1]
        if cmd == "list":
            profiles = profile_list()
            if not profiles:
                print("No saved profiles found.")
            else:
                print("Saved profiles:")
                for name, path in profiles.items():
                    print(f"  - {name} ({path})")
            return 0
        elif cmd == "delete":
            if len(args) < 3:
                print("Usage: hermes-stack-bootstrap --profile delete <name>", file=sys.stderr)
                return 1
            name = args[2]
            if profile_delete(name):
                print(f"✓ Profile '{name}' deleted.")
            else:
                print(f"✗ Profile '{name}' not found.", file=sys.stderr)
                return 1
            return 0
        elif cmd == "show":
            if len(args) < 3:
                print("Usage: hermes-stack-bootstrap --profile show <name>", file=sys.stderr)
                return 1
            name = args[2]
            profile = profile_show(name)
            if profile:
                print(f"Profile: {name}")
                print("-" * 40)
                for key, value in sorted(profile.items()):
                    print(f"{key}: {value}")
            else:
                print(f"✗ Profile '{name}' not found.", file=sys.stderr)
                return 1
            return 0
        else:
            print(f"Unknown profile command: {cmd}", file=sys.stderr)
            print("Available commands: list, delete, show", file=sys.stderr)
            return 1

    try:
        if "--quick" in args:
            options = wizard(args, execute=False)
            plans = build_plans(options)
            apply_plans(plans)
        else:
            wizard(args, execute=True)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
