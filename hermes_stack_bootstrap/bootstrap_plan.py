"""Execution-plan construction and display."""

from __future__ import annotations

import dataclasses
import json
import urllib.request
from pathlib import Path

from .bootstrap_data import (
    LCM_REPO,
    LATEST_PROGRESS_TAIL_TAG_PLACEHOLDER,
    PROGRESS_TAIL_REPO,
    InstallPlan,
    InstallerOptions,
    PlanStep,
)
from .bootstrap_runtime import (
    hermes_bin_for_options,
    install_mode_label,
    parse_profiles,
    runtime_python_for_options,
    target_home_for,
)
from .bootstrap_shell import shell_join, shell_quote
from .bootstrap_skill_packs import optional_skill_packs, skill_pack_stage_command
from .soul_generator import SoulAnswers


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
    env_parts = ["HPT_INTERACTIVE=0", f"HERMES_HOME={shell_quote(base_home)}"]
    if profile != "default":
        env_parts.append(f"HPT_PROFILES={shell_quote(profile)}")
    return f"curl -fsSL {progress_tail_install_url(ref)} | env {' '.join(env_parts)} bash"


def progress_tail_plan_command(*, base_home: Path, profile: str, ref: str) -> str:
    return progress_tail_install_command(
        base_home=base_home,
        profile=profile,
        ref=progress_tail_ref_for_plan(ref),
    )


def mnemosyne_pip_package_list(mode: str) -> list[str]:
    normalized = mode.strip().lower() or "full-local"
    if normalized == "full-local":
        return ["mnemosyne-memory[all]", "sqlite-vec"]
    if normalized == "hybrid":
        return ["mnemosyne-memory[embeddings]", "sqlite-vec"]
    if normalized == "full-online":
        return ["mnemosyne-memory", "sqlite-vec", "numpy"]
    raise ValueError(f"Unknown Mnemosyne mode: {mode}")


def mnemosyne_pip_packages(mode: str) -> str:
    return shell_join(mnemosyne_pip_package_list(mode))


def soul_answers_from_options(options: InstallerOptions) -> SoulAnswers:
    return SoulAnswers(
        agent_name=options.soul_agent_name,
        user_name=options.soul_user_name,
        communication_style=options.soul_communication,
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


def verification_command_for_options(options: InstallerOptions) -> str:
    hermes_bin_cmd = shell_quote(hermes_bin_for_options(options))
    profile_args = "" if options.profile == "default" else f" -p {options.profile}"
    plugins = f"{hermes_bin_cmd}{profile_args} plugins list --plain --no-bundled"
    if options.skip_mnemosyne:
        return plugins
    return (
        f"{hermes_bin_cmd}{profile_args} memory status && {hermes_bin_cmd}{profile_args} mnemosyne stats && {plugins}"
    )


def build_plan(options: InstallerOptions) -> InstallPlan:
    base_home = options.base_home.expanduser()
    target_home = target_home_for(base_home, options.profile)
    hermes_py = runtime_python_for_options(options)
    hermes_py_cmd = shell_quote(hermes_py)
    steps: list[PlanStep] = []

    if not options.skip_lcm:
        lcm_dir = target_home / "plugins" / "hermes-lcm"
        steps.append(
            PlanStep(
                "Install hermes-lcm from upstream README",
                f"git clone {shell_quote(LCM_REPO)} {shell_quote(lcm_dir)}",
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

    skill_step_metadata = {
        "obra-superpowers": (
            "Optional: install Obra Superpowers skills",
            "Stages upstream skills/* into skills/vendor/obra-superpowers as superpowers-* Hermes skills; repo tooling stays out of the skills root.",
        ),
        "hmx-knowledge": (
            "Optional: install HMX knowledge skills",
            "Private GitLab repo; use SSH agent or preconfigured HTTPS/token credentials. Stages discovered Hermes skill directories only and never stores tokens.",
        ),
        "impeccable": (
            "Optional: install Impeccable design skill",
            "Stages plugin/skills/impeccable only; repo scaffolding, Claude config, package files, and examples stay out of the skills root.",
        ),
        "ponytail": (
            "Optional recommended: install Ponytail skill pack",
            "Stages upstream skills/* only; repo tooling, hooks, package.json, docs, and examples stay out of the skills root.",
        ),
    }
    for spec, dest in optional_skill_packs(options, target_home):
        title, notes = skill_step_metadata[spec.name]
        steps.append(PlanStep(title, skill_pack_stage_command(spec, dest), notes))

    final_steps = []
    if not options.skip_config_env:
        final_steps.extend(
            [
                PlanStep(
                    "Merge config.yaml safely",
                    notes="Enable hermes-lcm + mnemosyne, set context.engine=lcm, disable built-in file memory.",
                ),
                PlanStep(
                    "Merge .env values",
                    notes="Write LCM tuning, selected Mnemosyne mode defaults, and any embedding API values explicitly supplied during install.",
                ),
            ]
        )
    if not options.skip_verify:
        final_steps.append(
            PlanStep(
                "Verify",
                verification_command_for_options(options),
                "Restart Hermes manually after applying changes, then run these checks.",
            )
        )
    if options.generate_soul:
        final_steps.append(
            PlanStep(
                "Generate SOUL.md with Hermes AI backend",
                soul_generation_command_preview(options),
                f"Writes {target_home / 'SOUL.md'}; existing files require overwrite approval and are backed up first.",
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
        build_plan(dataclasses.replace(options, profile=profile)) for profile in parse_profiles(options.profile)
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
    print(f"Install mode   : {install_mode_label(plan.options.install_mode)}")
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
