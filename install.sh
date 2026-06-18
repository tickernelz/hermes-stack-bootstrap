#!/usr/bin/env bash
set -euo pipefail

REPO="${HERMES_STACK_REPO:-tickernelz/hermes-stack-bootstrap}"
REF="${HERMES_STACK_REF:-main}"
SOURCE_DIR="${HERMES_STACK_SOURCE_DIR:-}"

is_executable() {
  [[ -n "${1:-}" && -x "$1" && -f "$1" ]]
}

find_hermes_in_path() {
  if [[ -n "${HERMES_BIN:-}" ]]; then
    printf '%s\n' "$HERMES_BIN"
    return 0
  fi
  command -v hermes 2>/dev/null || true
}

infer_python_from_hermes_bin() {
  local hermes_bin="${1:-}"
  [[ -n "$hermes_bin" ]] || return 1

  local real_bin
  real_bin="$(realpath "$hermes_bin" 2>/dev/null || printf '%s\n' "$hermes_bin")"
  local bin_dir
  bin_dir="$(dirname "$real_bin")"

  if is_executable "$bin_dir/python"; then
    printf '%s\n' "$bin_dir/python"
    return 0
  fi
  if is_executable "$bin_dir/python3"; then
    printf '%s\n' "$bin_dir/python3"
    return 0
  fi

  local shebang
  shebang="$(head -n 1 "$real_bin" 2>/dev/null || true)"
  if [[ "$shebang" == '#!'/* ]]; then
    local interpreter="${shebang#\#!}"
    interpreter="${interpreter%% *}"
    if is_executable "$interpreter"; then
      printf '%s\n' "$interpreter"
      return 0
    fi
  fi
  return 1
}

scan_filesystem_for_hermes() {
  local deadline=$((SECONDS + 4))
  local found=""
  # Flexible bounded search: look for executable files named hermes, prune pseudo/noisy trees.
  # No hardcoded /opt assumption; /opt is found only if it contains a matching executable.
  while IFS= read -r candidate; do
    if is_executable "$candidate"; then
      found="$candidate"
      break
    fi
    if (( SECONDS >= deadline )); then
      break
    fi
  done < <(
    timeout 4s find / \
      \( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /tmp -o -path /var/tmp -o -path /mnt -o -path /media \) -prune \
      -o -type f -name hermes -perm /111 -print 2>/dev/null || true
  )
  [[ -n "$found" ]] && printf '%s\n' "$found"
}

detect_hermes_bin() {
  local hermes_bin
  hermes_bin="$(find_hermes_in_path)"
  if [[ -n "$hermes_bin" ]]; then
    printf '%s\n' "$hermes_bin"
    return 0
  fi
  scan_filesystem_for_hermes || true
}

detect_hermes_home() {
  if [[ -n "${HERMES_HOME:-}" ]]; then
    printf '%s\n' "$HERMES_HOME"
    return 0
  fi

  local hermes_bin="${1:-}"
  if [[ -n "$hermes_bin" ]]; then
    local config_path
    config_path="$($hermes_bin config path 2>/dev/null | tail -n 1 || true)"
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

select_python_bin() {
  local hermes_home="${1:-}"
  local hermes_bin="${2:-}"

  if [[ -n "${HERMES_STACK_PYTHON:-}" ]]; then
    printf '%s\n' "$HERMES_STACK_PYTHON"
    return 0
  fi
  if [[ -n "$hermes_bin" ]]; then
    local inferred
    inferred="$(infer_python_from_hermes_bin "$hermes_bin" || true)"
    if [[ -n "$inferred" ]]; then
      printf '%s\n' "$inferred"
      return 0
    fi
  fi
  if is_executable "$hermes_home/hermes-agent/venv/bin/python"; then
    printf '%s\n' "$hermes_home/hermes-agent/venv/bin/python"
    return 0
  fi
  printf '%s\n' "python3"
}

tty_available() {
  [[ -e /dev/tty ]] || return 1
  { : < /dev/tty; } 2>/dev/null
}

run_bootstrap() {
  if [[ -t 0 ]]; then
    exec "$PYTHON_BIN" -m hermes_stack_bootstrap "$@"
  elif tty_available; then
    exec "$PYTHON_BIN" -m hermes_stack_bootstrap "$@" < /dev/tty
  else
    exec "$PYTHON_BIN" -m hermes_stack_bootstrap "$@"
  fi
}

DETECTED_HERMES_BIN="$(detect_hermes_bin)"
DETECTED_HERMES_HOME="$(detect_hermes_home "$DETECTED_HERMES_BIN")"
PYTHON_BIN="$(select_python_bin "$DETECTED_HERMES_HOME" "$DETECTED_HERMES_BIN")"

if [[ -n "$DETECTED_HERMES_BIN" && -z "${HERMES_BIN:-}" ]]; then
  export HERMES_BIN="$DETECTED_HERMES_BIN"
fi
if [[ -z "${HERMES_STACK_PYTHON:-}" && "$PYTHON_BIN" != "python3" ]]; then
  export HERMES_STACK_PYTHON="$PYTHON_BIN"
fi

if [[ -n "$SOURCE_DIR" ]]; then
  cd "$SOURCE_DIR"
  run_bootstrap "$@"
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
run_bootstrap "$@"
