# Hermes Stack Bootstrap

![Hermes Stack Bootstrap banner](assets/banner.png)

A small installer for a practical [Hermes Agent](https://hermes-agent.nousresearch.com/) stack:

- `hermes-lcm` for long-context compression.
- `mnemosyne-memory` for persistent memory.
- `hermes-progress-tail` for live progress bubbles.
- Optional skill packs: Superpowers, Impeccable, Ponytail, and private HMX knowledge skills.
- Optional `SOUL.md` generation through your configured Hermes backend.

It installs into your own Hermes profile. It does **not** ask you to copy someone else's `config.yaml` or `.env`.

## Quick start

Run the latest released installer:

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.14/install.sh | bash
```

Dry-run first if you want a safe preview:

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.14/install.sh | bash -s -- --dry-run
```

Inspect before running:

```bash
curl -fsSLO https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/v0.1.14/install.sh
less install.sh
bash install.sh --dry-run
bash install.sh
```

## Install modes

| Mode | Use when |
|---|---|
| `full` | You want the whole stack: plugins, Mnemosyne, config/env merge, optional skills, verification, and optional `SOUL.md`. |
| `plugin-skill-only` | You only want plugins and skill packs, without Mnemosyne package/config changes. |
| `soul-only` | You only want to generate or update `SOUL.md`. |

Examples:

```bash
bash install.sh --install-mode full
bash install.sh --install-mode plugin-skill-only
bash install.sh --install-mode soul-only --soul-agent-name Gatot --soul-user-name Zhafron
```

Interactive mode is a TUI wizard. It uses selectable choices where possible, including multi-profile selection and optional skill selection.

## What it changes

The installer makes a narrow merge into the selected Hermes profile:

- enables `hermes-lcm` and `mnemosyne`
- sets `context.engine: lcm`
- sets Mnemosyne as the memory provider
- writes LCM/Mnemosyne defaults for the selected memory mode
- optionally configures a named OpenAI-compatible HashMicro provider
- optionally stages selected skill packs
- optionally generates `SOUL.md`

Safety rules:

- Existing `config.yaml`, `.env`, and `SOUL.md` are backed up before non-dry-run writes.
- Dry-run does not write profile files.
- Hermes is not restarted automatically.
- Secrets stay in `.env`, not `config.yaml`.
- Dry-run output redacts obvious secret keys.
- Interactive choices are saved in `.hermes-stack-bootstrap.json` inside the target Hermes home, so reruns can reuse the last defaults without retyping everything.

## Common commands

```bash
# Wizard
bash install.sh

# Preview only
bash install.sh --dry-run

# Non-interactive defaults
bash install.sh --yes

# Named profile
bash install.sh --profile work

# Multiple profiles, processed sequentially
bash install.sh --profile default,work,client

# Skip components
bash install.sh --skip-lcm
bash install.sh --skip-mnemosyne
bash install.sh --skip-progress-tail

# Optional skill packs
bash install.sh --install-superpowers
bash install.sh --install-impeccable
bash install.sh --install-ponytail
GITLAB_TOKEN=glpat_xxx bash install.sh --install-hmx-knowledge
```

Optional skill-pack installs are isolated: if one pack fails, the installer warns, skips that pack, and continues with the rest. Existing active skills with the same `name:` manifest are backed up before the refreshed vendor copy is staged, so reruns do not leave duplicate HMX/Impeccable/Ponytail skills active.

```bash
# Pin progress-tail version/ref
bash install.sh --progress-tail-ref v0.1.81
```

## HashMicro provider setup

Interactive full installs offer to configure the recommended OpenAI-compatible HashMicro provider:

```text
https://xai.hashmicro.co/v1
```

The wizard can read `XAI_HASHMICRO_API_KEY`, fetch live model IDs from `/v1/models`, then ask for main, delegation, and auxiliary model routing.

Non-interactive example:

```bash
XAI_HASHMICRO_API_KEY=sk-xxx bash install.sh --yes \
  --setup-hashmicro-provider \
  --main-model gpt-5.5 \
  --main-context-length 400K \
  --delegation-model gpt-5.5-medium \
  --delegation-context-length 400K \
  --aux-all-model gpt-5.4-mini \
  --aux-all-context-length 409600
```

Important details:

- The key is saved as `XAI_HASHMICRO_API_KEY` in `.env`.
- `config.yaml` references `key_env`; it does not store the key.
- Context lengths are stored under `custom_providers[].models`, not in route blocks.
- GPT-5.5 context defaults to `272000`; explicit user-entered context values still win.
- Reasoning effort defaults to `xhigh`.

## Mnemosyne modes

| Mode | Embeddings | LLM consolidation | Good default? |
|---|---|---|---|
| `hybrid` | local `fastembed` | Hermes host LLM | Yes |
| `full-local` | local `fastembed` | local GGUF | Only if you want local LLM consolidation |
| `full-online` | remote embedding API | Hermes host LLM | Only if you already have an embedding API |

Default:

```bash
bash install.sh --mnemosyne-mode hybrid
```

Use env vars for embedding secrets, not CLI args:

```bash
MNEMOSYNE_EMBEDDING_API_URL=https://your-embedding-endpoint/v1 \
MNEMOSYNE_EMBEDDING_API_KEY=... \
MNEMOSYNE_EMBEDDING_MODEL=text-embedding-3-small \
MNEMOSYNE_EMBEDDING_DIM=1536 \
  bash install.sh --yes --mnemosyne-mode full-online
```

## SOUL.md generation

Generate `SOUL.md` through your configured Hermes backend:

```bash
bash install.sh --generate-soul
```

SOUL-only mode:

```bash
bash install.sh --install-mode soul-only
```

Non-interactive example:

```bash
bash install.sh --yes --install-mode soul-only \
  --soul-agent-name Gatot \
  --soul-user-name Zhafron \
  --soul-communication "Direct, concise, strict reviewer" \
  --soul-language "Bahasa Indonesia by default; English for code and APIs"
```

If `SOUL.md` exists, interactive mode asks before overwrite. Non-interactive overwrite requires `--soul-overwrite`. Failed generation does not write a partial file.

## Runtime detection

The installer keeps these separate:

| Path | Meaning |
|---|---|
| Hermes profile home | where `config.yaml`, `.env`, skills, and `SOUL.md` live |
| Hermes CLI | executable used for discovery, verification, and `SOUL.md` generation |
| Hermes runtime Python | Python env where Mnemosyne packages must be installed |

Override them when auto-detection is wrong:

```bash
bash install.sh \
  --home /home/user/.hermes \
  --hermes-bin /usr/local/bin/hermes \
  --hermes-python /srv/hermes/venv/bin/python
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

Inside a Hermes chat session:

```text
/lcm status
/progresstail doctor
/progresstail demo
```

## Local development

Use a repo-local venv. It is ignored by git.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pre-commit install
```

Run all checks before release:

```bash
FILES=$(git ls-files --cached --others --exclude-standard | grep -v '^\.venv/')
.venv/bin/pre-commit run --files $FILES
.venv/bin/python -m pytest -q -o 'addopts='
.venv/bin/python -m compileall -q hermes_stack_bootstrap tests scripts
.venv/bin/hermes-stack-bootstrap --help
```

Project rule: every checked text file must stay under 600 lines. Split files instead of adding exemptions.

For local installer testing:

```bash
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh --dry-run
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh
```

## Status

This is a focused bootstrapper for one practical Hermes stack. It is not a general Hermes distribution.
