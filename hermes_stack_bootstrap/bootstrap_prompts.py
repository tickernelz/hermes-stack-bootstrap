"""Interactive prompt helpers."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from .bootstrap_data import HASHMICRO_DEFAULT_REASONING_EFFORT, InstallerOptions
from .bootstrap_option_flow import (
    _env_get,
    _hashmicro_effective_model,
    _positive_int,
    apply_hashmicro_env_defaults,
    _context_default_for_model,
)
from .bootstrap_runtime import hermes_python_for, prompt_profiles
from .bootstrap_tui import RichPromptTui, create_tui
from .env_template import MNEMOSYNE_MODES
from .hermes_discovery import HermesRuntime
from .hermes_models import ProviderChoice, model_choices_for_provider, provider_choices
from .provider_setup import (
    AUXILIARY_TASKS,
    HASHMICRO_REASONING_EFFORTS,
    fetch_openai_compatible_model_metadata,
    hashmicro_model_with_reasoning_effort,
    normalize_hashmicro_reasoning_effort,
    parse_aux_context_length_overrides,
    parse_aux_model_overrides,
)
from .soul_generator import DEFAULT_SOUL_COMMUNICATION_STYLE, DEFAULT_SOUL_LANGUAGE, SoulAnswers


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


def prompt_yes_no(prompt: str, default: bool = False, ui: RichPromptTui | None = None) -> bool:
    answer = require_tui(ui).select(prompt, ("Yes", "No"), "Yes" if default else "No")
    if isinstance(answer, bool):
        return answer
    return str(answer).strip().lower() in {"yes", "y", "true", "1"}


def prompt_missing_runtime_python(
    runtime: HermesRuntime, ui: RichPromptTui | None = None
) -> tuple[HermesRuntime, bool]:
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
        if prompt_yes_no(f"Not executable: {candidate}. Skip Mnemosyne instead?", True, tui):
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
    provider_label = tui.select(
        provider_prompt,
        ("Use Hermes default", *by_label),
        "Use Hermes default" if not current_provider else default_label,
    )
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


def prompt_hashmicro_provider_setup(
    args: argparse.Namespace, tui: RichPromptTui, env: os._Environ[str] | dict[str, str]
) -> None:
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
            models, detected_contexts = fetch_openai_compatible_model_metadata(
                args.hashmicro_base_url, args.hashmicro_api_key
            )
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
    args.delegation_model = choose_model_from_options(
        tui, "HashMicro delegation model", models, args.delegation_model or args.main_model
    )
    args.delegation_context_length = str(
        prompt_hashmicro_context_length(
            tui,
            "HashMicro delegation context length",
            _hashmicro_effective_model(args.delegation_model, args.hashmicro_reasoning_effort, models),
            detected_contexts,
            getattr(args, "delegation_context_length", ""),
        )
    )
    aux_default = choose_model_from_options(
        tui,
        "HashMicro default auxiliary model",
        models,
        getattr(args, "aux_all_model", "") or args.delegation_model or args.main_model,
    )
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


def prompt_hmx_gitlab_token_if_needed(
    args: argparse.Namespace, tui: RichPromptTui, env: os._Environ[str] | dict[str, str]
) -> None:
    if not args.install_hmx_knowledge:
        return
    if not getattr(args, "hmx_gitlab_token", ""):
        args.hmx_gitlab_token = _env_get(env, "GITLAB_TOKEN", "")
    if not args.hmx_gitlab_token:
        args.hmx_gitlab_token = tui.password(
            "HMX GitLab token (hidden; empty to use SSH/credential helper only)"
        ).strip()


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
