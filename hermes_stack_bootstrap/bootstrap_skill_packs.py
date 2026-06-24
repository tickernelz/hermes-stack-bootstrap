"""Optional skill-pack staging and installation."""

from __future__ import annotations

import dataclasses
import re
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .bootstrap_commands import run_command
from .bootstrap_utils import retry_with_backoff
from .bootstrap_shell import shell_quote
from .bootstrap_data import (
    HMX_KNOWLEDGE_SKILL_PACK,
    IMPECCABLE_SKILL_PACK,
    PONYTAIL_SKILL_PACK,
    REPO_ROOT_SKILL_INSTALL_MARKERS,
    SUPERPOWERS_SKILL_PACK,
    InstallerOptions,
    InstallPlan,
    SkillPackSpec,
)


def skill_vendor_dir(target_home: Path, name: str) -> Path:
    return target_home / "skills" / "vendor" / name


def skill_pack_stage_command(spec: SkillPackSpec, dest: Path) -> str:
    return f"stage skills from {spec.repo_url} into {shell_quote(dest)}"


def is_repo_root_skill_install(path: Path) -> bool:
    """Return True when an optional skill pack was incorrectly cloned as a repo root."""
    return path.is_dir() and any((path / marker).exists() for marker in REPO_ROOT_SKILL_INSTALL_MARKERS)


def skill_pack_source_root(source_root: Path, spec: SkillPackSpec) -> Path:
    if spec.source_subdir:
        root = source_root / spec.source_subdir
        if not root.is_dir():
            raise ValueError(f"{spec.name} repo does not contain expected skill source: {root}")
        return root

    conventional_root = source_root / "skills"
    if conventional_root.is_dir():
        return conventional_root
    return source_root


def skill_pack_skill_dirs(source_root: Path, spec: SkillPackSpec) -> list[Path]:
    root = skill_pack_source_root(source_root, spec)
    if (root / "SKILL.md").is_file():
        return [root]

    skill_dirs = sorted(path for path in root.iterdir() if path.is_dir() and (path / "SKILL.md").is_file())
    if skill_dirs:
        return skill_dirs

    excluded = {".git", ".github", "node_modules", ".venv", "venv", "__pycache__"}
    skill_dirs = sorted(
        path.parent for path in root.rglob("SKILL.md") if not any(part in excluded for part in path.parts)
    )
    if not skill_dirs:
        raise ValueError(f"{spec.name} repo has no Hermes skill directories under {root}")
    return skill_dirs


def skill_pack_backup_path(dest: Path, spec: SkillPackSpec) -> Path:
    if dest.parent.name == "vendor" and dest.parent.parent.name == "skills":
        backup_root = dest.parent.parent.parent / "backups"
    elif dest.parent.name == "skills":
        backup_root = dest.parent.parent / "backups"
    elif "skills" in dest.parts:
        backup_root = dest.parents[len(dest.parts) - dest.parts.index("skills") - 1] / "backups"
    else:
        backup_root = dest.parent / "backups"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_root / f"{spec.name}-repo-root-backup-{timestamp}"
    suffix = 1
    while backup.exists():
        backup = backup_root / f"{spec.name}-repo-root-backup-{timestamp}-{suffix}"
        suffix += 1
    return backup


def skill_backup_path(skills_root: Path, skill_name: str) -> Path:
    backup_root = skills_root.parent / "backups"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", skill_name).strip("-") or "skill"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_root / f"{safe_name}-skill-backup-{timestamp}"
    suffix = 1
    while backup.exists():
        backup = backup_root / f"{safe_name}-skill-backup-{timestamp}-{suffix}"
        suffix += 1
    return backup


def move_aside_repo_root_skill_install(dest: Path, spec: SkillPackSpec) -> Path:
    backup = skill_pack_backup_path(dest, spec)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dest), str(backup))
    return backup


def manifest_skill_name(skill_dir: Path, fallback: str) -> str:
    manifest = skill_dir / "SKILL.md"
    if not manifest.is_file():
        return fallback
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*name:\s*['\"]?([^'\"#]+)", line)
        if match:
            return match.group(1).strip()
    return fallback


def skills_root_for_vendor_dest(dest: Path) -> Path | None:
    if dest.parent.name == "vendor" and dest.parent.parent.name == "skills":
        return dest.parent.parent
    return None


def existing_skill_paths_by_name(skills_root: Path, skill_name: str) -> list[Path]:
    paths: list[Path] = []
    for manifest in sorted(skills_root.rglob("SKILL.md")):
        skill_dir = manifest.parent
        if manifest_skill_name(skill_dir, skill_dir.name) == skill_name:
            paths.append(skill_dir)
    return paths


def replace_existing_skill_installs_by_name(dest: Path, skill_name: str, target: Path, spec: SkillPackSpec) -> None:
    skills_root = skills_root_for_vendor_dest(dest)
    if skills_root is None or not skills_root.exists():
        return
    for existing in existing_skill_paths_by_name(skills_root, skill_name):
        if not existing.exists() or existing == target or target in existing.parents or existing in target.parents:
            continue
        backup = skill_backup_path(skills_root, skill_name)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(existing), str(backup))
        print(f"Moved existing {skill_name} skill aside before installing updated {spec.name}: {backup}")


def staged_skill_dir_name(skill_dir: Path, spec: SkillPackSpec) -> str:
    name = skill_dir.name
    if spec.skill_name_prefix and not name.startswith(spec.skill_name_prefix):
        name = f"{spec.skill_name_prefix}{name}"
    return name


def rewrite_superpowers_skill_references(content: str, spec: SkillPackSpec) -> str:
    if not spec.skill_name_prefix:
        return content
    namespace = spec.skill_name_prefix.rstrip("-")
    for token in spec.body_token_prefixes:
        replacement = f"{spec.skill_name_prefix}{token}"
        if namespace:
            content = re.sub(rf"\b{re.escape(namespace)}:{re.escape(token)}\b", replacement, content)
        pattern = rf"(?<!{re.escape(spec.skill_name_prefix)})\b{re.escape(token)}\b"
        content = re.sub(pattern, replacement, content)
    return content


def rewrite_staged_skill_manifest(path: Path, target_name: str, spec: SkillPackSpec) -> None:
    content = path.read_text(encoding="utf-8")
    if spec.skill_name_prefix:
        content = re.sub(r"(?m)^name:\s*.*$", f"name: {target_name}", content, count=1)
        content = rewrite_superpowers_skill_references(content, spec)
    path.write_text(content, encoding="utf-8")


def rewrite_staged_skill_support_files(skill_dir: Path, spec: SkillPackSpec) -> None:
    if not spec.skill_name_prefix:
        return
    for path in skill_dir.rglob("*.md"):
        if path.name == "SKILL.md":
            continue
        content = path.read_text(encoding="utf-8")
        rewritten = rewrite_superpowers_skill_references(content, spec)
        if rewritten != content:
            path.write_text(rewritten, encoding="utf-8")


def stage_skill_pack(source_root: Path, dest: Path, spec: SkillPackSpec) -> None:
    """Copy only Hermes skill directories from an upstream repo into a vendor skill directory."""
    skill_dirs = skill_pack_skill_dirs(source_root, spec)
    if is_repo_root_skill_install(dest):
        backup = move_aside_repo_root_skill_install(dest, spec)
        print(f"Moved incorrect {spec.name} repo-root install aside: {backup}")

    dest.mkdir(parents=True, exist_ok=True)
    upstream_skill_names = {staged_skill_dir_name(skill_dir, spec) for skill_dir in skill_dirs}
    for child in dest.iterdir():
        if child.name not in upstream_skill_names:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for skill_dir in skill_dirs:
        target_name = staged_skill_dir_name(skill_dir, spec)
        target = dest / target_name
        incoming_skill_name = target_name if spec.skill_name_prefix else manifest_skill_name(skill_dir, target_name)
        replace_existing_skill_installs_by_name(dest, incoming_skill_name, target, spec)
        shutil.copytree(skill_dir, target, dirs_exist_ok=True)
        rewrite_staged_skill_manifest(target / "SKILL.md", target_name, spec)
        rewrite_staged_skill_support_files(target, spec)


def gitlab_https_url(repo_url: str) -> str:
    if repo_url.startswith("git@gitlab.com:"):
        return "https://gitlab.com/" + repo_url.removeprefix("git@gitlab.com:")
    if repo_url.startswith("https://gitlab.com/"):
        return repo_url
    return repo_url


def write_gitlab_askpass(token: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", delete=False, prefix="hermes-stack-gitlab-askpass-", encoding="utf-8")
    path = Path(handle.name)
    handle.write("#!/usr/bin/env sh\n")
    handle.write('case "$1" in\n')
    handle.write("  *Username*) printf '%s\\n' oauth2 ;;\n")
    handle.write(f"  *Password*) printf '%s\\n' {shlex.quote(token)} ;;\n")
    handle.write("  *) printf '\\n' ;;\n")
    handle.write("esac\n")
    handle.close()
    path.chmod(0o700)
    return path


def clone_skill_pack_repo(spec: SkillPackSpec, source_root: Path, *, dry_run: bool, gitlab_token: str = "") -> None:
    command = ["git", "clone", "--depth=1", spec.repo_url, str(source_root)]
    if dry_run:
        run_command(command, dry_run=True)
        return
    try:
        retry_with_backoff(
            lambda: run_command(command, dry_run=False, timeout=600),
            label=f"git clone ({spec.name})",
            retryable_exceptions=(ConnectionError, TimeoutError, subprocess.TimeoutExpired),
        )
        return
    except subprocess.CalledProcessError:
        if not gitlab_token or "gitlab.com" not in spec.repo_url:
            raise
    askpass = write_gitlab_askpass(gitlab_token)
    try:
        retry_env = {
            "GIT_ASKPASS": str(askpass),
            "GIT_TERMINAL_PROMPT": "0",
        }
        retry_with_backoff(
            lambda: run_command(
                ["git", "clone", "--depth=1", gitlab_https_url(spec.repo_url), str(source_root)],
                dry_run=False,
                env=retry_env,
                timeout=600,
            ),
            label=f"git clone ({spec.name}, HTTPS fallback)",
        )
    finally:
        askpass.unlink(missing_ok=True)


def install_skill_pack(spec: SkillPackSpec, dest: Path, *, dry_run: bool, gitlab_token: str = "") -> None:
    if dry_run:
        clone_skill_pack_repo(spec, Path(f"<temporary-directory>/{spec.name}"), dry_run=True, gitlab_token=gitlab_token)
        print(f"DRY-RUN stage Hermes skills from {spec.repo_url} into {dest}")
        return

    with tempfile.TemporaryDirectory(prefix=f"hermes-stack-{spec.name}-") as tmp:
        source_root = Path(tmp) / spec.name
        clone_skill_pack_repo(spec, source_root, dry_run=False, gitlab_token=gitlab_token)
        stage_skill_pack(source_root, dest, spec)


def optional_skill_packs(options: InstallerOptions, target_home: Path) -> list[tuple[SkillPackSpec, Path]]:
    packs: list[tuple[SkillPackSpec, Path]] = []
    if options.install_superpowers:
        packs.append((SUPERPOWERS_SKILL_PACK, skill_vendor_dir(target_home, "obra-superpowers")))
    if options.install_hmx_knowledge:
        packs.append(
            (
                dataclasses.replace(HMX_KNOWLEDGE_SKILL_PACK, repo_url=options.hmx_knowledge_url),
                skill_vendor_dir(target_home, "hmx-knowledge"),
            )
        )
    if options.install_impeccable:
        packs.append((IMPECCABLE_SKILL_PACK, skill_vendor_dir(target_home, "impeccable")))
    if options.install_ponytail:
        packs.append((PONYTAIL_SKILL_PACK, skill_vendor_dir(target_home, "ponytail")))
    return packs


def install_optional_skills(plan: InstallPlan) -> None:
    failures: list[str] = []
    for spec, dest in optional_skill_packs(plan.options, plan.target_home):
        token = plan.options.hmx_gitlab_token if spec.name == "hmx-knowledge" else ""
        try:
            install_skill_pack(spec, dest, dry_run=plan.options.dry_run, gitlab_token=token)
        except Exception as exc:
            failures.append(spec.name)
            print(f"Warning: optional skill pack {spec.name} failed and was skipped: {exc}")
    if failures:
        print("Optional skill packs skipped after errors: " + ", ".join(failures))
