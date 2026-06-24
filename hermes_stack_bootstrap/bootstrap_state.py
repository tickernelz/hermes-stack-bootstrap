"""Persist installer wizard defaults between runs."""

from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .bootstrap_data import InstallerOptions

STATE_FILENAME = ".hermes-stack-bootstrap.json"
SECRET_OPTION_KEYS = {
    "hmx_gitlab_token",
    "hashmicro_api_key",
    "mnemosyne_embedding_api_key",
}
STATE_TO_ARG_KEYS = {
    "hashmicro_main_model": "main_model",
    "hashmicro_main_context_length": "main_context_length",
    "hashmicro_delegation_model": "delegation_model",
    "hashmicro_delegation_context_length": "delegation_context_length",
}
ARG_TO_STATE_KEYS = {value: key for key, value in STATE_TO_ARG_KEYS.items()}
SAVED_ARG_KEYS = {
    "profile",
    "install_mode",
    "mnemosyne_mode",
    "mnemosyne_llm_provider",
    "mnemosyne_llm_model",
    "mnemosyne_embedding_api_url",
    "mnemosyne_embedding_model",
    "mnemosyne_embedding_dim",
    "skip_lcm",
    "skip_mnemosyne",
    "skip_progress_tail",
    "skip_config_env",
    "skip_verify",
    "progress_tail_ref",
    "install_superpowers",
    "install_hmx_knowledge",
    "install_impeccable",
    "install_ponytail",
    "hmx_knowledge_url",
    "setup_hashmicro_provider",
    "hashmicro_base_url",
    "hashmicro_provider_name",
    "hashmicro_key_env",
    "main_model",
    "main_context_length",
    "delegation_model",
    "delegation_context_length",
    "aux_all_model",
    "aux_all_context_length",
    "aux_model",
    "aux_context_length",
    "hashmicro_reasoning_effort",
    "generate_soul",
    "soul_agent_name",
    "soul_user_name",
    "soul_communication",
    "soul_language",
    "soul_provider",
    "soul_model",
}


def state_path_for(target_home: Path) -> Path:
    return target_home.expanduser() / STATE_FILENAME


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def explicit_flags_from_argv(argv: Iterable[str] | None) -> set[str]:
    if argv is None:
        return set()
    flags: set[str] = set()
    for raw in argv:
        item = str(raw)
        if item.startswith("--"):
            flags.add(item.split("=", 1)[0])
        elif item in {"-y"}:
            flags.add("--yes")
    return flags


def _flag_for_attr(attr: str) -> str:
    return "--" + attr.replace("_", "-")


def _coerce_for_existing(current: Any, value: Any) -> Any:
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, tuple):
        return tuple(value) if isinstance(value, (list, tuple)) else tuple(str(value).split(","))
    if isinstance(current, list):
        return list(value) if isinstance(value, list) else [str(value)]
    return str(value) if current is None or isinstance(current, str) else value


def apply_saved_state(args: argparse.Namespace, state: Mapping[str, Any], explicit_flags: set[str]) -> None:
    for state_key, value in state.items():
        if state_key in SECRET_OPTION_KEYS or value in (None, ""):
            continue
        attr = STATE_TO_ARG_KEYS.get(state_key, state_key)
        if attr == "profile":
            flag = "--profile"
        else:
            flag = _flag_for_attr(attr)
        if flag in explicit_flags:
            continue
        if attr == "setup_hashmicro_provider" and "--setup-hashmicro-provider" in explicit_flags:
            continue
        if not hasattr(args, attr):
            continue
        if attr == "profile":
            setattr(args, attr, [str(value)])
            continue
        setattr(args, attr, _coerce_for_existing(getattr(args, attr), value))


def _state_value_for_options(options: InstallerOptions, key: str) -> Any:
    option_key = ARG_TO_STATE_KEYS.get(key, key)
    value = getattr(options, option_key)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def options_state(options: InstallerOptions) -> dict[str, Any]:
    values: dict[str, Any] = {}
    raw = asdict(options)
    for key in SAVED_ARG_KEYS:
        option_key = ARG_TO_STATE_KEYS.get(key, key)
        if option_key in SECRET_OPTION_KEYS or option_key not in raw:
            continue
        value = _state_value_for_options(options, key)
        if value in (None, "", {}, []):
            continue
        values[key] = str(value) if isinstance(value, int) else value
    return values


def save_options_state(path: Path, options: InstallerOptions) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(options_state(options), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_env_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError:
            parsed = [raw_value.strip().strip('"').strip("'")]
        values[key.strip()] = parsed[0] if parsed else ""
    return values
