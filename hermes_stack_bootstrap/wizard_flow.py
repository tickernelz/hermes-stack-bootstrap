"""Nine-step wizard flow orchestrator."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path
from typing import Mapping, Sequence

from .bootstrap_apply import apply_plans
from .bootstrap_data import (
    HASHMICRO_BASE_URL,
    HASHMICRO_DEFAULT_REASONING_EFFORT,
    HASHMICRO_KEY_ENV,
    HASHMICRO_PROVIDER_NAME,
    HMX_KNOWLEDGE_REPO,
    InstallerOptions,
)
from .bootstrap_option_flow import _context_default_for_model
from .bootstrap_plan import build_plans, print_plan
from .bootstrap_runtime import target_home_for
from .bootstrap_state import load_env_values
from .hermes_discovery import discover_hermes_runtime
from .provider_setup import AUXILIARY_TASKS
from .wizard_cli_flags import cli_help, parse_cli_flags
from .wizard_core import (
    CHOICES_DIR,
    COMPONENTS,
    MODES,
    TOTAL_STEPS,
    Choice,
    WizardState,
    WizardTui,
    _apply_cli_flags,
    _choose,
    _detect_homes,
    _fetch_models,
    _label,
    _load_yaml_json,
    _multi,
    _save_choices,
)
from .wizard_tui import ConsoleWizardTui, create_tui


def step1(ui: WizardTui, state: WizardState) -> None:
    ui.step(1, TOTAL_STEPS, "Welcome, mode, and saved choices")
    saved_files = (
        sorted(CHOICES_DIR.glob("*.json")) + sorted(CHOICES_DIR.glob("*.yaml")) + sorted(CHOICES_DIR.glob("*.yml"))
    )
    existing = any((h / "config.yaml").exists() or (h / "profiles").exists() for h in _detect_homes(state.env))
    ui.info(
        f"Detected {'existing Hermes data' if existing else 'no existing Hermes install'}; saved profiles: {len(saved_files)}"
    )
    state.mode = _choose(
        ui, "Install intent", [Choice(k, v) for k, v in MODES.items()], state.saved.get("mode", state.mode)
    )
    state.dry_run = state.mode == "dry-run"
    if saved_files:
        choices = [Choice("Use recommended defaults", "fresh")] + [
            Choice(f"Load saved profile: {p.stem}", str(p)) for p in saved_files
        ]
        choices.append(Choice("Import choices from YAML/JSON file...", "import"))
        src = _choose(ui, "Choices source", choices, "fresh")
        if src == "import":
            src = ui.text("Choices file path", "")
        if src not in {"fresh", ""}:
            state.saved.update(_load_yaml_json(Path(src)))


def step2(ui: WizardTui, state: WizardState) -> None:
    ui.step(2, TOTAL_STEPS, "Target Hermes runtime and profile")
    homes = _detect_homes(state.env)
    home_choices = [Choice(str(h), str(h), recommended=i == 0) for i, h in enumerate(homes)] + [
        Choice("Custom path...", "custom")
    ]
    home = _choose(ui, "Hermes home", home_choices, str(state.saved.get("hermes_home") or homes[0]))
    state.home = Path(
        ui.text("Custom Hermes home", str(Path("~/.hermes").expanduser())) if home == "custom" else home
    ).expanduser()
    profiles_dir = state.home / "profiles"
    profiles = [p.name for p in profiles_dir.iterdir() if p.is_dir()] if profiles_dir.exists() else []
    profile = _choose(
        ui,
        "Hermes profile",
        [Choice(p, p) for p in profiles] + [Choice("default", "default"), Choice("Create new profile...", "new")],
        str(state.saved.get("profile", state.profile)),
    )
    state.profile = ui.text("New profile name", "default") if profile == "new" else profile
    runtime = discover_hermes_runtime(base_home=state.home, env=state.env)
    state.hermes_bin = runtime.hermes_bin or "hermes"
    py_choices = [
        Choice("Auto-detect Hermes Python", "auto"),
        Choice(f"Use current Python: {sys.executable}", sys.executable),
        Choice("Custom Python path...", "custom"),
        Choice("Skip Python/runtime checks", "skip"),
    ]
    py = _choose(ui, "Python/runtime", py_choices, "auto")
    if py == "auto":
        state.hermes_python, state.hermes_python_source = runtime.hermes_python, runtime.hermes_python_source
    elif py == "custom":
        state.hermes_python, state.hermes_python_source = Path(ui.text("Python path", sys.executable)), "custom"
    elif py != "skip":
        state.hermes_python, state.hermes_python_source = Path(py), "current"
    ui.summary_table(
        "Target files",
        [
            ("config", str(target_home_for(state.home, state.profile) / "config.yaml")),
            ("env", str(target_home_for(state.home, state.profile) / ".env")),
        ],
    )


def step3(ui: WizardTui, state: WizardState) -> None:
    ui.step(3, TOTAL_STEPS, "Provider setup")
    env_file = load_env_values(target_home_for(state.home, state.profile) / ".env")
    provider = state.saved.get("provider", {}) if isinstance(state.saved.get("provider"), dict) else {}
    state.provider_kind = _choose(
        ui,
        "Provider strategy",
        [
            Choice("HashMicro xAI provider", "hashmicro"),
            Choice("Use existing configured provider", "existing"),
            Choice("OpenAI-compatible custom provider", "custom"),
            Choice("Skip provider setup for now", "skip"),
        ],
        provider.get("kind", "hashmicro"),
    )
    if state.provider_kind == "skip":
        return
    if state.provider_kind == "custom":
        state.base_url = ui.text("Provider base URL", provider.get("base_url", "https://api.openai.com/v1"))
        state.key_env = ui.text("API key env var", provider.get("key_env", "OPENAI_API_KEY"))
        state.provider_name = ui.text("Provider display name", provider.get("provider_name", "custom-provider"))
    else:
        state.base_url = ui.text("HashMicro endpoint", provider.get("base_url", HASHMICRO_BASE_URL))
        state.key_env = provider.get("key_env", HASHMICRO_KEY_ENV)
        state.provider_name = ui.text("Provider name", provider.get("provider_name", HASHMICRO_PROVIDER_NAME))
    if not env_file.get(state.key_env) and not state.env.get(state.key_env):
        src = _choose(
            ui,
            "Credential source",
            [Choice("Enter key securely now", "enter"), Choice("Skip key and configure later", "skip")],
            "skip",
        )
        if src == "enter":
            state.api_key = ui.password("API key", state.key_env)
    try:
        with ui.spinner("Fetching model inventory"):
            state.models = _fetch_models(state.base_url, state.key_env, {**state.env, **env_file}, state.api_key)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        ui.warning(f"Could not fetch models: {exc}")
        state.models = []


def step4(ui: WizardTui, state: WizardState) -> None:
    ui.step(4, TOTAL_STEPS, "Model routing and context defaults")
    saved_models = state.saved.get("models", {}) if isinstance(state.saved.get("models"), dict) else {}
    choices = [Choice(m, m, recommended=m == "gpt-5.5") for m in state.models] + [
        Choice("Manual model name...", "manual")
    ]
    main = _choose(
        ui, "Main model", choices or [Choice("Manual model name...", "manual")], saved_models.get("main", "gpt-5.5")
    )
    state.main_model = ui.text("Manual model name", "gpt-5.5") if main == "manual" else main
    ctx_default = 272000 if state.main_model == "gpt-5.5" else _context_default_for_model(state.main_model, {})
    ctx = _choose(
        ui,
        "Context window",
        [
            Choice("272000 tokens", "272000"),
            Choice("128000 tokens", "128000"),
            Choice("64000 tokens", "64000"),
            Choice("Use provider/model default", "0"),
            Choice("Custom...", "custom"),
        ],
        str(saved_models.get("context") or ctx_default or 0),
    )
    state.context = int(ui.text("Custom context tokens", str(ctx_default or 128000)) if ctx == "custom" else ctx)
    delegation = _choose(
        ui,
        "Delegation model",
        [Choice(f"Same as main: {state.main_model}", "same")] + choices,
        saved_models.get("delegation", "same"),
    )
    state.delegation_model = (
        state.main_model
        if delegation == "same"
        else ui.text("Manual delegation model", state.main_model)
        if delegation == "manual"
        else delegation
    )
    state.delegation_context = int(saved_models.get("delegation_context") or state.context)
    aux_mode = _choose(
        ui,
        "Auxiliary routing",
        [
            Choice("Use same model for all auxiliary tasks", "same"),
            Choice("Use smaller/faster model for all auxiliary tasks", "small"),
            Choice("Customize by task", "custom"),
            Choice("Keep existing auxiliary routing", "keep"),
        ],
        "same",
    )
    if aux_mode == "small":
        model = state.models[-1] if state.models else ui.text("Smaller/faster model", state.main_model)
        state.aux = {task: model for task in AUXILIARY_TASKS}
        state.aux_contexts = {task: state.context for task in AUXILIARY_TASKS}
    elif aux_mode == "custom":
        tasks = _multi(ui, "Tasks to customize", [Choice(t, t) for t in AUXILIARY_TASKS], set())
        for task in tasks:
            state.aux[task] = _choose(ui, f"Model for {task}", [Choice("Same as main", "same")] + choices, "same")
            if state.aux[task] == "same":
                state.aux[task] = state.main_model
            state.aux_contexts[task] = state.context


def step5(ui: WizardTui, state: WizardState) -> None:
    ui.step(5, TOTAL_STEPS, "Stack components")
    defaults = (
        set(state.saved.get("components", state.components))
        if isinstance(state.saved.get("components", []), list)
        else state.components
    )
    choices = []
    existing_root = target_home_for(state.home, state.profile)
    for label, value in COMPONENTS.items():
        disabled = (
            state.mode == "skills-only"
            and value not in {"skills", "verify"}
            or state.mode == "plugins-only"
            and value not in {"plugins", "verify"}
            or state.mode == "provider-only"
            and value not in {"config", "verify"}
        )
        desc = (
            "installed, will update"
            if (existing_root / value).exists() or (value == "config" and (existing_root / "config.yaml").exists())
            else ""
        )
        choices.append(Choice(label, value, desc, disabled=disabled))
    state.components = _multi(ui, "Components", choices, defaults)


def step6(ui: WizardTui, state: WizardState) -> None:
    ui.step(6, TOTAL_STEPS, "Skill packs and credentials")
    if "skills" not in state.components:
        state.skill_packs = set()
        return
    packs = (
        state.saved.get("skills", {}).get("packs", list(state.skill_packs))
        if isinstance(state.saved.get("skills"), dict)
        else list(state.skill_packs)
    )
    state.skill_packs = _multi(
        ui,
        "Skill packs",
        [
            Choice("Core Hermes skills", "core"),
            Choice("Recommended productivity skills", "recommended"),
            Choice("HashMicro/HMX skills", "hmx", "requires GitLab token"),
            Choice("None / skip skill install", "none"),
        ],
        set(packs),
    )
    if "none" in state.skill_packs:
        state.skill_packs = set()
        return
    if "hmx" in state.skill_packs:
        env_file = load_env_values(target_home_for(state.home, state.profile) / ".env")
        if not env_file.get("GITLAB_TOKEN") and not state.env.get("GITLAB_TOKEN"):
            if (
                _choose(
                    ui,
                    "HMX credential source",
                    [Choice("Enter GitLab token securely now", "enter"), Choice("Skip HMX skills", "skip")],
                    "skip",
                )
                == "enter"
            ):
                state.hmx_token = ui.password("GitLab token", "GITLAB_TOKEN")
            else:
                state.skill_packs.discard("hmx")


def step7(ui: WizardTui, state: WizardState) -> None:
    ui.step(7, TOTAL_STEPS, "Skill conflict detection")
    skills_dir = target_home_for(state.home, state.profile) / "skills"
    existing = [p.name for p in skills_dir.iterdir() if p.is_dir()] if skills_dir.exists() else []
    conflicts = [name for name in existing if any(token in name.lower() for token in state.skill_packs)]
    ui.info(f"Existing skills scanned: {len(existing)}; possible conflicts: {len(conflicts)}")
    if not conflicts:
        return
    state.conflict_policy = _choose(
        ui,
        "Global conflict policy",
        [
            Choice("Ask per conflict", "ask"),
            Choice("Skip conflicting skills", "skip"),
            Choice("Backup then replace conflicts", "backup-replace"),
            Choice("Merge when safe, ask otherwise", "merge-safe"),
            Choice("Abort skill installation", "abort", danger=True),
        ],
        "ask",
    )
    if state.conflict_policy == "ask":
        for name in conflicts:
            state.conflict_decisions[name] = _choose(
                ui,
                f"Conflict: {name}",
                [
                    Choice("Keep existing / skip this skill", "skip"),
                    Choice("Backup existing then install new", "backup-replace"),
                    Choice(f"Install new as {name}-new", "install-new"),
                    Choice("Abort", "abort", danger=True),
                ],
                "skip",
            )


def step8(ui: WizardTui, state: WizardState) -> InstallerOptions:
    ui.step(8, TOTAL_STEPS, "Final review")
    preview_options = to_installer_options(state)
    plans = build_plans(preview_options)
    ui.summary_table(
        "Review",
        [
            ("Target", f"{state.home} / {state.profile}"),
            ("Mode", state.mode),
            ("Provider", f"{state.provider_kind}:{state.provider_name} {state.base_url}"),
            ("Models", f"main={state.main_model}, delegation={state.delegation_model}, context={state.context}"),
            ("Components", ", ".join(sorted(state.components))),
            ("Skill packs", ", ".join(sorted(state.skill_packs)) or "none"),
            ("Files", ", ".join(str(p.config_path) for p in plans)),
        ],
    )
    state.action = _choose(
        ui,
        "Action",
        [
            Choice("Apply changes now", "apply"),
            Choice("Show detailed diff/plan", "plan"),
            Choice("Save plan to file", "save-plan"),
            Choice("Go back and edit choices", "back"),
            Choice("Exit without changes", "cancel"),
        ],
        "plan" if state.dry_run else "apply",
    )
    save = _choose(
        ui,
        "Save choices",
        [
            Choice("Save non-secret choices as profile: default", "default"),
            Choice("Save as new profile...", "new"),
            Choice("Do not save choices", ""),
        ],
        "default",
    )
    state.save_profile = ui.text("Choices profile name", "default") if save == "new" else save
    return to_installer_options(state)


def step9(ui: WizardTui, state: WizardState, options: InstallerOptions) -> None:
    ui.step(9, TOTAL_STEPS, "Execute and verify")
    plans = build_plans(options)
    should_apply = state.action == "apply" or (state.action == "plan" and options.dry_run)
    if (state.action in {"plan", "save-plan"} or options.dry_run) and not should_apply:
        for plan in plans:
            print_plan(plan)
    if state.action == "save-plan":
        path = Path(ui.text("Plan output path", "hermes-stack-bootstrap-plan.txt"))
        path.write_text(
            "\n\n".join(f"Plan for {p.options.profile}\n" + "\n".join(s.title for s in p.steps) for p in plans),
            encoding="utf-8",
        )
        ui.info(f"Plan saved: {path}")
    if should_apply:
        if state.action == "apply" and not options.dry_run:
            for i, phase in enumerate(
                [
                    "Preparing backups",
                    "Writing .env secrets",
                    "Merging provider config",
                    "Writing model routing",
                    "Installing plugins/tools",
                    "Installing skills",
                    "Installing cron/memory assets",
                    "Running verification",
                    "Finalizing saved choices",
                ],
                1,
            ):
                ui.progress(phase, i, 9)
        apply_plans(plans)
    saved_path = _save_choices(state, CHOICES_DIR)
    ui.summary_table(
        "Finish",
        [
            ("Action", state.action),
            ("Choices saved", str(saved_path) if saved_path else "no"),
            (
                "Secrets",
                ", ".join(k for k, v in [(state.key_env, state.api_key), ("GITLAB_TOKEN", state.hmx_token)] if v)
                or "none written by wizard",
            ),
        ],
    )


def to_installer_options(state: WizardState) -> InstallerOptions:
    mode = state.cli_install_mode or ("plugin-skill-only" if state.mode in {"skills-only", "plugins-only"} else "full")
    setup_provider = state.provider_kind in {"hashmicro", "custom", "existing"} and "config" in state.components

    # Only install skills if "skills" component is enabled
    skills_enabled = "skills" in state.components
    install_superpowers = skills_enabled and "recommended" in state.skill_packs
    install_impeccable = skills_enabled and "recommended" in state.skill_packs
    install_hmx = skills_enabled and "hmx" in state.skill_packs
    install_ponytail = skills_enabled and "recommended" in state.skill_packs

    aux_contexts = {task: int(state.aux_contexts.get(task) or state.context) for task in state.aux}
    return InstallerOptions(
        base_home=state.home,
        profile=state.profile,
        hermes_bin=state.hermes_bin,
        hermes_python=state.hermes_python,
        hermes_python_source=state.hermes_python_source,
        yes=True,
        dry_run=state.dry_run or state.action in {"plan", "save-plan"},
        install_mode=mode,
        mnemosyne_mode=state.mnemosyne_mode,
        skip_lcm=state.cli_skip_lcm or "plugins" not in state.components,
        skip_mnemosyne="memories" not in state.components,
        skip_progress_tail=state.cli_skip_progress_tail or "plugins" not in state.components,
        skip_config_env="config" not in state.components,
        skip_verify="verify" not in state.components,
        progress_tail_ref=state.progress_tail_ref,
        install_superpowers=install_superpowers,
        install_hmx_knowledge=install_hmx,
        install_impeccable=install_impeccable,
        install_ponytail=install_ponytail,
        hmx_knowledge_url=HMX_KNOWLEDGE_REPO,
        hmx_gitlab_token=state.hmx_token,
        setup_hashmicro_provider=setup_provider,
        hashmicro_base_url=state.base_url,
        hashmicro_provider_name=state.provider_name,
        hashmicro_key_env=state.key_env,
        hashmicro_api_key=state.api_key,
        hashmicro_main_model=state.main_model,
        hashmicro_main_context_length=state.context,
        hashmicro_delegation_model=state.delegation_model,
        hashmicro_delegation_context_length=state.delegation_context,
        hashmicro_auxiliary_models=state.aux,
        hashmicro_auxiliary_context_lengths=aux_contexts,
        hashmicro_reasoning_effort=HASHMICRO_DEFAULT_REASONING_EFFORT,
        hashmicro_available_models=tuple(state.models),
        generate_soul="soul" in state.components,
        soul_agent_name=state.soul_agent_name,
        soul_user_name=state.soul_user_name,
        soul_communication=state.soul_communication,
        soul_language=state.soul_language,
        soul_provider=state.soul_provider,
        soul_model=state.soul_model,
        soul_overwrite=state.soul_overwrite,
    )


def quick_install(*, env: Mapping[str, str] | None = None, ui: WizardTui | None = None) -> InstallerOptions:
    """Quick install mode: skip wizard, use recommended defaults.

    This function bypasses the interactive wizard and returns InstallerOptions
    with sensible defaults for a standard full-stack installation.
    """
    runtime_env = dict(os.environ if env is None else env)
    state = WizardState(env=runtime_env)
    tui = ui or ConsoleWizardTui()

    # Set recommended defaults
    state.mode = "full"
    state.home = Path(runtime_env.get("HERMES_HOME", "~/.hermes")).expanduser()
    state.profile = "default"

    # Skip provider setup (user can configure later)
    state.provider_kind = "skip"
    state.provider_name = ""
    state.base_url = ""
    state.key_env = ""
    state.api_key = ""

    # Use Hermes defaults for models
    state.main_model = ""
    state.context = 0
    state.delegation_model = ""
    state.aux = {}
    state.models = []

    # Install core components
    state.components = {"config", "plugins", "skills", "verify"}

    # Install recommended skill packs
    state.skill_packs = {"recommended"}
    state.hmx_token = ""

    # No dry run, proceed to install
    state.dry_run = False
    state.action = "apply"
    state.save_profile = ""

    tui.info("🚀 Quick install mode - using recommended defaults")
    tui.info(f"   Target: {state.home}")
    tui.info(f"   Profile: {state.profile}")
    tui.info(f"   Components: {', '.join(sorted(state.components))}")
    tui.info(f"   Skills: {', '.join(sorted(state.skill_packs))}")

    options = to_installer_options(state)
    return options


def run_wizard_v2(
    *,
    env: Mapping[str, str] | None = None,
    ui: WizardTui | None = None,
    execute: bool = True,
    argv: Sequence[str] | None = None,
) -> InstallerOptions:
    """Run all nine v2 wizard steps and return the resulting options.

    When ``execute`` is false, Step 9 is skipped after options are built; this is
    useful for tests and for callers that only need the dataclass conversion.
    """
    runtime_env = dict(os.environ if env is None else env)
    flags = parse_cli_flags(sys.argv[1:] if argv is None else argv)
    if flags.get("quick"):
        return quick_install(env=runtime_env, ui=ui)
    state = WizardState(env=runtime_env)
    _apply_cli_flags(state, flags)
    tui = ui or create_tui()
    if state.cli_yes:
        tui.info("Non-interactive mode - using defaults and CLI flags")
        # Discover runtime like interactive mode does unless CLI supplied it.
        runtime = discover_hermes_runtime(base_home=state.home, env=runtime_env)
        if runtime and runtime.hermes_python and state.hermes_python is None:
            state.hermes_python = runtime.hermes_python
            state.hermes_python_source = runtime.hermes_python_source
        options = to_installer_options(state)
        if execute:
            step9(tui, state, options)
        return options
    step1(tui, state)
    step2(tui, state)
    step3(tui, state)
    step4(tui, state)
    step5(tui, state)
    step6(tui, state)
    step7(tui, state)
    options = step8(tui, state)
    if state.action == "back":
        step4(tui, state)
        step5(tui, state)
        options = step8(tui, state)
    if state.action == "cancel":
        tui.info("Cancelled; no changes applied.")
        return options
    if execute:
        step9(tui, state, options)
    return options


# Compatibility alias for callers that expect a simple wizard function.
wizard_v2 = run_wizard_v2
