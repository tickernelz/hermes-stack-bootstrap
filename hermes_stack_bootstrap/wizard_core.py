"""Shared state and helpers for the Hermes stack bootstrap wizard."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .bootstrap_data import (
    HASHMICRO_BASE_URL,
    HASHMICRO_KEY_ENV,
    HASHMICRO_PROVIDER_NAME,
    HMX_KNOWLEDGE_REPO,
    PROGRESS_TAIL_REF,
)
from .provider_setup import AUXILIARY_TASKS, parse_aux_context_length_overrides, parse_aux_model_overrides

TOTAL_STEPS = 9
CHOICES_DIR = Path("~/.config/hermes-stack-bootstrap/profiles").expanduser()
MODES = {
    "Full stack install or update": "full",
    "Provider/model setup only": "provider-only",
    "Skills only": "skills-only",
    "Plugins/tools only": "plugins-only",
    "Repair or verify existing install": "verify",
    "Dry run / preview only": "dry-run",
}
COMPONENTS = {
    "Core config merge": "config",
    "Plugins/tools": "plugins",
    "Skills": "skills",
    "Cron jobs": "cron",
    "Memories/templates": "memories",
    "SOUL.md generation/update": "soul",
    "Verification smoke tests": "verify",
}


class WizardTui(Protocol):
    def step(self, *args: Any) -> None: ...
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def select(self, prompt: str, choices: Sequence[Any], default: Any = None) -> Any: ...
    def multi_select(
        self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None
    ) -> Sequence[Any]: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...
    def text(self, prompt: str, default: str | None = None, validate: Any = None) -> str: ...
    def password(self, prompt: str, env_name: str | None = None) -> str: ...
    def summary_table(self, title: str, rows: Sequence[tuple[str, str]]) -> None: ...
    def progress(self, label: str, current: int, total: int) -> None: ...
    def spinner(self, label: str): ...


@dataclass
class Choice:
    label: str
    value: str
    description: str = ""
    disabled: bool = False
    recommended: bool = False
    danger: bool = False

    def __str__(self) -> str:
        suffix = " (disabled)" if self.disabled else ""
        return f"{self.label}{suffix}"


@dataclass
class WizardState:
    env: Mapping[str, str]
    saved: dict[str, Any] = field(default_factory=dict)
    mode: str = "full"
    dry_run: bool = False
    home: Path = field(default_factory=lambda: Path("~/.hermes").expanduser())
    profile: str = "default"
    hermes_bin: str = "hermes"
    hermes_python: Path | None = None
    hermes_python_source: str = "skip"
    provider_kind: str = "hashmicro"
    provider_name: str = HASHMICRO_PROVIDER_NAME
    base_url: str = HASHMICRO_BASE_URL
    key_env: str = HASHMICRO_KEY_ENV
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    main_model: str = "gpt-5.5"
    delegation_model: str = "gpt-5.5"
    context: int = 272000
    delegation_context: int = 272000
    aux: dict[str, str] = field(default_factory=dict)
    aux_contexts: dict[str, int] = field(default_factory=dict)
    components: set[str] = field(default_factory=lambda: {"config", "plugins", "skills", "verify"})
    skill_packs: set[str] = field(default_factory=lambda: {"core", "recommended"})
    hmx_token: str = ""
    conflict_policy: str = "ask"
    conflict_decisions: dict[str, str] = field(default_factory=dict)
    action: str = "apply"
    save_profile: str = ""
    cli_yes: bool = False
    cli_install_mode: str | None = None
    cli_skip_lcm: bool = False
    cli_skip_progress_tail: bool = False
    mnemosyne_mode: str = "hybrid"
    progress_tail_ref: str = PROGRESS_TAIL_REF
    generate_soul_requested: bool = False
    soul_agent_name: str = "Assistant"
    soul_user_name: str = "User"
    soul_communication: str = ""
    soul_language: str = ""
    soul_provider: str = ""
    soul_model: str = ""
    soul_overwrite: bool = False


def _value(x: Any) -> Any:
    return getattr(x, "value", x)


def _label(x: Any) -> str:
    return getattr(x, "label", str(x))


def _choose(ui: WizardTui, prompt: str, choices: Sequence[Choice], default: str) -> str:
    default_choice = next((c for c in choices if c.value == default and not c.disabled), None)
    return str(_value(ui.select(prompt, choices, default_choice or choices[0])))


def _multi(ui: WizardTui, prompt: str, choices: Sequence[Choice], defaults: set[str]) -> set[str]:
    d = [c for c in choices if c.value in defaults and not c.disabled]
    return {str(_value(c)) for c in ui.multi_select(prompt, choices, d)}


def _apply_cli_flags(state: WizardState, flags: Mapping[str, Any]) -> None:
    state.cli_yes = bool(flags.get("yes"))
    if flags.get("home"):
        state.home = Path(str(flags["home"])).expanduser()
    if flags.get("hermes_bin"):
        state.hermes_bin = str(flags["hermes_bin"])
    if flags.get("hermes_python"):
        state.hermes_python = Path(str(flags["hermes_python"])).expanduser()
        state.hermes_python_source = "cli"
    if flags.get("mnemosyne_mode"):
        state.mnemosyne_mode = str(flags["mnemosyne_mode"])
    if flags.get("progress_tail_ref"):
        state.progress_tail_ref = str(flags["progress_tail_ref"])
    if flags.get("dry_run"):
        state.dry_run = True
        state.mode = "dry-run"
        state.action = "plan"
    elif state.cli_yes:
        state.action = "apply"
    if flags.get("profile"):
        state.profile = str(flags["profile"])
    if flags.get("install_mode"):
        state.cli_install_mode = str(flags["install_mode"])
        if state.cli_install_mode == "soul-only":
            state.components = {"soul", "verify"}
            state.generate_soul_requested = True
        elif state.cli_install_mode == "plugin-skill-only":
            state.components = {"plugins", "skills", "verify"}
        else:
            state.components = {"config", "plugins", "skills", "memories", "verify"}
    if flags.get("generate_soul"):
        state.components.add("soul")
        state.generate_soul_requested = True
    for flag, component in (("skip_mnemosyne", "memories"), ("skip_config_env", "config"), ("skip_verify", "verify")):
        if flags.get(flag):
            state.components.discard(component)
    state.cli_skip_lcm = bool(flags.get("skip_lcm"))
    state.cli_skip_progress_tail = bool(flags.get("skip_progress_tail"))
    if state.cli_skip_lcm and state.cli_skip_progress_tail:
        state.components.discard("plugins")
    if "skills" in state.components and any(
        flags.get(name)
        for name in ("install_superpowers", "install_hmx_knowledge", "install_impeccable", "install_ponytail")
    ):
        if flags.get("install_superpowers") or flags.get("install_impeccable") or flags.get("install_ponytail"):
            state.skill_packs.add("recommended")
        if flags.get("install_hmx_knowledge"):
            state.skill_packs.add("hmx")
    _apply_provider_cli_flags(state, flags)
    _apply_soul_cli_flags(state, flags)


def _apply_provider_cli_flags(state: WizardState, flags: Mapping[str, Any]) -> None:
    if not flags.get("setup_hashmicro_provider"):
        return
    state.provider_kind = "hashmicro"
    state.provider_name = str(flags.get("hashmicro_provider_name") or HASHMICRO_PROVIDER_NAME)
    state.base_url = str(flags.get("hashmicro_base_url") or HASHMICRO_BASE_URL)
    state.key_env = str(flags.get("hashmicro_key_env") or HASHMICRO_KEY_ENV)
    if state.env.get(state.key_env):
        state.api_key = state.env[state.key_env]
    if flags.get("main_model"):
        state.main_model = str(flags["main_model"])
    if flags.get("main_context_length"):
        state.context = int(flags["main_context_length"])
    if flags.get("delegation_model"):
        state.delegation_model = str(flags["delegation_model"])
    state.delegation_context = (
        int(flags["delegation_context_length"]) if flags.get("delegation_context_length") else state.context
    )
    aux_models: dict[str, str] = {}
    if flags.get("aux_all_model"):
        aux_models.update({task: str(flags["aux_all_model"]) for task in AUXILIARY_TASKS})
    aux_models.update(parse_aux_model_overrides(flags.get("aux_model") or []))
    if aux_models:
        state.aux = aux_models
    aux_contexts: dict[str, int] = {}
    if flags.get("aux_all_context_length"):
        aux_contexts.update({task: int(flags["aux_all_context_length"]) for task in AUXILIARY_TASKS})
    aux_contexts.update(parse_aux_context_length_overrides(flags.get("aux_context_length") or []))
    if aux_contexts:
        state.aux_contexts = aux_contexts


def _apply_soul_cli_flags(state: WizardState, flags: Mapping[str, Any]) -> None:
    for field_name in (
        "soul_agent_name",
        "soul_user_name",
        "soul_communication",
        "soul_language",
        "soul_provider",
        "soul_model",
    ):
        if flags.get(field_name):
            setattr(state, field_name, str(flags[field_name]))
    state.soul_overwrite = bool(flags.get("soul_overwrite"))


def _load_yaml_json(path: Path) -> dict[str, Any]:
    text = path.expanduser().read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return dict(json.loads(text))
    try:
        import yaml  # type: ignore

        return dict(yaml.safe_load(text) or {})
    except ImportError:
        data: dict[str, Any] = {}
        for line in text.splitlines():
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                data[k.strip()] = v.strip().strip("'\"")
        return data


def _save_choices(state: WizardState, choices_dir: Path = CHOICES_DIR) -> Path | None:
    if not state.save_profile:
        return None
    choices_dir.mkdir(parents=True, exist_ok=True)
    path = choices_dir / f"{state.save_profile}.json"
    data = {
        "version": 1,
        "mode": state.mode,
        "hermes_home": str(state.home),
        "profile": state.profile,
        "provider": {
            "kind": state.provider_kind,
            "provider_name": state.provider_name,
            "base_url": state.base_url,
            "key_env": state.key_env,
        },
        "models": {
            "main": state.main_model,
            "delegation": state.delegation_model,
            "aux_overrides": state.aux,
            "context": state.context,
            "delegation_context": state.delegation_context,
            "aux_contexts": state.aux_contexts,
        },
        "components": sorted(state.components),
        "skills": {"packs": sorted(state.skill_packs), "conflict_policy": state.conflict_policy},
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _detect_homes(env: Mapping[str, str]) -> list[Path]:
    homes = [Path("~/.hermes").expanduser()]
    if env.get("HERMES_HOME"):
        homes.insert(0, Path(env["HERMES_HOME"]).expanduser())
    cwd_home = Path.cwd() / ".hermes"
    if cwd_home.exists():
        homes.append(cwd_home)
    return list(dict.fromkeys(homes))


def _fetch_models(base_url: str, key_env: str, env: Mapping[str, str], api_key: str = "") -> list[str]:
    key = api_key or env.get(key_env, "")
    req = urllib.request.Request(base_url.rstrip("/") + "/models")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310 - user-selected endpoint
        payload = json.loads(response.read().decode("utf-8"))
    return sorted(str(item.get("id")) for item in payload.get("data", []) if item.get("id"))
