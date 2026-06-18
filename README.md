# Hermes Stack Bootstrap

Opinionated bootstrapper for a small local-first [Hermes Agent](https://hermes-agent.nousresearch.com/) stack:

- [`hermes-lcm`](https://github.com/stephenschoettler/hermes-lcm) for long-context conversation memory/compression
- [`mnemosyne-memory`](https://github.com/AxDSan/mnemosyne) as the Hermes memory provider, configured for local-first use
- [`hermes-progress-tail`](https://github.com/tickernelz/hermes-progress-tail) for live progress/status bubbles

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

Target a named profile:

```bash
bash install.sh --profile work
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
    vector_type: float32
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
MNEMOSYNE_LLM_ENABLED=true
MNEMOSYNE_LLM_N_CTX=2048
MNEMOSYNE_LLM_MAX_TOKENS=512
MNEMOSYNE_LLM_N_THREADS=4
MNEMOSYNE_VEC_TYPE=float32
```

Remote embedding/LLM settings are intentionally omitted. Configure those yourself after installation if you do not want the local-first setup.

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
