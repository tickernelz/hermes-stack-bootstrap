"""Option validation and provider metadata normalization."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Mapping

from .bootstrap_data import InstallerOptions
from .env_template import MNEMOSYNE_MODES
from .provider_setup import (
    AUXILIARY_TASKS,
    HASHMICRO_KEY_ENV,
    HashmicroProviderSetup,
    default_hashmicro_context_length,
    fetch_openai_compatible_model_metadata,
    hashmicro_model_with_reasoning_effort,
    normalize_hashmicro_reasoning_effort,
    parse_aux_context_length_overrides,
    parse_aux_model_overrides,
)


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


def _context_default_for_model(model: str, detected_contexts: Mapping[str, int] | None = None) -> int:
    # User-confirmed correction: GPT-5.5 Codex variants are 272K even if a
    # live endpoint reports a larger generic context value.
    normalized = str(model or "").lower().replace("-", " ").replace("/", " ")
    if "gpt 5.5" in normalized and "codex" in normalized:
        return 272000
    return int((detected_contexts or {}).get(model) or default_hashmicro_context_length(model))


def _hashmicro_effective_model(model: str, effort: str, available_models: Iterable[str] | None = None) -> str:
    return (
        hashmicro_model_with_reasoning_effort(model, effort, available_models) if effort else str(model or "").strip()
    )


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
            f"Conflicting context lengths for HashMicro model {model}: {contexts[model]} vs {int(context_length)}"
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
        delegation_model=_hashmicro_effective_model(
            options.hashmicro_delegation_model, effort, options.hashmicro_available_models
        ),
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
