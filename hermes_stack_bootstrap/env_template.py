"""Environment template helpers for the Hermes stack bootstrapper."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_./:@%+=,-]+$")


DEFAULT_LCM_SUMMARY_MODEL = ""


DEFAULT_LCM_ENV = {
    "LCM_ENABLE_SLASH_COMMAND": "1",
    "LCM_CONTEXT_THRESHOLD": "0.8",
    "LCM_FRESH_TAIL_COUNT": "72",
    "LCM_LARGE_OUTPUT_EXTERNALIZATION_ENABLED": "true",
    "LCM_LARGE_OUTPUT_EXTERNALIZATION_THRESHOLD_CHARS": "12000",
    "LCM_LARGE_OUTPUT_TRANSCRIPT_GC_ENABLED": "true",
    "LCM_EXPANSION_CONTEXT_TOKENS": "128000",
    "LCM_SUMMARY_TIMEOUT_MS": "180000",
    "LCM_EXPANSION_TIMEOUT_MS": "240000",
}


BASE_MNEMOSYNE_ENV = {
    "MNEMOSYNE_LLM_ENABLED": "true",
    "MNEMOSYNE_LLM_MAX_TOKENS": "2048",
    "MNEMOSYNE_WM_MAX_ITEMS": "10000",
    "MNEMOSYNE_WM_TTL_HOURS": "48",
    "MNEMOSYNE_EP_LIMIT": "50000",
    "MNEMOSYNE_SLEEP_BATCH": "3000",
    "MNEMOSYNE_SP_MAX": "1000",
    "MNEMOSYNE_RECENCY_HALFLIFE": "168",
}

LOCAL_EMBEDDING_ENV = {
    # Explicit local fastembed model/dim so unrelated OpenAI/OpenRouter keys cannot silently switch behavior.
    "MNEMOSYNE_EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    "MNEMOSYNE_EMBEDDING_DIM": "384",
    # Mnemosyne docs default to int8 as the good storage/accuracy tradeoff for local use.
    "MNEMOSYNE_VEC_TYPE": "int8",
}

LOCAL_LLM_ENV = {
    # Force the local LLM path and keep remote LLM URLs/API keys out of public installs.
    "MNEMOSYNE_FORCE_LOCAL": "1",
    "MNEMOSYNE_LLM_REPO": "openbmb/MiniCPM5-1B-GGUF",
    "MNEMOSYNE_LLM_FILE": "MiniCPM5-1B-Q4_K_M.gguf",
    "MNEMOSYNE_LLM_N_CTX": "2048",
    "MNEMOSYNE_LLM_N_THREADS": "4",
}

HOST_LLM_ENV = {
    # Route consolidation through Hermes' authenticated provider/model resolution.
    "MNEMOSYNE_HOST_LLM_ENABLED": "true",
    "MNEMOSYNE_HOST_LLM_N_CTX": "32000",
}

ONLINE_EMBEDDING_ENV_KEYS = frozenset(
    {
        "MNEMOSYNE_EMBEDDINGS_VIA_API",
        "MNEMOSYNE_EMBEDDING_API_URL",
        "MNEMOSYNE_EMBEDDING_API_KEY",
    }
)

MNEMOSYNE_MODES = ("full-local", "hybrid", "full-online")

# Keys this bootstrapper owns. Used so switching modes removes stale managed keys
# while preserving user-managed secrets such as MNEMOSYNE_EMBEDDING_API_KEY.
MANAGED_MNEMOSYNE_ENV_KEYS = frozenset(
    {
        "MNEMOSYNE_DATA_DIR",
        *BASE_MNEMOSYNE_ENV,
        *LOCAL_EMBEDDING_ENV,
        *LOCAL_LLM_ENV,
        *HOST_LLM_ENV,
        *ONLINE_EMBEDDING_ENV_KEYS,
        "MNEMOSYNE_HOST_LLM_PROVIDER",
        "MNEMOSYNE_HOST_LLM_MODEL",
    }
)


def build_env_values(
    *,
    home: str,
    summary_model: str = "",
    lcm_summary_model: str = DEFAULT_LCM_SUMMARY_MODEL,
    lcm_expansion_model: str = "",
    mnemosyne_mode: str = "hybrid",
    mnemosyne_host_llm_provider: str = "",
    mnemosyne_host_llm_model: str = "",
    mnemosyne_embedding_api_url: str = "",
    mnemosyne_embedding_api_key: str = "",
    mnemosyne_embedding_model: str = "",
    mnemosyne_embedding_dim: str = "",
    mnemosyne_data_dir: str = "",
) -> dict[str, str]:
    """Build env values for LCM + Mnemosyne.

    Mnemosyne modes:
    - full-local: local fastembed + local GGUF consolidation.
    - hybrid: local fastembed + Hermes host LLM provider/model.
    - full-online: Hermes host LLM plus optional user-supplied embedding API settings.

    API keys are only included when explicitly supplied by the installer prompt or environment.
    """
    mode = mnemosyne_mode.strip().lower() or "hybrid"
    if mode not in MNEMOSYNE_MODES:
        raise ValueError(f"Unknown Mnemosyne mode: {mnemosyne_mode}")

    embedding_values = {
        "mnemosyne_embedding_api_url": mnemosyne_embedding_api_url.strip(),
        "mnemosyne_embedding_api_key": mnemosyne_embedding_api_key.strip(),
        "mnemosyne_embedding_model": mnemosyne_embedding_model.strip(),
        "mnemosyne_embedding_dim": mnemosyne_embedding_dim.strip(),
    }
    supplied_embedding_values = {key: value for key, value in embedding_values.items() if value}
    if supplied_embedding_values and mode != "full-online":
        raise ValueError("Embedding API settings are only valid with mnemosyne_mode='full-online'")
    if mode == "full-online" and supplied_embedding_values:
        required = {
            "mnemosyne_embedding_api_url": "MNEMOSYNE_EMBEDDING_API_URL",
            "mnemosyne_embedding_model": "MNEMOSYNE_EMBEDDING_MODEL",
            "mnemosyne_embedding_dim": "MNEMOSYNE_EMBEDDING_DIM",
        }
        for key, env_name in required.items():
            if not embedding_values[key]:
                raise ValueError(f"full-online embedding API config requires {env_name}")

    values: dict[str, str] = {}
    values.update(DEFAULT_LCM_ENV)

    # Backward compatible alias: --summary-model used to set both LCM model envs.
    if summary_model:
        lcm_summary_model = summary_model
        if not lcm_expansion_model:
            lcm_expansion_model = summary_model

    if lcm_summary_model:
        values["LCM_SUMMARY_MODEL"] = lcm_summary_model
    if lcm_expansion_model:
        values["LCM_EXPANSION_MODEL"] = lcm_expansion_model

    values.update(BASE_MNEMOSYNE_ENV)
    if mode in {"full-local", "hybrid"}:
        values.update(LOCAL_EMBEDDING_ENV)
    if mode == "full-local":
        values.update(LOCAL_LLM_ENV)
    else:
        values.update(HOST_LLM_ENV)
        if mnemosyne_host_llm_provider:
            values["MNEMOSYNE_HOST_LLM_PROVIDER"] = mnemosyne_host_llm_provider
        if mnemosyne_host_llm_model:
            values["MNEMOSYNE_HOST_LLM_MODEL"] = mnemosyne_host_llm_model
        if supplied_embedding_values:
            values["MNEMOSYNE_EMBEDDINGS_VIA_API"] = "true"
            values["MNEMOSYNE_EMBEDDING_API_URL"] = embedding_values["mnemosyne_embedding_api_url"]
            if embedding_values["mnemosyne_embedding_api_key"]:
                values["MNEMOSYNE_EMBEDDING_API_KEY"] = embedding_values["mnemosyne_embedding_api_key"]
            values["MNEMOSYNE_EMBEDDING_MODEL"] = embedding_values["mnemosyne_embedding_model"]
            values["MNEMOSYNE_EMBEDDING_DIM"] = embedding_values["mnemosyne_embedding_dim"]

    values["MNEMOSYNE_DATA_DIR"] = mnemosyne_data_dir or str(Path(home).expanduser() / "mnemosyne" / "data")
    return values


def quote_env_value(value: str) -> str:
    if value == "":
        return '""'
    if _SAFE_VALUE.match(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def render_env_block(values: Mapping[str, str], *, redact_keys: set[str] | None = None) -> str:
    redacted = set(redact_keys or set())
    lines: list[str] = []
    for key in sorted(values):
        value = "<redacted>" if key in redacted and values[key] else str(values[key])
        lines.append(f"{key}={quote_env_value(value)}\n")
    return "".join(lines)


def managed_env_keys() -> set[str]:
    return set(DEFAULT_LCM_ENV) | {"LCM_SUMMARY_MODEL", "LCM_EXPANSION_MODEL"} | set(MANAGED_MNEMOSYNE_ENV_KEYS)


def _unquote_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _should_drop_stale_managed_key(key: str, raw_value: str, selected_values: Mapping[str, str]) -> bool:
    if key in LOCAL_EMBEDDING_ENV:
        return _unquote_env_value(raw_value) == LOCAL_EMBEDDING_ENV[key]
    if key in ONLINE_EMBEDDING_ENV_KEYS:
        return any(local_key in selected_values for local_key in LOCAL_EMBEDDING_ENV)
    return True


def merge_env_text(
    existing_text: str,
    values: Mapping[str, str],
    *,
    managed_keys: set[str] | None = None,
) -> str:
    """Append/update managed env values while preserving unrelated lines.

    When managed_keys is provided, stale values owned by the bootstrapper are
    removed if the selected mode no longer emits them. User-owned secrets and
    endpoint keys are intentionally outside the managed set.
    """
    managed = set(values)
    all_managed = managed if managed_keys is None else set(managed_keys)
    output: list[str] = []
    seen: set[str] = set()
    for line in existing_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            if key in managed:
                output.append(f"{key}={quote_env_value(str(values[key]))}")
                seen.add(key)
                continue
            if key in all_managed and _should_drop_stale_managed_key(key, raw_value, values):
                continue
        output.append(line)
    missing = [key for key in sorted(managed) if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Added by hermes-stack-bootstrap")
        for key in missing:
            output.append(f"{key}={quote_env_value(str(values[key]))}")
    return "\n".join(output).rstrip() + "\n"
