# Hermes Stack Bootstrap

Opinionated bootstrapper for a small local-first [Hermes Agent](https://hermes-agent.nousresearch.com/) stack:

- [`hermes-lcm`](https://github.com/stephenschoettler/hermes-lcm) for long-context conversation memory/compression
- [`mnemosyne-memory`](https://github.com/AxDSan/mnemosyne) as the Hermes memory provider, configured for local-first use
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
| `mnemosyne-memory` | installs `mnemosyne-memory[all]` and `sqlite-vec` into the Hermes runtime venv | local-first defaults; no remote API keys written |
| `hermes-progress-tail` | runs the upstream `install.sh` from the latest GitHub release | can be pinned with `--progress-tail-ref` |
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
- writes non-secret LCM and local Mnemosyne defaults

It does **not** write tokens, passwords, private keys, provider API keys, Telegram bot tokens, dashboard secrets, or private endpoint credentials.

Existing files are backed up before non-dry-run writes.

Hermes is **not restarted automatically**. Restart manually after reviewing the result.

## Hermes home and profile detection

The installer tries to find the Hermes base directory in this order:

1. `HERMES_HOME`
2. `hermes config path`
3. `~/.hermes`

Interactive mode lets you override the detected path manually.

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

Target a custom Hermes home:

```bash
bash install.sh --home /opt/hermes
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

Override the LCM summary/expansion model:

```bash
bash install.sh --summary-model openrouter/google/gemini-2.5-flash
```

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

## Environment defaults

The installer writes non-secret defaults to the selected profile's `.env`.

### LCM

```env
LCM_ENABLE_SLASH_COMMAND=1
LCM_CONTEXT_THRESHOLD=0.8
LCM_FRESH_TAIL_COUNT=72
LCM_LARGE_OUTPUT_EXTERNALIZATION_ENABLED=true
LCM_LARGE_OUTPUT_EXTERNALIZATION_THRESHOLD_CHARS=12000
LCM_LARGE_OUTPUT_TRANSCRIPT_GC_ENABLED=true
LCM_EXPANSION_CONTEXT_TOKENS=128000
LCM_SUMMARY_MODEL=lokal_sub2api/gpt-5.4-mini
LCM_EXPANSION_MODEL=lokal_sub2api/gpt-5.4-mini
LCM_SUMMARY_TIMEOUT_MS=180000
LCM_EXPANSION_TIMEOUT_MS=240000
```

If your Hermes provider alias is different, pass `--summary-model`.

### Mnemosyne

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

These defaults follow Mnemosyne's local-first docs: local fastembed (`BAAI/bge-small-en-v1.5`), local MiniCPM5-1B GGUF consolidation, `MNEMOSYNE_FORCE_LOCAL=1`, and `int8` vectors for a practical storage/accuracy tradeoff.

Remote embedding/LLM URL and API-key settings are intentionally omitted. Configure those yourself after installation if you do not want the local-first setup.

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
