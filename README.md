# hermes-stack-bootstrap

One-line installer/wizard for the small Hermes stack Zhafron wants to share:

1. [`hermes-lcm`](https://github.com/stephenschoettler/hermes-lcm) — installed exactly as a user plugin per its README.
2. [`mnemosyne-memory`](https://github.com/AxDSan/mnemosyne) — installed into Hermes' runtime Python with the full local profile.
3. [`hermes-progress-tail`](https://github.com/tickernelz/hermes-progress-tail) — installed through its upstream installer.

This repo is intentionally **not** a clone of Zhafron's full `~/.hermes/config.yaml` or `.env`.
It only applies the minimum config/env needed for those three components.

## One-line install

After this repo is published:

```bash
curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/main/install.sh | bash
```

Safer inspect-first flow:

```bash
curl -fsSLO https://raw.githubusercontent.com/tickernelz/hermes-stack-bootstrap/main/install.sh
less install.sh
bash install.sh
```

Local checkout:

```bash
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh --dry-run
HERMES_STACK_SOURCE_DIR="$PWD" bash install.sh
```

## What the wizard does

- Auto-detects the Hermes base path with `HERMES_HOME`, `hermes config path`, then `~/.hermes`, and lets the user override it manually.
- Lets the user choose `default` or a named Hermes profile.
- Installs/updates `hermes-lcm`:

  ```bash
  git clone https://github.com/stephenschoettler/hermes-lcm ~/.hermes/plugins/hermes-lcm
  ```

  For a named profile, it uses `~/.hermes/profiles/<profile>/plugins/hermes-lcm`.

- Installs Mnemosyne into Hermes' runtime venv:

  ```bash
  ~/.hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[all]' sqlite-vec
  HERMES_HOME=~/.hermes ~/.hermes/hermes-agent/venv/bin/python -m mnemosyne.install
  ```

- Installs progress-tail through its README one-liner. By default the bootstrapper resolves GitHub's latest release tag at install time, so updating progress-tail does not require editing this repo:

  ```bash
  curl -fsSL "https://raw.githubusercontent.com/tickernelz/hermes-progress-tail/${LATEST_HERMES_PROGRESS_TAIL_TAG}/install.sh" | bash
  ```

  Pin a specific progress-tail release only when needed:

  ```bash
  bash install.sh --progress-tail-ref v0.1.81
  ```

- Merges minimal `config.yaml` changes:

  ```yaml
  plugins:
    enabled:
      - hermes-lcm
      - mnemosyne
  context:
    engine: lcm
  memory:
    provider: mnemosyne
    memory_enabled: false
    user_profile_enabled: false
  platform_toolsets:
    telegram:
      - memory
  ```

  The `platform_toolsets.telegram: [memory]` addition is important; without it Telegram sessions may not expose the Mnemosyne tools.

- Merges non-secret `.env` defaults for LCM and local Mnemosyne.
- Backs up existing `config.yaml` and `.env` before writes.
- Does **not** restart Hermes automatically.

## Local Mnemosyne policy

Zhafron's private machine currently has some remote endpoint variables, but this shared installer does **not** copy them.
The public preset is local-first:

```env
MNEMOSYNE_LLM_ENABLED=true
MNEMOSYNE_FORCE_LOCAL=1
MNEMOSYNE_VEC_TYPE=float32
```

It avoids writing:

```env
MNEMOSYNE_EMBEDDING_API_KEY=
MNEMOSYNE_LLM_API_KEY=
MNEMOSYNE_LLM_BASE_URL=
```

Users who want remote embeddings/LLM should configure those explicitly after installation.

## LCM preset

The shared LCM values mirror Zhafron's non-secret tuning:

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

Override summary model if the user's Hermes provider alias differs:

```bash
bash install.sh --summary-model openrouter/google/gemini-2.5-flash
```

The default mirrors Zhafron's `.env`: `lokal_sub2api/gpt-5.4-mini`.

## Dry run

```bash
bash install.sh --dry-run
```

Dry-run prints the plan, install commands, config diff preview, and `.env` additions without writing files.

## Verification after install

Restart Hermes manually, then run:

```bash
hermes memory status
hermes mnemosyne stats
hermes plugins list --plain --no-bundled
```

For LCM, after one normal message initializes the session, use `lcm_status` or `/lcm status`.

For progress-tail in Telegram/gateway, use:

```text
/progresstail doctor
/progresstail demo
```

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q hermes_stack_bootstrap
bash -n install.sh
```
