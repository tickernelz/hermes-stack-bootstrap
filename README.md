# Hermes Stack Bootstrap

![Hermes Stack Bootstrap banner](assets/banner.png)

Small, safe bootstrapper for a focused [Hermes Agent](https://hermes-agent.nousresearch.com/) stack:

- [`hermes-lcm`](https://github.com/stephenschoettler/hermes-lcm) for long-context compression.
- [`mnemosyne-memory`](https://github.com/AxDSan/mnemosyne) for persistent memory.
- [`hermes-progress-tail`](https://github.com/tickernelz/hermes-progress-tail) for live progress/status bubbles.
- Optional skill packs: [`obra/superpowers`](https://github.com/obra/superpowers), [`pbakaus/impeccable`](https://github.com/pbakaus/impeccable), [`DietrichGebert/ponytail`](https://github.com/DietrichGebert/ponytail), and a private HMX knowledge repo.

It installs the stack into your own Hermes profile. It does **not** ask you to copy someone else's `config.yaml` or `.env`.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.10/install.sh | bash
```

Dry run first:

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.10/install.sh | bash -s -- --dry-run
```

Inspect before running:

```bash
curl -fsSLO https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.10/install.sh
less install.sh
bash install.sh --dry-run
bash install.sh
```

Interactive mode starts with an install scope choice:

| Mode | What it does |
|---|---|
| `Full process` | Installs/updates plugins, Mnemosyne, optional skills, config/env merges, verification, then offers SOUL.md generation. |
| `Plugin & skill only` | Installs/updates plugin repos and selected skill packs, skips Mnemosyne package install and config/env merge, then offers SOUL.md generation. |
| `Generate SOUL.md only` | Skips install/config work and only generates `SOUL.md` after plan approval. |

Interactive mode is TUI-only (`Rich` + `prompt_toolkit`). The wizard uses selectable choices where possible, including a checkbox-style multi-select for target profiles so users do not need to type comma-separated profile names. `install.sh` bootstraps `PyYAML`, `Rich`, and `prompt_toolkit` into a cached isolated installer venv under `${HERMES_STACK_BOOTSTRAP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/hermes-stack-bootstrap}`, then launches the wizard with `HERMES_STACK_PYTHON` still pointing at the detected Hermes runtime Python. This keeps installer UI dependencies from upgrading or downgrading packages inside Hermes' own venv. `curl | bash` is supported; the installer reattaches prompts to `/dev/tty` when stdin is the curl pipe.

Cache controls:

| Env var | Behavior |
|---|---|
| `HERMES_STACK_BOOTSTRAP_CACHE_DIR` | Override the installer-venv cache directory. |
| `HERMES_STACK_RECREATE_BOOTSTRAP_VENV=1` | Delete/recreate the cached installer venv on this run. |
| `HERMES_STACK_SKIP_BOOTSTRAP_DEPS=1` | Skip installer dependency bootstrap and run with the selected Python. |

`--yes --dry-run` stays read-only and does not create the cached installer venv.

## What it changes

The installer makes a narrow, reviewable merge into the selected Hermes profile:

- enables `hermes-lcm` and `mnemosyne`
- sets `context.engine: lcm`
- sets Mnemosyne as the memory provider
- writes LCM/Mnemosyne defaults for the selected memory mode
- seeds Telegram toolsets from CLI/top-level toolsets, or from all known toolsets when no CLI toolset exists, then appends `memory`
- optionally configures a named `custom:xai-hashmicro` OpenAI-compatible provider and model routing
- optionally installs selected skill packs
- optionally generates `SOUL.md` through your configured Hermes backend

It does **not** write tokens, provider keys, Telegram bot tokens, private keys, dashboard secrets, HMX GitLab tokens, HashMicro API keys, or embedding API credentials unless you explicitly provide them during the install run.

Existing `config.yaml`, `.env`, and `SOUL.md` are backed up before non-dry-run writes. Hermes is not restarted automatically.

## Components

| Component | How it installs | Notes |
|---|---|---|
| `hermes-lcm` | clones/updates plugin repo | upstream layout preserved |
| `mnemosyne-memory` | installs package set into Hermes runtime Python | default mode: `hybrid` |
| `hermes-progress-tail` | runs upstream release installer | pin with `--progress-tail-ref` |
| HashMicro provider | merges named `custom:xai-hashmicro` provider config | prompted in full interactive mode; flag: `--setup-hashmicro-provider`; key is stored as `XAI_HASHMICRO_API_KEY` in `.env`, never in `config.yaml` |
| `SOUL.md` | optional `hermes chat -q` generation | asks agent name, user name, communication style, and language; shows a loading status while the Hermes backend generates content; defaults keep lazy users moving |
| `superpowers` | stages upstream `skills/*` as `superpowers-*` Hermes skills | prompted in TUI; flag: `--install-superpowers`; repo tooling is not copied into Hermes skills; older bad repo-root installs are moved aside under `backups/` |
| HMX knowledge | stages `skills/*` from the private repo | prompted in TUI; flag: `--install-hmx-knowledge`; retries GitLab HTTPS with temporary `GIT_ASKPASS` when `GITLAB_TOKEN` is provided; token is stored in `.env` only when provided; older bad repo-root installs are moved aside under `backups/` |
| `impeccable` | stages `plugin/skills/impeccable` only | prompted in TUI; flag: `--install-impeccable`; repo scaffolding/Claude config/package files are not copied into Hermes skills; older bad repo-root installs are moved aside under `backups/` |
| `ponytail` | stages upstream `skills/*` only | prompted in TUI; recommended default: yes; flag: `--install-ponytail`; repo tooling/hooks are not copied into Hermes skills; older bad repo-root installs are moved aside under `backups/` |

### Generated `SOUL.md` posture

The generator creates a compact global identity for a critical, tool-using senior operator. It prompts for agent name, user name, communication style, and language. If communication/language are left blank, it uses safe defaults:

- communication style: direct, pragmatic, concise, technically honest, warm enough, no fluff or sycophancy
- language: match the user's language; use English for code, APIs, commands, and technical identifiers

The generated persona emphasizes:

- helpful skepticism and pushback against weak assumptions
- effective tool use instead of guessing retrievable facts
- evidence-backed completion claims and real verification
- context management, delegation, memory discipline, and safety boundaries
- direct, pragmatic communication without sycophancy

It still respects Hermes' `SOUL.md` boundary: project-specific commands, repo workflows, paths, ports, provider names, API keys, secrets, and temporary task state belong in `AGENTS.md`, skills, memory, `config.yaml`, or `.env`, not in `SOUL.md`.

## Runtime and profile detection

The installer keeps three paths separate:

| Path | Meaning |
|---|---|
| Hermes profile base | user-owned profile tree: config, env, skills, SOUL |
| Hermes CLI | executable used for discovery, verification, and `SOUL.md` generation |
| Hermes runtime Python | Python env where Mnemosyne packages must be installed |

Detection order:

1. explicit flags/env: `--home`, `--hermes-bin`, `--hermes-python`, `HERMES_HOME`, `HERMES_BIN`, `HERMES_STACK_PYTHON`
2. `hermes config path`
3. every `hermes` executable in `$PATH`
4. Python inferred from launcher realpath, shebang, sibling venv, or shell wrapper `exec ".../venv/bin/hermes" "$@"`
5. profile-local `hermes-agent/venv/bin/python`
6. bounded filesystem scan for an executable named `hermes`

Shared runtime example:

```bash
bash install.sh \
  --home /home/lutfi22/.hermes \
  --hermes-bin /usr/local/bin/hermes \
  --hermes-python /srv/shared/hermes/venv/bin/python
```

Named profiles are supported. `--profile work` targets:

```text
<hermes-home>/profiles/work
```

Multiple profiles run sequentially:

```bash
bash install.sh --profile default,work,client
```

## Common commands

```bash
# wizard
bash install.sh

# no writes
bash install.sh --dry-run

# choose installer scope non-interactively
bash install.sh --install-mode full
bash install.sh --install-mode plugin-skill-only
bash install.sh --install-mode soul-only --soul-agent-name Gatot --soul-user-name Zhafron
bash install.sh --install-mode soul-only \
  --soul-agent-name Gatot \
  --soul-user-name Zhafron \
  --soul-communication "Direct, concise, strict reviewer" \
  --soul-language "Bahasa Indonesia by default; English for code and APIs"

# non-interactive defaults
bash install.sh --yes

# skip one component
bash install.sh --skip-lcm
bash install.sh --skip-mnemosyne
bash install.sh --skip-progress-tail

# optional skills
bash install.sh --install-superpowers
bash install.sh --install-hmx-knowledge
GITLAB_TOKEN=glpat_xxx bash install.sh --install-hmx-knowledge
bash install.sh --install-impeccable
bash install.sh --install-ponytail

# recommended HashMicro/xAI provider setup
XAI_HASHMICRO_API_KEY=sk-xxx bash install.sh --yes \
  --setup-hashmicro-provider \
  --main-model gpt-5.5 \
  --main-context-length 400K \
  --delegation-model gpt-5.5-medium \
  --delegation-context-length 400K \
  --aux-all-model gpt-5.4-mini \
  --aux-all-context-length 409600

# pin progress-tail
bash install.sh --progress-tail-ref v0.1.81
```

LCM model overrides are optional. Empty values let Hermes resolve `auxiliary.compression`.

```bash
bash install.sh \
  --lcm-summary-model openrouter/google/gemini-2.5-flash \
  --lcm-expansion-model openrouter/anthropic/claude-sonnet-4
```

## HashMicro provider setup

Interactive full installs ask whether to configure the recommended OpenAI-compatible xAI HashMicro provider. If accepted, the wizard reads `XAI_HASHMICRO_API_KEY` from the environment or prompts for it hidden, fetches live model IDs and exposed context metadata from `/v1/models` when possible, then asks for:

- main Hermes model
- reasoning effort (`xhigh` default; applied as the HashMicro model suffix such as `gpt-5.5-xhigh`)
- main model context length
- `delegate_task` model and context length
- default auxiliary model and context length
- optional per-auxiliary-task model/context overrides

If `/v1/models` does not expose context metadata, the wizard uses conservative fallbacks based on the live HashMicro model list: plain `gpt-5.5` defaults to `272_000`, `gpt-5.5-{medium,high,xhigh}` defaults to `400_000`, GPT-5.5 Codex variants default to the user-confirmed `272_000`, `gpt-5.4*` defaults to `200_000`, and `gpt-5.4-mini*` defaults to `409_600`. Manual context inputs also accept shorthand such as `272K` and `400K`.

The merge writes a named provider and routes through it:

```yaml
custom_providers:
  - name: xai-hashmicro
    base_url: https://xai.hashmicro.co/v1
    key_env: XAI_HASHMICRO_API_KEY
    api_mode: chat_completions
    discover_models: true
    models:
      gpt-5.5-xhigh:
        context_length: 400000
      gpt-5.4-mini:
        context_length: 409600

model:
  provider: custom:xai-hashmicro
  default: gpt-5.5-xhigh

agent:
  reasoning_effort: xhigh

delegation:
  provider: custom:xai-hashmicro
  model: gpt-5.5-xhigh
  reasoning_effort: xhigh
```

Context length is intentionally stored only under `custom_providers[].models`; main, delegation, and auxiliary routes only reference `provider` + `model`.

Auxiliary routes use the same named provider and clear stale direct `base_url` / `api_key` values so secrets stay centralized in `.env`.

Non-interactive example:

```bash
XAI_HASHMICRO_API_KEY=sk-xxx bash install.sh --yes \
  --setup-hashmicro-provider \
  --main-model gpt-5.5 \
  --main-context-length 400K \
  --delegation-model gpt-5.5-medium \
  --delegation-context-length 400K \
  --aux-all-model gpt-5.4-mini \
  --aux-all-context-length 409600 \
  --aux-model compression=gpt-5.5-medium \
  --aux-context-length compression=400K
```

Supported flags: `--hashmicro-base-url`, `--hashmicro-provider-name`, `--hashmicro-key-env`, `--main-model`, `--main-context-length`, `--delegation-model`, `--delegation-context-length`, `--aux-all-model`, `--aux-all-context-length`, repeated `--aux-model task=model`, repeated `--aux-context-length task=context_length`, and `--hashmicro-reasoning-effort`.

## Mnemosyne modes

| Mode | Embeddings | LLM consolidation | Packages |
|---|---|---|---|
| `hybrid` | local `fastembed` | Hermes host LLM | `mnemosyne-memory[embeddings] sqlite-vec` |
| `full-local` | local `fastembed` | local GGUF | `mnemosyne-memory[all] sqlite-vec` |
| `full-online` | remote embedding API | Hermes host LLM | `mnemosyne-memory sqlite-vec numpy` |

Default:

```bash
bash install.sh --mnemosyne-mode hybrid
```

Choose Hermes provider/model for Mnemosyne consolidation:

```bash
bash install.sh --mnemosyne-mode hybrid \
  --mnemosyne-llm-provider openrouter \
  --mnemosyne-llm-model anthropic/claude-sonnet-4
```

For `full-online`, pass embedding secrets through env, not CLI flags:

```bash
MNEMOSYNE_EMBEDDING_API_URL=https://your-embedding-endpoint/v1 \
MNEMOSYNE_EMBEDDING_API_KEY=... \
MNEMOSYNE_EMBEDDING_MODEL=text-embedding-3-small \
MNEMOSYNE_EMBEDDING_DIM=1536 \
  bash install.sh --yes --mnemosyne-mode full-online \
    --mnemosyne-llm-provider openrouter \
    --mnemosyne-llm-model anthropic/claude-sonnet-4
```

The dry-run preview redacts `MNEMOSYNE_EMBEDDING_API_KEY`. When switching modes, bootstrapper-managed stale keys are removed; unrelated user keys are preserved.

## HMX GitLab access and secret handling

HMX knowledge staging copies only real Hermes skill directories from the repo's `skills/` directory. Top-level repo files such as `README.md`, `tools/`, `.git`, package metadata, and CI files are not installed as Hermes skills. Per-skill support files under `references/`, `scripts/`, `templates/`, `assets/`, and known upstream sidecar folders are preserved.

For private GitLab access, the installer tries the configured repo URL first. If clone fails and `GITLAB_TOKEN` is available, it retries HTTPS with a temporary `GIT_ASKPASS` script. The token is **not** put into the clone URL or command arguments, and the temporary askpass file is deleted after the attempt.

Use env for non-interactive runs:

```bash
GITLAB_TOKEN=glpat_xxx bash install.sh --yes --install-hmx-knowledge
```

Interactive runs prompt for the token hidden when HMX is selected and no `GITLAB_TOKEN` exists in the environment. Provided tokens are written to the target profile `.env` so future reruns can reuse them. Dry-run output redacts `GITLAB_TOKEN`, `XAI_HASHMICRO_API_KEY`, `MNEMOSYNE_EMBEDDING_API_KEY`, and other obvious secret keys.

## SOUL.md generation

Generate once through your configured Hermes backend. In interactive runs, SOUL.md generation is offered **after** the selected install process finishes, so the main install prompts stay focused on scope, plugins, and skills.

```bash
bash install.sh --generate-soul
```

SOUL-only interactive mode skips install/config work and prompts for agent/user identity after plan approval:

```bash
bash install.sh --install-mode soul-only
```

Non-interactive:

```bash
bash install.sh --yes --install-mode soul-only \
  --soul-agent-name Gatot \
  --soul-user-name Zhafron
```

Optional provider/model override:

```bash
bash install.sh --generate-soul \
  --soul-provider openrouter \
  --soul-model anthropic/claude-sonnet-4
```

If `SOUL.md` exists, interactive mode asks before overwrite immediately before generation. Non-interactive mode requires `--soul-overwrite`. A failed model call does not write a partial file.

## Config shape

Simplified target config:

```yaml
plugins:
  enabled:
    - hermes-lcm
    - mnemosyne

context:
  engine: lcm

compression:
  enabled: true
  threshold: 0.8
  target_ratio: 0.6
  protect_last_n: 72

memory:
  provider: mnemosyne
  memory_enabled: false
  user_profile_enabled: false
  mnemosyne:
    auto_sleep: true
    profile_isolation: false
    vector_type: int8
    skip_contexts: cron,flush,subagent,background,skill_loop

platform_toolsets:
  telegram:
    - <existing CLI/top-level toolsets, or all known toolsets if none exist>
    - memory
```

Important `.env` defaults:

```env
LCM_ENABLE_SLASH_COMMAND=1
LCM_CONTEXT_THRESHOLD=0.8
LCM_FRESH_TAIL_COUNT=72
LCM_EXPANSION_CONTEXT_TOKENS=128000
LCM_SUMMARY_TIMEOUT_MS=180000
LCM_EXPANSION_TIMEOUT_MS=240000
LCM_LARGE_OUTPUT_EXTERNALIZATION_ENABLED=true
LCM_LARGE_OUTPUT_EXTERNALIZATION_THRESHOLD_CHARS=12000
LCM_LARGE_OUTPUT_TRANSCRIPT_GC_ENABLED=true

MNEMOSYNE_DATA_DIR=<hermes-profile>/mnemosyne/data
MNEMOSYNE_WM_MAX_ITEMS=10000
MNEMOSYNE_WM_TTL_HOURS=48
MNEMOSYNE_EP_LIMIT=50000
MNEMOSYNE_SLEEP_BATCH=3000
MNEMOSYNE_SP_MAX=1000
MNEMOSYNE_RECENCY_HALFLIFE=168
```

## After install

Restart Hermes manually, then check:

```bash
hermes memory status
hermes mnemosyne stats
hermes plugins list --plain --no-bundled
```

For a named profile:

```bash
hermes -p work memory status
hermes -p work mnemosyne stats
hermes -p work plugins list --plain --no-bundled
```

Session-level checks after a normal conversation starts:

```text
/lcm status
/progresstail doctor
/progresstail demo
```

## Local development

Use a local checkout:

```bash
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh --dry-run
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh
```

Run checks:

```bash
python -m unittest discover -s tests -v
python -m compileall -q hermes_stack_bootstrap
bash -n install.sh
git diff --check
```

## Status

This is a small bootstrapper for one practical Hermes stack. It is not a general Hermes distribution.
