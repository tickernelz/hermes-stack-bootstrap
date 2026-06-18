"""Command-line wizard and execution plan for hermes-stack-bootstrap."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import getpass
import json
import os
import shutil
import shlex
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .config_merge import build_target_config, read_config, write_config
from .env_template import (
    DEFAULT_LCM_SUMMARY_MODEL,
    MNEMOSYNE_MODES,
    build_env_values,
    managed_env_keys,
    merge_env_text,
    render_env_block,
)
from .hermes_discovery import HermesRuntime, discover_hermes_runtime
from .soul_generator import SoulAnswers, generate_soul_with_hermes


LCM_REPO = "https://github.com/stephenschoettler/hermes-lcm"
PROGRESS_TAIL_REPO = "tickernelz/hermes-progress-tail"
PROGRESS_TAIL_REF = os.environ.get("HERMES_STACK_PROGRESS_TAIL_REF", "latest")
LATEST_PROGRESS_TAIL_TAG_PLACEHOLDER = "${LATEST_HERMES_PROGRESS_TAIL_TAG}"
SUPERPOWERS_REPO = "https://github.com/obra/superpowers"
HMX_KNOWLEDGE_REPO = os.environ.get(
    "HMX_KNOWLEDGE_GIT_URL",
    "git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git",
)
IMPECCABLE_REPO = "https://github.com/pbakaus/impeccable"
SENSITIVE_ENV_KEYS = {"MNEMOSYNE_EMBEDDING_API_KEY"}


@dataclass(frozen=True)
class InstallerOptions:
    base_home: Path
    profile: str
    hermes_bin: str = "hermes"
    hermes_bin_source: str = "default"
    hermes_python: Path | None = None
    hermes_python_source: str = "profile-local default"
    yes: bool = False
    dry_run: bool = False
    summary_model: str = ""
    lcm_summary_model: str = DEFAULT_LCM_SUMMARY_MODEL
    lcm_expansion_model: str = ""
    mnemosyne_mode: str = "full-local"
    mnemosyne_host_llm_provider: str = ""
    mnemosyne_host_llm_model: str = ""
    mnemosyne_embedding_api_url: str = ""
    mnemosyne_embedding_api_key: str = ""
    mnemosyne_embedding_model: str = ""
    mnemosyne_embedding_dim: str = ""
    skip_lcm: bool = False
    skip_mnemosyne: bool = False
    skip_progress_tail: bool = False
    progress_tail_ref: str = PROGRESS_TAIL_REF
    install_superpowers: bool = False
    install_hmx_knowledge: bool = False
    install_impeccable: bool = False
    hmx_knowledge_url: str = HMX_KNOWLEDGE_REPO
    generate_soul: bool = False
    soul_agent_name: str = ""
    soul_user_name: str = ""
    soul_role: str = ""
    soul_behavior: str = ""
    soul_communication: str = ""
    soul_focus: str = ""
    soul_avoid: str = ""
    soul_language: str = ""
    soul_provider: str = ""
    soul_model: str = ""
    soul_overwrite: bool = False


@dataclass(frozen=True)
class PlanStep:
    title: str
    command: str = ""
    notes: str = ""


@dataclass(frozen=True)
class InstallPlan:
    options: InstallerOptions
    target_home: Path
    config_path: Path
    env_path: Path
    steps: tuple[PlanStep, ...]


def shell_quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def target_home_for(base_home: Path, profile: str) -> Path:
    if profile == "default":
        return base_home
    return base_home / "profiles" / profile


def parse_profiles(raw_profiles: Iterable[str] | str | None) -> tuple[str, ...]:
    """Normalize CLI profile values from repeated/comma-separated flags."""
    if raw_profiles is None:
        return ("default",)
    if isinstance(raw_profiles, str):
        raw_items: Iterable[str] = (raw_profiles,)
    else:
        raw_items = raw_profiles

    profiles: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        for part in str(raw_item).split(","):
            profile = part.strip() or "default"
            if profile not in seen:
                profiles.append(profile)
                seen.add(profile)
    return tuple(profiles or ["default"])


def hermes_python_for(base_home: Path) -> Path:
    return base_home / "hermes-agent" / "venv" / "bin" / "python"


def runtime_python_for_options(options: InstallerOptions) -> Path:
    return options.hermes_python or hermes_python_for(options.base_home.expanduser())


def hermes_bin_for_options(options: InstallerOptions) -> str:
    return options.hermes_bin or "hermes"


def runtime_missing_message(options: InstallerOptions) -> str:
    return "\n".join(
        [
            "Could not find the Python environment that runs Hermes, so Mnemosyne cannot be installed safely.",
            f"Detected Hermes CLI: {hermes_bin_for_options(options)} ({options.hermes_bin_source})",
            f"Detected profile base: {options.base_home.expanduser()}",
            "",
            "Fix options:",
            "  1. Re-run with --hermes-python /path/to/python",
            "  2. Or set HERMES_STACK_PYTHON=/path/to/python",
            "  3. Or use --skip-mnemosyne if Mnemosyne is already installed",
            "",
            "Tip: if `which hermes` is a small shell wrapper, run `head -20 $(which hermes)` and use the Python from the venv it execs.",
        ]
    )


def validate_runtime_options(options: InstallerOptions) -> None:
    if options.skip_mnemosyne:
        return
    if options.hermes_python is None:
        raise ValueError(runtime_missing_message(options))


def base_home_from_config_path(config_path: str | Path) -> Path:
    """Infer Hermes base home from `hermes config path` output."""
    path = Path(str(config_path).strip()).expanduser()
    if path.name != "config.yaml":
        return path.parent
    parts = path.parts
    if len(parts) >= 3 and parts[-3] == "profiles":
        return Path(*parts[:-3])
    return path.parent


def detect_base_home(hermes_bin: str | None = None) -> Path:
    """Best-effort Hermes base path detection with safe fallbacks."""
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(env_home).expanduser()

    selected_hermes_bin = hermes_bin or os.environ.get("HERMES_BIN") or shutil.which("hermes")
    if selected_hermes_bin:
        try:
            completed = subprocess.run(
                [selected_hermes_bin, "config", "path"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = completed.stdout.strip().splitlines()
            if output:
                return base_home_from_config_path(output[-1])
        except Exception:
            pass

    default_home = Path("~/.hermes").expanduser()
    if (default_home / "config.yaml").exists() or (default_home / "hermes-agent").exists():
        return default_home
    return default_home


def progress_tail_ref_for_plan(ref: str) -> str:
    return LATEST_PROGRESS_TAIL_TAG_PLACEHOLDER if ref == "latest" else ref


def progress_tail_install_url(ref: str) -> str:
    return f"https://raw.githubusercontent.com/{PROGRESS_TAIL_REPO}/{ref}/install.sh"


def resolve_progress_tail_ref(ref: str) -> str:
    if ref != "latest":
        return ref
    url = f"https://api.github.com/repos/{PROGRESS_TAIL_REPO}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed GitHub API URL
        data = json.loads(response.read().decode("utf-8"))
    tag_name = data.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        raise RuntimeError(f"Could not resolve latest release tag for {PROGRESS_TAIL_REPO}")
    return tag_name


def progress_tail_install_command(*, base_home: Path, profile: str, ref: str) -> str:
    env_parts = ["HPT_INTERACTIVE=0", f"HERMES_HOME={base_home}"]
    if profile != "default":
        env_parts.append(f"HPT_PROFILES={profile}")
    return f"curl -fsSL {progress_tail_install_url(ref)} | env {' '.join(env_parts)} bash"


def progress_tail_plan_command(*, base_home: Path, profile: str, ref: str) -> str:
    return progress_tail_install_command(
        base_home=base_home,
        profile=profile,
        ref=progress_tail_ref_for_plan(ref),
    )


def skill_vendor_dir(target_home: Path, name: str) -> Path:
    return target_home / "skills" / "vendor" / name


def skill_repo_clone_command(repo_url: str, dest: Path) -> str:
    return f"git clone --depth=1 {repo_url} {dest}"


def skill_repo_update_command(dest: Path) -> str:
    return f"git -C {dest} pull --ff-only"


def mnemosyne_pip_packages(mode: str) -> str:
    normalized = mode.strip().lower() or "full-local"
    if normalized == "full-local":
        return "'mnemosyne-memory[all]' sqlite-vec"
    if normalized == "hybrid":
        return "'mnemosyne-memory[embeddings]' sqlite-vec"
    if normalized == "full-online":
        return "mnemosyne-memory sqlite-vec numpy"
    raise ValueError(f"Unknown Mnemosyne mode: {mode}")


def soul_answers_from_options(options: InstallerOptions) -> SoulAnswers:
    return SoulAnswers(
        agent_name=options.soul_agent_name,
        user_name=options.soul_user_name,
        role=options.soul_role,
        behavior=options.soul_behavior,
        communication=options.soul_communication,
        focus=options.soul_focus,
        avoid=options.soul_avoid,
        language=options.soul_language,
    )


def soul_generation_command_preview(options: InstallerOptions) -> str:
    parts = [f"HERMES_HOME={shell_quote(options.base_home.expanduser())}", shell_quote(hermes_bin_for_options(options))]
    if options.profile != "default":
        parts.extend(["-p", options.profile])
    parts.extend(["chat", "--quiet"])
    if options.soul_provider:
        parts.extend(["--provider", options.soul_provider])
    if options.soul_model:
        parts.extend(["--model", options.soul_model])
    parts.extend(["-q", "'<generated SOUL.md prompt>'"])
    return " ".join(parts)


def build_plan(options: InstallerOptions) -> InstallPlan:
    base_home = options.base_home.expanduser()
    target_home = target_home_for(base_home, options.profile)
    hermes_py = runtime_python_for_options(options)
    hermes_py_cmd = shell_quote(hermes_py)
    hermes_bin = hermes_bin_for_options(options)
    hermes_bin_cmd = shell_quote(hermes_bin)
    steps: list[PlanStep] = []

    if not options.skip_lcm:
        lcm_dir = target_home / "plugins" / "hermes-lcm"
        steps.append(
            PlanStep(
                "Install hermes-lcm from upstream README",
                f"git clone {LCM_REPO} {lcm_dir}",
                "If the directory already exists, the installer runs git pull --ff-only instead.",
            )
        )

    if not options.skip_mnemosyne:
        steps.extend(
            [
                PlanStep(
                    f"Install Mnemosyne package for {options.mnemosyne_mode} mode into Hermes runtime venv",
                    f"{hermes_py_cmd} -m pip install --upgrade --no-cache-dir {mnemosyne_pip_packages(options.mnemosyne_mode)}",
                    "full-local uses local embeddings + local GGUF LLM; hybrid uses local embeddings + Hermes host LLM; full-online uses user-supplied embedding API settings and routes LLM via Hermes.",
                ),
                PlanStep(
                    "Register Mnemosyne as Hermes memory provider",
                    f"HERMES_HOME={shell_quote(target_home)} {hermes_py_cmd} -m mnemosyne.install",
                    "The installer also merges memory.provider=mnemosyne and plugins.enabled+=mnemosyne.",
                ),
            ]
        )

    if not options.skip_progress_tail:
        steps.append(
            PlanStep(
                "Install hermes-progress-tail from upstream README",
                progress_tail_plan_command(
                    base_home=base_home,
                    profile=options.profile,
                    ref=options.progress_tail_ref,
                ),
                "The bootstrapper resolves 'latest' to the current GitHub release tag at install time; upstream installer owns progress_tail config merging.",
            )
        )

    if options.install_superpowers:
        dest = skill_vendor_dir(target_home, "obra-superpowers")
        steps.append(
            PlanStep(
                "Optional: install Obra Superpowers skills",
                skill_repo_clone_command(SUPERPOWERS_REPO, dest),
                "Installs the public Superpowers skill pack under skills/vendor/ so Hermes can discover its SKILL.md files.",
            )
        )

    if options.install_hmx_knowledge:
        dest = skill_vendor_dir(target_home, "hmx-knowledge")
        steps.append(
            PlanStep(
                "Optional: install HMX knowledge skills",
                skill_repo_clone_command(options.hmx_knowledge_url, dest),
                "Private GitLab repo; use SSH agent or preconfigured HTTPS/token credentials. The installer never stores tokens.",
            )
        )

    if options.install_impeccable:
        dest = skill_vendor_dir(target_home, "impeccable")
        steps.append(
            PlanStep(
                "Optional: install Impeccable design skill",
                skill_repo_clone_command(IMPECCABLE_REPO, dest),
                "Installs the public Impeccable skill repo under skills/vendor/.",
            )
        )

    verify_command = f"{hermes_bin_cmd} memory status && {hermes_bin_cmd} mnemosyne stats && {hermes_bin_cmd} plugins list --plain --no-bundled"
    if options.profile != "default":
        verify_command = (
            f"{hermes_bin_cmd} -p {options.profile} memory status && "
            f"{hermes_bin_cmd} -p {options.profile} mnemosyne stats && "
            f"{hermes_bin_cmd} -p {options.profile} plugins list --plain --no-bundled"
        )

    final_steps = [
        PlanStep(
            "Merge config.yaml safely",
            notes="Enable hermes-lcm + mnemosyne, set context.engine=lcm, disable built-in file memory.",
        ),
        PlanStep(
            "Merge .env values",
            notes="Write LCM tuning, selected Mnemosyne mode defaults, and any embedding API values explicitly supplied during install.",
        ),
    ]
    if options.generate_soul:
        final_steps.append(
            PlanStep(
                "Generate SOUL.md with Hermes AI backend",
                soul_generation_command_preview(options),
                f"Writes {target_home / 'SOUL.md'}; existing files require overwrite approval and are backed up first.",
            )
        )
    final_steps.append(
        PlanStep(
            "Verify",
            verify_command,
            "Restart Hermes manually after applying changes, then run these checks.",
        )
    )
    steps.extend(final_steps)

    return InstallPlan(
        options=options,
        target_home=target_home,
        config_path=target_home / "config.yaml",
        env_path=target_home / ".env",
        steps=tuple(steps),
    )


def build_plans(options: InstallerOptions) -> tuple[InstallPlan, ...]:
    """Build one profile-scoped plan per requested profile."""
    return tuple(
        build_plan(dataclasses.replace(options, profile=profile))
        for profile in parse_profiles(options.profile)
    )


def print_plan(plan: InstallPlan) -> None:
    print("\nHermes Stack Bootstrap plan")
    print("=" * 28)
    print(f"Target profile : {plan.options.profile}")
    print(f"Hermes profile base : {plan.options.base_home.expanduser()}")
    print(f"Hermes CLI          : {hermes_bin_for_options(plan.options)} ({plan.options.hermes_bin_source})")
    hermes_py = plan.options.hermes_python
    hermes_py_display = str(hermes_py) if hermes_py is not None else "not found"
    print(f"Hermes Python       : {hermes_py_display} ({plan.options.hermes_python_source})")
    print(f"Target home    : {plan.target_home}")
    print(f"Config path    : {plan.config_path}")
    print(f"Env path       : {plan.env_path}")
    print(f"Dry run        : {plan.options.dry_run}")
    print(f"Mnemosyne mode : {plan.options.mnemosyne_mode}")
    if plan.options.lcm_summary_model:
        print(f"LCM summary    : {plan.options.lcm_summary_model}")
    else:
        print("LCM summary    : Hermes auxiliary.compression")
    if plan.options.lcm_expansion_model:
        print(f"LCM expansion  : {plan.options.lcm_expansion_model}")
    else:
        print("LCM expansion  : summary model / Hermes auxiliary")
    for index, step in enumerate(plan.steps, start=1):
        print(f"\n{index}. {step.title}")
        if step.command:
            print(f"   $ {step.command}")
        if step.notes:
            print(f"   {step.notes}")


def run_command(command: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN $ {command}")
        return
    subprocess.run(command, shell=True, check=True)


def backup_files(plan: InstallPlan) -> Path | None:
    existing = [path for path in (plan.config_path, plan.env_path) if path.exists()]
    if not existing:
        return None
    backup_dir = plan.target_home / "backups" / (
        "hermes-stack-bootstrap-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def install_lcm(plan: InstallPlan) -> None:
    if plan.options.skip_lcm:
        return
    lcm_dir = plan.target_home / "plugins" / "hermes-lcm"
    if lcm_dir.exists():
        run_command(f"git -C {lcm_dir} pull --ff-only", dry_run=plan.options.dry_run)
    else:
        lcm_dir.parent.mkdir(parents=True, exist_ok=True)
        run_command(f"git clone {LCM_REPO} {lcm_dir}", dry_run=plan.options.dry_run)


def install_mnemosyne(plan: InstallPlan) -> None:
    if plan.options.skip_mnemosyne:
        return
    hermes_py = runtime_python_for_options(plan.options)
    hermes_py_cmd = shell_quote(hermes_py)
    run_command(
        f"{hermes_py_cmd} -m pip install --upgrade --no-cache-dir {mnemosyne_pip_packages(plan.options.mnemosyne_mode)}",
        dry_run=plan.options.dry_run,
    )
    run_command(
        f"HERMES_HOME={shell_quote(plan.target_home)} {hermes_py_cmd} -m mnemosyne.install",
        dry_run=plan.options.dry_run,
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
    run_command(command, dry_run=plan.options.dry_run)


def install_skill_repo(repo_url: str, dest: Path, *, dry_run: bool) -> None:
    if dest.exists():
        run_command(skill_repo_update_command(dest), dry_run=dry_run)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_command(skill_repo_clone_command(repo_url, dest), dry_run=dry_run)


def install_optional_skills(plan: InstallPlan) -> None:
    if plan.options.install_superpowers:
        install_skill_repo(
            SUPERPOWERS_REPO,
            skill_vendor_dir(plan.target_home, "obra-superpowers"),
            dry_run=plan.options.dry_run,
        )
    if plan.options.install_hmx_knowledge:
        install_skill_repo(
            plan.options.hmx_knowledge_url,
            skill_vendor_dir(plan.target_home, "hmx-knowledge"),
            dry_run=plan.options.dry_run,
        )
    if plan.options.install_impeccable:
        install_skill_repo(
            IMPECCABLE_REPO,
            skill_vendor_dir(plan.target_home, "impeccable"),
            dry_run=plan.options.dry_run,
        )


def merge_config_and_env(plan: InstallPlan) -> None:
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
        print("\n--- config.yaml preview ---")
        try:
            import yaml  # type: ignore

            before = yaml.safe_dump(current_config, sort_keys=False, allow_unicode=True).splitlines()
            after = yaml.safe_dump(merged_config, sort_keys=False, allow_unicode=True).splitlines()
            print("\n".join(difflib.unified_diff(before, after, fromfile="current", tofile="target", lineterm="")))
        except Exception:
            print(merged_config)
        print("\n--- .env additions/updates preview ---")
        print(render_env_block(env_values, redact_keys=SENSITIVE_ENV_KEYS), end="")
        return

    plan.target_home.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_files(plan)
    if backup_dir:
        print(f"Backup written: {backup_dir}")

    current_config = read_config(plan.config_path)
    write_config(plan.config_path, build_target_config(current_config))

    existing_env = plan.env_path.read_text() if plan.env_path.exists() else ""
    plan.env_path.write_text(merge_env_text(existing_env, env_values, managed_keys=managed_env_keys()))


def backup_soul_file(soul_path: Path) -> Path:
    backup_dir = soul_path.parent / "backups" / (
        "hermes-stack-bootstrap-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(soul_path, backup_dir / soul_path.name)
    return backup_dir


def resolve_soul_overwrite_before_apply(plan: InstallPlan) -> InstallPlan:
    if not plan.options.generate_soul or plan.options.dry_run:
        return plan
    soul_path = plan.target_home / "SOUL.md"
    if not soul_path.exists() or plan.options.soul_overwrite:
        return plan
    if plan.options.yes:
        raise ValueError(f"SOUL.md already exists at {soul_path}; pass --soul-overwrite to replace it")
    answer = input(f"SOUL.md already exists at {soul_path}. Overwrite after backup? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("SOUL.md generation skipped.")
        return dataclasses.replace(plan, options=dataclasses.replace(plan.options, generate_soul=False))
    return dataclasses.replace(plan, options=dataclasses.replace(plan.options, soul_overwrite=True))


def apply_soul_generation(plan: InstallPlan) -> None:
    if not plan.options.generate_soul:
        return
    soul_path = plan.target_home / "SOUL.md"
    if plan.options.dry_run:
        print(f"DRY-RUN would generate SOUL.md via Hermes backend: {soul_path}")
        return

    if soul_path.exists() and not plan.options.soul_overwrite:
        raise ValueError(f"SOUL.md already exists at {soul_path}; pass --soul-overwrite to replace it")

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
    soul_path.write_text(generated.rstrip() + "\n", encoding="utf-8")
    print(f"SOUL.md written: {soul_path}")


def run_verification(plan: InstallPlan) -> None:
    if plan.options.dry_run:
        print("DRY-RUN verification skipped")
        return
    hermes_bin = shell_quote(hermes_bin_for_options(plan.options))
    commands = [
        f"{hermes_bin} memory status",
        f"{hermes_bin} mnemosyne stats",
        f"{hermes_bin} plugins list --plain --no-bundled",
    ]
    if plan.options.profile != "default":
        commands = [
            f"{hermes_bin} -p {plan.options.profile} memory status",
            f"{hermes_bin} -p {plan.options.profile} mnemosyne stats",
            f"{hermes_bin} -p {plan.options.profile} plugins list --plain --no-bundled",
        ]
    for command in commands:
        run_command(command, dry_run=False)


def apply_plan(plan: InstallPlan) -> None:
    validate_runtime_options(plan.options)
    print_plan(plan)
    if not plan.options.yes:
        answer = input("\nApply this plan? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return
    plan = resolve_soul_overwrite_before_apply(plan)
    install_lcm(plan)
    install_mnemosyne(plan)
    install_progress_tail(plan)
    install_optional_skills(plan)
    merge_config_and_env(plan)
    apply_soul_generation(plan)
    run_verification(plan)
    print("\nDone. Restart Hermes manually after applying changes: /restart")


def apply_plans(plans: tuple[InstallPlan, ...]) -> None:
    if len(plans) == 1:
        apply_plan(plans[0])
        return

    print(f"Applying {len(plans)} profile plans sequentially: {', '.join(plan.options.profile for plan in plans)}")
    for index, plan in enumerate(plans, start=1):
        print(f"\n### Profile {index}/{len(plans)}: {plan.options.profile}")
        apply_plan(plan)


def prompt_default(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def _env_get(env: os._Environ[str] | dict[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    return value if value is not None else default


def validate_embedding_options(
    *,
    mode: str,
    api_url: str,
    api_key: str,
    model: str,
    dim: str,
) -> None:
    supplied = [api_url, api_key, model, dim]
    if any(supplied) and mode != "full-online":
        raise ValueError("Mnemosyne embedding API settings require --mnemosyne-mode full-online")
    if mode == "full-online" and any(supplied):
        if not api_url:
            raise ValueError("full-online embedding API config requires --mnemosyne-embedding-api-url")
        if not model:
            raise ValueError("full-online embedding API config requires --mnemosyne-embedding-model")
        if not dim:
            raise ValueError("full-online embedding API config requires --mnemosyne-embedding-dim")


def apply_full_online_embedding_env_defaults(args: argparse.Namespace, env: os._Environ[str] | dict[str, str]) -> None:
    if args.mnemosyne_mode != "full-online":
        return
    if not args.mnemosyne_embedding_api_url:
        args.mnemosyne_embedding_api_url = _env_get(env, "MNEMOSYNE_EMBEDDING_API_URL", "")
    if not args.mnemosyne_embedding_api_key:
        args.mnemosyne_embedding_api_key = _env_get(env, "MNEMOSYNE_EMBEDDING_API_KEY", "")
    if not args.mnemosyne_embedding_model:
        args.mnemosyne_embedding_model = _env_get(env, "MNEMOSYNE_EMBEDDING_MODEL", "")
    if not args.mnemosyne_embedding_dim:
        args.mnemosyne_embedding_dim = _env_get(env, "MNEMOSYNE_EMBEDDING_DIM", "")


def validate_soul_options(args: argparse.Namespace) -> None:
    if not args.generate_soul:
        return
    required = {
        "soul_agent_name": "--soul-agent-name",
        "soul_user_name": "--soul-user-name",
        "soul_role": "--soul-role",
        "soul_behavior": "--soul-behavior",
        "soul_communication": "--soul-communication",
        "soul_focus": "--soul-focus",
        "soul_avoid": "--soul-avoid",
        "soul_language": "--soul-language",
    }
    for attr, flag in required.items():
        if not getattr(args, attr, "").strip():
            raise ValueError(f"--generate-soul requires {flag}")


def prompt_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{suffix}] ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def prompt_missing_runtime_python(runtime: HermesRuntime) -> tuple[HermesRuntime, bool]:
    print("\nHermes runtime Python was not found, so Mnemosyne cannot be installed safely yet.")
    print(f"Detected Hermes CLI: {runtime.hermes_bin or 'not found'} ({runtime.hermes_bin_source})")
    print("Enter the Python path used by Hermes, or type 's' to skip Mnemosyne for this run, or 'q' to abort.")
    while True:
        answer = input("Hermes runtime Python path [s]: ").strip()
        if not answer or answer.lower() in {"s", "skip"}:
            return runtime, True
        if answer.lower() in {"q", "quit", "abort"}:
            raise ValueError("Aborted: Hermes runtime Python was not found")
        candidate = Path(answer).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return dataclasses.replace(runtime, hermes_python=candidate, hermes_python_source="manual prompt"), False
        print(f"Not executable: {candidate}")
        print("Try a path like /path/to/hermes-agent/venv/bin/python, or type 's' to skip Mnemosyne.")


def prompt_soul_answers(args: argparse.Namespace) -> None:
    args.soul_agent_name = prompt_default("Agent name", args.soul_agent_name or "Hermes")
    args.soul_user_name = prompt_default("User name", args.soul_user_name)
    args.soul_role = prompt_default("Agent role", args.soul_role or "generalist assistant")
    args.soul_behavior = prompt_default("Behavior / personality", args.soul_behavior)
    args.soul_communication = prompt_default("Communication style", args.soul_communication)
    args.soul_focus = prompt_default("Main focus", args.soul_focus)
    args.soul_avoid = prompt_default("Things to avoid", args.soul_avoid)
    args.soul_language = prompt_default("Default language", args.soul_language or "match user language")
    args.soul_provider = prompt_default(
        "SOUL generation provider override (empty = Hermes default)", args.soul_provider
    )
    args.soul_model = prompt_default("SOUL generation model override (empty = Hermes default)", args.soul_model)


def wizard(argv: Iterable[str] | None = None, *, env: os._Environ[str] | dict[str, str] | None = None) -> InstallerOptions:
    runtime_env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Bootstrap Hermes LCM + Mnemosyne + progress-tail")
    parser.add_argument("--home", default=None)
    parser.add_argument(
        "--hermes-bin",
        default=_env_get(runtime_env, "HERMES_BIN", ""),
        help="Hermes CLI executable. Defaults to PATH/discovery; env: HERMES_BIN.",
    )
    parser.add_argument(
        "--hermes-python",
        default=_env_get(runtime_env, "HERMES_STACK_PYTHON", ""),
        help="Python executable for the Hermes runtime venv. Defaults to discovery; env: HERMES_STACK_PYTHON.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=None,
        help="Target profile. Repeat or comma-separate for multiple profiles, e.g. --profile default,work --profile client.",
    )
    parser.add_argument(
        "--summary-model",
        default="",
        help="Deprecated alias: sets both --lcm-summary-model and --lcm-expansion-model.",
    )
    parser.add_argument(
        "--lcm-summary-model",
        default=_env_get(runtime_env, "HERMES_STACK_LCM_SUMMARY_MODEL", DEFAULT_LCM_SUMMARY_MODEL),
        help="LCM summarization model using a Hermes provider/model name. Empty uses Hermes auxiliary.compression.",
    )
    parser.add_argument(
        "--lcm-expansion-model",
        default=_env_get(runtime_env, "HERMES_STACK_LCM_EXPANSION_MODEL", ""),
        help="LCM lcm_expand_query synthesis model. Empty falls back to summary model or Hermes auxiliary.",
    )
    parser.add_argument(
        "--mnemosyne-mode",
        choices=MNEMOSYNE_MODES,
        default=_env_get(runtime_env, "HERMES_STACK_MNEMOSYNE_MODE", "full-local"),
        help="full-local=local embeddings+local GGUF LLM; hybrid=local embeddings+Hermes LLM; full-online=Hermes LLM+user-managed embedding endpoint/model.",
    )
    parser.add_argument(
        "--mnemosyne-llm-provider",
        default=_env_get(runtime_env, "HERMES_STACK_MNEMOSYNE_LLM_PROVIDER", ""),
        help="Optional Hermes provider override for Mnemosyne host LLM in hybrid/full-online modes.",
    )
    parser.add_argument(
        "--mnemosyne-llm-model",
        default=_env_get(runtime_env, "HERMES_STACK_MNEMOSYNE_LLM_MODEL", ""),
        help="Optional Hermes model override for Mnemosyne host LLM in hybrid/full-online modes.",
    )
    parser.add_argument(
        "--mnemosyne-embedding-api-url",
        default="",
        help="Full-online embedding API endpoint. API key is read from prompt or MNEMOSYNE_EMBEDDING_API_KEY, not from a CLI flag.",
    )
    parser.add_argument(
        "--mnemosyne-embedding-model",
        default="",
        help="Full-online embedding model name, e.g. text-embedding-3-small.",
    )
    parser.add_argument(
        "--mnemosyne-embedding-dim",
        default="",
        help="Full-online embedding vector dimension, e.g. 1536.",
    )
    parser.set_defaults(mnemosyne_embedding_api_key="")
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-lcm", action="store_true")
    parser.add_argument("--skip-mnemosyne", action="store_true")
    parser.add_argument("--skip-progress-tail", action="store_true")
    parser.add_argument(
        "--progress-tail-ref",
        default=_env_get(runtime_env, "HERMES_STACK_PROGRESS_TAIL_REF", PROGRESS_TAIL_REF),
        help="hermes-progress-tail git ref or 'latest' to resolve the newest GitHub release",
    )
    parser.add_argument("--install-superpowers", action="store_true")
    parser.add_argument("--install-hmx-knowledge", action="store_true")
    parser.add_argument("--install-impeccable", action="store_true")
    parser.add_argument("--generate-soul", action="store_true", help="Generate SOUL.md once via the user's Hermes AI backend.")
    parser.add_argument("--soul-agent-name", default="")
    parser.add_argument("--soul-user-name", default="")
    parser.add_argument("--soul-role", default="")
    parser.add_argument("--soul-behavior", default="")
    parser.add_argument("--soul-communication", default="")
    parser.add_argument("--soul-focus", default="")
    parser.add_argument("--soul-avoid", default="")
    parser.add_argument("--soul-language", default="")
    parser.add_argument("--soul-provider", default="", help="Optional provider override for the Hermes SOUL generation call.")
    parser.add_argument("--soul-model", default="", help="Optional model override for the Hermes SOUL generation call.")
    parser.add_argument("--soul-overwrite", action="store_true", help="Allow replacing an existing SOUL.md after backup.")
    parser.add_argument(
        "--hmx-knowledge-url",
        default=_env_get(runtime_env, "HMX_KNOWLEDGE_GIT_URL", HMX_KNOWLEDGE_REPO),
        help="Private HMX knowledge repo URL. Prefer SSH or a git credential helper; do not put tokens in shell history.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    apply_full_online_embedding_env_defaults(args, runtime_env)

    home = Path(args.home).expanduser() if args.home else detect_base_home(args.hermes_bin or None)
    runtime = discover_hermes_runtime(
        base_home=home,
        hermes_bin=args.hermes_bin,
        hermes_python=args.hermes_python,
        env=runtime_env,
    )
    profiles = parse_profiles(args.profile)
    if not args.yes:
        print("Hermes Stack Bootstrap")
        print("Installs: hermes-lcm, Mnemosyne, hermes-progress-tail; optional skill packs are flag-gated.")
        home = Path(prompt_default("Hermes base path", str(home))).expanduser()
        runtime = discover_hermes_runtime(
            base_home=home,
            hermes_bin=args.hermes_bin,
            hermes_python=args.hermes_python,
            env=runtime_env,
        )
        print(f"Detected Hermes CLI: {runtime.hermes_bin or 'not found'} ({runtime.hermes_bin_source})")
        print(f"Detected Hermes runtime Python: {runtime.hermes_python or 'not found'} ({runtime.hermes_python_source})")
        if runtime.hermes_python is None and not args.skip_mnemosyne:
            runtime, skip_mnemosyne = prompt_missing_runtime_python(runtime)
            args.skip_mnemosyne = skip_mnemosyne
        if args.profile is None:
            profiles = parse_profiles(prompt_default("Target profile(s), comma-separated", "default"))
        if not args.skip_mnemosyne:
            args.mnemosyne_mode = prompt_default(
                "Mnemosyne mode (full-local, hybrid, full-online)", args.mnemosyne_mode
            ).strip().lower()
            if args.mnemosyne_mode not in MNEMOSYNE_MODES:
                raise ValueError(f"Unknown Mnemosyne mode: {args.mnemosyne_mode}")
        apply_full_online_embedding_env_defaults(args, runtime_env)
        if not args.skip_mnemosyne and args.mnemosyne_mode in {"hybrid", "full-online"}:
            args.mnemosyne_llm_provider = prompt_default(
                "Mnemosyne Hermes LLM provider override (empty = Hermes auxiliary/default)",
                args.mnemosyne_llm_provider,
            )
            args.mnemosyne_llm_model = prompt_default(
                "Mnemosyne Hermes LLM model override (empty = Hermes auxiliary/default)",
                args.mnemosyne_llm_model,
            )
        if not args.skip_mnemosyne and args.mnemosyne_mode == "full-online":
            args.mnemosyne_embedding_api_url = prompt_default(
                "Mnemosyne embedding API URL (empty = configure later)",
                args.mnemosyne_embedding_api_url,
            )
            if args.mnemosyne_embedding_api_url:
                if not args.mnemosyne_embedding_api_key:
                    args.mnemosyne_embedding_api_key = getpass.getpass(
                        "Mnemosyne embedding API key (hidden; empty if endpoint needs no key): "
                    ).strip()
                args.mnemosyne_embedding_model = prompt_default(
                    "Mnemosyne embedding model", args.mnemosyne_embedding_model
                )
                args.mnemosyne_embedding_dim = prompt_default(
                    "Mnemosyne embedding dimension", args.mnemosyne_embedding_dim
                )
        if not args.summary_model:
            args.lcm_summary_model = prompt_default(
                "LCM summary model (empty = Hermes auxiliary.compression)",
                args.lcm_summary_model,
            )
            args.lcm_expansion_model = prompt_default(
                "LCM expansion model (empty = summary model / Hermes auxiliary)",
                args.lcm_expansion_model,
            )
        if not args.generate_soul:
            args.generate_soul = prompt_yes_no("Generate SOUL.md with Hermes AI backend?", False)
        if args.generate_soul:
            prompt_soul_answers(args)
    if args.summary_model:
        args.lcm_summary_model = args.summary_model
        if not args.lcm_expansion_model:
            args.lcm_expansion_model = args.summary_model
    profile = ",".join(profiles)
    validate_embedding_options(
        mode=args.mnemosyne_mode,
        api_url=args.mnemosyne_embedding_api_url,
        api_key=args.mnemosyne_embedding_api_key,
        model=args.mnemosyne_embedding_model,
        dim=args.mnemosyne_embedding_dim,
    )
    validate_soul_options(args)

    return InstallerOptions(
        base_home=home,
        profile=profile,
        hermes_bin=runtime.hermes_bin or args.hermes_bin or "hermes",
        hermes_bin_source=runtime.hermes_bin_source,
        hermes_python=runtime.hermes_python,
        hermes_python_source=runtime.hermes_python_source,
        yes=args.yes,
        dry_run=args.dry_run,
        summary_model=args.summary_model,
        lcm_summary_model=args.lcm_summary_model,
        lcm_expansion_model=args.lcm_expansion_model,
        mnemosyne_mode=args.mnemosyne_mode,
        mnemosyne_host_llm_provider=args.mnemosyne_llm_provider,
        mnemosyne_host_llm_model=args.mnemosyne_llm_model,
        mnemosyne_embedding_api_url=args.mnemosyne_embedding_api_url,
        mnemosyne_embedding_api_key=args.mnemosyne_embedding_api_key,
        mnemosyne_embedding_model=args.mnemosyne_embedding_model,
        mnemosyne_embedding_dim=args.mnemosyne_embedding_dim,
        skip_lcm=args.skip_lcm,
        skip_mnemosyne=args.skip_mnemosyne,
        skip_progress_tail=args.skip_progress_tail,
        progress_tail_ref=args.progress_tail_ref,
        install_superpowers=args.install_superpowers,
        install_hmx_knowledge=args.install_hmx_knowledge,
        install_impeccable=args.install_impeccable,
        hmx_knowledge_url=args.hmx_knowledge_url,
        generate_soul=args.generate_soul,
        soul_agent_name=args.soul_agent_name,
        soul_user_name=args.soul_user_name,
        soul_role=args.soul_role,
        soul_behavior=args.soul_behavior,
        soul_communication=args.soul_communication,
        soul_focus=args.soul_focus,
        soul_avoid=args.soul_avoid,
        soul_language=args.soul_language,
        soul_provider=args.soul_provider,
        soul_model=args.soul_model,
        soul_overwrite=args.soul_overwrite,
    )


def main(argv: Iterable[str] | None = None) -> int:
    options = wizard(argv)
    plans = build_plans(options)
    try:
        apply_plans(plans)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
