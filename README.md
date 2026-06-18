# Hermes Stack Bootstrap

Opinionated bootstrapper for a small [Hermes Agent](https://hermes-agent.nousresearch.com/) stack:

- [`hermes-lcm`](https://github.com/stephenschoettler/hermes-lcm) for long-context conversation memory/compression
- [`mnemosyne-memory`](https://github.com/AxDSan/mnemosyne) as the Hermes memory provider, selectable as full-local, hybrid, or full-online
- [`hermes-progress-tail`](https://github.com/tickernelz/hermes-progress-tail) for live progress/status bubbles

Optional skill packs can also be installed:

- [`obra/superpowers`](https://github.com/obra/superpowers)
- private HMX knowledge repo (`git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git` by default)
- [`pbakaus/impeccable`](https://github.com/pbakaus/impeccable)

The goal is a safe copy-paste installer that guides users through the same stack without asking them to copy someone else's private `config.yaml` or `.env`.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/main/install.sh | bash
```

Dry run first:

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/main/install.sh | bash -s -- --dry-run
```

`curl | bash` works in interactive mode: the shell wrapper reattaches Python prompts to `/dev/tty` when stdin is the curl pipe.

Inspect first:

```bash
curl -fsSLO https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/main/install.sh
less install.sh
bash install.sh --dry-run
bash install.sh
```

## What it installs

| Component | Install method | Notes |
|---|---|---|
| `hermes-lcm` | clones/updates `https://github.com/stephenschoettler/hermes-lcm` into the selected Hermes plugin directory | follows the upstream repo layout |
| `mnemosyne-memory` | installs mode-specific Mnemosyne package set into the Hermes runtime venv | default `full-local`; `hybrid` and `full-online` are available |
| `hermes-progress-tail` | runs the upstream `install.sh` from the latest GitHub release | can be pinned with `--progress-tail-ref` |
| `SOUL.md` generation | optional one-shot `hermes chat -q` call through the user's configured Hermes backend | enable with `--generate-soul`; no fallback mode |
| `obra/superpowers` | optional `git clone --depth=1` into `skills/vendor/obra-superpowers` | enable with `--install-superpowers` |
| HMX knowledge | optional clone into `skills/vendor/hmx-knowledge` | private repo; user must already have SSH/token access |
| `pbakaus/impeccable` | optional `git clone --depth=1` into `skills/vendor/impeccable` | enable with `--install-impeccable` |

## Safety model

This project intentionally does **not** publish or copy a full Hermes profile.

It only merges a small, reviewable set of config/env values:

- enables the required plugins
- switches context engine to LCM
- configures Mnemosyne as the memory provider
- exposes the `memory` toolset on Telegram so Mnemosyne tools are available there
- writes LCM/Mnemosyne defaults for the selected mode
- writes Mnemosyne embedding API credentials only when the user supplies them during the install run
- optionally writes `SOUL.md` only when `--generate-soul` is enabled or the interactive wizard asks and the user agrees

It does **not** write tokens, passwords, private keys, provider API keys, Telegram bot tokens, dashboard secrets, private endpoint credentials, or Mnemosyne embedding API credentials unless the user explicitly provides them to the installer.

Existing files are backed up before non-dry-run writes.

Hermes is **not restarted automatically**. Restart manually after reviewing the result.

## Hermes home, runtime, and profile detection

The installer keeps profile files separate from the Hermes runtime:

| Path | What it means | Typical examples |
|---|---|---|
| Hermes profile base | user-owned config/env/SOUL/profile tree | `~/.hermes`, `/home/lutfi22/.hermes` |
| Hermes CLI | executable used for config discovery, verification, and SOUL generation | `hermes`, `/usr/local/bin/hermes`, `/srv/hermes/venv/bin/hermes` |
| Hermes runtime Python | Python environment where Mnemosyne dependencies are installed | `~/.hermes/hermes-agent/venv/bin/python`, `/srv/shared/hermes/venv/bin/python` |

This supports shared servers where Hermes itself is installed globally while each user keeps a private profile under `~/.hermes`.

Profile base detection order:

1. `--home`
2. `HERMES_HOME`
3. `hermes config path` from the selected Hermes CLI
4. `~/.hermes`

Hermes CLI / runtime detection order:

1. `--hermes-bin` / `HERMES_BIN` and `--hermes-python` / `HERMES_STACK_PYTHON`
2. every executable named `hermes` in `$PATH`
3. Python inferred from the selected Hermes executable's realpath/sibling venv or shebang
4. profile-local `hermes-agent/venv/bin/python`
5. bounded filesystem scan for executable files named `hermes`

Runtime discovery also understands common Hermes shell wrappers such as:

```bash
#!/usr/bin/env bash
exec "/path/to/hermes-agent/venv/bin/hermes" "$@"
```

In that case it follows the `exec` target and uses the sibling `python` / `python3` from the same venv. If runtime Python still cannot be found in interactive mode, the wizard now stops early and lets the user either paste the Python path or skip Mnemosyne for that run instead of failing after all prompts.

The filesystem scan is deliberately bounded and prunes pseudo/noisy trees such as `/proc`, `/sys`, `/dev`, `/run`, `/tmp`, `/mnt`, and `/media`. It searches for an executable named `hermes`; it does **not** assume `/opt` or any other fixed install directory.

Interactive mode lets you override the detected profile base manually. For explicit shared-runtime installs:

```bash
HERMES_HOME=/home/lutfi22/.hermes \
HERMES_BIN=/usr/local/bin/hermes \
HERMES_STACK_PYTHON=/srv/shared/hermes/venv/bin/python \
  bash install.sh
```

or:

```bash
bash install.sh \
  --home /home/lutfi22/.hermes \
  --hermes-bin /usr/local/bin/hermes \
  --hermes-python /srv/shared/hermes/venv/bin/python
```

Named profiles are supported. For example, profile `work` maps to:

```text
<hermes-home>/profiles/work
```

Multiple profiles are supported in one invocation by repeating `--profile` or passing comma-separated names. They run sequentially, not in parallel, to keep backups and command output readable.

## Common commands

Run the wizard:

```bash
bash install.sh
```

Dry run without writing files:

```bash
bash install.sh --dry-run
```

Run non-interactively against the detected Hermes home:

```bash
bash install.sh --yes
```

Target a custom Hermes profile home:

```bash
bash install.sh --home /home/lutfi22/.hermes
```

Target a shared/global Hermes runtime explicitly:

```bash
bash install.sh \
  --home /home/lutfi22/.hermes \
  --hermes-bin /usr/local/bin/hermes \
  --hermes-python /srv/shared/hermes/venv/bin/python
```

Target one named profile:

```bash
bash install.sh --profile work
```

Target multiple profiles in one run. The installer applies them sequentially, one profile-scoped plan at a time:

```bash
bash install.sh --profile default,work,client
# equivalent:
bash install.sh --profile default --profile work --profile client
```

Set LCM summary and expansion models explicitly from Hermes' available providers/models:

```bash
bash install.sh \
  --lcm-summary-model openrouter/google/gemini-2.5-flash \
  --lcm-expansion-model openrouter/anthropic/claude-sonnet-4
```

Leave them empty to let Hermes resolve `auxiliary.compression`. The old `--summary-model` flag is still accepted as a backward-compatible alias that sets both LCM models.

Choose a Mnemosyne mode:

```bash
# Default: local embeddings + local GGUF LLM consolidation
bash install.sh --mnemosyne-mode full-local

# Hybrid: local embeddings + Hermes provider/model for Mnemosyne LLM consolidation
bash install.sh --mnemosyne-mode hybrid \
  --mnemosyne-llm-provider openrouter \
  --mnemosyne-llm-model anthropic/claude-sonnet-4

# Full online: Hermes provider/model for Mnemosyne LLM; installer also asks for embedding API URL/key/model/dim in interactive mode
bash install.sh --mnemosyne-mode full-online \
  --mnemosyne-llm-provider openrouter \
  --mnemosyne-llm-model anthropic/claude-sonnet-4
```

For non-interactive full-online installs, put the embedding API key in the environment rather than a CLI flag:

```bash
MNEMOSYNE_EMBEDDING_API_URL=https://your-embedding-endpoint/v1 \
MNEMOSYNE_EMBEDDING_API_KEY=... \
MNEMOSYNE_EMBEDDING_MODEL=text-embedding-3-small \
MNEMOSYNE_EMBEDDING_DIM=1536 \
  bash install.sh --yes --mnemosyne-mode full-online \
    --mnemosyne-llm-provider openrouter \
    --mnemosyne-llm-model anthropic/claude-sonnet-4
```

Generate `SOUL.md` once through the user's configured Hermes AI backend:

```bash
bash install.sh --generate-soul
```

Non-interactive example:

```bash
bash install.sh --yes --generate-soul \
  --soul-agent-name Gatot \
  --soul-user-name Zhafron \
  --soul-role "generalist senior operator" \
  --soul-behavior "direct, skeptical, useful" \
  --soul-communication "casual Indonesian, concise" \
  --soul-focus "software engineering and operations" \
  --soul-avoid "sycophancy, fake certainty, overengineering" \
  --soul-language "match user language"
```

Use the user's Hermes default provider/model by default. Optional override:

```bash
bash install.sh --generate-soul \
  --soul-provider openrouter \
  --soul-model anthropic/claude-sonnet-4
```

If `SOUL.md` already exists, interactive mode asks before overwrite; non-interactive mode requires `--soul-overwrite`. Existing `SOUL.md` is backed up before replacement. If the Hermes backend call fails, the installer fails and does not write `SOUL.md`.

Pin a specific progress-tail release instead of the latest release:

```bash
bash install.sh --progress-tail-ref v0.1.81
```

Skip one component:

```bash
bash install.sh --skip-lcm
bash install.sh --skip-mnemosyne
bash install.sh --skip-progress-tail
```

Install optional skill packs:

```bash
bash install.sh --install-superpowers
bash install.sh --install-impeccable
```

Install the private HMX knowledge repo:

```bash
# Recommended: SSH access via ssh-agent
bash install.sh --install-hmx-knowledge

# Or override the repo URL if your org uses a different clone URL.
# Prefer a git credential helper or GIT_ASKPASS for tokens; do not paste tokens into shell history.
HMX_KNOWLEDGE_GIT_URL=https://gitlab.com/hashmicro1/hmx/hmx-knowledge.git \
  bash install.sh --install-hmx-knowledge
```

## Config changes

The config merge is intentionally narrow. In simplified form, it ensures:

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
    - memory
```

Unrelated config keys are preserved.

`platform_toolsets.telegram: [memory]` is included because Telegram sessions otherwise may not expose Mnemosyne's tools.

If the discovered runtime Python is globally installed but not writable by the current user, ask the server admin to preinstall Mnemosyne into that runtime, run the installer with appropriate privileges, or use `--skip-mnemosyne` if Mnemosyne is already installed. The installer will not silently install Mnemosyne into an unrelated user Python because Hermes would not see it.

## SOUL.md generation

`SOUL.md` is Hermes' primary identity file. The installer can generate it once by calling the user's own Hermes backend with `hermes chat -q`; no bootstrapper API key or fallback generation mode is used.

Interactive mode asks for:

- agent name
- user name
- agent role
- behavior/personality
- communication style
- main focus
- things to avoid
- default language
- optional provider/model override for the generation call

The generated file targets:

```text
<hermes-profile>/SOUL.md
```

The prompt follows Hermes' documented boundary: `SOUL.md` should contain stable identity, tone, communication defaults, judgment posture, broad execution defaults, domain focus, and boundaries. It should not contain project-specific commands, paths, repo workflows, API keys, provider secrets, or temporary setup notes.

Dry runs show that generation would happen but do not call the model. Real runs fail hard if the Hermes backend call fails; they do not fall back to a template and do not write partial output.

## Environment defaults

It writes the selected profile's `.env` during the same install run. For secrets, prefer the interactive wizard: it prompts with hidden input so API keys do not land in shell history. In non-interactive mode, pass secrets through environment variables, not CLI flags.

### LCM

```env
LCM_ENABLE_SLASH_COMMAND=1
LCM_CONTEXT_THRESHOLD=0.8
LCM_FRESH_TAIL_COUNT=72
LCM_LARGE_OUTPUT_EXTERNALIZATION_ENABLED=true
LCM_LARGE_OUTPUT_EXTERNALIZATION_THRESHOLD_CHARS=12000
LCM_LARGE_OUTPUT_TRANSCRIPT_GC_ENABLED=true
LCM_EXPANSION_CONTEXT_TOKENS=128000
LCM_SUMMARY_TIMEOUT_MS=180000
LCM_EXPANSION_TIMEOUT_MS=240000
```

By default, the installer does **not** write `LCM_SUMMARY_MODEL` or `LCM_EXPANSION_MODEL`; LCM will use Hermes' `auxiliary.compression` resolution. Set them with `--lcm-summary-model` and `--lcm-expansion-model` if you want explicit provider/model names.

### Mnemosyne

The wizard exposes three modes:

| Mode | Embeddings | LLM consolidation | Package install |
|---|---|---|---|
| `full-local` | local fastembed | local MiniCPM5 GGUF | `mnemosyne-memory[all] sqlite-vec` |
| `hybrid` | local fastembed | Hermes host LLM provider/model | `mnemosyne-memory[embeddings] sqlite-vec` |
| `full-online` | embedding API/model captured during install or from env | Hermes host LLM provider/model | `mnemosyne-memory sqlite-vec numpy` |

#### `full-local` env

```env
MNEMOSYNE_DATA_DIR=<hermes-profile>/mnemosyne/data
MNEMOSYNE_FORCE_LOCAL=1
MNEMOSYNE_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
MNEMOSYNE_EMBEDDING_DIM=384
MNEMOSYNE_VEC_TYPE=int8
MNEMOSYNE_LLM_ENABLED=true
MNEMOSYNE_LLM_REPO=openbmb/MiniCPM5-1B-GGUF
MNEMOSYNE_LLM_FILE=MiniCPM5-1B-Q4_K_M.gguf
MNEMOSYNE_LLM_N_CTX=2048
MNEMOSYNE_LLM_MAX_TOKENS=2048
MNEMOSYNE_LLM_N_THREADS=4
MNEMOSYNE_WM_MAX_ITEMS=10000
MNEMOSYNE_WM_TTL_HOURS=48
MNEMOSYNE_EP_LIMIT=50000
MNEMOSYNE_SLEEP_BATCH=3000
MNEMOSYNE_SP_MAX=1000
MNEMOSYNE_RECENCY_HALFLIFE=168
```

#### `hybrid` env

```env
MNEMOSYNE_DATA_DIR=<hermes-profile>/mnemosyne/data
MNEMOSYNE_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
MNEMOSYNE_EMBEDDING_DIM=384
MNEMOSYNE_VEC_TYPE=int8
MNEMOSYNE_LLM_ENABLED=true
MNEMOSYNE_LLM_MAX_TOKENS=2048
MNEMOSYNE_HOST_LLM_ENABLED=true
MNEMOSYNE_HOST_LLM_N_CTX=32000
# Optional when supplied:
MNEMOSYNE_HOST_LLM_PROVIDER=<hermes-provider>
MNEMOSYNE_HOST_LLM_MODEL=<hermes-model>
```

#### `full-online` env

```env
MNEMOSYNE_DATA_DIR=<hermes-profile>/mnemosyne/data
MNEMOSYNE_LLM_ENABLED=true
MNEMOSYNE_LLM_MAX_TOKENS=2048
MNEMOSYNE_HOST_LLM_ENABLED=true
MNEMOSYNE_HOST_LLM_N_CTX=32000
# Optional when supplied:
MNEMOSYNE_HOST_LLM_PROVIDER=<hermes-provider>
MNEMOSYNE_HOST_LLM_MODEL=<hermes-model>
MNEMOSYNE_EMBEDDINGS_VIA_API=true
MNEMOSYNE_EMBEDDING_API_URL=https://your-embedding-endpoint/v1
MNEMOSYNE_EMBEDDING_API_KEY=...
MNEMOSYNE_EMBEDDING_MODEL=text-embedding-3-small
MNEMOSYNE_EMBEDDING_DIM=1536
```

For `full-online`, the interactive installer prompts for embedding API URL, hidden API key, model, and dimension in the same run. Non-interactive installs can set those via `MNEMOSYNE_EMBEDDING_API_URL`, `MNEMOSYNE_EMBEDDING_API_KEY`, `MNEMOSYNE_EMBEDDING_MODEL`, and `MNEMOSYNE_EMBEDDING_DIM` before calling `bash install.sh --yes --mnemosyne-mode full-online`.

The installer does not accept API keys as CLI flags because that leaks into shell history/process lists. Dry-run previews redact `MNEMOSYNE_EMBEDDING_API_KEY`. When switching modes, it removes stale bootstrapper-managed keys such as `MNEMOSYNE_FORCE_LOCAL`, `MNEMOSYNE_LLM_REPO`, or `MNEMOSYNE_HOST_LLM_ENABLED`; it preserves API keys/endpoints and non-default embedding model/dimension values you added yourself while staying in `full-online`.

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

LCM status is available after a normal conversation initializes the session:

```text
/lcm status
```

Progress-tail checks:

```text
/progresstail doctor
/progresstail demo
```

## Local development

Use a local checkout without downloading from GitHub:

```bash
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh --dry-run
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh
```

Run tests:

```bash
python -m unittest discover -s tests -v
python -m compileall -q hermes_stack_bootstrap
bash -n install.sh
```

## Project status

This is a small bootstrapper, not a general Hermes distribution. It is meant to make one specific stack easy to install and review.
