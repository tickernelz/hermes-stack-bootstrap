#!/usr/bin/env bash
set -euo pipefail

REPO="${HERMES_STACK_REPO:-tickernelz/hermes-stack-bootstrap}"
REF="${HERMES_STACK_REF:-main}"
SOURCE_DIR="${HERMES_STACK_SOURCE_DIR:-}"

detect_hermes_home() {
  if [[ -n "${HERMES_HOME:-}" ]]; then
    printf '%s\n' "$HERMES_HOME"
    return 0
  fi
  if command -v hermes >/dev/null 2>&1; then
    local config_path
    config_path="$(hermes config path 2>/dev/null | tail -n 1 || true)"
    if [[ "$config_path" == */profiles/*/config.yaml ]]; then
      printf '%s\n' "${config_path%%/profiles/*}"
      return 0
    fi
    if [[ "$config_path" == */config.yaml ]]; then
      printf '%s\n' "${config_path%/config.yaml}"
      return 0
    fi
  fi
  printf '%s\n' "$HOME/.hermes"
}

DETECTED_HERMES_HOME="$(detect_hermes_home)"
PYTHON_BIN="${HERMES_STACK_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$DETECTED_HERMES_HOME/hermes-agent/venv/bin/python" ]]; then
    PYTHON_BIN="$DETECTED_HERMES_HOME/hermes-agent/venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ -n "$SOURCE_DIR" ]]; then
  cd "$SOURCE_DIR"
  exec "$PYTHON_BIN" -m hermes_stack_bootstrap "$@"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE_URL="https://github.com/${REPO}/archive/${REF}.tar.gz"
echo "Downloading hermes-stack-bootstrap from ${ARCHIVE_URL}"

curl -fsSL "$ARCHIVE_URL" -o "$TMP_DIR/bootstrap.tar.gz"
tar -xzf "$TMP_DIR/bootstrap.tar.gz" -C "$TMP_DIR"
EXTRACTED="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

cd "$EXTRACTED"
exec "$PYTHON_BIN" -m hermes_stack_bootstrap "$@"
