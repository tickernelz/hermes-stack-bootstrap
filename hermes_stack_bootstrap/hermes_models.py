"""Small wrappers around Hermes' own provider/model inventory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderChoice:
    slug: str
    label: str
    models: tuple[str, ...]


def list_hermes_authenticated_providers() -> list[dict]:
    """Return Hermes' authenticated provider inventory.

    Kept as a tiny indirection so tests can patch it without importing Hermes.
    """
    try:
        from hermes_cli.inventory import build_models_payload, load_picker_context

        return build_models_payload(load_picker_context(), max_models=50)["providers"]
    except Exception:
        from hermes_cli.model_switch import list_authenticated_providers

        return list_authenticated_providers(max_models=50)


def provider_model_ids(provider: str) -> list[str]:
    from hermes_cli.models import provider_model_ids as _provider_model_ids

    return _provider_model_ids(provider)


def _json_from_runtime(
    hermes_python: Path,
    expression: str,
    hermes_home: Path | None = None,
) -> object:
    env = None
    if hermes_home is not None:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(hermes_home)
    completed = subprocess.run(
        [str(hermes_python), "-c", expression],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    return json.loads(completed.stdout or "null")


def _provider_rows_from_runtime(hermes_python: Path | None, hermes_home: Path | None = None) -> list[dict] | None:
    if hermes_python is None or Path(hermes_python) == Path(sys.executable):
        return None
    script = (
        "import json;"
        "\ntry:\n"
        " from hermes_cli.inventory import build_models_payload,load_picker_context\n"
        " rows=build_models_payload(load_picker_context(), max_models=50)['providers']\n"
        "except Exception:\n"
        " from hermes_cli.model_switch import list_authenticated_providers\n"
        " rows=list_authenticated_providers(max_models=50)\n"
        "print(json.dumps(rows))"
    )
    try:
        rows = _json_from_runtime(Path(hermes_python), script, hermes_home)
    except Exception:
        return None
    return rows if isinstance(rows, list) else None


def provider_choices(
    hermes_python: Path | None = None,
    hermes_home: Path | None = None,
) -> list[ProviderChoice]:
    try:
        runtime_rows = _provider_rows_from_runtime(hermes_python, hermes_home)
        rows = runtime_rows if runtime_rows is not None else list_hermes_authenticated_providers()
    except Exception:
        return []

    choices: list[ProviderChoice] = []
    for row in rows:
        slug = str(row.get("slug") or "").strip()
        if not slug:
            continue
        name = str(row.get("name") or slug).strip()
        models = tuple(str(model) for model in (row.get("models") or []) if str(model).strip())
        total = int(row.get("total_models") or len(models) or 0)
        suffix = f" — {total} model{'s' if total != 1 else ''}" if total else ""
        choices.append(ProviderChoice(slug=slug, label=f"{name}{suffix}", models=models))
    return choices


def _provider_model_ids_from_runtime(
    provider: str,
    hermes_python: Path | None,
    hermes_home: Path | None = None,
) -> tuple[str, ...] | None:
    if hermes_python is None or Path(hermes_python) == Path(sys.executable):
        return None
    script = (
        "import json;"
        "from hermes_cli.models import provider_model_ids;"
        f"print(json.dumps(provider_model_ids({provider!r})))"
    )
    try:
        models = _json_from_runtime(Path(hermes_python), script, hermes_home)
    except Exception:
        return None
    return tuple(str(model) for model in models) if isinstance(models, list) else None


def model_choices_for_provider(
    provider: str,
    providers: list[ProviderChoice],
    hermes_python: Path | None = None,
    hermes_home: Path | None = None,
) -> tuple[str, ...]:
    for choice in providers:
        if choice.slug == provider:
            return choice.models
    runtime_models = _provider_model_ids_from_runtime(provider, hermes_python, hermes_home)
    if runtime_models is not None:
        return runtime_models
    try:
        return tuple(provider_model_ids(provider))
    except Exception:
        return ()
