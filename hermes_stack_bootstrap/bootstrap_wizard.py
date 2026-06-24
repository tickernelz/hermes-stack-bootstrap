"""Argument parser and wizard orchestration."""

from __future__ import annotations

import argparse
import dataclasses
import os
from pathlib import Path
from typing import Iterable

from .bootstrap_apply import apply_plans
from .bootstrap_data import (
    DEFAULT_LCM_SUMMARY_MODEL,
    HASHMICRO_BASE_URL,
    HASHMICRO_DEFAULT_REASONING_EFFORT,
    HASHMICRO_KEY_ENV,
    HASHMICRO_PROVIDER_NAME,
    HMX_KNOWLEDGE_REPO,
    INSTALL_MODE_LABELS,
    INSTALL_MODE_VALUES,
    PROGRESS_TAIL_REF,
    InstallerOptions,
)
from .bootstrap_option_flow import (
    _context_default_for_model,
    _env_get,
    _hashmicro_effective_model,
    _positive_int,
    apply_full_online_embedding_env_defaults,
    apply_hashmicro_env_defaults,
    hashmicro_auxiliary_context_lengths_from_args,
    hashmicro_auxiliary_models_from_args,
    populate_hashmicro_model_metadata,
    validate_embedding_options,
    validate_soul_options,
)
from .bootstrap_plan import build_plans
from .bootstrap_prompts import (
    choose_model_from_options,
    hashmicro_provider_choice_from_args,
    prompt_default,
    prompt_hashmicro_provider_setup,
    prompt_hmx_gitlab_token_if_needed,
    prompt_missing_runtime_python,
    prompt_profiles,
    prompt_soul_options,
    prompt_yes_no,
    require_tui,
    select_model_from_detected_providers,
    select_provider_and_model,
    tui_step,
)
from .bootstrap_runtime import (
    apply_install_mode_defaults,
    detect_base_home,
    hermes_python_for,
    install_mode_label,
    normalize_install_mode,
    parse_profiles,
    validate_runtime_options,
)
from .bootstrap_tui import RichPromptTui, TuiDependencyError, create_tui
from .env_template import MNEMOSYNE_MODES
from .hermes_discovery import discover_hermes_runtime
from .hermes_models import provider_choices
from .provider_setup import AUXILIARY_TASKS, HASHMICRO_REASONING_EFFORTS, normalize_hashmicro_reasoning_effort
from .soul_generator import DEFAULT_SOUL_COMMUNICATION_STYLE, DEFAULT_SOUL_LANGUAGE


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
    parser.add_argument(
        "--generate-soul", action="store_true", help="Generate SOUL.md once via the user's Hermes AI backend."
    )
    parser.add_argument("--soul-agent-name", default="")
    parser.add_argument("--soul-user-name", default="")
    parser.add_argument("--soul-role", default="")
    parser.add_argument("--soul-behavior", default="")
    parser.add_argument("--soul-communication", default=DEFAULT_SOUL_COMMUNICATION_STYLE)
    parser.add_argument("--soul-focus", default="")
    parser.add_argument("--soul-avoid", default="")
    parser.add_argument("--soul-language", default=DEFAULT_SOUL_LANGUAGE)
    parser.add_argument(
        "--soul-provider", default="", help="Optional provider override for the Hermes SOUL generation call."
    )
    parser.add_argument("--soul-model", default="", help="Optional model override for the Hermes SOUL generation call.")
    parser.add_argument(
        "--soul-overwrite", action="store_true", help="Allow replacing an existing SOUL.md after backup."
    )
    parser.add_argument(
        "--hmx-knowledge-url",
        default=_env_get(runtime_env, "HMX_KNOWLEDGE_GIT_URL", HMX_KNOWLEDGE_REPO),
        help="Private HMX knowledge repo URL. Prefer SSH or a git credential helper; do not put tokens in shell history.",
    )
    parser.set_defaults(hmx_gitlab_token=_env_get(runtime_env, "GITLAB_TOKEN", ""))
    parser.add_argument(
        "--setup-hashmicro-provider",
        action="store_true",
        help="Configure the recommended xAI HashMicro OpenAI-compatible provider.",
    )
    parser.add_argument(
        "--hashmicro-base-url", default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_BASE_URL", HASHMICRO_BASE_URL)
    )
    parser.add_argument(
        "--hashmicro-provider-name",
        default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_PROVIDER_NAME", HASHMICRO_PROVIDER_NAME),
    )
    parser.add_argument(
        "--hashmicro-key-env", default=_env_get(runtime_env, "HERMES_STACK_HASHMICRO_KEY_ENV", HASHMICRO_KEY_ENV)
    )
    parser.add_argument(
        "--main-model",
        default=_env_get(runtime_env, "HERMES_STACK_MAIN_MODEL", ""),
        help="Main Hermes model when --setup-hashmicro-provider is enabled.",
    )
    parser.add_argument(
        "--main-context-length",
        default=_env_get(runtime_env, "HERMES_STACK_MAIN_CONTEXT_LENGTH", ""),
        help="Context length for the selected HashMicro main model, stored under custom_providers[].models.",
    )
    parser.add_argument(
        "--delegation-model",
        default=_env_get(runtime_env, "HERMES_STACK_DELEGATION_MODEL", ""),
        help="delegate_task model when --setup-hashmicro-provider is enabled.",
    )
    parser.add_argument(
        "--delegation-context-length",
        default=_env_get(runtime_env, "HERMES_STACK_DELEGATION_CONTEXT_LENGTH", ""),
        help="Context length for the selected HashMicro delegation model, stored under custom_providers[].models.",
    )
    parser.add_argument(
        "--aux-all-model",
        default=_env_get(runtime_env, "HERMES_STACK_AUX_ALL_MODEL", ""),
        help="Use one model for all known auxiliary tasks.",
    )
    parser.add_argument(
        "--aux-all-context-length",
        default=_env_get(runtime_env, "HERMES_STACK_AUX_ALL_CONTEXT_LENGTH", ""),
        help="Context length for --aux-all-model, stored under custom_providers[].models.",
    )
    parser.add_argument(
        "--aux-model", action="append", default=[], help="Auxiliary task override in task=model form. Repeatable."
    )
    parser.add_argument(
        "--aux-context-length",
        action="append",
        default=[],
        help="Auxiliary context override in task=context_length form. Repeatable.",
    )
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
        needs_provider_choices = (not args.skip_mnemosyne and args.mnemosyne_mode in {"hybrid", "full-online"}) or (
            not args.skip_config_env and not args.summary_model
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
            args.mnemosyne_mode = (
                tui.select(
                    "Mnemosyne mode",
                    tuple(MNEMOSYNE_MODES),
                    args.mnemosyne_mode,
                )
                .strip()
                .lower()
            )
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
    hashmicro_delegation_context_length = _positive_int(
        args.delegation_context_length, field="--delegation-context-length"
    )
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
