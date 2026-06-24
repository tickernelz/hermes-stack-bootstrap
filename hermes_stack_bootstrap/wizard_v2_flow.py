"""Nine-step wizard v2 flow orchestrator.

This module is intentionally self-contained and fakeable.  It converts the
interactive v2 decisions into the existing :class:`InstallerOptions` shape, then
uses ``bootstrap_plan``/``bootstrap_apply`` for plan construction and execution.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .bootstrap_apply import apply_plans
from .bootstrap_data import (
    HASHMICRO_BASE_URL,
    HASHMICRO_DEFAULT_REASONING_EFFORT,
    HASHMICRO_KEY_ENV,
    HASHMICRO_PROVIDER_NAME,
    HMX_KNOWLEDGE_REPO,
    PROGRESS_TAIL_REF,
    InstallerOptions,
)
from .bootstrap_option_flow import _context_default_for_model
from .bootstrap_plan import build_plans, print_plan
from .bootstrap_runtime import target_home_for
from .bootstrap_state import load_env_values
from .hermes_discovery import discover_hermes_runtime
from .provider_setup import AUXILIARY_TASKS

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
    def multi_select(self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None) -> Sequence[Any]: ...
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


class ConsoleWizardTui:
    """Small no-dependency fallback TUI; tests can pass a fake with same methods."""

    def step(self, index: int, total: int = TOTAL_STEPS, title: str = "", subtitle: str | None = None) -> None:
        print(f"\nHermes Stack Bootstrap Wizard\nStep {index}/{total}: {title}")
        if subtitle:
            print(subtitle)

    def info(self, message: str) -> None: print(message)
    def warning(self, message: str) -> None: print(f"Warning: {message}")

    def select(self, prompt: str, choices: Sequence[Any], default: Any = None) -> Any:
        enabled = [c for c in choices if not getattr(c, "disabled", False)]
        labels = [getattr(c, "label", str(c)) for c in enabled]
        default = default if default is not None else (enabled[0] if enabled else None)
        default_label = getattr(default, "label", str(default)) if default is not None else ""
        print(prompt)
        for i, c in enumerate(enabled, 1):
            mark = "*" if labels[i - 1] == default_label else " "
            desc = getattr(c, "description", "")
            print(f"  {i}. {mark} {labels[i - 1]}" + (f" — {desc}" if desc else ""))
        ans = input(f"Select [{default_label}]: ").strip()
        if not ans:
            return default
        if ans.isdigit() and 1 <= int(ans) <= len(enabled):
            return enabled[int(ans) - 1]
        for c in enabled:
            if ans.lower() == getattr(c, "label", str(c)).lower():
                return c
        return default

    def multi_select(self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None) -> Sequence[Any]:
        defaults = list(defaults or [])
        self.select(prompt + " (comma numbers; Enter keeps defaults)", choices, defaults[0] if defaults else None)
        labels = [getattr(c, "label", str(c)) for c in choices if not getattr(c, "disabled", False)]
        print("  " + " | ".join(f"{i + 1}:{label}" for i, label in enumerate(labels)))
        ans = input("Select: ").strip()
        if not ans:
            return defaults
        out = []
        for part in ans.split(","):
            if part.strip().isdigit() and 1 <= int(part) <= len(labels):
                out.append(choices[int(part) - 1])
        return out or defaults

    def confirm(self, prompt: str, default: bool = True) -> bool:
        ans = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not ans else ans.startswith("y")

    def text(self, prompt: str, default: str | None = None, validate: Any = None) -> str:
        value = input(f"{prompt} [{default or ''}]: ").strip() or (default or "")
        if validate and not validate(value):
            raise ValueError(f"Invalid value for {prompt}: {value}")
        return value

    def password(self, prompt: str, env_name: str | None = None) -> str:
        import getpass

        return getpass.getpass(f"{prompt}{f' ({env_name})' if env_name else ''}: ").strip()

    def summary_table(self, title: str, rows: Sequence[tuple[str, str]]) -> None:
        print(f"\n{title}")
        for k, v in rows:
            print(f"  {k}: {v}")

    def progress(self, label: str, current: int, total: int) -> None: print(f"[{current}/{total}] {label}")

    def spinner(self, label: str):
        class S:
            def __enter__(self): print(label); return self
            def __exit__(self, *_: Any) -> None: return None
        return S()


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
    aux: dict[str, str] = field(default_factory=dict)
    components: set[str] = field(default_factory=lambda: {"config", "plugins", "skills", "verify"})
    skill_packs: set[str] = field(default_factory=lambda: {"core", "recommended"})
    hmx_token: str = ""
    conflict_policy: str = "ask"
    conflict_decisions: dict[str, str] = field(default_factory=dict)
    action: str = "apply"
    save_profile: str = ""


def _value(x: Any) -> Any: return getattr(x, "value", x)
def _label(x: Any) -> str: return getattr(x, "label", str(x))
def _choose(ui: WizardTui, prompt: str, choices: Sequence[Choice], default: str) -> str:
    default_choice = next((c for c in choices if c.value == default and not c.disabled), None)
    return str(_value(ui.select(prompt, choices, default_choice or choices[0])))
def _multi(ui: WizardTui, prompt: str, choices: Sequence[Choice], defaults: set[str]) -> set[str]:
    d = [c for c in choices if c.value in defaults and not c.disabled]
    return {str(_value(c)) for c in ui.multi_select(prompt, choices, d)}


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


def _save_choices(state: WizardState) -> Path | None:
    if not state.save_profile:
        return None
    CHOICES_DIR.mkdir(parents=True, exist_ok=True)
    path = CHOICES_DIR / f"{state.save_profile}.json"
    data = {
        "version": 1, "mode": state.mode, "hermes_home": str(state.home), "profile": state.profile,
        "provider": {"kind": state.provider_kind, "provider_name": state.provider_name, "base_url": state.base_url, "key_env": state.key_env},
        "models": {"main": state.main_model, "delegation": state.delegation_model, "aux_overrides": state.aux, "context": state.context},
        "components": sorted(state.components), "skills": {"packs": sorted(state.skill_packs), "conflict_policy": state.conflict_policy},
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


def step1(ui: WizardTui, state: WizardState) -> None:
    ui.step(1, TOTAL_STEPS, "Welcome, mode, and saved choices")
    saved_files = sorted(CHOICES_DIR.glob("*.json")) + sorted(CHOICES_DIR.glob("*.yaml")) + sorted(CHOICES_DIR.glob("*.yml"))
    existing = any((h / "config.yaml").exists() or (h / "profiles").exists() for h in _detect_homes(state.env))
    ui.info(f"Detected {'existing Hermes data' if existing else 'no existing Hermes install'}; saved profiles: {len(saved_files)}")
    state.mode = _choose(ui, "Install intent", [Choice(k, v) for k, v in MODES.items()], state.saved.get("mode", "full"))
    state.dry_run = state.mode == "dry-run"
    if saved_files:
        choices = [Choice("Use recommended defaults", "fresh")] + [Choice(f"Load saved profile: {p.stem}", str(p)) for p in saved_files]
        choices.append(Choice("Import choices from YAML/JSON file...", "import"))
        src = _choose(ui, "Choices source", choices, "fresh")
        if src == "import":
            src = ui.text("Choices file path", "")
        if src not in {"fresh", ""}:
            state.saved.update(_load_yaml_json(Path(src)))


def step2(ui: WizardTui, state: WizardState) -> None:
    ui.step(2, TOTAL_STEPS, "Target Hermes runtime and profile")
    homes = _detect_homes(state.env)
    home_choices = [Choice(str(h), str(h), recommended=i == 0) for i, h in enumerate(homes)] + [Choice("Custom path...", "custom")]
    home = _choose(ui, "Hermes home", home_choices, str(state.saved.get("hermes_home") or homes[0]))
    state.home = Path(ui.text("Custom Hermes home", str(Path("~/.hermes").expanduser())) if home == "custom" else home).expanduser()
    profiles_dir = state.home / "profiles"
    profiles = [p.name for p in profiles_dir.iterdir() if p.is_dir()] if profiles_dir.exists() else []
    profile = _choose(ui, "Hermes profile", [Choice(p, p) for p in profiles] + [Choice("default", "default"), Choice("Create new profile...", "new")], str(state.saved.get("profile", "default")))
    state.profile = ui.text("New profile name", "default") if profile == "new" else profile
    runtime = discover_hermes_runtime(base_home=state.home, env=state.env)
    state.hermes_bin = runtime.hermes_bin or "hermes"
    py_choices = [Choice("Auto-detect Hermes Python", "auto"), Choice(f"Use current Python: {sys.executable}", sys.executable), Choice("Custom Python path...", "custom"), Choice("Skip Python/runtime checks", "skip")]
    py = _choose(ui, "Python/runtime", py_choices, "auto")
    if py == "auto":
        state.hermes_python, state.hermes_python_source = runtime.hermes_python, runtime.hermes_python_source
    elif py == "custom":
        state.hermes_python, state.hermes_python_source = Path(ui.text("Python path", sys.executable)), "custom"
    elif py != "skip":
        state.hermes_python, state.hermes_python_source = Path(py), "current"
    ui.summary_table("Target files", [("config", str(target_home_for(state.home, state.profile) / "config.yaml")), ("env", str(target_home_for(state.home, state.profile) / ".env"))])


def step3(ui: WizardTui, state: WizardState) -> None:
    ui.step(3, TOTAL_STEPS, "Provider setup")
    env_file = load_env_values(target_home_for(state.home, state.profile) / ".env")
    provider = state.saved.get("provider", {}) if isinstance(state.saved.get("provider"), dict) else {}
    state.provider_kind = _choose(ui, "Provider strategy", [Choice("HashMicro xAI provider", "hashmicro"), Choice("Use existing configured provider", "existing"), Choice("OpenAI-compatible custom provider", "custom"), Choice("Skip provider setup for now", "skip")], provider.get("kind", "hashmicro"))
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
        src = _choose(ui, "Credential source", [Choice("Enter key securely now", "enter"), Choice("Skip key and configure later", "skip")], "skip")
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
    choices = [Choice(m, m, recommended=m == "gpt-5.5") for m in state.models] + [Choice("Manual model name...", "manual")]
    main = _choose(ui, "Main model", choices or [Choice("Manual model name...", "manual")], saved_models.get("main", "gpt-5.5"))
    state.main_model = ui.text("Manual model name", "gpt-5.5") if main == "manual" else main
    ctx_default = 272000 if state.main_model == "gpt-5.5" else _context_default_for_model(state.main_model, {})
    ctx = _choose(ui, "Context window", [Choice("272000 tokens", "272000"), Choice("128000 tokens", "128000"), Choice("64000 tokens", "64000"), Choice("Use provider/model default", "0"), Choice("Custom...", "custom")], str(saved_models.get("context") or ctx_default or 0))
    state.context = int(ui.text("Custom context tokens", str(ctx_default or 128000)) if ctx == "custom" else ctx)
    delegation = _choose(ui, "Delegation model", [Choice(f"Same as main: {state.main_model}", "same")] + choices, saved_models.get("delegation", "same"))
    state.delegation_model = state.main_model if delegation == "same" else ui.text("Manual delegation model", state.main_model) if delegation == "manual" else delegation
    aux_mode = _choose(ui, "Auxiliary routing", [Choice("Use same model for all auxiliary tasks", "same"), Choice("Use smaller/faster model for all auxiliary tasks", "small"), Choice("Customize by task", "custom"), Choice("Keep existing auxiliary routing", "keep")], "same")
    if aux_mode == "small":
        model = state.models[-1] if state.models else ui.text("Smaller/faster model", state.main_model)
        state.aux = {task: model for task in AUXILIARY_TASKS}
    elif aux_mode == "custom":
        tasks = _multi(ui, "Tasks to customize", [Choice(t, t) for t in AUXILIARY_TASKS], set())
        for task in tasks:
            state.aux[task] = _choose(ui, f"Model for {task}", [Choice("Same as main", "same")] + choices, "same")
            if state.aux[task] == "same":
                state.aux[task] = state.main_model


def step5(ui: WizardTui, state: WizardState) -> None:
    ui.step(5, TOTAL_STEPS, "Stack components")
    defaults = set(state.saved.get("components", state.components)) if isinstance(state.saved.get("components", []), list) else state.components
    choices = []
    existing_root = target_home_for(state.home, state.profile)
    for label, value in COMPONENTS.items():
        disabled = state.mode == "skills-only" and value not in {"skills", "verify"} or state.mode == "plugins-only" and value not in {"plugins", "verify"} or state.mode == "provider-only" and value not in {"config", "verify"}
        desc = "installed, will update" if (existing_root / value).exists() or (value == "config" and (existing_root / "config.yaml").exists()) else ""
        choices.append(Choice(label, value, desc, disabled=disabled))
    state.components = _multi(ui, "Components", choices, defaults)


def step6(ui: WizardTui, state: WizardState) -> None:
    ui.step(6, TOTAL_STEPS, "Skill packs and credentials")
    if "skills" not in state.components:
        state.skill_packs = set(); return
    packs = state.saved.get("skills", {}).get("packs", list(state.skill_packs)) if isinstance(state.saved.get("skills"), dict) else list(state.skill_packs)
    state.skill_packs = _multi(ui, "Skill packs", [Choice("Core Hermes skills", "core"), Choice("Recommended productivity skills", "recommended"), Choice("HashMicro/HMX skills", "hmx", "requires GitLab token"), Choice("None / skip skill install", "none")], set(packs))
    if "none" in state.skill_packs:
        state.skill_packs = set(); return
    if "hmx" in state.skill_packs:
        env_file = load_env_values(target_home_for(state.home, state.profile) / ".env")
        if not env_file.get("GITLAB_TOKEN") and not state.env.get("GITLAB_TOKEN"):
            if _choose(ui, "HMX credential source", [Choice("Enter GitLab token securely now", "enter"), Choice("Skip HMX skills", "skip")], "skip") == "enter":
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
    state.conflict_policy = _choose(ui, "Global conflict policy", [Choice("Ask per conflict", "ask"), Choice("Skip conflicting skills", "skip"), Choice("Backup then replace conflicts", "backup-replace"), Choice("Merge when safe, ask otherwise", "merge-safe"), Choice("Abort skill installation", "abort", danger=True)], "ask")
    if state.conflict_policy == "ask":
        for name in conflicts:
            state.conflict_decisions[name] = _choose(ui, f"Conflict: {name}", [Choice("Keep existing / skip this skill", "skip"), Choice("Backup existing then install new", "backup-replace"), Choice(f"Install new as {name}-new", "install-new"), Choice("Abort", "abort", danger=True)], "skip")


def step8(ui: WizardTui, state: WizardState) -> InstallerOptions:
    ui.step(8, TOTAL_STEPS, "Final review")
    options = to_installer_options(state)
    plans = build_plans(options)
    ui.summary_table("Review", [("Target", f"{state.home} / {state.profile}"), ("Mode", state.mode), ("Provider", f"{state.provider_kind}:{state.provider_name} {state.base_url}"), ("Models", f"main={state.main_model}, delegation={state.delegation_model}, context={state.context}"), ("Components", ", ".join(sorted(state.components))), ("Skill packs", ", ".join(sorted(state.skill_packs)) or "none"), ("Files", ", ".join(str(p.config_path) for p in plans))])
    state.action = _choose(ui, "Action", [Choice("Apply changes now", "apply"), Choice("Show detailed diff/plan", "plan"), Choice("Save plan to file", "save-plan"), Choice("Go back and edit choices", "back"), Choice("Exit without changes", "cancel")], "plan" if state.dry_run else "apply")
    save = _choose(ui, "Save choices", [Choice("Save non-secret choices as profile: default", "default"), Choice("Save as new profile...", "new"), Choice("Do not save choices", "")], "default")
    state.save_profile = ui.text("Choices profile name", "default") if save == "new" else save
    return options


def step9(ui: WizardTui, state: WizardState, options: InstallerOptions) -> None:
    ui.step(9, TOTAL_STEPS, "Execute and verify")
    plans = build_plans(options)
    if state.action in {"plan", "save-plan"} or options.dry_run:
        for plan in plans:
            print_plan(plan)
    if state.action == "save-plan":
        path = Path(ui.text("Plan output path", "hermes-stack-bootstrap-plan.txt"))
        path.write_text("\n\n".join(f"Plan for {p.options.profile}\n" + "\n".join(s.title for s in p.steps) for p in plans), encoding="utf-8")
        ui.info(f"Plan saved: {path}")
    if state.action == "apply":
        for i, phase in enumerate(["Preparing backups", "Writing .env secrets", "Merging provider config", "Writing model routing", "Installing plugins/tools", "Installing skills", "Installing cron/memory assets", "Running verification", "Finalizing saved choices"], 1):
            ui.progress(phase, i, 9)
        apply_plans(plans)
    saved_path = _save_choices(state)
    ui.summary_table("Finish", [("Action", state.action), ("Choices saved", str(saved_path) if saved_path else "no"), ("Secrets", ", ".join(k for k, v in [(state.key_env, state.api_key), ("GITLAB_TOKEN", state.hmx_token)] if v) or "none written by wizard")])


def to_installer_options(state: WizardState) -> InstallerOptions:
    mode = "plugin-skill-only" if state.mode in {"skills-only", "plugins-only"} else "full"
    setup_provider = state.provider_kind in {"hashmicro", "custom", "existing"} and "config" in state.components
    return InstallerOptions(
        base_home=state.home, profile=state.profile, hermes_bin=state.hermes_bin, hermes_python=state.hermes_python,
        hermes_python_source=state.hermes_python_source, yes=True, dry_run=state.dry_run or state.action in {"plan", "save-plan"}, install_mode=mode,
        skip_lcm="plugins" not in state.components, skip_mnemosyne="memories" not in state.components,
        skip_progress_tail="plugins" not in state.components, skip_config_env="config" not in state.components,
        skip_verify="verify" not in state.components, progress_tail_ref=PROGRESS_TAIL_REF,
        install_superpowers="recommended" in state.skill_packs, install_hmx_knowledge="hmx" in state.skill_packs,
        install_impeccable="recommended" in state.skill_packs, install_ponytail="recommended" in state.skill_packs,
        hmx_knowledge_url=HMX_KNOWLEDGE_REPO, hmx_gitlab_token=state.hmx_token,
        setup_hashmicro_provider=setup_provider, hashmicro_base_url=state.base_url, hashmicro_provider_name=state.provider_name,
        hashmicro_key_env=state.key_env, hashmicro_api_key=state.api_key, hashmicro_main_model=state.main_model,
        hashmicro_main_context_length=state.context, hashmicro_delegation_model=state.delegation_model,
        hashmicro_delegation_context_length=state.context, hashmicro_auxiliary_models=state.aux,
        hashmicro_auxiliary_context_lengths={k: state.context for k in state.aux}, hashmicro_reasoning_effort=HASHMICRO_DEFAULT_REASONING_EFFORT,
        hashmicro_available_models=tuple(state.models), generate_soul="soul" in state.components,
    )


def run_wizard_v2(*, env: Mapping[str, str] | None = None, ui: WizardTui | None = None, execute: bool = True) -> InstallerOptions:
    """Run all nine v2 wizard steps and return the resulting options.

    When ``execute`` is false, Step 9 is skipped after options are built; this is
    useful for tests and for callers that only need the dataclass conversion.
    """
    runtime_env = dict(os.environ if env is None else env)
    state = WizardState(env=runtime_env)
    tui = ui or ConsoleWizardTui()
    step1(tui, state); step2(tui, state); step3(tui, state); step4(tui, state)
    step5(tui, state); step6(tui, state); step7(tui, state)
    options = step8(tui, state)
    if state.action == "back":
        step4(tui, state); step5(tui, state); options = step8(tui, state)
    if state.action == "cancel":
        tui.info("Cancelled; no changes applied.")
        return options
    if execute:
        step9(tui, state, options)
    return options


# Compatibility alias for callers that expect a simple wizard function.
wizard_v2 = run_wizard_v2
