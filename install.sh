#!/usr/bin/env bash
set -euo pipefail

REPO="${HERMES_STACK_REPO:-tickernelz/hermes-stack-bootstrap}"
REF="${HERMES_STACK_REF:-v0.1.15}"
SOURCE_DIR="${HERMES_STACK_SOURCE_DIR:-}"
BOOTSTRAP_DEPS=("PyYAML>=6" "rich>=13" "prompt_toolkit>=3")
TMP_DIR=""
BOOTSTRAP_VENV_DIR=""
BOOTSTRAP_PYTHON=""
BOOTSTRAP_CACHE_DIR="${HERMES_STACK_BOOTSTRAP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/hermes-stack-bootstrap}"

cleanup() {
  if [[ -n "${TMP_DIR:-}" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

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

looks_like_python_executable() {
  local path_or_name="${1:-}"
  local base_name
  base_name="$(basename "$path_or_name")"
  [[ "$base_name" == python* ]]
}

resolve_from_path() {
  local executable_name="${1:-}"
  [[ -n "$executable_name" ]] || return 1
  local old_ifs="$IFS"
  local path_dir
  IFS=':'
  for path_dir in $PATH; do
    [[ -n "$path_dir" ]] || continue
    if is_executable "$path_dir/$executable_name"; then
      IFS="$old_ifs"
      printf '%s\n' "$path_dir/$executable_name"
      return 0
    fi
  done
  IFS="$old_ifs"
  return 1
}

resolve_env_shebang_utility() {
  local target="${1:-}"
  read -r -a parts <<< "$target"
  [[ ${#parts[@]} -ge 2 ]] || return 1
  [[ "$(basename "${parts[0]}")" == "env" ]] || return 1

  local index=1
  while (( index < ${#parts[@]} )); do
    local token="${parts[$index]}"
    if [[ "$token" == "--" ]]; then
      ((index++))
      break
    fi
    if [[ "$token" == "-S" ]]; then
      ((index++))
      break
    fi
    if [[ "$token" == "-u" || "$token" == "-C" || "$token" == "-P" ]]; then
      ((index += 2))
      continue
    fi
    if [[ "$token" == -* ]]; then
      ((index++))
      continue
    fi
    if [[ "$token" == *=* && "$token" != /* ]]; then
      ((index++))
      continue
    fi
    break
  done

  (( index < ${#parts[@]} )) || return 1
  local executable_name="${parts[$index]}"
  looks_like_python_executable "$executable_name" || return 1
  if [[ "$executable_name" == /* && -x "$executable_name" && -f "$executable_name" ]]; then
    printf '%s\n' "$executable_name"
    return 0
  fi
  resolve_from_path "$executable_name"
}

infer_python_from_launcher_target() {
  local target="${1:-}"
  [[ -n "$target" ]] || return 1
  local real_target
  real_target="$(realpath "$target" 2>/dev/null || printf '%s\n' "$target")"
  local target_dir
  target_dir="$(dirname "$real_target")"
  if looks_like_python_executable "$real_target" && is_executable "$real_target"; then
    printf '%s\n' "$real_target"
    return 0
  fi
  if is_executable "$target_dir/python"; then
    printf '%s\n' "$target_dir/python"
    return 0
  fi
  if is_executable "$target_dir/python3"; then
    printf '%s\n' "$target_dir/python3"
    return 0
  fi
  return 1
}

infer_python_from_shell_launcher() {
  local real_bin="${1:-}"
  [[ -n "$real_bin" ]] || return 1
  local line
  while IFS= read -r line; do
    [[ "$line" == *exec* ]] || continue
    local after_exec="${line#*exec }"
    [[ "$after_exec" != "$line" ]] || continue
    local command_token="${after_exec%%[[:space:]]*}"
    command_token="${command_token%\"}"
    command_token="${command_token#\"}"
    command_token="${command_token%\'}"
    command_token="${command_token#\'}"
    [[ -n "$command_token" && "$command_token" != \$* ]] || continue
    if [[ "$command_token" != /* ]]; then
      command_token="$(resolve_from_path "$command_token" || true)"
    fi
    [[ -n "$command_token" ]] || continue
    local inferred
    inferred="$(infer_python_from_launcher_target "$command_token" || true)"
    if [[ -n "$inferred" ]]; then
      printf '%s\n' "$inferred"
      return 0
    fi
  done < "$real_bin"
  return 1
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
    local target="${shebang#\#!}"
    local interpreter="${target%% *}"
    if [[ "$(basename "$interpreter")" == "env" ]]; then
      local env_resolved
      env_resolved="$(resolve_env_shebang_utility "$target" || true)"
      if [[ -n "$env_resolved" ]]; then
        printf '%s\n' "$env_resolved"
        return 0
      fi
      local shell_inferred
      shell_inferred="$(infer_python_from_shell_launcher "$real_bin" || true)"
      if [[ -n "$shell_inferred" ]]; then
        printf '%s\n' "$shell_inferred"
        return 0
      fi
    elif looks_like_python_executable "$interpreter" && is_executable "$interpreter"; then
      printf '%s\n' "$interpreter"
      return 0
    elif [[ "$(basename "$interpreter")" == "sh" || "$(basename "$interpreter")" == "bash" || "$(basename "$interpreter")" == "dash" || "$(basename "$interpreter")" == "zsh" ]]; then
      local shell_inferred
      shell_inferred="$(infer_python_from_shell_launcher "$real_bin" || true)"
      if [[ -n "$shell_inferred" ]]; then
        printf '%s\n' "$shell_inferred"
        return 0
      fi
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

should_bootstrap_tui_deps() {
  if [[ "${HERMES_STACK_SKIP_BOOTSTRAP_DEPS:-}" == "1" ]]; then
    return 1
  fi
  local arg
  local has_yes=0
  local has_dry_run=0
  for arg in "$@"; do
    case "$arg" in
      --yes|-y)
        has_yes=1
        ;;
      --dry-run)
        has_dry_run=1
        ;;
    esac
  done
  # Keep noninteractive dry-run purely read-only; real noninteractive installs
  # still get bootstrap dependencies so PyYAML/config rendering cannot fail late.
  if (( has_yes == 1 && has_dry_run == 1 )); then
    return 1
  fi
  return 0
}

bootstrap_python_for_venv() {
  local venv_dir="$1"
  if is_executable "$venv_dir/bin/python"; then
    printf '%s\n' "$venv_dir/bin/python"
    return 0
  fi
  if is_executable "$venv_dir/Scripts/python.exe"; then
    printf '%s\n' "$venv_dir/Scripts/python.exe"
    return 0
  fi
  if is_executable "$venv_dir/Scripts/python"; then
    printf '%s\n' "$venv_dir/Scripts/python"
    return 0
  fi
  return 1
}

bootstrap_deps_fingerprint() {
  printf '%s\n' "${BOOTSTRAP_DEPS[@]}" | "$PYTHON_BIN" -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}

python_cache_tag() {
  local python_bin="$1"
  local version
  version="$($python_bin - <<'PY' 2>/dev/null || true
import sys
print(f"py{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  if [[ -z "$version" ]]; then
    version="py-unknown"
  fi
  printf '%s\n' "$version"
}

bootstrap_marker_path() {
  printf '%s\n' "$BOOTSTRAP_VENV_DIR/.hermes-stack-bootstrap-deps.sha256"
}

cached_bootstrap_venv_valid() {
  local expected="$1"
  [[ "${HERMES_STACK_RECREATE_BOOTSTRAP_VENV:-}" != "1" ]] || return 1
  local bootstrap_python
  bootstrap_python="$(bootstrap_python_for_venv "$BOOTSTRAP_VENV_DIR" || true)"
  [[ -n "$bootstrap_python" ]] || return 1
  [[ -f "$(bootstrap_marker_path)" ]] || return 1
  [[ "$(cat "$(bootstrap_marker_path)" 2>/dev/null || true)" == "$expected" ]]
}

create_bootstrap_venv() {
  local fingerprint
  fingerprint="$(bootstrap_deps_fingerprint)"
  local tag
  tag="$(python_cache_tag "$PYTHON_BIN")"
  BOOTSTRAP_VENV_DIR="$BOOTSTRAP_CACHE_DIR/bootstrap-venv-$tag"
  if cached_bootstrap_venv_valid "$fingerprint"; then
    BOOTSTRAP_PYTHON="$(bootstrap_python_for_venv "$BOOTSTRAP_VENV_DIR")"
    return 0
  fi
  rm -rf "$BOOTSTRAP_VENV_DIR"
  mkdir -p "$BOOTSTRAP_CACHE_DIR"
  echo "Creating isolated installer venv with ${PYTHON_BIN}" >&2
  if ! "$PYTHON_BIN" -m venv "$BOOTSTRAP_VENV_DIR"; then
    {
      echo "Error: Failed to create isolated installer venv."
      echo "Python: ${PYTHON_BIN}"
      echo "Manual fallback: ${PYTHON_BIN} -m venv ${BOOTSTRAP_VENV_DIR}"
      echo "Then install TUI deps in that venv and run this installer module from the source checkout."
    } >&2
    return 1
  fi
  BOOTSTRAP_PYTHON="$(bootstrap_python_for_venv "$BOOTSTRAP_VENV_DIR")" || {
    echo "Error: Isolated installer venv did not contain a Python executable: ${BOOTSTRAP_VENV_DIR}" >&2
    return 1
  }
}

install_bootstrap_deps() {
  local bootstrap_python="$1"
  local fingerprint
  fingerprint="$(bootstrap_deps_fingerprint)"
  if [[ -f "$(bootstrap_marker_path)" && "$(cat "$(bootstrap_marker_path)" 2>/dev/null || true)" == "$fingerprint" ]]; then
    return 0
  fi
  echo "Installing TUI bootstrap dependencies in isolated venv with ${bootstrap_python}"
  if PYTHONPATH= PYTHONHOME= PIP_DISABLE_PIP_VERSION_CHECK=1 VIRTUAL_ENV="$BOOTSTRAP_VENV_DIR" "$bootstrap_python" -m pip install --upgrade --no-cache-dir "${BOOTSTRAP_DEPS[@]}"; then
    printf '%s\n' "$fingerprint" > "$(bootstrap_marker_path)"
    return 0
  fi
  local manual_deps="${BOOTSTRAP_DEPS[*]}"
  {
    echo "Error: Failed to install TUI bootstrap dependencies in isolated installer venv."
    echo "Hermes runtime Python (unchanged): ${PYTHON_BIN}"
    echo "Installer Python: ${bootstrap_python}"
    echo "Manual install: ${bootstrap_python} -m pip install ${manual_deps}"
    echo "Then rerun this installer. Noninteractive installs can still use --yes."
  } >&2
  return 1
}

run_bootstrap() {
  local run_python="$PYTHON_BIN"
  if should_bootstrap_tui_deps "$@"; then
    create_bootstrap_venv
    run_python="$BOOTSTRAP_PYTHON"
    install_bootstrap_deps "$run_python"
  fi
  if [[ -t 0 ]]; then
    "$run_python" -m hermes_stack_bootstrap "$@"
  elif tty_available; then
    "$run_python" -m hermes_stack_bootstrap "$@" < /dev/tty
  else
    "$run_python" -m hermes_stack_bootstrap "$@"
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
  exit $?
fi

TMP_DIR="$(mktemp -d)"

ARCHIVE_URL="https://github.com/${REPO}/archive/${REF}.tar.gz"
echo "Downloading hermes-stack-bootstrap from ${ARCHIVE_URL}"

curl -fsSL "$ARCHIVE_URL" -o "$TMP_DIR/bootstrap.tar.gz"
tar -xzf "$TMP_DIR/bootstrap.tar.gz" -C "$TMP_DIR"
EXTRACTED="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

cd "$EXTRACTED"
run_bootstrap "$@"
