"""YAML state management for the v2 bootstrap wizard.

The v2 wizard stores reusable, human-readable install choices outside the
Hermes profile.  This module is intentionally small and side-effect-light:
callers decide when to prompt; this module finds profiles, loads/saves YAML,
and converts current installer options into a strictly non-secret document.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .bootstrap_data import HASHMICRO_BASE_URL, HASHMICRO_KEY_ENV, HASHMICRO_PROVIDER_NAME, InstallerOptions

STATE_VERSION = 1
CONFIG_DIR = Path("~/.config/hermes-stack-bootstrap").expanduser()
PROFILES_DIR = CONFIG_DIR / "profiles"
DEFAULT_PROFILE_NAMES = ("default", "work", "personal", "hashmicro")
SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential|gitlab[_-]?token|access[_-]?token)", re.I)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ProviderChoices:
    kind: str = ""
    provider_name: str = ""
    base_url: str = ""
    key_env: str = ""


@dataclass(frozen=True)
class ModelChoices:
    main: str = ""
    delegation: str = ""
    aux_default: str = ""
    aux_overrides: dict[str, str] = field(default_factory=dict)
    context: int = 0
    delegation_context: int = 0
    aux_contexts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ComponentChoices:
    install_config: bool = True
    install_plugins: bool = True
    install_skills: bool = True
    install_cron: bool = False
    install_memory: bool = False
    install_soul: bool = False


@dataclass(frozen=True)
class SkillChoices:
    packs: list[str] = field(default_factory=list)
    conflict_policy: str = "ask"


@dataclass(frozen=True)
class VerificationChoices:
    run_smoke: bool = True
    create_soul: str = "ask"


@dataclass(frozen=True)
class WizardProfile:
    version: int = STATE_VERSION
    mode: str = "full"
    hermes_home: str = "~/.hermes"
    profile: str = "default"
    provider: ProviderChoices = field(default_factory=ProviderChoices)
    models: ModelChoices = field(default_factory=ModelChoices)
    components: ComponentChoices = field(default_factory=ComponentChoices)
    skills: SkillChoices = field(default_factory=SkillChoices)
    verification: VerificationChoices = field(default_factory=VerificationChoices)


class WizardStateError(ValueError):
    """Raised when a saved wizard profile is invalid or unsafe."""


def profiles_dir(base_dir: Path | None = None) -> Path:
    return (base_dir or PROFILES_DIR).expanduser()


def profile_path(name: str, base_dir: Path | None = None) -> Path:
    safe = normalize_profile_name(name)
    return profiles_dir(base_dir) / f"{safe}.yaml"


def normalize_profile_name(name: str) -> str:
    safe = (name or "default").strip()
    if safe.endswith((".yaml", ".yml")):
        safe = Path(safe).stem
    if not safe or safe in {".", ".."} or "/" in safe or "\\" in safe or not SAFE_NAME_RE.match(safe):
        raise WizardStateError(f"Invalid wizard profile name: {name!r}")
    return safe


def list_profiles(base_dir: Path | None = None) -> list[str]:
    directory = profiles_dir(base_dir)
    try:
        paths = [*directory.glob("*.yaml"), *directory.glob("*.yml")]
    except OSError:
        return []
    return sorted({path.stem for path in paths if path.is_file()})


def profile_list(base_dir: Path | None = None) -> dict[str, Path]:
    """Return dict mapping profile names to their file paths for CLI usage."""
    directory = profiles_dir(base_dir)
    profiles = {}
    try:
        paths = [*directory.glob("*.yaml"), *directory.glob("*.yml")]
    except OSError:
        return profiles
    
    for path in paths:
        if path.is_file():
            name = path.stem
            profiles[name] = path
    
    return profiles


def profile_delete(name: str, base_dir: Path | None = None) -> bool:
    """Delete a profile by name. Returns True if deleted, False if not found."""
    path = profile_path(name, base_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def profile_show(name: str, base_dir: Path | None = None) -> dict | None:
    """Load and return profile data as dict. Returns None if not found."""
    path = profile_path(name, base_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def load_profile(name: str, base_dir: Path | None = None) -> WizardProfile:
    return load_profile_file(profile_path(name, base_dir))


def load_profile_file(path: Path) -> WizardProfile:
    try:
        raw = yaml.safe_load(path.expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise WizardStateError(f"Could not read wizard profile {path}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise WizardStateError(f"Wizard profile {path} must contain a YAML mapping")
    cleaned = scrub_secrets(dict(raw))
    return profile_from_mapping(cleaned)


def save_profile(name: str, profile: WizardProfile | Mapping[str, Any], base_dir: Path | None = None) -> Path:
    path = profile_path(name, base_dir)
    save_profile_file(path, profile)
    return path


def save_profile_file(path: Path, profile: WizardProfile | Mapping[str, Any]) -> None:
    data = scrub_secrets(profile_to_dict(profile))
    data["version"] = int(data.get("version") or STATE_VERSION)
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def profile_to_dict(profile: WizardProfile | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(profile, WizardProfile):
        return _drop_empty(asdict(profile))
    return _drop_empty(dict(profile))


def profile_from_mapping(data: Mapping[str, Any]) -> WizardProfile:
    version = int(data.get("version") or STATE_VERSION)
    if version > STATE_VERSION:
        raise WizardStateError(f"Unsupported wizard profile version: {version}")
    provider = _mapping(data.get("provider"))
    models = _mapping(data.get("models"))
    components = _mapping(data.get("components"))
    skills = _mapping(data.get("skills"))
    verification = _mapping(data.get("verification"))
    return WizardProfile(
        version=version,
        mode=str(data.get("mode") or "full"),
        hermes_home=str(data.get("hermes_home") or "~/.hermes"),
        profile=str(data.get("profile") or "default"),
        provider=ProviderChoices(
            kind=str(provider.get("kind") or ""),
            provider_name=str(provider.get("provider_name") or provider.get("name") or ""),
            base_url=str(provider.get("base_url") or provider.get("url") or ""),
            key_env=str(provider.get("key_env") or ""),
        ),
        models=ModelChoices(
            main=str(models.get("main") or ""),
            delegation=str(models.get("delegation") or ""),
            aux_default=str(models.get("aux_default") or ""),
            aux_overrides=_str_dict(models.get("aux_overrides")),
            context=_int(models.get("context")),
            delegation_context=_int(models.get("delegation_context")),
            aux_contexts=_int_dict(models.get("aux_contexts")),
        ),
        components=ComponentChoices(
            install_config=bool(components.get("install_config", True)),
            install_plugins=bool(components.get("install_plugins", True)),
            install_skills=bool(components.get("install_skills", True)),
            install_cron=bool(components.get("install_cron", False)),
            install_memory=bool(components.get("install_memory", False)),
            install_soul=bool(components.get("install_soul", False)),
        ),
        skills=SkillChoices(
            packs=list(skills.get("packs") or []),
            conflict_policy=str(skills.get("conflict_policy") or "ask"),
        ),
        verification=VerificationChoices(
            run_smoke=bool(verification.get("run_smoke", True)),
            create_soul=str(verification.get("create_soul") or "ask"),
        ),
    )


def profile_from_options(options: InstallerOptions) -> WizardProfile:
    packs: list[str] = []
    if options.install_superpowers:
        packs.append("core")
    if options.install_hmx_knowledge:
        packs.append("hmx")
    if options.install_impeccable:
        packs.append("impeccable")
    if options.install_ponytail:
        packs.append("ponytail")
    provider = ProviderChoices(
        kind="hashmicro" if options.setup_hashmicro_provider else "",
        provider_name=options.hashmicro_provider_name if options.setup_hashmicro_provider else "",
        base_url=options.hashmicro_base_url if options.setup_hashmicro_provider else "",
        key_env=options.hashmicro_key_env if options.setup_hashmicro_provider else "",
    )
    models = ModelChoices(
        main=options.hashmicro_main_model,
        delegation=options.hashmicro_delegation_model,
        aux_default=_common_value(options.hashmicro_auxiliary_models),
        aux_overrides=dict(options.hashmicro_auxiliary_models or {}),
        context=int(options.hashmicro_main_context_length or 0),
        delegation_context=int(options.hashmicro_delegation_context_length or 0),
        aux_contexts=dict(options.hashmicro_auxiliary_context_lengths or {}),
    )
    return WizardProfile(
        mode=options.install_mode,
        hermes_home=str(options.base_home),
        profile=options.profile or "default",
        provider=provider,
        models=models,
        components=ComponentChoices(
            install_config=not options.skip_config_env,
            install_plugins=not options.skip_lcm or not options.skip_progress_tail,
            install_skills=bool(packs),
            install_soul=bool(options.generate_soul),
        ),
        skills=SkillChoices(packs=packs, conflict_policy="ask"),
        verification=VerificationChoices(run_smoke=not options.skip_verify, create_soul="yes" if options.generate_soul else "ask"),
    )


def apply_profile_defaults(args: Any, profile: WizardProfile, explicit_flags: set[str] | None = None) -> None:
    """Apply loaded choices to an argparse namespace without overriding explicit flags."""
    explicit = explicit_flags or set()
    _set_default(args, "install_mode", profile.mode, explicit, "--install-mode")
    _set_default(args, "home", profile.hermes_home, explicit, "--home", "--hermes-home")
    _set_default(args, "profile", [profile.profile], explicit, "--profile")
    if profile.provider.provider_name or profile.provider.base_url:
        _set_default(args, "setup_hashmicro_provider", profile.provider.kind == "hashmicro", explicit, "--setup-hashmicro-provider")
        _set_default(args, "hashmicro_provider_name", profile.provider.provider_name, explicit, "--hashmicro-provider-name")
        _set_default(args, "hashmicro_base_url", profile.provider.base_url, explicit, "--hashmicro-base-url")
        _set_default(args, "hashmicro_key_env", profile.provider.key_env, explicit, "--hashmicro-key-env")
    _set_default(args, "main_model", profile.models.main, explicit, "--main-model")
    _set_default(args, "delegation_model", profile.models.delegation, explicit, "--delegation-model")
    _set_default(args, "main_context_length", str(profile.models.context or ""), explicit, "--main-context-length")
    _set_default(
        args, "delegation_context_length", str(profile.models.delegation_context or ""), explicit, "--delegation-context-length"
    )
    if profile.models.aux_default:
        _set_default(args, "aux_all_model", profile.models.aux_default, explicit, "--aux-all-model")
    if profile.models.aux_overrides and "--aux-model" not in explicit and hasattr(args, "aux_model"):
        args.aux_model = [f"{key}={value}" for key, value in sorted(profile.models.aux_overrides.items())]
    _set_default(args, "skip_config_env", not profile.components.install_config, explicit, "--skip-config-env")
    _set_default(args, "skip_verify", not profile.verification.run_smoke, explicit, "--skip-verify")
    _set_default(args, "generate_soul", profile.components.install_soul, explicit, "--generate-soul")
    pack_flags = {
        "core": "install_superpowers",
        "hmx": "install_hmx_knowledge",
        "impeccable": "install_impeccable",
        "ponytail": "install_ponytail",
    }
    for pack, attr in pack_flags.items():
        _set_default(args, attr, pack in profile.skills.packs, explicit, "--" + attr.replace("_", "-"))


def startup_choices(base_dir: Path | None = None) -> list[dict[str, str]]:
    choices = [{"label": "Start fresh using recommended defaults", "value": "fresh"}]
    for name in list_profiles(base_dir):
        choices.append({"label": f"Load saved choices: {name}", "value": name})
    choices.append({"label": "Import choices from file...", "value": "import"})
    return choices


def prompt_load_profile(tui: Any, base_dir: Path | None = None) -> tuple[str, WizardProfile | None]:
    names = list_profiles(base_dir)
    if not names:
        return "fresh", None
    labels = ["Start fresh using recommended defaults", *[f"Load saved choices: {name}" for name in names], "Import choices from file..."]
    selected = tui.select("Choices source", tuple(labels), labels[1] if "default" in names else labels[0])
    if selected == labels[0]:
        return "fresh", None
    if selected == labels[-1]:
        path = Path(tui.text("Path to choices YAML/JSON file")).expanduser()
        return "import", load_profile_file(path)
    name = selected.removeprefix("Load saved choices: ")
    return name, load_profile(name, base_dir)


def prompt_save_profile(tui: Any, profile: WizardProfile, loaded_name: str | None = None, base_dir: Path | None = None) -> Path | None:
    default_name = loaded_name or "default"
    labels = [f"Save non-secret choices as profile: {default_name}", "Save as new profile...", "Do not save choices"]
    selected = tui.select("Save choices", tuple(labels), labels[0])
    if selected == labels[-1]:
        return None
    name = default_name if selected == labels[0] else tui.text("Profile name", default="default")
    return save_profile(name, profile, base_dir)


def scrub_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text) and key_text not in {"key_env"}:
                continue
            cleaned[key_text] = scrub_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _set_default(args: Any, attr: str, value: Any, explicit: set[str], *flags: str) -> None:
    if not hasattr(args, attr) or any(flag in explicit for flag in flags) or value in (None, ""):
        return
    setattr(args, attr, value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _str_dict(value: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in _mapping(value).items() if v not in (None, "")}


def _int_dict(value: Any) -> dict[str, int]:
    return {str(k): _int(v) for k, v in _mapping(value).items() if _int(v) > 0}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_empty(v) for k, v in value.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_drop_empty(item) for item in value]
    return value


def _common_value(values: Mapping[str, str]) -> str:
    unique = {value for value in (values or {}).values() if value}
    return unique.pop() if len(unique) == 1 else ""


def recommended_default_profile() -> WizardProfile:
    return WizardProfile(
        provider=ProviderChoices(
            kind="hashmicro",
            provider_name=HASHMICRO_PROVIDER_NAME,
            base_url=HASHMICRO_BASE_URL,
            key_env=HASHMICRO_KEY_ENV,
        ),
        models=ModelChoices(main="gpt-5.5", delegation="gpt-5.5", aux_default="gpt-5.5", context=272000),
        components=ComponentChoices(),
        skills=SkillChoices(packs=["core", "recommended"], conflict_policy="ask"),
        verification=VerificationChoices(run_smoke=True, create_soul="ask"),
    )
