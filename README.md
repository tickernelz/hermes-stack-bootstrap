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
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.8/install.sh | bash
```

Dry run first:

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.8/install.sh | bash -s -- --dry-run
```

Inspect before running:

```bash
curl -fsSLO https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.8/install.sh
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

Interactive mode is TUI-only (`Rich` + `prompt_toolkit`). `install.sh` bootstraps `PyYAML`, `Rich`, and `prompt_toolkit` into a temporary isolated installer venv, then launches the wizard with `HERMES_STACK_PYTHON` still pointing at the detected Hermes runtime Python. This keeps installer UI dependencies from upgrading or downgrading packages inside Hermes' own venv. `curl | bash` is supported; the installer reattaches prompts to `/dev/tty` when stdin is the curl pipe.

## What it changes

The installer makes a narrow, reviewable merge into the selected Hermes profile:

- enables `hermes-lcm` and `mnemosyne`
- sets `context.engine: lcm`
- sets Mnemosyne as the memory provider
- writes LCM/Mnemosyne defaults for the selected memory mode
- seeds Telegram toolsets from CLI/top-level toolsets, or from all known toolsets when no CLI toolset exists, then appends `memory`
- optionally installs selected skill packs
- optionally generates `SOUL.md` through your configured Hermes backend

It does **not** write tokens, provider keys, Telegram bot tokens, private keys, dashboard secrets, or embedding API credentials unless you explicitly provide them during the install run.

Existing `config.yaml`, `.env`, and `SOUL.md` are backed up before non-dry-run writes. Hermes is not restarted automatically.

## Components

| Component | How it installs | Notes |
|---|---|---|
| `hermes-lcm` | clones/updates plugin repo | upstream layout preserved |
| `mnemosyne-memory` | installs package set into Hermes runtime Python | default mode: `hybrid` |
| `hermes-progress-tail` | runs upstream release installer | pin with `--progress-tail-ref` |
| `SOUL.md` | optional `hermes chat -q` generation | asks agent name, user name, communication style, and language; defaults keep lazy users moving |
| `superpowers` | stages upstream `skills/*` as `superpowers-*` Hermes skills | prompted in TUI; flag: `--install-superpowers`; repo tooling is not copied into Hermes skills; older bad repo-root installs are moved aside under `backups/` |
| HMX knowledge | stages discovered Hermes skill dirs | prompted in TUI; private repo; user must already have access; flag: `--install-hmx-knowledge`; tokens are never stored; older bad repo-root installs are moved aside under `backups/` |
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
bash install.sh --install-impeccable
bash install.sh --install-ponytail

# pin progress-tail
bash install.sh --progress-tail-ref v0.1.81
```

LCM model overrides are optional. Empty values let Hermes resolve `auxiliary.compression`.

```bash
bash install.sh \
  --lcm-summary-model openrouter/google/gemini-2.5-flash \
  --lcm-expansion-model openrouter/anthropic/claude-sonnet-4
```

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
