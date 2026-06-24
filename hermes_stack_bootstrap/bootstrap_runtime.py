"""Runtime/profile discovery and option normalization helpers."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from .bootstrap_data import INSTALL_MODE_CHOICES, INSTALL_MODE_LABELS, INSTALL_MODE_VALUES, InstallerOptions
from .bootstrap_tui import RichPromptTui


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


def prompt_profiles(
    tui: RichPromptTui, base_home: Path, current_profiles: Iterable[str] | str | None = None
) -> tuple[str, ...]:
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
