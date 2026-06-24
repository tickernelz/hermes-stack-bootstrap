"""Apply execution plans."""

from __future__ import annotations

import dataclasses
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .bootstrap_commands import run_command
from .bootstrap_data import LCM_REPO, SENSITIVE_ENV_KEYS, InstallerOptions, InstallPlan
from .bootstrap_option_flow import hashmicro_setup_from_options
from .bootstrap_plan import (
    mnemosyne_pip_package_list,
    print_plan,
    progress_tail_install_command,
    progress_tail_ref_for_plan,
    resolve_progress_tail_ref,
    soul_answers_from_options,
)
from .bootstrap_prompts import prompt_soul_options, prompt_yes_no, require_tui, tui_status
from .bootstrap_runtime import hermes_bin_for_options, runtime_python_for_options, validate_runtime_options
from .bootstrap_shell import render_command
from .bootstrap_skill_packs import install_optional_skills
from .bootstrap_state import save_options_state, state_path_for
from .bootstrap_tui import RichPromptTui
from .bootstrap_utils import atomic_write_text, retry_with_backoff
from .config_merge import build_target_config, read_config, write_config
from .env_template import build_env_values, managed_env_keys, merge_env_text, render_env_block
from .provider_setup import build_hashmicro_env_values, merge_hashmicro_provider_config, secret_env_keys
from .soul_generator import generate_soul_with_hermes


def backup_files(plan: InstallPlan) -> Path | None:
    existing = [path for path in (plan.config_path, plan.env_path) if path.exists()]
    if not existing:
        return None
    backup_dir = plan.target_home / "backups" / ("hermes-stack-bootstrap-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def install_lcm(plan: InstallPlan) -> None:
    if plan.options.skip_lcm:
        return
    lcm_dir = plan.target_home / "plugins" / "hermes-lcm"
    if lcm_dir.exists():
        retry_with_backoff(
            lambda: run_command(
                ["git", "-C", str(lcm_dir), "pull", "--ff-only"], dry_run=plan.options.dry_run, timeout=600
            ),
            label="git pull (hermes-lcm)",
        )
    else:
        lcm_dir.parent.mkdir(parents=True, exist_ok=True)
        retry_with_backoff(
            lambda: run_command(["git", "clone", LCM_REPO, str(lcm_dir)], dry_run=plan.options.dry_run, timeout=600),
            label="git clone (hermes-lcm)",
        )


def mnemosyne_packages_satisfied(hermes_python: Path, packages: Sequence[str]) -> bool:
    """Return True when pip resolver says the requested packages are satisfied."""
    with tempfile.NamedTemporaryFile(suffix=".json") as report:
        try:
            subprocess.run(
                [
                    str(hermes_python),
                    "-m",
                    "pip",
                    "install",
                    "--dry-run",
                    "--quiet",
                    "--report",
                    report.name,
                    *packages,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            data = json.loads(Path(report.name).read_text(encoding="utf-8"))
            return not data.get("install")
        except subprocess.CalledProcessError as exc:
            print(
                f"Warning: pip dry-run failed (exit {exc.returncode}), assuming packages not satisfied",
                file=sys.stderr,
            )
            return False
        except subprocess.TimeoutExpired:
            print("Warning: pip dry-run timed out, assuming packages not satisfied", file=sys.stderr)
            return False
        except json.JSONDecodeError as exc:
            print(f"Warning: could not parse pip report ({exc}), assuming packages not satisfied", file=sys.stderr)
            return False
        except OSError as exc:
            print(f"Warning: pip report read failed ({exc}), assuming packages not satisfied", file=sys.stderr)
            return False
        except ValueError as exc:
            print(f"Warning: invalid pip report ({exc}), assuming packages not satisfied", file=sys.stderr)
            return False


def mnemosyne_runtime_needs_sudo(hermes_python: Path) -> bool:
    """Return True when the Hermes runtime Python writes to non-writable paths."""
    probe = (
        "import json,sysconfig;"
        "paths=[sysconfig.get_paths().get('purelib',''),sysconfig.get_paths().get('platlib',''),sysconfig.get_path('scripts') or ''];"
        "print(json.dumps([p for p in paths if p]))"
    )
    completed = subprocess.run(
        [str(hermes_python), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    paths = json.loads(completed.stdout or "[]")
    return any(path and not os.access(path, os.W_OK) for path in paths)


def install_mnemosyne(plan: InstallPlan) -> None:
    if plan.options.skip_mnemosyne:
        return
    hermes_py = runtime_python_for_options(plan.options)
    packages = mnemosyne_pip_package_list(plan.options.mnemosyne_mode)
    if plan.options.dry_run:
        run_command(
            [str(hermes_py), "-m", "pip", "install", "--upgrade", "--no-cache-dir", *packages],
            dry_run=True,
            timeout=600,
        )
    elif mnemosyne_packages_satisfied(hermes_py, packages):
        print("Mnemosyne packages already installed in Hermes runtime Python. Skipping pip install.")
    else:
        pip_command = [str(hermes_py), "-m", "pip", "install", "--upgrade", "--no-cache-dir", *packages]
        if mnemosyne_runtime_needs_sudo(hermes_py):
            sudo_command = ["sudo", *pip_command]
            if plan.options.yes:
                raise PermissionError(
                    "Hermes runtime venv is not writable. Install missing Mnemosyne packages manually: "
                    f"{render_command(sudo_command)}"
                )
            run_command(["sudo", "-v"], dry_run=False)
            run_command(sudo_command, dry_run=False, timeout=600)
        else:
            run_command(pip_command, dry_run=False, timeout=600)
    run_command(
        [str(hermes_py), "-m", "mnemosyne.install"],
        dry_run=plan.options.dry_run,
        env={"HERMES_HOME": str(plan.target_home)},
    )


def install_progress_tail(plan: InstallPlan) -> None:
    if plan.options.skip_progress_tail:
        return
    ref = progress_tail_ref_for_plan(plan.options.progress_tail_ref)
    if not plan.options.dry_run:
        ref = resolve_progress_tail_ref(plan.options.progress_tail_ref)
        if plan.options.progress_tail_ref == "latest":
            print(f"Resolved hermes-progress-tail latest release: {ref}")
    command = progress_tail_install_command(
        base_home=plan.options.base_home.expanduser(),
        profile=plan.options.profile,
        ref=ref,
    )
    run_command(["bash", "-lc", command], dry_run=plan.options.dry_run)


def hmx_env_values(options: InstallerOptions) -> dict[str, str]:
    if options.install_hmx_knowledge and options.hmx_gitlab_token.strip():
        return {"GITLAB_TOKEN": options.hmx_gitlab_token.strip()}
    return {}


def merge_config_and_env(plan: InstallPlan) -> None:
    if plan.options.skip_config_env:
        print("Config/.env merge skipped for selected install mode.")
        return
    env_values = build_env_values(
        home=str(plan.target_home),
        summary_model=plan.options.summary_model,
        lcm_summary_model=plan.options.lcm_summary_model,
        lcm_expansion_model=plan.options.lcm_expansion_model,
        mnemosyne_mode=plan.options.mnemosyne_mode,
        mnemosyne_host_llm_provider=plan.options.mnemosyne_host_llm_provider,
        mnemosyne_host_llm_model=plan.options.mnemosyne_host_llm_model,
        mnemosyne_embedding_api_url=plan.options.mnemosyne_embedding_api_url,
        mnemosyne_embedding_api_key=plan.options.mnemosyne_embedding_api_key,
        mnemosyne_embedding_model=plan.options.mnemosyne_embedding_model,
        mnemosyne_embedding_dim=plan.options.mnemosyne_embedding_dim,
    )

    if plan.options.dry_run:
        current_config = read_config(plan.config_path) if plan.config_path.exists() else {}
        merged_config = build_target_config(current_config)
        merged_config = merge_hashmicro_provider_config(merged_config, hashmicro_setup_from_options(plan.options))
        print("\n--- config.yaml preview ---")
        try:
            import yaml  # type: ignore

            before = yaml.safe_dump(current_config, sort_keys=False, allow_unicode=True).splitlines()
            after = yaml.safe_dump(merged_config, sort_keys=False, allow_unicode=True).splitlines()
            print("\n".join(difflib.unified_diff(before, after, fromfile="current", tofile="target", lineterm="")))
        except Exception:
            print(merged_config)
        print("\n--- .env additions/updates preview ---")
        preview_env_values = {
            **env_values,
            **hmx_env_values(plan.options),
            **build_hashmicro_env_values(hashmicro_setup_from_options(plan.options)),
        }
        print(
            render_env_block(preview_env_values, redact_keys=SENSITIVE_ENV_KEYS | secret_env_keys(preview_env_values)),
            end="",
        )
        return

    plan.target_home.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_files(plan)
    if backup_dir:
        print(f"Backup written: {backup_dir}")

    current_config = read_config(plan.config_path)
    target_config = build_target_config(current_config)
    target_config = merge_hashmicro_provider_config(target_config, hashmicro_setup_from_options(plan.options))
    write_config(plan.config_path, target_config)

    existing_env = plan.env_path.read_text() if plan.env_path.exists() else ""
    env_values = {
        **env_values,
        **hmx_env_values(plan.options),
        **build_hashmicro_env_values(hashmicro_setup_from_options(plan.options)),
    }
    atomic_write_text(
        plan.env_path, merge_env_text(existing_env, env_values, managed_keys=managed_env_keys() | set(env_values))
    )


def backup_soul_file(soul_path: Path) -> Path:
    backup_dir = soul_path.parent / "backups" / ("hermes-stack-bootstrap-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(soul_path, backup_dir / soul_path.name)
    return backup_dir


def resolve_soul_overwrite_before_apply(plan: InstallPlan, ui: RichPromptTui | None = None) -> InstallPlan:
    if not plan.options.generate_soul or plan.options.dry_run:
        return plan
    soul_path = plan.target_home / "SOUL.md"
    if not soul_path.exists() or plan.options.soul_overwrite:
        return plan
    if plan.options.yes:
        raise ValueError(f"SOUL.md already exists at {soul_path}; pass --soul-overwrite to replace it")
    if not prompt_yes_no(f"SOUL.md already exists at {soul_path}. Overwrite after backup?", False, ui):
        print("SOUL.md generation skipped.")
        return dataclasses.replace(plan, options=dataclasses.replace(plan.options, generate_soul=False))
    return dataclasses.replace(plan, options=dataclasses.replace(plan.options, soul_overwrite=True))


def apply_soul_generation(plan: InstallPlan, ui: RichPromptTui | None = None) -> None:
    if not plan.options.generate_soul:
        return
    soul_path = plan.target_home / "SOUL.md"
    if plan.options.dry_run:
        print(f"DRY-RUN would generate SOUL.md via Hermes backend: {soul_path}")
        return

    if soul_path.exists() and not plan.options.soul_overwrite:
        raise ValueError(f"SOUL.md already exists at {soul_path}; pass --soul-overwrite to replace it")

    with tui_status(ui, "Generating SOUL.md with Hermes AI backend..."):
        generated = generate_soul_with_hermes(
            base_home=plan.options.base_home.expanduser(),
            profile=plan.options.profile,
            provider=plan.options.soul_provider,
            model=plan.options.soul_model,
            answers=soul_answers_from_options(plan.options),
            hermes_bin=hermes_bin_for_options(plan.options),
        )

    plan.target_home.mkdir(parents=True, exist_ok=True)
    if soul_path.exists():
        backup_dir = backup_soul_file(soul_path)
        print(f"SOUL.md backup written: {backup_dir}")
    atomic_write_text(soul_path, generated.rstrip() + "\n")
    print(f"SOUL.md written: {soul_path}")


def run_verification(plan: InstallPlan) -> None:
    if plan.options.skip_verify:
        print("Verification skipped for selected install mode.")
        return
    if plan.options.dry_run:
        print("DRY-RUN verification skipped")
        return
    hermes_bin = hermes_bin_for_options(plan.options)
    commands: list[list[str]] = [[hermes_bin, "plugins", "list", "--plain", "--no-bundled"]]
    if not plan.options.skip_mnemosyne:
        commands = [
            [hermes_bin, "memory", "status"],
            [hermes_bin, "mnemosyne", "stats"],
            [hermes_bin, "plugins", "list", "--plain", "--no-bundled"],
        ]
    if plan.options.profile != "default":
        commands = [[hermes_bin, "-p", plan.options.profile, "plugins", "list", "--plain", "--no-bundled"]]
        if not plan.options.skip_mnemosyne:
            commands = [
                [hermes_bin, "-p", plan.options.profile, "memory", "status"],
                [hermes_bin, "-p", plan.options.profile, "mnemosyne", "stats"],
                [hermes_bin, "-p", plan.options.profile, "plugins", "list", "--plain", "--no-bundled"],
            ]
    for command in commands:
        run_command(command, dry_run=False)


def apply_plan(plan: InstallPlan, ui: RichPromptTui | None = None) -> None:
    validate_runtime_options(plan.options)
    print_plan(plan)
    if not plan.options.yes:
        ui = require_tui(ui)
        if not prompt_yes_no("Apply this plan?", False, ui):
            print("Aborted.")
            return
    if not plan.options.dry_run:
        save_options_state(state_path_for(plan.target_home), plan.options)
    install_lcm(plan)
    install_mnemosyne(plan)
    install_progress_tail(plan)
    install_optional_skills(plan)
    merge_config_and_env(plan)
    run_verification(plan)
    if plan.options.generate_soul:
        soul_options = plan.options
        if not soul_options.soul_agent_name.strip() or not soul_options.soul_user_name.strip():
            soul_options = prompt_soul_options(soul_options, ui)
        soul_plan = dataclasses.replace(plan, options=soul_options)
        soul_plan = resolve_soul_overwrite_before_apply(soul_plan, ui)
        apply_soul_generation(soul_plan, ui)
    elif not plan.options.yes:
        ui = require_tui(ui)
        if prompt_yes_no("Generate SOUL.md with Hermes AI backend now?", False, ui):
            soul_options = prompt_soul_options(plan.options, ui)
            soul_plan = dataclasses.replace(plan, options=soul_options)
            soul_plan = resolve_soul_overwrite_before_apply(soul_plan, ui)
            apply_soul_generation(soul_plan, ui)
    print("\nDone. Restart Hermes manually after applying changes: /restart")


def apply_plans(plans: tuple[InstallPlan, ...], ui: RichPromptTui | None = None) -> None:
    if len(plans) == 1:
        apply_plan(plans[0], ui)
        return

    print(f"Applying {len(plans)} profile plans sequentially: {', '.join(plan.options.profile for plan in plans)}")
    for index, plan in enumerate(plans, start=1):
        print(f"\n### Profile {index}/{len(plans)}: {plan.options.profile}")
        apply_plan(plan, ui)
