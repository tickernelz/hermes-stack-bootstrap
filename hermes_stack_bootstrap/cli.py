"""Command-line wizard and execution plan for hermes-stack-bootstrap."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import getpass
import json
import os
import shutil
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


def base_home_from_config_path(config_path: str | Path) -> Path:
    """Infer Hermes base home from `hermes config path` output."""
    path = Path(str(config_path).strip()).expanduser()
    if path.name != "config.yaml":
        return path.parent
    parts = path.parts
    if len(parts) >= 3 and parts[-3] == "profiles":
        return Path(*parts[:-3])
    return path.parent


def detect_base_home() -> Path:
    """Best-effort Hermes base path detection with safe fallbacks."""
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(env_home).expanduser()

    hermes_bin = shutil.which("hermes")
    if hermes_bin:
        try:
            completed = subprocess.run(
                [hermes_bin, "config", "path"],
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


def build_plan(options: InstallerOptions) -> InstallPlan:
    base_home = options.base_home.expanduser()
    target_home = target_home_for(base_home, options.profile)
    hermes_py = hermes_python_for(base_home)
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
                    f"{hermes_py} -m pip install --upgrade --no-cache-dir {mnemosyne_pip_packages(options.mnemosyne_mode)}",
                    "full-local uses local embeddings + local GGUF LLM; hybrid uses local embeddings + Hermes host LLM; full-online uses user-supplied embedding API settings and routes LLM via Hermes.",
                ),
                PlanStep(
                    "Register Mnemosyne as Hermes memory provider",
                    f"HERMES_HOME={target_home} {hermes_py} -m mnemosyne.install",
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

    verify_command = "hermes memory status && hermes mnemosyne stats && hermes plugins list --plain --no-bundled"
    if options.profile != "default":
        verify_command = (
            f"hermes -p {options.profile} memory status && "
            f"hermes -p {options.profile} mnemosyne stats && "
            f"hermes -p {options.profile} plugins list --plain --no-bundled"
        )

    steps.extend(
        [
            PlanStep(
                "Merge config.yaml safely",
                notes="Enable hermes-lcm + mnemosyne, set context.engine=lcm, disable built-in file memory.",
            ),
            PlanStep(
                "Merge .env values",
                notes="Write LCM tuning, selected Mnemosyne mode defaults, and any embedding API values explicitly supplied during install.",
            ),
            PlanStep(
                "Verify",
                verify_command,
                "Restart Hermes manually after applying changes, then run these checks.",
            ),
        ]
    )

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
    hermes_py = hermes_python_for(plan.options.base_home.expanduser())
    run_command(
        f"{hermes_py} -m pip install --upgrade --no-cache-dir {mnemosyne_pip_packages(plan.options.mnemosyne_mode)}",
        dry_run=plan.options.dry_run,
    )
    run_command(
        f"HERMES_HOME={plan.target_home} {hermes_py} -m mnemosyne.install",
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


def run_verification(plan: InstallPlan) -> None:
    if plan.options.dry_run:
        print("DRY-RUN verification skipped")
        return
    commands = [
        "hermes memory status",
        "hermes mnemosyne stats",
        "hermes plugins list --plain --no-bundled",
    ]
    if plan.options.profile != "default":
        commands = [
            f"hermes -p {plan.options.profile} memory status",
            f"hermes -p {plan.options.profile} mnemosyne stats",
            f"hermes -p {plan.options.profile} plugins list --plain --no-bundled",
        ]
    for command in commands:
        run_command(command, dry_run=False)


def apply_plan(plan: InstallPlan) -> None:
    print_plan(plan)
    if not plan.options.yes:
        answer = input("\nApply this plan? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return
    install_lcm(plan)
    install_mnemosyne(plan)
    install_progress_tail(plan)
    install_optional_skills(plan)
    merge_config_and_env(plan)
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


def wizard(argv: Iterable[str] | None = None, *, env: os._Environ[str] | dict[str, str] | None = None) -> InstallerOptions:
    runtime_env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Bootstrap Hermes LCM + Mnemosyne + progress-tail")
    parser.add_argument("--home", default=None)
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
    parser.add_argument(
        "--hmx-knowledge-url",
        default=_env_get(runtime_env, "HMX_KNOWLEDGE_GIT_URL", HMX_KNOWLEDGE_REPO),
        help="Private HMX knowledge repo URL. Prefer SSH or a git credential helper; do not put tokens in shell history.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    apply_full_online_embedding_env_defaults(args, runtime_env)

    home = Path(args.home).expanduser() if args.home else detect_base_home()
    profiles = parse_profiles(args.profile)
    if not args.yes:
        print("Hermes Stack Bootstrap")
        print("Installs: hermes-lcm, Mnemosyne, hermes-progress-tail; optional skill packs are flag-gated.")
        home = Path(prompt_default("Hermes base path", str(home))).expanduser()
        if args.profile is None:
            profiles = parse_profiles(prompt_default("Target profile(s), comma-separated", "default"))
        args.mnemosyne_mode = prompt_default(
            "Mnemosyne mode (full-local, hybrid, full-online)", args.mnemosyne_mode
        ).strip().lower()
        if args.mnemosyne_mode not in MNEMOSYNE_MODES:
            raise ValueError(f"Unknown Mnemosyne mode: {args.mnemosyne_mode}")
        apply_full_online_embedding_env_defaults(args, runtime_env)
        if args.mnemosyne_mode in {"hybrid", "full-online"}:
            args.mnemosyne_llm_provider = prompt_default(
                "Mnemosyne Hermes LLM provider override (empty = Hermes auxiliary/default)",
                args.mnemosyne_llm_provider,
            )
            args.mnemosyne_llm_model = prompt_default(
                "Mnemosyne Hermes LLM model override (empty = Hermes auxiliary/default)",
                args.mnemosyne_llm_model,
            )
        if args.mnemosyne_mode == "full-online":
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

    return InstallerOptions(
        base_home=home,
        profile=profile,
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
