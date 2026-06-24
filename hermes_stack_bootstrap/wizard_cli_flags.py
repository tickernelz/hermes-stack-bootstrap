"""CLI flag parsing for the Hermes stack bootstrap wizard."""

from __future__ import annotations

import argparse
from typing import Any, Sequence

from .bootstrap_option_flow import _positive_int


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-stack-bootstrap",
        description="Bootstrap Hermes LCM, Mnemosyne, progress-tail, skills, SOUL.md, and provider routing.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Run non-interactively with defaults and supplied flags"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview planned changes without writing profile files")
    parser.add_argument("--quick", action="store_true", help="Use recommended defaults without the interactive wizard")
    parser.add_argument("--home", help="Hermes base home, usually ~/.hermes")
    parser.add_argument(
        "--profile", action="append", default=[], help="Target profile; repeat or comma-separate values"
    )
    parser.add_argument("--hermes-bin", help="Hermes CLI executable used for verification and SOUL generation")
    parser.add_argument("--hermes-python", help="Python executable for the Hermes runtime environment")
    parser.add_argument("--install-mode", choices=("full", "plugin-skill-only", "soul-only"), help="Install scope")
    parser.add_argument(
        "--mnemosyne-mode", choices=("hybrid", "full-local", "full-online"), help="Mnemosyne install mode"
    )
    parser.add_argument("--skip-lcm", action="store_true")
    parser.add_argument("--skip-mnemosyne", action="store_true")
    parser.add_argument("--skip-progress-tail", action="store_true")
    parser.add_argument("--skip-config-env", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--progress-tail-ref", default="", help="hermes-progress-tail git ref/tag; defaults to latest")
    parser.add_argument("--install-superpowers", action="store_true")
    parser.add_argument("--install-hmx-knowledge", action="store_true")
    parser.add_argument("--install-impeccable", action="store_true")
    parser.add_argument("--install-ponytail", action="store_true")
    parser.add_argument("--setup-hashmicro-provider", action="store_true")
    parser.add_argument("--hashmicro-base-url")
    parser.add_argument("--hashmicro-provider-name")
    parser.add_argument("--hashmicro-key-env")
    parser.add_argument("--main-model")
    parser.add_argument("--main-context-length", type=lambda value: _positive_int(value, field="--main-context-length"))
    parser.add_argument("--delegation-model")
    parser.add_argument(
        "--delegation-context-length", type=lambda value: _positive_int(value, field="--delegation-context-length")
    )
    parser.add_argument("--aux-all-model")
    parser.add_argument(
        "--aux-all-context-length", type=lambda value: _positive_int(value, field="--aux-all-context-length")
    )
    parser.add_argument("--aux-model", action="append", default=[])
    parser.add_argument("--aux-context-length", action="append", default=[])
    parser.add_argument("--hashmicro-reasoning-effort", default="")
    parser.add_argument("--generate-soul", action="store_true")
    parser.add_argument("--soul-agent-name")
    parser.add_argument("--soul-user-name")
    parser.add_argument("--soul-communication")
    parser.add_argument("--soul-language")
    parser.add_argument("--soul-provider")
    parser.add_argument("--soul-model")
    parser.add_argument("--soul-overwrite", action="store_true")
    return parser


def parse_cli_flags(argv: Sequence[str] | None = None) -> dict[str, Any]:
    """Parse automation-friendly wizard flags."""
    ns = build_cli_parser().parse_args(list(argv or []))
    profiles = [part.strip() for item in ns.profile for part in str(item).split(",") if part.strip()]
    return {**vars(ns), "profile": ",".join(profiles) if profiles else ""}


def cli_help(argv: Sequence[str] | None = None) -> str:
    """Return rendered CLI help without entering the wizard."""
    return build_cli_parser().format_help()
