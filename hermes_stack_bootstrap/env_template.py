"""Environment template helpers for the Hermes stack bootstrapper."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_./:@%+=,-]+$")


DEFAULT_LCM_SUMMARY_MODEL = "lokal_sub2api/gpt-5.4-mini"


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


DEFAULT_LOCAL_MNEMOSYNE_ENV = {
    # Force the local LLM fallback path and keep remote LLM URLs/API keys out of public installs.
    "MNEMOSYNE_FORCE_LOCAL": "1",
    "MNEMOSYNE_LLM_ENABLED": "true",
    "MNEMOSYNE_LLM_REPO": "openbmb/MiniCPM5-1B-GGUF",
    "MNEMOSYNE_LLM_FILE": "MiniCPM5-1B-Q4_K_M.gguf",
    "MNEMOSYNE_LLM_N_CTX": "2048",
    "MNEMOSYNE_LLM_MAX_TOKENS": "2048",
    "MNEMOSYNE_LLM_N_THREADS": "4",
    # Explicit local fastembed model/dim so an unrelated OPENAI/OpenRouter key cannot silently switch behavior.
    "MNEMOSYNE_EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    "MNEMOSYNE_EMBEDDING_DIM": "384",
    # Mnemosyne docs default to int8 as the good storage/accuracy tradeoff for local use.
    "MNEMOSYNE_VEC_TYPE": "int8",
    "MNEMOSYNE_WM_MAX_ITEMS": "10000",
    "MNEMOSYNE_WM_TTL_HOURS": "48",
    "MNEMOSYNE_EP_LIMIT": "50000",
    "MNEMOSYNE_SLEEP_BATCH": "3000",
    "MNEMOSYNE_SP_MAX": "1000",
    "MNEMOSYNE_RECENCY_HALFLIFE": "168",
}


def build_env_values(
    *,
    home: str,
    summary_model: str = DEFAULT_LCM_SUMMARY_MODEL,
    mnemosyne_data_dir: str = "",
) -> dict[str, str]:
    """Build non-secret env defaults for LCM + local Mnemosyne.

    This deliberately avoids remote API key variables. The Mnemosyne preset is
    local-first: local embeddings from the `[all]` install profile and local GGUF
    LLM fallback via `llama-cpp-python`/`ctransformers`.
    """
    values: dict[str, str] = {}
    values.update(DEFAULT_LCM_ENV)
    if summary_model:
        values["LCM_SUMMARY_MODEL"] = summary_model
        values["LCM_EXPANSION_MODEL"] = summary_model

    values.update(DEFAULT_LOCAL_MNEMOSYNE_ENV)
    values["MNEMOSYNE_DATA_DIR"] = mnemosyne_data_dir or str(
        Path(home).expanduser() / "mnemosyne" / "data"
    )
    return values


def quote_env_value(value: str) -> str:
    if value == "":
        return '""'
    if _SAFE_VALUE.match(value):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def render_env_block(values: Mapping[str, str]) -> str:
    return "".join(f"{key}={quote_env_value(str(values[key]))}\n" for key in sorted(values))


def merge_env_text(existing_text: str, values: Mapping[str, str]) -> str:
    """Append/update managed env values while preserving unrelated lines."""
    managed = set(values)
    output: list[str] = []
    seen: set[str] = set()
    for line in existing_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in managed:
                output.append(f"{key}={quote_env_value(str(values[key]))}")
                seen.add(key)
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
