"""Safe config merge helpers for the Hermes stack bootstrapper."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


REQUIRED_PLUGINS = ("hermes-lcm", "mnemosyne")


DEFAULT_MEMORY_MNEMOSYNE = {
    "auto_sleep": True,
    "profile_isolation": False,
    "vector_type": "int8",
    "skip_contexts": "cron,flush,subagent,background,skill_loop",
}


DEFAULT_COMPRESSION = {
    "enabled": True,
    "threshold": 0.8,
    "target_ratio": 0.6,
    "protect_last_n": 72,
}

# Explicit fallback for a fresh Telegram platform config when neither CLI nor
# top-level toolset selections exist. Keep this as toolset names, not tool
# names: `platform_toolsets.<platform>` is an allowlist of toolsets.
ALL_FALLBACK_TELEGRAM_TOOLSETS = (
    "web",
    "search",
    "x_search",
    "vision",
    "video",
    "image_gen",
    "video_gen",
    "computer_use",
    "terminal",
    "moa",
    "skills",
    "browser",
    "cronjob",
    "file",
    "code_execution",
    "tts",
    "todo",
    "memory",
    "context_engine",
    "session_search",
    "clarify",
    "delegation",
    "homeassistant",
    "kanban",
    "discord",
    "discord_admin",
    "yuanbao",
    "feishu_doc",
    "feishu_drive",
    "spotify",
    "debugging",
    "safe",
    "coding",
)


def _ensure_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _append_unique(items: list[Any], new_items: tuple[str, ...]) -> list[Any]:
    result = list(items)
    for item in new_items:
        if item not in result:
            result.append(item)
    return result


def _telegram_seed_toolsets(cfg: dict[str, Any], platform_toolsets: dict[str, Any]) -> list[Any]:
    seed = _ensure_list(platform_toolsets.get("cli"))
    if not seed:
        seed = _ensure_list(cfg.get("toolsets"))
    if not seed:
        seed = list(ALL_FALLBACK_TELEGRAM_TOOLSETS)
    return seed


def _telegram_toolsets_for(cfg: dict[str, Any], platform_toolsets: dict[str, Any]) -> list[Any]:
    """Return Telegram toolsets without narrowing a first-time Telegram config.

    Adding only ``memory`` creates an explicit Telegram override and disables the
    broad default ``hermes-telegram`` tool universe. When Telegram has no saved
    selection yet, seed it from the CLI selection first, then top-level
    ``toolsets``, and finally all known toolsets.
    """
    if "telegram" in platform_toolsets:
        existing = _ensure_list(platform_toolsets.get("telegram"))
        if existing == ["memory"]:
            return _append_unique(_telegram_seed_toolsets(cfg, platform_toolsets), ("memory",))
        return _append_unique(existing, ("memory",))

    return _append_unique(_telegram_seed_toolsets(cfg, platform_toolsets), ("memory",))


def build_target_config(existing: dict[str, Any] | None) -> dict[str, Any]:
    """Return config with LCM + Mnemosyne activated, preserving unrelated keys.

    This intentionally does *not* configure hermes-progress-tail. That plugin's
    upstream installer owns its own config merge contract and should be invoked
    per its README.
    """
    cfg: dict[str, Any] = deepcopy(existing or {})

    plugins = _ensure_mapping(cfg.get("plugins"))
    plugins["enabled"] = _append_unique(_ensure_list(plugins.get("enabled")), REQUIRED_PLUGINS)
    cfg["plugins"] = plugins

    context = _ensure_mapping(cfg.get("context"))
    context["engine"] = "lcm"
    cfg["context"] = context

    compression = _ensure_mapping(cfg.get("compression"))
    for key, value in DEFAULT_COMPRESSION.items():
        compression[key] = value
    cfg["compression"] = compression

    memory = _ensure_mapping(cfg.get("memory"))
    memory["provider"] = "mnemosyne"
    memory["memory_enabled"] = False
    memory["user_profile_enabled"] = False
    mnemosyne = _ensure_mapping(memory.get("mnemosyne"))
    for key, value in DEFAULT_MEMORY_MNEMOSYNE.items():
        mnemosyne.setdefault(key, value)
    memory["mnemosyne"] = mnemosyne
    cfg["memory"] = memory

    platform_toolsets = _ensure_mapping(cfg.get("platform_toolsets"))
    platform_toolsets["telegram"] = _telegram_toolsets_for(cfg, platform_toolsets)
    cfg["platform_toolsets"] = platform_toolsets

    return cfg


def _yaml_module():
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "PyYAML is required to edit config.yaml. Run this installer with Hermes' runtime Python or install PyYAML."
        ) from exc
    return yaml


def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    yaml = _yaml_module()
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def write_config(path: Path, config: dict[str, Any]) -> None:
    yaml = _yaml_module()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    path.write_text(text)
