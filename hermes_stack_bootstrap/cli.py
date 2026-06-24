"""Command-line entrypoint and compatibility exports for hermes-stack-bootstrap."""

from __future__ import annotations

import subprocess
import sys
from typing import Iterable

from . import bootstrap_apply as _apply
from . import bootstrap_option_flow as _option_flow
from . import bootstrap_prompts as _prompts
from . import bootstrap_skill_packs as _skill_packs
from . import bootstrap_wizard as _wizard
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
from .bootstrap_prompts import *
from .bootstrap_runtime import *
from .bootstrap_shell import *
from .bootstrap_skill_packs import *
from .bootstrap_tui import RichPromptTui, TuiDependencyError, create_tui
from .hermes_discovery import discover_hermes_runtime
from .hermes_models import provider_choices
from .provider_setup import fetch_openai_compatible_model_metadata
from .soul_generator import generate_soul_with_hermes

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
    _wizard.create_tui = create_tui
    _prompts.create_tui = create_tui
    _wizard.detect_base_home = detect_base_home
    _wizard.discover_hermes_runtime = discover_hermes_runtime
    _wizard.provider_choices = provider_choices
    _option_flow.fetch_openai_compatible_model_metadata = fetch_openai_compatible_model_metadata
    _prompts.fetch_openai_compatible_model_metadata = fetch_openai_compatible_model_metadata


def apply_plan(plan, ui=None) -> None:
    _sync_apply_compat_globals()
    return _apply_apply_plan(plan, ui)


def apply_plans(plans, ui=None) -> None:
    _sync_apply_compat_globals()
    return _apply_apply_plans(plans, ui)


def wizard(argv: Iterable[str] | None = None, *, env=None, ui=None):
    _sync_wizard_compat_globals()
    
    # Check for --quick flag first
    if argv is None:
        argv_list = sys.argv[1:]
    else:
        argv_list = list(argv)
    
    if "--quick" in argv_list:
        # Quick install mode: skip wizard, use recommended defaults
        from .wizard_v2_flow import quick_install
        return quick_install(env=env, ui=ui)
    
    # Wizard v2 is the default interactive flow ONLY when called without
    # explicit argv (i.e., user ran the command without any CLI flags).
    # When argv is explicitly provided (even empty list), use legacy wizard
    # for backward compatibility with existing tests and noninteractive CLI usage.
    if argv is not None:
        # Show deprecation warning for legacy wizard usage
        if not any(arg.startswith('-') for arg in argv_list):
            print(
                "⚠️  Legacy wizard is deprecated and will be removed in v1.0.0.\n"
                "    Please use wizard v2 (run without CLI flags) or migrate to\n"
                "    profile-based configuration.\n"
                "    Quick install: bash install.sh --quick\n",
                file=sys.stderr,
            )
        return _wizard.wizard(argv, env=env, ui=ui)
    
    # No explicit argv: check sys.argv for CLI flags
    cli_argv = sys.argv[1:]
    has_flags = any(arg.startswith('-') for arg in cli_argv)
    
    if has_flags:
        return _wizard.wizard(cli_argv, env=env, ui=ui)
    from .wizard_v2_flow import run_wizard_v2
    return run_wizard_v2(env=env, ui=ui)


def main(argv: Iterable[str] | None = None) -> int:
    """Main entry point for hermes-stack-bootstrap CLI.
    
    Supports three modes:
    - Profile management: --profile list|delete|show [name]
    - Quick install: --quick (no wizard, use defaults)
    - Wizard v2: no flags (interactive 9-step wizard)
    - Legacy wizard: any other flags (deprecated)
    """
    # Parse profile management commands
    args = list(argv) if argv is not None else sys.argv[1:]
    
    if args and args[0] == "--profile":
        from .wizard_v2_state import profile_list, profile_delete, profile_show
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
        options = wizard(argv)
        plans = build_plans(options)
        apply_plans(plans)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
