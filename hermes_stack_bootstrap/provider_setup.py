"""HashMicro/xAI provider setup helpers for hermes-stack-bootstrap."""

from __future__ import annotations

import json
import re
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


HASHMICRO_PROVIDER_NAME = "xai-hashmicro"
HASHMICRO_PROVIDER_ID = f"custom:{HASHMICRO_PROVIDER_NAME}"
HASHMICRO_BASE_URL = "https://xai.hashmicro.co/v1"
HASHMICRO_KEY_ENV = "XAI_HASHMICRO_API_KEY"
HASHMICRO_API_MODE = "chat_completions"
HASHMICRO_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
HASHMICRO_DEFAULT_REASONING_EFFORT = "xhigh"

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
_CONTEXT_FIELD_NAMES = (
    "context_length",
    "context_window",
    "max_context_length",
    "max_context_window",
)


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
    model_context_lengths: Mapping[str, int] = field(default_factory=dict)
    reasoning_effort: str = ""

    @property
    def provider_id(self) -> str:
        return f"custom:{self.provider_name.strip()}"


def _model_id_from_item(item: Any) -> str:
    if isinstance(item, dict):
        value = item.get("id") or item.get("name")
        return str(value).strip() if value else ""
    return str(item).strip()


def _coerce_positive_int(value: Any) -> int:
    if isinstance(value, str):
        text = value.strip().lower().replace(",", "").replace("_", "")
        multiplier = 1
        if text.endswith("k"):
            multiplier = 1_000
            text = text[:-1]
        elif text.endswith("m"):
            multiplier = 1_000_000
            text = text[:-1]
        try:
            parsed = int(float(text) * multiplier)
        except ValueError:
            return 0
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
    return parsed if parsed > 0 else 0


def normalize_hashmicro_reasoning_effort(effort: str, *, default: str = "") -> str:
    normalized = str(effort or "").strip().lower()
    if not normalized:
        return default
    if normalized not in HASHMICRO_REASONING_EFFORTS:
        raise ValueError("HashMicro reasoning effort must be one of: " + ", ".join(HASHMICRO_REASONING_EFFORTS))
    return normalized


def _hashmicro_reasoning_variant_candidate(model: str, effort: str) -> str:
    suffix_re = re.compile(
        r"^(?P<prefix>.*?)(?P<reasoning>-reasoning)?-(?:minimal|low|medium|high|xhigh)$", re.IGNORECASE
    )
    match = suffix_re.match(model)
    if match:
        return f"{match.group('prefix')}{match.group('reasoning') or ''}-{effort}"
    if model.lower().endswith("-reasoning"):
        return f"{model}-{effort}"
    return f"{model}-{effort}"


def _known_hashmicro_reasoning_variant(model: str, effort: str) -> bool:
    """Conservative offline fallback based on the observed HashMicro /models list."""
    normalized = model.lower()
    effort = effort.lower()
    if "gpt-5.4-mini" in normalized:
        return False
    if normalized in {"gpt-5.5", "gpt-5.5-high", "gpt-5.5-medium", "gpt-5.5-xhigh"}:
        return effort in {"medium", "high", "xhigh"}
    if normalized.startswith(("cx/gpt-5.5", "codex/gpt-5.5")):
        return effort in {"low", "medium", "high", "xhigh"}
    if normalized.startswith(("cx/gpt-5.4", "codex/gpt-5.4")):
        return effort in {"low", "medium", "high", "xhigh"}
    return False


def hashmicro_model_with_reasoning_effort(
    model: str,
    effort: str,
    available_models: Iterable[str] | None = None,
) -> str:
    """Return the HashMicro model ID variant for a selected reasoning effort.

    When a live /models list is available, never invent a suffix variant that the
    endpoint did not advertise; return the selected model unchanged instead.
    """
    selected = str(model or "").strip()
    normalized_effort = normalize_hashmicro_reasoning_effort(effort)
    if not selected or not normalized_effort:
        return selected
    candidate = _hashmicro_reasoning_variant_candidate(selected, normalized_effort)
    available = {str(item).strip() for item in (available_models or []) if str(item).strip()}
    if available:
        if candidate in available:
            return candidate
        return selected
    if _known_hashmicro_reasoning_variant(selected, normalized_effort):
        return candidate
    return selected


def _context_length_from_item(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    for key in _CONTEXT_FIELD_NAMES:
        parsed = _coerce_positive_int(item.get(key))
        if parsed:
            return parsed
    for container_key in ("limits", "metadata"):
        nested = item.get(container_key)
        if not isinstance(nested, dict):
            continue
        for key in _CONTEXT_FIELD_NAMES:
            parsed = _coerce_positive_int(nested.get(key))
            if parsed:
                return parsed
    return 0


def default_hashmicro_context_length(model: str) -> int:
    """Best-known HashMicro context fallback for GPT 5.x family aliases."""
    normalized = str(model or "").strip().lower()
    if not normalized:
        return 0
    if "gpt-5.5" in normalized and "codex" in normalized:
        return 272_000
    if "gpt-5.4-mini" in normalized:
        return 409_600
    if "gpt-5.4" in normalized:
        return 200_000
    if "gpt-5.5" in normalized:
        if any(normalized.endswith(f"-{effort}") for effort in ("medium", "high", "xhigh")):
            return 400_000
        return 272_000
    return 0


def parse_openai_compatible_model_contexts_response(
    payload: bytes | str | Mapping[str, Any] | list[Any],
) -> dict[str, int]:
    """Return context_length metadata when an OpenAI-compatible /models endpoint exposes it."""
    if isinstance(payload, bytes):
        data: Any = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    items = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}

    contexts: dict[str, int] = {}
    for item in items:
        model = _model_id_from_item(item)
        context_length = _context_length_from_item(item)
        if model and context_length and model not in contexts:
            contexts[model] = context_length
    return contexts


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


def fetch_openai_compatible_model_metadata(
    base_url: str,
    api_key: str,
    *,
    timeout: float = 30.0,
) -> tuple[list[str], dict[str, int]]:
    """Fetch model IDs and any context metadata from /models."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured API endpoint
        payload = response.read()
    return parse_openai_compatible_models_response(payload), parse_openai_compatible_model_contexts_response(payload)


def fetch_openai_compatible_models(base_url: str, api_key: str, *, timeout: float = 30.0) -> list[str]:
    """Fetch model IDs from an OpenAI-compatible endpoint's /models API."""
    models, _contexts = fetch_openai_compatible_model_metadata(base_url, api_key, timeout=timeout)
    return models


def _selected_model_contexts(setup: HashmicroProviderSetup) -> dict[str, int]:
    contexts: dict[str, int] = {}
    selected_models = [setup.main_model, setup.delegation_model, *setup.auxiliary_models.values()]
    provided = {str(model).strip(): _coerce_positive_int(value) for model, value in setup.model_context_lengths.items()}
    for raw_model in selected_models:
        model = str(raw_model or "").strip()
        if not model or model in contexts:
            continue
        context_length = provided.get(model) or default_hashmicro_context_length(model)
        if context_length:
            contexts[model] = context_length
    return contexts


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
    model_contexts = _selected_model_contexts(setup)
    if model_contexts:
        entry["models"] = {
            model: {"context_length": context_length} for model, context_length in model_contexts.items()
        }
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


def merge_hashmicro_provider_config(
    existing: Mapping[str, Any] | None, setup: HashmicroProviderSetup
) -> dict[str, Any]:
    """Merge HashMicro named provider and selected model routes into config."""
    cfg: dict[str, Any] = deepcopy(dict(existing or {}))
    if not setup.enabled:
        return cfg

    cfg["custom_providers"] = _merge_custom_provider_entries(cfg.get("custom_providers"), setup)

    model = _ensure_mapping(cfg.get("model"))
    model["provider"] = setup.provider_id
    if setup.main_model.strip():
        model["default"] = setup.main_model.strip()
    # Context metadata for HashMicro models lives in custom_providers[].models.
    # Keep route blocks as provider+model only so a single provider metadata map
    # is the source of truth for main, delegation, and auxiliary clients.
    model.pop("context_length", None)
    cfg["model"] = model

    reasoning_effort = normalize_hashmicro_reasoning_effort(setup.reasoning_effort)
    if reasoning_effort:
        agent_cfg = _ensure_mapping(cfg.get("agent"))
        agent_cfg["reasoning_effort"] = reasoning_effort
        cfg["agent"] = agent_cfg

    delegation = _ensure_mapping(cfg.get("delegation"))
    if setup.delegation_model.strip():
        delegation["provider"] = setup.provider_id
        delegation["model"] = setup.delegation_model.strip()
        if reasoning_effort:
            delegation["reasoning_effort"] = reasoning_effort
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
        task_cfg.pop("context_length", None)
        # Named custom providers resolve auth/base_url/context metadata via custom_providers.
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


def parse_aux_context_length_overrides(overrides: Iterable[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for raw in overrides:
        if "=" not in raw:
            raise ValueError("Auxiliary context length overrides must use task=context_length")
        task, value = (part.strip() for part in raw.split("=", 1))
        if not task or not value:
            raise ValueError("Auxiliary context length overrides must use task=context_length")
        if task not in AUXILIARY_TASKS:
            raise ValueError(f"Unknown auxiliary task: {task}")
        context_length = _coerce_positive_int(value)
        if not context_length:
            raise ValueError("Auxiliary context length must be a positive integer")
        parsed[task] = context_length
    return parsed
