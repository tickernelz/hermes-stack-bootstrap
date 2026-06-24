"""HashMicro/xAI provider setup helpers for hermes-stack-bootstrap."""

from __future__ import annotations

import json
import re
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


HASHMICRO_PROVIDER_NAME = "xai-hashmicro"
HASHMICRO_BASE_URL = "https://xai.hashmicro.co/v1"
HASHMICRO_KEY_ENV = "XAI_HASHMICRO_API_KEY"
HASHMICRO_API_MODE = "chat_completions"

AUXILIARY_TASKS = (
    "vision",
    "web_extract",
    "compression",
    "skills_hub",
    "approval",
    "mcp",
    "title_generation",
    "tts_audio_tags",
    "triage_specifier",
    "kanban_decomposer",
    "profile_describer",
    "curator",
    "monitor",
    "background_review",
)

_SECRET_KEY_RE = re.compile(r"(?:API_KEY|TOKEN|SECRET|PASSWORD)$", re.IGNORECASE)


@dataclass(frozen=True)
class HashmicroProviderSetup:
    enabled: bool = False
    base_url: str = HASHMICRO_BASE_URL
    provider_name: str = HASHMICRO_PROVIDER_NAME
    key_env: str = HASHMICRO_KEY_ENV
    api_key: str = ""
    api_mode: str = HASHMICRO_API_MODE
    discover_models: bool = True
    main_model: str = ""
    delegation_model: str = ""
    auxiliary_models: Mapping[str, str] = field(default_factory=dict)

    @property
    def provider_id(self) -> str:
        return f"custom:{self.provider_name.strip()}"


def _model_id_from_item(item: Any) -> str:
    if isinstance(item, dict):
        value = item.get("id") or item.get("name")
        return str(value).strip() if value else ""
    return str(item).strip()


def parse_openai_compatible_models_response(payload: bytes | str | Mapping[str, Any] | list[Any]) -> list[str]:
    """Return ordered model IDs from an OpenAI-compatible /models response."""
    if isinstance(payload, bytes):
        data: Any = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    items = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    models: list[str] = []
    seen: set[str] = set()
    for item in items:
        model = _model_id_from_item(item)
        if model and model not in seen:
            models.append(model)
            seen.add(model)
    return models


def fetch_openai_compatible_models(base_url: str, api_key: str, *, timeout: float = 30.0) -> list[str]:
    """Fetch model IDs from an OpenAI-compatible endpoint's /models API."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured API endpoint
        return parse_openai_compatible_models_response(response.read())


def _provider_entry(setup: HashmicroProviderSetup) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": setup.provider_name.strip(),
        "base_url": setup.base_url.strip().rstrip("/"),
        "key_env": setup.key_env.strip(),
        "api_mode": setup.api_mode.strip() or HASHMICRO_API_MODE,
        "discover_models": bool(setup.discover_models),
    }
    if setup.main_model.strip():
        entry["model"] = setup.main_model.strip()
    return entry


def _merge_custom_provider_entries(existing: Any, setup: HashmicroProviderSetup) -> list[dict[str, Any]]:
    new_entry = _provider_entry(setup)
    target_name = setup.provider_name.strip().lower()
    entries: list[dict[str, Any]] = []
    replaced = False
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            if name == target_name:
                entries.append(new_entry)
                replaced = True
            else:
                entries.append(deepcopy(item))
    if not replaced:
        entries.append(new_entry)
    return entries


def _ensure_mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def merge_hashmicro_provider_config(existing: Mapping[str, Any] | None, setup: HashmicroProviderSetup) -> dict[str, Any]:
    """Merge HashMicro named provider and selected model routes into config."""
    cfg: dict[str, Any] = deepcopy(dict(existing or {}))
    if not setup.enabled:
        return cfg

    cfg["custom_providers"] = _merge_custom_provider_entries(cfg.get("custom_providers"), setup)

    model = _ensure_mapping(cfg.get("model"))
    model["provider"] = setup.provider_id
    if setup.main_model.strip():
        model["default"] = setup.main_model.strip()
    cfg["model"] = model

    delegation = _ensure_mapping(cfg.get("delegation"))
    if setup.delegation_model.strip():
        delegation["provider"] = setup.provider_id
        delegation["model"] = setup.delegation_model.strip()
    cfg["delegation"] = delegation

    aux = _ensure_mapping(cfg.get("auxiliary"))
    for task, raw_model in setup.auxiliary_models.items():
        task_name = str(task).strip()
        model_name = str(raw_model).strip()
        if not task_name or not model_name:
            continue
        if task_name not in AUXILIARY_TASKS:
            raise ValueError(f"Unknown auxiliary task: {task_name}")
        task_cfg = _ensure_mapping(aux.get(task_name))
        task_cfg["provider"] = setup.provider_id
        task_cfg["model"] = model_name
        # Named custom providers resolve auth/base_url via custom_providers.
        # Leaving stale direct endpoint fields here would override provider routing.
        task_cfg["base_url"] = ""
        task_cfg["api_key"] = ""
        aux[task_name] = task_cfg
    cfg["auxiliary"] = aux
    return cfg


def build_hashmicro_env_values(setup: HashmicroProviderSetup) -> dict[str, str]:
    if not setup.enabled or not setup.api_key.strip():
        return {}
    return {setup.key_env.strip(): setup.api_key.strip()}


def secret_env_keys(values: Mapping[str, str]) -> set[str]:
    return {key for key in values if _SECRET_KEY_RE.search(key)}


def parse_aux_model_overrides(overrides: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in overrides:
        if "=" not in raw:
            raise ValueError("Auxiliary model overrides must use task=model")
        task, model = (part.strip() for part in raw.split("=", 1))
        if not task or not model:
            raise ValueError("Auxiliary model overrides must use task=model")
        if task not in AUXILIARY_TASKS:
            raise ValueError(f"Unknown auxiliary task: {task}")
        parsed[task] = model
    return parsed
