# AGENTS.md

Instructions for AI agents working on this repository.

## Project purpose

`hermes-stack-bootstrap` is a small public installer for a practical Hermes Agent stack:

- `hermes-lcm`
- `mnemosyne-memory`
- `hermes-progress-tail`
- optional Hermes skill packs
- optional `SOUL.md` generation
- optional OpenAI-compatible HashMicro provider setup

Keep it focused. This repo is not a general Hermes distribution.

## Working style

- Be conservative. This installer edits user Hermes profiles, so safety matters.
- Prefer small, boring changes over clever abstractions.
- Preserve existing behavior unless the task explicitly asks to change it.
- Verify with real commands before claiming success.
- Do not store or print secrets.
- Do not release until pre-commit, tests, compileall, and a smoke command pass.

## Environment

Use a repo-local venv. Do **not** install dev tools into Conda `base_user`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

`.venv/` is ignored by git.

## Required checks

Before handing off code or preparing a release, run:

```bash
FILES=$(git ls-files --cached --others --exclude-standard | grep -v '^\.venv/')
.venv/bin/pre-commit run --files $FILES
.venv/bin/python -m pytest -q -o 'addopts='
.venv/bin/python -m compileall -q hermes_stack_bootstrap tests scripts
.venv/bin/hermes-stack-bootstrap --help
```

Also run `git diff --check` before commit/release.

The pre-commit hooks are intentionally light:

- `ruff format`
- `ruff check --fix`
- max 600 lines per checked text file

Do not make linting strict without explicit approval.

## File size rule

Every checked source/doc/config file must stay under 600 lines.

If a file grows too large, split by responsibility. Do not add exemptions unless the user explicitly approves it.

## Architecture notes

`hermes_stack_bootstrap/cli.py` is a thin compatibility entrypoint. Tests and external users may still patch/import symbols from it.

Core modules are split by responsibility:

- `bootstrap_data.py` — constants and dataclasses
- `bootstrap_tui.py` — Rich/prompt_toolkit TUI facade
- `bootstrap_shell.py` — shell quoting/rendering helpers
- `bootstrap_runtime.py` — profile/runtime path helpers
- `bootstrap_plan.py` — plan construction and display
- `bootstrap_apply.py` — side-effecting install/apply logic
- `bootstrap_skill_packs.py` — optional skill pack staging/install
- `bootstrap_option_flow.py` — CLI/env option normalization
- `bootstrap_prompts.py` — interactive prompt helpers
- `bootstrap_wizard.py` — parser and wizard orchestration
- `bootstrap_commands.py` — subprocess wrapper

When moving functions out of `cli.py`, keep old patch points working or update tests deliberately.

Common compatibility trap:

- Tests may patch `hermes_stack_bootstrap.cli.install_mnemosyne`.
- Implementation may live in `bootstrap_apply.install_mnemosyne`.
- The shim must sync patched names into implementation modules before delegating.

## Installer safety rules

- Dry-run must not write profile files.
- Existing `config.yaml`, `.env`, and `SOUL.md` need backups before non-dry-run writes.
- Never write provider/API tokens into `config.yaml`.
- Secrets belong in `.env` through env-var names like `XAI_HASHMICRO_API_KEY`, not inline config values.
- Dry-run output must redact obvious secrets.
- Non-dry-run confirmed installs save non-secret wizard defaults to `.hermes-stack-bootstrap.json` in the target Hermes home.
- Persisted defaults must never include API keys, GitLab tokens, passwords, or embedding secrets.
- Hermes is not restarted automatically.
- `curl | bash` must remain prompt-safe by reattaching interactive prompts to `/dev/tty`.

## HashMicro provider rules

Provider setup targets this OpenAI-compatible endpoint:

```text
https://xai.hashmicro.co/v1
```

Keep these rules unless the user changes direction:

- named provider default: `xai-hashmicro`
- provider reference in config: `custom:xai-hashmicro`
- key env default: `XAI_HASHMICRO_API_KEY`
- default reasoning effort: `xhigh`
- context lengths live under `custom_providers[].models`, not route blocks
- route blocks should normally contain `provider` and `model` only
- GPT-5.5 variants default to `272000` context length unless the user explicitly enters another value

## Skill pack staging rules

Stage only real Hermes skill directories.

Do copy per-skill support directories such as:

- `references/`
- `reference/`
- `scripts/`
- `templates/`
- `assets/`
- `examples/`

Do not install repo scaffolding as Hermes skills:

- `.git/`
- CI files
- package metadata
- root `README.md`
- repo-level tooling

Older bad repo-root skill installs should be moved aside under profile backups, not deleted blindly.

If an installed skill already has the same `name:` manifest as an incoming optional skill, move the installed copy aside under profile backups and install the refreshed bootstrap-managed copy. Avoid active duplicate skill names; Hermes recursive discovery can otherwise shadow or load the wrong skill.

If an optional skill pack fails to clone/install, warn and continue with the remaining optional packs. A GitLab token rate limit must not abort unrelated skill installs or the rest of the bootstrap.

## SOUL.md generation rules

SOUL generation should go through the user's configured Hermes backend.

- Ask for agent name, user name, communication style, and language.
- Provide useful defaults for lazy users.
- If `SOUL.md` exists, interactive mode asks before overwrite.
- Non-interactive overwrite requires `--soul-overwrite`.
- Failed generation must not write a partial file.

Keep `SOUL.md` generic. Project-specific commands, paths, provider names, issue state, and temporary task state do not belong there.

## Release checklist

Only release after:

1. Working tree reviewed.
2. README and help text match behavior.
3. Required checks pass from `.venv`.
4. `git diff --check` passes.
5. Version bump is intentional.
6. Tag/release target is confirmed.
7. Raw install smoke is run against the tag after publishing.

Do not create tags, push, publish releases, or restart services without explicit user approval.
