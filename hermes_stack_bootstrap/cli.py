"""Command-line wizard and execution plan for hermes-stack-bootstrap."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import shutil
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

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
from .hermes_models import ProviderChoice, model_choices_for_provider, provider_choices
from .provider_setup import (
    AUXILIARY_TASKS,
    HASHMICRO_BASE_URL,
    HASHMICRO_KEY_ENV,
    HASHMICRO_PROVIDER_NAME,
    HASHMICRO_REASONING_EFFORTS,
    HASHMICRO_DEFAULT_REASONING_EFFORT,
    HashmicroProviderSetup,
    build_hashmicro_env_values,
    default_hashmicro_context_length,
    fetch_openai_compatible_model_metadata,
    merge_hashmicro_provider_config,
    hashmicro_model_with_reasoning_effort,
    normalize_hashmicro_reasoning_effort,
    parse_aux_context_length_overrides,
    parse_aux_model_overrides,
    secret_env_keys,
)
from .soul_generator import (
    DEFAULT_SOUL_COMMUNICATION_STYLE,
    DEFAULT_SOUL_LANGUAGE,
    SoulAnswers,
    generate_soul_with_hermes,
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
PONYTAIL_REPO = "https://github.com/DietrichGebert/ponytail"
REPO_ROOT_SKILL_INSTALL_MARKERS = (".git", "package.json", "skills")
SENSITIVE_ENV_KEYS = {"MNEMOSYNE_EMBEDDING_API_KEY", "XAI_HASHMICRO_API_KEY", "GITLAB_TOKEN"}
INSTALL_MODE_LABELS = {
    "full": "Full process",
    "plugin-skill-only": "Plugin & skill only",
    "soul-only": "Generate SOUL.md only",
}
INSTALL_MODE_VALUES = {label: mode for mode, label in INSTALL_MODE_LABELS.items()}
INSTALL_MODE_CHOICES = tuple(INSTALL_MODE_LABELS)


class TuiDependencyError(RuntimeError):
    """Raised when interactive TUI dependencies are unavailable."""


class RichPromptTui:
    """Small TUI facade backed by Rich output and prompt_toolkit input."""

    def __init__(self) -> None:
        try:
            from prompt_toolkit import prompt as toolkit_prompt  # type: ignore
            from prompt_toolkit.completion import WordCompleter  # type: ignore
            from prompt_toolkit.shortcuts import checkboxlist_dialog  # type: ignore
            from rich.console import Console  # type: ignore
            from rich.panel import Panel  # type: ignore
            from rich.table import Table  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            manual = f"{sys.executable} -m pip install 'PyYAML>=6' 'rich>=13' 'prompt_toolkit>=3'"
            raise TuiDependencyError(
                "Interactive install requires TUI dependencies: rich and prompt_toolkit. "
                "The install.sh bootstrapper installs them automatically. "
                f"If you run the Python module directly, install them manually with: {manual}"
            ) from exc
        self._prompt = toolkit_prompt
        self._word_completer = WordCompleter
        self._checkboxlist_dialog = checkboxlist_dialog
        self.console = Console()
        self._panel = Panel
        self._table = Table

    def banner(self, title: str, subtitle: str) -> None:
        self.console.print(self._panel(subtitle, title=title, border_style="cyan"))

    def step(self, title: str) -> None:
        self.console.print(f"\n[bold cyan]{title}[/bold cyan]")

    def text(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        value = self._prompt(f"{prompt}{suffix}: ").strip()
        return value or default

    def password(self, prompt: str) -> str:
        return self._prompt(f"{prompt}: ", is_password=True).strip()

    def confirm(self, prompt: str, default: bool = False) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            answer = self._prompt(f"{prompt} [{suffix}] ").strip().lower()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self.console.print("[yellow]Please answer yes or no.[/yellow]")

    def select(self, prompt: str, choices: Sequence[str], default: str = "") -> str:
        choices = tuple(choices)
        if not choices:
            return default
        default = default if default in choices else choices[0]
        table = self._table.grid(padding=(0, 2))
        table.add_column(justify="right")
        table.add_column()
        for index, choice in enumerate(choices, start=1):
            marker = "*" if choice == default else " "
            table.add_row(f"{index}.", f"{marker} {choice}")
        self.console.print(prompt)
        self.console.print(table)
        completer = self._word_completer(list(choices), ignore_case=True)
        while True:
            answer = self._prompt(f"Select [{default}]: ", completer=completer).strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                return choices[int(answer) - 1]
            for choice in choices:
                if answer.lower() == choice.lower():
                    return choice
            self.console.print(f"[yellow]Choose one of: {', '.join(choices)}[/yellow]")

    def multi_select(self, prompt: str, choices: Sequence[str], defaults: Sequence[str] = ()) -> tuple[str, ...]:
        choices = tuple(choices)
        if not choices:
            return tuple(defaults)
        defaults = tuple(choice for choice in defaults if choice in choices)
        result = self._checkboxlist_dialog(
            title=prompt,
            text="Use Space to toggle, Enter to continue.",
            values=[(choice, choice) for choice in choices],
            default_values=list(defaults),
        ).run()
        selected = tuple(result or ())
        return selected or defaults or (choices[0],)

    def status(self, message: str):
        return self.console.status(message, spinner="dots")

    def runtime_summary(self, runtime: HermesRuntime) -> None:
        table = self._table(title="Detected Hermes runtime", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Hermes CLI", f"{runtime.hermes_bin or 'not found'} ({runtime.hermes_bin_source})")
        table.add_row("Hermes Python", f"{runtime.hermes_python or 'not found'} ({runtime.hermes_python_source})")
        self.console.print(table)


def create_tui() -> RichPromptTui:
    return RichPromptTui()


@dataclass(frozen=True)
class SkillPackSpec:
    name: str
    repo_url: str
    source_subdir: str = ""
    skill_name_prefix: str = ""
    body_token_prefixes: tuple[str, ...] = ()


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
    install_mode: str = "full"
    summary_model: str = ""
    lcm_summary_model: str = DEFAULT_LCM_SUMMARY_MODEL
    lcm_expansion_model: str = ""
    mnemosyne_mode: str = "hybrid"
    mnemosyne_host_llm_provider: str = ""
    mnemosyne_host_llm_model: str = ""
    mnemosyne_embedding_api_url: str = ""
    mnemosyne_embedding_api_key: str = ""
    mnemosyne_embedding_model: str = ""
    mnemosyne_embedding_dim: str = ""
    skip_lcm: bool = False
    skip_mnemosyne: bool = False
    skip_progress_tail: bool = False
    skip_config_env: bool = False
    skip_verify: bool = False
    progress_tail_ref: str = PROGRESS_TAIL_REF
    install_superpowers: bool = False
    install_hmx_knowledge: bool = False
    install_impeccable: bool = False
    install_ponytail: bool = False
    hmx_knowledge_url: str = HMX_KNOWLEDGE_REPO
    hmx_gitlab_token: str = ""
    setup_hashmicro_provider: bool = False
    hashmicro_base_url: str = HASHMICRO_BASE_URL
    hashmicro_provider_name: str = HASHMICRO_PROVIDER_NAME
    hashmicro_key_env: str = HASHMICRO_KEY_ENV
    hashmicro_api_key: str = ""
    hashmicro_main_model: str = ""
    hashmicro_main_context_length: int = 0
    hashmicro_delegation_model: str = ""
    hashmicro_delegation_context_length: int = 0
    hashmicro_auxiliary_models: Mapping[str, str] = dataclasses.field(default_factory=dict)
    hashmicro_auxiliary_context_lengths: Mapping[str, int] = dataclasses.field(default_factory=dict)
    hashmicro_reasoning_effort: str = ""
    hashmicro_available_models: Sequence[str] = dataclasses.field(default_factory=tuple)
    generate_soul: bool = False
    soul_agent_name: str = ""
    soul_user_name: str = ""
    soul_role: str = ""
    soul_behavior: str = ""
    soul_communication: str = DEFAULT_SOUL_COMMUNICATION_STYLE
    soul_focus: str = ""
    soul_avoid: str = ""
    soul_language: str = DEFAULT_SOUL_LANGUAGE
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


SUPERPOWERS_SKILL_TOKENS = (
    "brainstorming",
    "dispatching-parallel-agents",
    "executing-plans",
    "finishing-a-development-branch",
    "receiving-code-review",
    "requesting-code-review",
    "subagent-driven-development",
    "systematic-debugging",
    "test-driven-development",
    "using-git-worktrees",
    "using-superpowers",
    "verification-before-completion",
    "writing-plans",
    "writing-skills",
)
SUPERPOWERS_SKILL_PACK = SkillPackSpec(
    name="obra-superpowers",
    repo_url=SUPERPOWERS_REPO,
    source_subdir="skills",
    skill_name_prefix="superpowers-",
    body_token_prefixes=SUPERPOWERS_SKILL_TOKENS,
)
HMX_KNOWLEDGE_SKILL_PACK = SkillPackSpec(name="hmx-knowledge", repo_url=HMX_KNOWLEDGE_REPO, source_subdir="skills")
IMPECCABLE_SKILL_PACK = SkillPackSpec(name="impeccable", repo_url=IMPECCABLE_REPO, source_subdir="plugin/skills")
PONYTAIL_SKILL_PACK = SkillPackSpec(name="ponytail", repo_url=PONYTAIL_REPO, source_subdir="skills")


_WINDOWS_DRIVE_PATH_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def path_for_shell(value: str | Path) -> str:
    """Return a POSIX-shell-friendly display/execution path for Git Bash plans.

    The installer can run under Windows Python while the visible terminal is Git
    Bash. Native Windows paths like C:\\Users\\... must not be emitted into bash
    snippets as-is; Git Bash expects /c/Users/....
    """
    text = str(value)
    match = _WINDOWS_DRIVE_PATH_RE.match(text)
    if not match:
        return text
    drive, rest = match.groups()
    normalized_rest = rest.replace("\\", "/")
    return f"/{drive.lower()}/{normalized_rest}"


def shell_quote(value: str | Path) -> str:
    return shlex.quote(path_for_shell(value))


def shell_join(args: Sequence[str | Path]) -> str:
    return " ".join(shell_quote(arg) for arg in args)


def env_prefix_for_shell(env: Mapping[str, str] | None) -> str:
    if not env:
        return ""
    return " ".join(f"{key}={shell_quote(value)}" for key, value in env.items())


def render_command(command: str | Sequence[str | Path], *, env: Mapping[str, str] | None = None) -> str:
    command_text = command if isinstance(command, str) else shell_join(command)
    env_prefix = env_prefix_for_shell(env)
    return f"{env_prefix} {command_text}" if env_prefix else command_text


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


def profile_choices_for_home(base_home: Path) -> tuple[str, ...]:
    """Return selectable Hermes profiles from the target home."""
    choices = ["default"]
    profiles_dir = base_home.expanduser() / "profiles"
    if profiles_dir.is_dir():
        for path in sorted(profiles_dir.iterdir(), key=lambda item: item.name.lower()):
            if path.is_dir() and not path.name.startswith("."):
                choices.append(path.name)
    return tuple(dict.fromkeys(choices))


def prompt_profiles(tui: RichPromptTui, base_home: Path, current_profiles: Iterable[str] | str | None = None) -> tuple[str, ...]:
    choices = profile_choices_for_home(base_home)
    defaults = parse_profiles(current_profiles)
    if len(choices) == 1:
        return tuple(getattr(tui, "multi_select")("Target profile(s)", choices, defaults))
    return tuple(getattr(tui, "multi_select")("Target profile(s)", choices, defaults))


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


def normalize_install_mode(mode: str) -> str:
    normalized = (mode or "full").strip().lower().replace("_", "-")
    aliases = {
        "full-process": "full",
        "plugins-skill-only": "plugin-skill-only",
        "plugins-skills-only": "plugin-skill-only",
        "plugin-skills-only": "plugin-skill-only",
        "plugins-only": "plugin-skill-only",
        "skills-only": "plugin-skill-only",
        "soul": "soul-only",
        "generate-soul": "soul-only",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in INSTALL_MODE_CHOICES:
        raise ValueError(f"Unknown install mode: {mode}")
    return normalized


def apply_install_mode_defaults(args: argparse.Namespace) -> None:
    args.install_mode = normalize_install_mode(args.install_mode)
    if args.install_mode == "full":
        return
    if args.install_mode == "plugin-skill-only":
        args.skip_mnemosyne = True
        args.skip_config_env = True
        return
    if args.install_mode == "soul-only":
        args.skip_lcm = True
        args.skip_mnemosyne = True
        args.skip_progress_tail = True
        args.skip_config_env = True
        args.skip_verify = True
        args.generate_soul = True


def install_mode_label(mode: str) -> str:
    return INSTALL_MODE_LABELS[normalize_install_mode(mode)]


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


def skill_vendor_dir(target_home: Path, name: str) -> Path:
    return target_home / "skills" / "vendor" / name


def skill_pack_stage_command(spec: SkillPackSpec, dest: Path) -> str:
    return f"stage skills from {spec.repo_url} into {shell_quote(dest)}"


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
        f"{hermes_bin_cmd}{profile_args} memory status && "
        f"{hermes_bin_cmd}{profile_args} mnemosyne stats && "
        f"{plugins}"
    )


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
        run_command(["git", "-C", str(lcm_dir), "pull", "--ff-only"], dry_run=plan.options.dry_run)
    else:
        lcm_dir.parent.mkdir(parents=True, exist_ok=True)
        run_command(["git", "clone", LCM_REPO, str(lcm_dir)], dry_run=plan.options.dry_run)


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
        except Exception:
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
        run_command([str(hermes_py), "-m", "pip", "install", "--upgrade", "--no-cache-dir", *packages], dry_run=True)
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
            run_command(sudo_command, dry_run=False)
        else:
            run_command(pip_command, dry_run=False)
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
        path.parent
        for path in root.rglob("SKILL.md")
        if not any(part in excluded for part in path.parts)
    )
    if not skill_dirs:
        raise ValueError(f"{spec.name} repo has no Hermes skill directories under {root}")
    return skill_dirs


def skill_pack_backup_path(dest: Path, spec: SkillPackSpec) -> Path:
    if dest.parent.name == "vendor" and dest.parent.parent.name == "skills":
        backup_root = dest.parent.parent.parent / "backups"
    else:
        backup_root = dest.parent / "backups"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_root / f"{spec.name}-repo-root-backup-{timestamp}"
    suffix = 1
    while backup.exists():
        backup = backup_root / f"{spec.name}-repo-root-backup-{timestamp}-{suffix}"
        suffix += 1
    return backup


def move_aside_repo_root_skill_install(dest: Path, spec: SkillPackSpec) -> Path:
    backup = skill_pack_backup_path(dest, spec)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dest), str(backup))
    return backup


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
    handle.write("case \"$1\" in\n")
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
        run_command(command, dry_run=False)
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
        run_command(
            ["git", "clone", "--depth=1", gitlab_https_url(spec.repo_url), str(source_root)],
            dry_run=False,
            env=retry_env,
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
    for spec, dest in optional_skill_packs(plan.options, plan.target_home):
        token = plan.options.hmx_gitlab_token if spec.name == "hmx-knowledge" else ""
        install_skill_pack(spec, dest, dry_run=plan.options.dry_run, gitlab_token=token)


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
        preview_env_values = {**env_values, **hmx_env_values(plan.options), **build_hashmicro_env_values(hashmicro_setup_from_options(plan.options))}
        print(render_env_block(preview_env_values, redact_keys=SENSITIVE_ENV_KEYS | secret_env_keys(preview_env_values)), end="")
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
    env_values = {**env_values, **hmx_env_values(plan.options), **build_hashmicro_env_values(hashmicro_setup_from_options(plan.options))}
    plan.env_path.write_text(merge_env_text(existing_env, env_values, managed_keys=managed_env_keys() | set(env_values)))


def backup_soul_file(soul_path: Path) -> Path:
    backup_dir = soul_path.parent / "backups" / (
        "hermes-stack-bootstrap-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
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
    soul_path.write_text(generated.rstrip() + "\n", encoding="utf-8")
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


def require_tui(ui: RichPromptTui | None = None) -> RichPromptTui:
    return ui or create_tui()


def prompt_default(prompt: str, default: str, ui: RichPromptTui | None = None) -> str:
    return require_tui(ui).text(prompt, default)


def tui_step(tui: RichPromptTui, title: str) -> None:
    step = getattr(tui, "step", None)
    if callable(step):
        step(title)


@contextmanager
def tui_status(ui: RichPromptTui | None, message: str) -> Iterator[None]:
    status = getattr(ui, "status", None) if ui is not None else None
    if callable(status):
        with status(message):
            yield
        return
    print(message)
    yield


def _env_get(env: os._Environ[str] | dict[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    return value if value is not None else default


def _positive_int(value: object, *, field: str) -> int:
    text = str(value or "").strip().lower().replace(",", "").replace("_", "")
    if not text:
        return 0
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        parsed = int(float(text) * multiplier)
    except ValueError as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


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


def hashmicro_auxiliary_models_from_args(args: argparse.Namespace) -> dict[str, str]:
    models: dict[str, str] = {}
    aux_all = str(getattr(args, "aux_all_model", "") or "").strip()
    if aux_all:
        models.update({task: aux_all for task in AUXILIARY_TASKS})
    models.update(parse_aux_model_overrides(getattr(args, "aux_model", []) or []))
    return models


def hashmicro_auxiliary_context_lengths_from_args(
    args: argparse.Namespace,
    auxiliary_models: Mapping[str, str] | None = None,
    *,
    reasoning_effort: str = "",
    available_models: Iterable[str] | None = None,
) -> dict[str, int]:
    contexts: dict[str, int] = {}
    aux_all = _positive_int(getattr(args, "aux_all_context_length", ""), field="--aux-all-context-length")
    if aux_all:
        contexts.update({task: aux_all for task in AUXILIARY_TASKS})
    contexts.update(parse_aux_context_length_overrides(getattr(args, "aux_context_length", []) or []))
    detected_contexts = getattr(args, "hashmicro_detected_model_contexts", {}) or {}
    for task, model in (auxiliary_models or {}).items():
        if task not in contexts:
            effective_model = _hashmicro_effective_model(str(model), reasoning_effort, available_models)
            contexts[task] = _context_default_for_model(effective_model, detected_contexts)
    return {task: context for task, context in contexts.items() if context}


def _hashmicro_effective_model(model: str, effort: str, available_models: Iterable[str] | None = None) -> str:
    return hashmicro_model_with_reasoning_effort(model, effort, available_models) if effort else str(model or "").strip()


def _hashmicro_effective_auxiliary_models(options: InstallerOptions) -> dict[str, str]:
    effort = normalize_hashmicro_reasoning_effort(options.hashmicro_reasoning_effort)
    return {
        task: _hashmicro_effective_model(model, effort, options.hashmicro_available_models)
        for task, model in options.hashmicro_auxiliary_models.items()
        if str(model or "").strip()
    }


def _set_hashmicro_model_context(contexts: dict[str, int], model: str, context_length: int) -> None:
    if not model or not context_length:
        return
    if model in contexts and contexts[model] != int(context_length):
        raise ValueError(
            f"Conflicting context lengths for HashMicro model {model}: "
            f"{contexts[model]} vs {int(context_length)}"
        )
    contexts[model] = int(context_length)


def hashmicro_model_context_lengths_from_options(options: InstallerOptions) -> dict[str, int]:
    contexts: dict[str, int] = {}
    effort = normalize_hashmicro_reasoning_effort(options.hashmicro_reasoning_effort)
    if options.hashmicro_main_model and options.hashmicro_main_context_length:
        _set_hashmicro_model_context(
            contexts,
            _hashmicro_effective_model(options.hashmicro_main_model, effort, options.hashmicro_available_models),
            int(options.hashmicro_main_context_length),
        )
    if options.hashmicro_delegation_model and options.hashmicro_delegation_context_length:
        _set_hashmicro_model_context(
            contexts,
            _hashmicro_effective_model(options.hashmicro_delegation_model, effort, options.hashmicro_available_models),
            int(options.hashmicro_delegation_context_length),
        )
    for task, model in options.hashmicro_auxiliary_models.items():
        context_length = int(options.hashmicro_auxiliary_context_lengths.get(task, 0) or 0)
        if model and context_length:
            _set_hashmicro_model_context(
                contexts,
                _hashmicro_effective_model(str(model), effort, options.hashmicro_available_models),
                context_length,
            )
    return contexts


def hashmicro_setup_from_options(options: InstallerOptions) -> HashmicroProviderSetup:
    effort = normalize_hashmicro_reasoning_effort(options.hashmicro_reasoning_effort)
    return HashmicroProviderSetup(
        enabled=options.setup_hashmicro_provider,
        base_url=options.hashmicro_base_url,
        provider_name=options.hashmicro_provider_name,
        key_env=options.hashmicro_key_env,
        api_key=options.hashmicro_api_key,
        main_model=_hashmicro_effective_model(options.hashmicro_main_model, effort, options.hashmicro_available_models),
        delegation_model=_hashmicro_effective_model(options.hashmicro_delegation_model, effort, options.hashmicro_available_models),
        auxiliary_models=_hashmicro_effective_auxiliary_models(options),
        model_context_lengths=hashmicro_model_context_lengths_from_options(options),
        reasoning_effort=options.hashmicro_reasoning_effort,
    )


def apply_hashmicro_env_defaults(args: argparse.Namespace, env: os._Environ[str] | dict[str, str]) -> None:
    if not getattr(args, "setup_hashmicro_provider", False):
        return
    key_env = str(getattr(args, "hashmicro_key_env", "") or HASHMICRO_KEY_ENV).strip()
    if not getattr(args, "hashmicro_api_key", ""):
        args.hashmicro_api_key = _env_get(env, key_env, "")


def populate_hashmicro_model_metadata(args: argparse.Namespace) -> None:
    if not getattr(args, "setup_hashmicro_provider", False):
        return
    if getattr(args, "hashmicro_detected_models", None):
        return
    if not getattr(args, "hashmicro_api_key", ""):
        return
    try:
        models, contexts = fetch_openai_compatible_model_metadata(args.hashmicro_base_url, args.hashmicro_api_key)
    except Exception as exc:
        print(f"Warning: could not fetch HashMicro model list: {exc}", file=sys.stderr)
        return
    args.hashmicro_detected_models = tuple(models)
    args.hashmicro_detected_model_contexts = contexts


def validate_soul_options(args: argparse.Namespace) -> None:
    if not args.generate_soul or not args.yes:
        return
    required = {
        "soul_agent_name": "--soul-agent-name",
        "soul_user_name": "--soul-user-name",
    }
    for attr, flag in required.items():
        if not getattr(args, attr, "").strip():
            raise ValueError(f"--generate-soul requires {flag}")


def prompt_yes_no(prompt: str, default: bool = False, ui: RichPromptTui | None = None) -> bool:
    return require_tui(ui).confirm(prompt, default)


def prompt_missing_runtime_python(runtime: HermesRuntime, ui: RichPromptTui | None = None) -> tuple[HermesRuntime, bool]:
    tui = require_tui(ui)
    action = tui.select(
        "Hermes runtime Python was not found, so Mnemosyne cannot be installed safely yet.",
        ("Skip Mnemosyne", "Paste runtime Python path", "Abort"),
        "Skip Mnemosyne",
    )
    if action == "Skip Mnemosyne":
        return runtime, True
    if action == "Abort":
        raise ValueError("Aborted: Hermes runtime Python was not found")
    while True:
        answer = tui.text("Hermes runtime Python path", "")
        if not answer:
            continue
        candidate = Path(answer).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return dataclasses.replace(runtime, hermes_python=candidate, hermes_python_source="manual prompt"), False
        if tui.confirm(f"Not executable: {candidate}. Skip Mnemosyne instead?", True):
            return runtime, True


def select_provider_and_model(
    *,
    tui: RichPromptTui,
    providers: list[ProviderChoice],
    provider_prompt: str,
    model_prompt: str,
    current_provider: str = "",
    current_model: str = "",
    hermes_python: Path | None = None,
    hermes_home: Path | None = None,
) -> tuple[str, str]:
    if not providers:
        return current_provider, current_model
    by_label = {choice.label: choice for choice in providers}
    default_label = next((choice.label for choice in providers if choice.slug == current_provider), providers[0].label)
    provider_label = tui.select(provider_prompt, ("Use Hermes default", *by_label), "Use Hermes default" if not current_provider else default_label)
    if provider_label == "Use Hermes default":
        return "", ""
    provider = by_label[provider_label]
    models = model_choices_for_provider(provider.slug, providers, hermes_python, hermes_home)
    if not models:
        return provider.slug, current_model
    default_model = current_model if current_model in models else models[0]
    model = tui.select(model_prompt, models, default_model)
    return provider.slug, model


def select_model_from_detected_providers(
    *,
    tui: RichPromptTui,
    providers: list[ProviderChoice],
    prompt: str,
    current_model: str = "",
    default_model: str = "",
) -> str:
    models: list[str] = []
    seen: set[str] = set()
    for provider in providers:
        for model in provider.models:
            if model not in seen:
                seen.add(model)
                models.append(model)
    if not models:
        return tui.text(f"{prompt} (empty = Hermes auxiliary/default)", current_model or default_model)
    default = current_model if current_model in models else (default_model if default_model in models else models[0])
    return tui.select(prompt, models, default)


def choose_model_from_options(tui: RichPromptTui, prompt: str, models: list[str], current: str = "") -> str:
    if models:
        default = current if current in models else models[0]
        return tui.select(prompt, tuple(models), default)
    return tui.text(f"{prompt} (manual)", current)


def _context_default_for_model(model: str, detected_contexts: Mapping[str, int] | None = None) -> int:
    # User-confirmed correction: GPT-5.5 Codex variants are 272K even if a
    # live endpoint reports a larger generic context value.
    model_name = str(model or "")
    if "gpt-5.5" in model_name.lower() and "codex" in model_name.lower():
        return 272_000
    detected = detected_contexts or {}
    return int(detected.get(model_name) or default_hashmicro_context_length(model_name) or 0)


def prompt_hashmicro_context_length(
    tui: RichPromptTui,
    prompt: str,
    model: str,
    detected_contexts: Mapping[str, int] | None = None,
    current: object = "",
) -> int:
    default_value = _positive_int(current, field=prompt) or _context_default_for_model(model, detected_contexts)
    answer = tui.text(prompt, str(default_value) if default_value else "")
    return _positive_int(answer, field=prompt)


def choose_hashmicro_reasoning_effort(tui: RichPromptTui, current: str = "") -> str:
    default = normalize_hashmicro_reasoning_effort(current, default=HASHMICRO_DEFAULT_REASONING_EFFORT)
    return normalize_hashmicro_reasoning_effort(
        tui.select("HashMicro reasoning effort", HASHMICRO_REASONING_EFFORTS, default),
        default=HASHMICRO_DEFAULT_REASONING_EFFORT,
    )


def prompt_hashmicro_provider_setup(args: argparse.Namespace, tui: RichPromptTui, env: os._Environ[str] | dict[str, str]) -> None:
    if not prompt_yes_no("Configure recommended xAI HashMicro provider?", bool(args.setup_hashmicro_provider), tui):
        return
    args.setup_hashmicro_provider = True
    if not getattr(args, "hashmicro_api_key", ""):
        args.hashmicro_api_key = _env_get(env, args.hashmicro_key_env, "")
    if not args.hashmicro_api_key:
        args.hashmicro_api_key = tui.password("HashMicro API key (hidden; saved as XAI_HASHMICRO_API_KEY)").strip()
    models: list[str] = list(getattr(args, "hashmicro_detected_models", ()) or [])
    detected_contexts: dict[str, int] = dict(getattr(args, "hashmicro_detected_model_contexts", {}) or {})
    if args.hashmicro_api_key and not models:
        try:
            models, detected_contexts = fetch_openai_compatible_model_metadata(args.hashmicro_base_url, args.hashmicro_api_key)
        except Exception as exc:
            print(f"Warning: could not fetch HashMicro model list: {exc}", file=sys.stderr)
    args.hashmicro_detected_models = tuple(models)
    args.hashmicro_detected_model_contexts = detected_contexts
    args.main_model = choose_model_from_options(tui, "HashMicro main model", models, args.main_model)
    args.hashmicro_reasoning_effort = choose_hashmicro_reasoning_effort(
        tui,
        getattr(args, "hashmicro_reasoning_effort", "") or HASHMICRO_DEFAULT_REASONING_EFFORT,
    )
    args.main_context_length = str(
        prompt_hashmicro_context_length(
            tui,
            "HashMicro main context length",
            _hashmicro_effective_model(args.main_model, args.hashmicro_reasoning_effort, models),
            detected_contexts,
            getattr(args, "main_context_length", ""),
        )
    )
    args.delegation_model = choose_model_from_options(tui, "HashMicro delegation model", models, args.delegation_model or args.main_model)
    args.delegation_context_length = str(
        prompt_hashmicro_context_length(
            tui,
            "HashMicro delegation context length",
            _hashmicro_effective_model(args.delegation_model, args.hashmicro_reasoning_effort, models),
            detected_contexts,
            getattr(args, "delegation_context_length", ""),
        )
    )
    aux_default = choose_model_from_options(tui, "HashMicro default auxiliary model", models, getattr(args, "aux_all_model", "") or args.delegation_model or args.main_model)
    args.aux_all_model = aux_default
    args.aux_all_context_length = str(
        prompt_hashmicro_context_length(
            tui,
            "HashMicro default auxiliary context length",
            _hashmicro_effective_model(aux_default, args.hashmicro_reasoning_effort, models),
            detected_contexts,
            getattr(args, "aux_all_context_length", ""),
        )
    )
    if aux_default:
        args.aux_model = [override for override in (getattr(args, "aux_model", []) or []) if "=" in override]
    if prompt_yes_no("Customize per auxiliary task?", False, tui):
        overrides = parse_aux_model_overrides(args.aux_model or [])
        context_overrides = parse_aux_context_length_overrides(getattr(args, "aux_context_length", []) or [])
        for task in AUXILIARY_TASKS:
            current = overrides.get(task, aux_default)
            selected = choose_model_from_options(tui, f"HashMicro auxiliary model for {task}", models, current)
            if selected:
                overrides[task] = selected
                context_overrides[task] = prompt_hashmicro_context_length(
                    tui,
                    f"HashMicro auxiliary context length for {task}",
                    _hashmicro_effective_model(selected, args.hashmicro_reasoning_effort, models),
                    detected_contexts,
                    context_overrides.get(task) or args.aux_all_context_length,
                )
        args.aux_model = [f"{task}={model}" for task, model in overrides.items()]
        args.aux_context_length = [f"{task}={context}" for task, context in context_overrides.items()]


def hashmicro_provider_choice_from_args(args: argparse.Namespace) -> ProviderChoice | None:
    models = tuple(getattr(args, "hashmicro_detected_models", ()) or ())
    if not getattr(args, "setup_hashmicro_provider", False) or not models:
        return None
    label = f"xAI HashMicro — {len(models)} models"
    return ProviderChoice(f"custom:{args.hashmicro_provider_name}", label, models)


def prompt_hmx_gitlab_token_if_needed(args: argparse.Namespace, tui: RichPromptTui, env: os._Environ[str] | dict[str, str]) -> None:
    if not args.install_hmx_knowledge:
        return
    if not getattr(args, "hmx_gitlab_token", ""):
        args.hmx_gitlab_token = _env_get(env, "GITLAB_TOKEN", "")
    if not args.hmx_gitlab_token:
        args.hmx_gitlab_token = tui.password("HMX GitLab token (hidden; empty to use SSH/credential helper only)").strip()


def prompt_soul_answers(args: argparse.Namespace, ui: RichPromptTui | None = None) -> None:
    tui = require_tui(ui)
    args.soul_agent_name = prompt_default("Agent name", args.soul_agent_name or "Hermes", tui)
    args.soul_user_name = prompt_default("User name", args.soul_user_name, tui)
    args.soul_communication = prompt_default(
        "Communication style",
        args.soul_communication or DEFAULT_SOUL_COMMUNICATION_STYLE,
        tui,
    )
    args.soul_language = prompt_default(
        "Language",
        args.soul_language or DEFAULT_SOUL_LANGUAGE,
        tui,
    )


def prompt_soul_options(options: InstallerOptions, ui: RichPromptTui | None = None) -> InstallerOptions:
    tui = require_tui(ui)
    agent_name = prompt_default("Agent name", options.soul_agent_name or "Hermes", tui)
    user_name = prompt_default("User name", options.soul_user_name, tui)
    communication = prompt_default(
        "Communication style",
        options.soul_communication or DEFAULT_SOUL_COMMUNICATION_STYLE,
        tui,
    )
    language = prompt_default("Language", options.soul_language or DEFAULT_SOUL_LANGUAGE, tui)
    if not agent_name.strip() or not user_name.strip():
        raise ValueError("SOUL.md generation requires agent name and user name")
    return dataclasses.replace(
        options,
        generate_soul=True,
        soul_agent_name=agent_name,
        soul_user_name=user_name,
        soul_communication=communication or DEFAULT_SOUL_COMMUNICATION_STYLE,
        soul_language=language or DEFAULT_SOUL_LANGUAGE,
    )


def wizard(
    argv: Iterable[str] | None = None,
    *,
    env: os._Environ[str] | dict[str, str] | None = None,
    ui: RichPromptTui | None = None,
) -> InstallerOptions:
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
        default=_env_get(runtime_env, "HERMES_STACK_MNEMOSYNE_MODE", "hybrid"),
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
    parser.add_argument(
        "--install-mode",
        default=_env_get(runtime_env, "HERMES_STACK_INSTALL_MODE", "full"),
        metavar="{full,plugin-skill-only,soul-only}",
        help="Installer scope: full, plugin-skill-only, or soul-only. Aliases: plugins-only, skills-only, soul.",
    )
    parser.add_argument("--skip-lcm", action="store_true")
    parser.add_argument("--skip-mnemosyne", action="store_true")
    parser.add_argument("--skip-progress-tail", action="store_true")
    parser.add_argument("--skip-config-env", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument(
        "--progress-tail-ref",
        default=_env_get(runtime_env, "HERMES_STACK_PROGRESS_TAIL_REF", PROGRESS_TAIL_REF),
        help="hermes-progress-tail git ref or 'latest' to resolve the newest GitHub release",
    )
    parser.add_argument("--install-superpowers", action="store_true")
    parser.add_argument("--install-hmx-knowledge", action="store_true")
    parser.add_argument("--install-impeccable", action="store_true")
    parser.add_argument("--install-ponytail", action="store_true")
    parser.add_argument("--generate-soul", action="store_true", help="Generate SOUL.md once via the user's Hermes AI backend.")
    parser.add_argument("--soul-agent-name", default="")
    parser.add_argument("--soul-user-name", default="")
    parser.add_argument("--soul-role", default="")
    parser.add_argument("--soul-behavior", default="")
    parser.add_argument("--soul-communication", default=DEFAULT_SOUL_COMMUNICATION_STYLE)
    parser.add_argument("--soul-focus", default="")
    parser.add_argument("--soul-avoid", default="")
    parser.add_argument("--soul-language", default=DEFAULT_SOUL_LANGUAGE)
    parser.add_argument("--soul-provider", default="", help="Optional provider override for the Hermes SOUL generation call.")
    parser.add_argument("--soul-model", default="", help="Optional model override for the Hermes SOUL generation call.")
    parser.add_argument("--soul-overwrite", action="store_true", help="Allow replacing an existing SOUL.md after backup.")
    parser.add_argument(
        "--hmx-knowledge-url",
        default=_env_get(runtime_env, "HMX_KNOWLEDGE_GIT_URL", HMX_KNOWLEDGE_REPO),
        help="Private HMX knowledge repo URL. Prefer SSH or a git credential helper; do not put tokens in shell history.",
    )
    parser.set_defaults(hmx_gitlab_token=_env_get(runtime_env, "GITLAB_TOKEN", ""))
    parser.add_argument("--setup-hashmicro-provider", action="store_true", help="Configure the recommended xAI HashMicro OpenAI-compatible provider.")
    parser.add_argument("--hashmicro-base-url", default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_BASE_URL", HASHMICRO_BASE_URL))
    parser.add_argument("--hashmicro-provider-name", default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_PROVIDER_NAME", HASHMICRO_PROVIDER_NAME))
    parser.add_argument("--hashmicro-key-env", default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_KEY_ENV", HASHMICRO_KEY_ENV))
    parser.add_argument("--main-model", default=_env_get(runtime_env, "HERMES_STACK_MAIN_MODEL", ""), help="Main Hermes model when --setup-hashmicro-provider is enabled.")
    parser.add_argument("--main-context-length", default=_env_get(runtime_env, "HERMES_STACK_MAIN_CONTEXT_LENGTH", ""), help="Context length for the selected HashMicro main model, stored under custom_providers[].models.")
    parser.add_argument("--delegation-model", default=_env_get(runtime_env, "HERMES_STACK_DELEGATION_MODEL", ""), help="delegate_task model when --setup-hashmicro-provider is enabled.")
    parser.add_argument("--delegation-context-length", default=_env_get(runtime_env, "HERMES_STACK_DELEGATION_CONTEXT_LENGTH", ""), help="Context length for the selected HashMicro delegation model, stored under custom_providers[].models.")
    parser.add_argument("--aux-all-model", default=_env_get(runtime_env, "HERMES_STACK_AUX_ALL_MODEL", ""), help="Use one model for all known auxiliary tasks.")
    parser.add_argument("--aux-all-context-length", default=_env_get(runtime_env, "HERMES_STACK_AUX_ALL_CONTEXT_LENGTH", ""), help="Context length for --aux-all-model, stored under custom_providers[].models.")
    parser.add_argument("--aux-model", action="append", default=[], help="Auxiliary task override in task=model form. Repeatable.")
    parser.add_argument("--aux-context-length", action="append", default=[], help="Auxiliary context override in task=context_length form. Repeatable.")
    parser.add_argument(
        "--hashmicro-reasoning-effort",
        choices=HASHMICRO_REASONING_EFFORTS,
        default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_REASONING_EFFORT", HASHMICRO_DEFAULT_REASONING_EFFORT),
        help="Reasoning effort for HashMicro main/delegation routes.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    args.install_mode = normalize_install_mode(args.install_mode)
    if args.yes:
        apply_install_mode_defaults(args)
    apply_full_online_embedding_env_defaults(args, runtime_env)
    apply_hashmicro_env_defaults(args, runtime_env)
    populate_hashmicro_model_metadata(args)

    home = Path(args.home).expanduser() if args.home else detect_base_home(args.hermes_bin or None)
    runtime = discover_hermes_runtime(
        base_home=home,
        hermes_bin=args.hermes_bin,
        hermes_python=args.hermes_python,
        env=runtime_env,
    )
    profiles = parse_profiles(args.profile)
    if not args.yes:
        tui = require_tui(ui)
        tui.banner(
            "Hermes Stack Bootstrap",
            "Installs hermes-lcm, Mnemosyne, and hermes-progress-tail. Optional skill packs are prompted before install.",
        )
        tui_step(tui, "1. Install scope")
        args.install_mode = INSTALL_MODE_VALUES[
            tui.select("Install mode", tuple(INSTALL_MODE_VALUES), install_mode_label(args.install_mode))
        ]
        apply_install_mode_defaults(args)
        tui_step(tui, "2. Hermes target/runtime")
        home = Path(prompt_default("Hermes base path", str(home), tui)).expanduser()
        runtime = discover_hermes_runtime(
            base_home=home,
            hermes_bin=args.hermes_bin,
            hermes_python=args.hermes_python,
            env=runtime_env,
        )
        tui.runtime_summary(runtime)
        needs_provider_choices = (
            (not args.skip_mnemosyne and args.mnemosyne_mode in {"hybrid", "full-online"})
            or (not args.skip_config_env and not args.summary_model)
        )
        detected_providers = provider_choices(runtime.hermes_python, home) if needs_provider_choices else []
        if runtime.hermes_python is None and not args.skip_mnemosyne:
            runtime, skip_mnemosyne = prompt_missing_runtime_python(runtime, tui)
            args.skip_mnemosyne = skip_mnemosyne
        if args.profile is None:
            profiles = prompt_profiles(tui, home, profiles)
        if args.install_mode != "soul-only" and not args.skip_config_env:
            tui_step(tui, "3. Recommended provider setup")
            prompt_hashmicro_provider_setup(args, tui, runtime_env)
            hashmicro_choice = hashmicro_provider_choice_from_args(args)
            if hashmicro_choice:
                detected_providers = [hashmicro_choice, *detected_providers]
        if not args.skip_mnemosyne:
            tui_step(tui, "4. Model routing")
            args.mnemosyne_mode = tui.select(
                "Mnemosyne mode",
                tuple(MNEMOSYNE_MODES),
                args.mnemosyne_mode,
            ).strip().lower()
            if args.mnemosyne_mode not in MNEMOSYNE_MODES:
                raise ValueError(f"Unknown Mnemosyne mode: {args.mnemosyne_mode}")
        apply_full_online_embedding_env_defaults(args, runtime_env)
        if not args.skip_mnemosyne and args.mnemosyne_mode in {"hybrid", "full-online"}:
            args.mnemosyne_llm_provider, args.mnemosyne_llm_model = select_provider_and_model(
                tui=tui,
                providers=detected_providers,
                provider_prompt="Mnemosyne host LLM provider",
                model_prompt="Mnemosyne host LLM model",
                current_provider=args.mnemosyne_llm_provider,
                current_model=args.mnemosyne_llm_model,
                hermes_python=runtime.hermes_python,
                hermes_home=home,
            )
        if not args.skip_mnemosyne and args.mnemosyne_mode == "full-online":
            args.mnemosyne_embedding_api_url = prompt_default(
                "Mnemosyne embedding API URL (empty = configure later)",
                args.mnemosyne_embedding_api_url,
                tui,
            )
            if args.mnemosyne_embedding_api_url:
                if not args.mnemosyne_embedding_api_key:
                    args.mnemosyne_embedding_api_key = tui.password(
                        "Mnemosyne embedding API key (hidden; empty if endpoint needs no key)"
                    ).strip()
                args.mnemosyne_embedding_model = prompt_default(
                    "Mnemosyne embedding model", args.mnemosyne_embedding_model, tui
                )
                args.mnemosyne_embedding_dim = prompt_default(
                    "Mnemosyne embedding dimension", args.mnemosyne_embedding_dim, tui
                )
        if not args.skip_config_env and not args.summary_model:
            if args.skip_mnemosyne:
                tui_step(tui, "4. Model routing")
            args.lcm_summary_model = select_model_from_detected_providers(
                tui=tui,
                providers=detected_providers,
                prompt="LCM summary model",
                current_model=args.lcm_summary_model,
            )
            args.lcm_expansion_model = select_model_from_detected_providers(
                tui=tui,
                providers=detected_providers,
                prompt="LCM expansion model",
                current_model=args.lcm_expansion_model,
                default_model=args.lcm_summary_model,
            )
        if args.install_mode != "soul-only" and not args.skip_config_env:
            tui_step(tui, "5. Stack components")
        if args.install_mode != "soul-only":
            tui_step(tui, "6. Skill packs and credentials")
        if args.install_mode != "soul-only" and not args.install_superpowers:
            args.install_superpowers = prompt_yes_no("Install Obra Superpowers skill pack?", False, tui)
        if args.install_mode != "soul-only" and not args.install_hmx_knowledge:
            args.install_hmx_knowledge = prompt_yes_no("Install HMX knowledge skill pack?", False, tui)
        if args.install_mode != "soul-only" and args.install_hmx_knowledge:
            prompt_hmx_gitlab_token_if_needed(args, tui, runtime_env)
        if args.install_mode != "soul-only" and not args.install_impeccable:
            args.install_impeccable = prompt_yes_no("Install Impeccable design skill?", False, tui)
        if args.install_mode != "soul-only" and not args.install_ponytail:
            args.install_ponytail = prompt_yes_no("Install strongly recommended Ponytail skill pack?", True, tui)
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

    hashmicro_aux_models = hashmicro_auxiliary_models_from_args(args)
    detected_hashmicro_contexts = getattr(args, "hashmicro_detected_model_contexts", {}) or {}
    detected_hashmicro_models = tuple(getattr(args, "hashmicro_detected_models", ()) or ())
    hashmicro_reasoning_effort = ""
    if args.setup_hashmicro_provider:
        hashmicro_reasoning_effort = normalize_hashmicro_reasoning_effort(
            args.hashmicro_reasoning_effort,
            default=HASHMICRO_DEFAULT_REASONING_EFFORT,
        )
    hashmicro_main_context_length = _positive_int(args.main_context_length, field="--main-context-length")
    if args.setup_hashmicro_provider and args.main_model and not hashmicro_main_context_length:
        hashmicro_main_context_length = _context_default_for_model(
            _hashmicro_effective_model(args.main_model, hashmicro_reasoning_effort, detected_hashmicro_models),
            detected_hashmicro_contexts,
        )
    hashmicro_delegation_context_length = _positive_int(args.delegation_context_length, field="--delegation-context-length")
    if args.setup_hashmicro_provider and args.delegation_model and not hashmicro_delegation_context_length:
        hashmicro_delegation_context_length = _context_default_for_model(
            _hashmicro_effective_model(args.delegation_model, hashmicro_reasoning_effort, detected_hashmicro_models),
            detected_hashmicro_contexts,
        )
    hashmicro_aux_contexts = hashmicro_auxiliary_context_lengths_from_args(
        args,
        hashmicro_aux_models,
        reasoning_effort=hashmicro_reasoning_effort,
        available_models=detected_hashmicro_models,
    )

    return InstallerOptions(
        base_home=home,
        profile=profile,
        hermes_bin=runtime.hermes_bin or args.hermes_bin or "hermes",
        hermes_bin_source=runtime.hermes_bin_source,
        hermes_python=runtime.hermes_python,
        hermes_python_source=runtime.hermes_python_source,
        yes=args.yes,
        dry_run=args.dry_run,
        install_mode=args.install_mode,
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
        skip_config_env=args.skip_config_env,
        skip_verify=args.skip_verify,
        progress_tail_ref=args.progress_tail_ref,
        install_superpowers=args.install_superpowers,
        install_hmx_knowledge=args.install_hmx_knowledge,
        install_impeccable=args.install_impeccable,
        install_ponytail=args.install_ponytail,
        hmx_knowledge_url=args.hmx_knowledge_url,
        hmx_gitlab_token=args.hmx_gitlab_token,
        setup_hashmicro_provider=args.setup_hashmicro_provider,
        hashmicro_base_url=args.hashmicro_base_url,
        hashmicro_provider_name=args.hashmicro_provider_name,
        hashmicro_key_env=args.hashmicro_key_env,
        hashmicro_api_key=getattr(args, "hashmicro_api_key", ""),
        hashmicro_main_model=args.main_model,
        hashmicro_main_context_length=hashmicro_main_context_length,
        hashmicro_delegation_model=args.delegation_model,
        hashmicro_delegation_context_length=hashmicro_delegation_context_length,
        hashmicro_auxiliary_models=hashmicro_aux_models,
        hashmicro_auxiliary_context_lengths=hashmicro_aux_contexts,
        hashmicro_reasoning_effort=hashmicro_reasoning_effort,
        hashmicro_available_models=tuple(getattr(args, "hashmicro_detected_models", ()) or ()),
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
