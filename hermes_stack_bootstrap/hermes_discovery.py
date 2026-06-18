"""Fast, flexible discovery for Hermes CLI and runtime Python.

The bootstrapper writes profile files under HERMES_HOME, but packages must be
installed into the Python environment that actually runs Hermes. Those are not
always the same tree: shared servers often keep Hermes under a global directory
while every user keeps profiles under ~/.hermes.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


EXCLUDED_DIR_NAMES = {
    ".cache",
    ".git",
    "__pycache__",
    "node_modules",
    "proc",
    "sys",
    "dev",
    "run",
    "tmp",
    "var/tmp",
    "lost+found",
}
EXCLUDED_ROOT_PREFIXES = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
    "/var/tmp",
    "/mnt",
    "/media",
)
DIRECTORY_PRIORITY_NAMES = {
    "bin": 0,
    ".local": 1,
    "venv": 1,
    ".venv": 1,
    "current": 2,
    "apps": 2,
    "shared": 2,
    "hermes": 2,
}


@dataclass(frozen=True)
class HermesRuntime:
    hermes_bin: str | None
    hermes_bin_source: str
    hermes_python: Path | None
    hermes_python_source: str


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _looks_like_python_executable(path: Path | str) -> bool:
    return Path(path).name.startswith("python")


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser().absolute()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def find_hermes_bins_from_path(*, env: Mapping[str, str] | None = None) -> list[Path]:
    """Return every executable named `hermes` found in PATH order."""
    runtime_env = os.environ if env is None else env
    candidates: list[Path] = []
    for raw_dir in runtime_env.get("PATH", "").split(os.pathsep):
        if not raw_dir:
            continue
        candidate = Path(raw_dir).expanduser() / "hermes"
        if _is_executable(candidate):
            candidates.append(candidate)
    return _dedupe_paths(candidates)


def _resolve_env_utility_from_shebang_tokens(tokens: list[str], *, env: Mapping[str, str]) -> Path | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if token == "-S":
            index += 1
            break
        if token in {"-u", "-C", "-P"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if "=" in token and not token.startswith("/"):
            index += 1
            continue
        break

    if index >= len(tokens):
        return None
    executable_name = tokens[index]
    if not _looks_like_python_executable(executable_name):
        return None
    executable_path = Path(executable_name).expanduser()
    if executable_path.is_absolute() and _is_executable(executable_path):
        return executable_path.resolve()
    for raw_dir in env.get("PATH", "").split(os.pathsep):
        if not raw_dir:
            continue
        candidate = Path(raw_dir).expanduser() / executable_name
        if _is_executable(candidate):
            return candidate.resolve()
    return None


def _python_from_env_shebang(target: str, *, env: Mapping[str, str] | None = None) -> Path | None:
    runtime_env = os.environ if env is None else env
    parts = target.split()
    if len(parts) < 2 or Path(parts[0]).name != "env":
        return None
    return _resolve_env_utility_from_shebang_tokens(parts, env=runtime_env)


def infer_python_from_hermes_bin(hermes_bin: str | Path, *, env: Mapping[str, str] | None = None) -> Path | None:
    """Infer the Python executable that owns a Hermes script, if obvious.

    Fast checks only: realpath sibling `python`/`python3` first, then an absolute
    or `/usr/bin/env python...` shebang.
    """
    path = Path(hermes_bin).expanduser()
    try:
        real = path.resolve()
    except OSError:
        real = path.absolute()

    for sibling in (real.parent / "python", real.parent / "python3"):
        if _is_executable(sibling):
            return sibling.resolve()

    try:
        with real.open("rb") as handle:
            first_line = handle.readline(512).decode("utf-8", errors="ignore").strip()
    except OSError:
        return None

    if not first_line.startswith("#!"):
        return None
    target = first_line[2:].strip()
    if target.startswith("/"):
        first_token = target.split()[0]
        if Path(first_token).name == "env":
            return _python_from_env_shebang(target, env=env)
        candidate = Path(first_token)
        if _looks_like_python_executable(candidate) and _is_executable(candidate):
            return candidate.resolve()
    return _python_from_env_shebang(target, env=env)


def _should_skip_dir(path: Path, *, skip_root_prefixes: bool = True) -> bool:
    name = path.name
    if name in EXCLUDED_DIR_NAMES:
        return True
    if not skip_root_prefixes:
        return False
    raw = str(path)
    return any(raw == prefix or raw.startswith(prefix + os.sep) for prefix in EXCLUDED_ROOT_PREFIXES)


def _sort_dirs(dirs: Iterable[Path]) -> list[Path]:
    return sorted(
        dirs,
        key=lambda path: (DIRECTORY_PRIORITY_NAMES.get(path.name, 10), len(path.parts), path.name),
    )


def scan_filesystem_for_hermes(
    *,
    roots: Iterable[Path] | None = None,
    deadline_seconds: float = 4.0,
    max_results: int = 10,
    max_dirs: int = 25_000,
) -> list[Path]:
    """Bounded BFS for executable files named `hermes`.

    This intentionally searches by executable name and deadline rather than
    assuming a fixed directory such as /opt. It prunes pseudo filesystems and
    common huge/noisy trees, then stops as soon as enough good candidates or the
    deadline is reached.
    """
    start = time.monotonic()
    explicit_roots = roots is not None
    queue = [Path("/")] if roots is None else [path.expanduser() for path in roots]
    results: list[Path] = []
    visited_dirs = 0

    while queue and len(results) < max_results and visited_dirs < max_dirs:
        if time.monotonic() - start > deadline_seconds:
            break
        current = queue.pop(0)
        if _should_skip_dir(current, skip_root_prefixes=not explicit_roots):
            continue
        visited_dirs += 1
        try:
            candidate = current / "hermes"
            if _is_executable(candidate):
                results.append(candidate)
            children = [entry for entry in current.iterdir() if entry.is_dir() and not entry.is_symlink()]
        except OSError:
            continue
        queue.extend(
            _sort_dirs(
                child
                for child in children
                if not _should_skip_dir(child, skip_root_prefixes=not explicit_roots)
            )
        )

    return _dedupe_paths(results)


def _runtime_python_from_profile_home(base_home: Path) -> Path | None:
    candidate = base_home.expanduser() / "hermes-agent" / "venv" / "bin" / "python"
    return candidate if _is_executable(candidate) else None


def _select_hermes_bin(
    *,
    explicit_bin: str,
    env: Mapping[str, str],
    scan_filesystem: bool,
) -> tuple[str | None, str]:
    if explicit_bin:
        return str(Path(explicit_bin).expanduser()), "explicit"

    path_candidates = find_hermes_bins_from_path(env=env)
    if path_candidates:
        return str(path_candidates[0]), "PATH"

    if scan_filesystem:
        fs_candidates = scan_filesystem_for_hermes()
        if fs_candidates:
            return str(fs_candidates[0]), "bounded filesystem scan"

    return None, "not found"


def discover_hermes_runtime(
    *,
    base_home: Path,
    hermes_bin: str = "",
    hermes_python: str = "",
    env: Mapping[str, str] | None = None,
    scan_filesystem: bool = True,
) -> HermesRuntime:
    """Discover Hermes CLI and the Python runtime used for package installs."""
    runtime_env = os.environ if env is None else env
    explicit_bin = hermes_bin or runtime_env.get("HERMES_BIN", "")
    explicit_python = hermes_python or runtime_env.get("HERMES_STACK_PYTHON", "")

    selected_bin, bin_source = _select_hermes_bin(
        explicit_bin=explicit_bin,
        env=runtime_env,
        scan_filesystem=scan_filesystem,
    )

    if explicit_python:
        return HermesRuntime(
            hermes_bin=selected_bin,
            hermes_bin_source=bin_source,
            hermes_python=Path(explicit_python).expanduser(),
            hermes_python_source="explicit",
        )

    inferred = infer_python_from_hermes_bin(selected_bin, env=runtime_env) if selected_bin else None
    if inferred is not None:
        return HermesRuntime(
            hermes_bin=selected_bin,
            hermes_bin_source=bin_source,
            hermes_python=inferred,
            hermes_python_source="inferred from Hermes CLI",
        )

    profile_python = _runtime_python_from_profile_home(base_home)
    if profile_python is not None:
        return HermesRuntime(
            hermes_bin=selected_bin,
            hermes_bin_source=bin_source,
            hermes_python=profile_python,
            hermes_python_source="profile-local Hermes runtime",
        )

    return HermesRuntime(
        hermes_bin=selected_bin,
        hermes_bin_source=bin_source,
        hermes_python=None,
        hermes_python_source="not found",
    )
