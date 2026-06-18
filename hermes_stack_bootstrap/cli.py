"""Command-line wizard and execution plan for hermes-stack-bootstrap."""

from __future__ import annotations

import argparse
import difflib
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
    build_env_values,
    merge_env_text,
    render_env_block,
)


LCM_REPO = "https://github.com/stephenschoettler/hermes-lcm"
PROGRESS_TAIL_REPO = "tickernelz/hermes-progress-tail"
PROGRESS_TAIL_REF = os.environ.get("HERMES_STACK_PROGRESS_TAIL_REF", "latest")
LATEST_PROGRESS_TAIL_TAG_PLACEHOLDER = "${LATEST_HERMES_PROGRESS_TAIL_TAG}"


@dataclass(frozen=True)
class InstallerOptions:
    base_home: Path
    profile: str
    yes: bool = False
    dry_run: bool = False
    summary_model: str = ""
    skip_lcm: bool = False
    skip_mnemosyne: bool = False
    skip_progress_tail: bool = False
    progress_tail_ref: str = PROGRESS_TAIL_REF


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
                    "Install Mnemosyne full local package into Hermes runtime venv",
                    f"{hermes_py} -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[all]' sqlite-vec",
                    "This follows Mnemosyne's full-feature local profile: local embeddings plus local GGUF LLM fallback.",
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

    steps.extend(
        [
            PlanStep(
                "Merge config.yaml safely",
                notes="Enable hermes-lcm + mnemosyne, set context.engine=lcm, disable built-in file memory.",
            ),
            PlanStep(
                "Merge .env non-secret defaults",
                notes="Write LCM tuning and local-first Mnemosyne defaults. No API keys are added.",
            ),
            PlanStep(
                "Verify",
                "hermes memory status && hermes mnemosyne stats && hermes plugins list --plain --no-bundled",
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


def print_plan(plan: InstallPlan) -> None:
    print("\nHermes Stack Bootstrap plan")
    print("=" * 28)
    print(f"Target profile : {plan.options.profile}")
    print(f"Target home    : {plan.target_home}")
    print(f"Config path    : {plan.config_path}")
    print(f"Env path       : {plan.env_path}")
    print(f"Dry run        : {plan.options.dry_run}")
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
        f"{hermes_py} -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[all]' sqlite-vec",
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


def merge_config_and_env(plan: InstallPlan) -> None:
    env_values = build_env_values(
        home=str(plan.target_home),
        summary_model=plan.options.summary_model,
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
        print(render_env_block(env_values), end="")
        return

    plan.target_home.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_files(plan)
    if backup_dir:
        print(f"Backup written: {backup_dir}")

    current_config = read_config(plan.config_path)
    write_config(plan.config_path, build_target_config(current_config))

    existing_env = plan.env_path.read_text() if plan.env_path.exists() else ""
    plan.env_path.write_text(merge_env_text(existing_env, env_values))


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
    merge_config_and_env(plan)
    run_verification(plan)
    print("\nDone. Restart Hermes manually after applying changes: /restart")


def prompt_default(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def wizard(argv: Iterable[str] | None = None) -> InstallerOptions:
    parser = argparse.ArgumentParser(description="Bootstrap Hermes LCM + Mnemosyne + progress-tail")
    parser.add_argument("--home", default=None)
    parser.add_argument("--profile", default="")
    parser.add_argument(
        "--summary-model",
        default=os.environ.get("HERMES_STACK_SUMMARY_MODEL", DEFAULT_LCM_SUMMARY_MODEL),
    )
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-lcm", action="store_true")
    parser.add_argument("--skip-mnemosyne", action="store_true")
    parser.add_argument("--skip-progress-tail", action="store_true")
    parser.add_argument(
        "--progress-tail-ref",
        default=os.environ.get("HERMES_STACK_PROGRESS_TAIL_REF", PROGRESS_TAIL_REF),
        help="hermes-progress-tail git ref or 'latest' to resolve the newest GitHub release",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    home = Path(args.home).expanduser() if args.home else detect_base_home()
    profile = args.profile
    if not args.yes:
        print("Hermes Stack Bootstrap")
        print("Installs only: hermes-lcm, Mnemosyne full-local, hermes-progress-tail.")
        home = Path(prompt_default("Hermes base path", str(home))).expanduser()
        if not profile:
            profile = prompt_default("Target profile", "default")
        if not args.summary_model:
            args.summary_model = prompt_default(
                "LCM summary model override (empty = Hermes auxiliary)", ""
            )
    if not profile:
        profile = "default"

    return InstallerOptions(
        base_home=home,
        profile=profile,
        yes=args.yes,
        dry_run=args.dry_run,
        summary_model=args.summary_model,
        skip_lcm=args.skip_lcm,
        skip_mnemosyne=args.skip_mnemosyne,
        skip_progress_tail=args.skip_progress_tail,
        progress_tail_ref=args.progress_tail_ref,
    )


def main(argv: Iterable[str] | None = None) -> int:
    options = wizard(argv)
    plan = build_plan(options)
    try:
        apply_plan(plan)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
