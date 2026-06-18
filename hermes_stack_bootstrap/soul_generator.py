"""Hermes-backed SOUL.md generation helpers."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


MAX_SOUL_CHARS = 12_000
_PREAMBLE_RE = re.compile(r"^(here is|here's|sure|of course|below is|certainly)\b", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(?P<body>.*)\n```\s*$", re.DOTALL)


@dataclass(frozen=True)
class SoulAnswers:
    agent_name: str
    user_name: str
    role: str
    behavior: str
    communication: str
    focus: str
    avoid: str
    language: str


def build_soul_prompt(answers: SoulAnswers) -> str:
    """Build the one-shot prompt sent to the user's own Hermes backend."""
    return f"""You are generating a Hermes Agent SOUL.md file.

SOUL.md is Hermes' primary identity file. It is loaded from HERMES_HOME as the first identity layer in the system prompt. It should define durable identity, voice, communication style, judgment, and broad behavior defaults.

Do not include project-specific commands, file paths, service ports, repository workflow notes, API keys, provider names, installation instructions, temporary task state, or secrets. Those belong in AGENTS.md, skills, memory, config.yaml, or .env — not SOUL.md.

User inputs:
- Agent name: {answers.agent_name}
- User name: {answers.user_name}
- Agent role: {answers.role}
- Behavior / personality: {answers.behavior}
- Communication style: {answers.communication}
- Main focus: {answers.focus}
- Things to avoid: {answers.avoid}
- Default language: {answers.language}

Use this Markdown structure unless the content strongly suggests a smaller equivalent:

# Identity

# Personality

# Communication

# Judgment

# Execution

# Domain Focus

# Boundaries

# Operating Defaults

Output only the final SOUL.md Markdown.
No preamble.
No code fence.
No explanation.
Keep it concise, stable, specific, and broadly applicable across conversations.
""".strip()


def sanitize_soul_markdown(raw: str, *, max_chars: int = MAX_SOUL_CHARS) -> str:
    """Clean model output and reject unsafe/invalid SOUL content."""
    text = raw.strip()
    if not text:
        raise ValueError("Generated SOUL.md is empty")

    match = _CODE_FENCE_RE.match(text)
    if match:
        text = match.group("body").strip()

    if not text:
        raise ValueError("Generated SOUL.md is empty")
    if len(text) > max_chars:
        raise ValueError(f"Generated SOUL.md is too large ({len(text)} chars; max {max_chars})")
    if _PREAMBLE_RE.match(text):
        raise ValueError("Generated SOUL.md includes a preamble instead of raw Markdown")
    if text.startswith("```") or text.endswith("```"):
        raise ValueError("Generated SOUL.md still contains code fences")
    return text


def build_hermes_soul_command(
    *,
    profile: str,
    provider: str,
    model: str,
    prompt: str,
    hermes_bin: str = "hermes",
) -> list[str]:
    """Build the Hermes CLI command that calls the user's configured backend."""
    command = [hermes_bin or "hermes"]
    if profile != "default":
        command.extend(["-p", profile])
    command.extend(["chat", "--quiet"])
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    command.extend(["-q", prompt])
    return command


def generate_soul_with_hermes(
    *,
    base_home: Path,
    profile: str,
    provider: str,
    model: str,
    answers: SoulAnswers,
    hermes_bin: str = "hermes",
    timeout: int = 300,
) -> str:
    """Generate SOUL.md via the user's Hermes backend, or fail loudly."""
    prompt = build_soul_prompt(answers)
    command = build_hermes_soul_command(
        profile=profile,
        provider=provider,
        model=model,
        prompt=prompt,
        hermes_bin=hermes_bin,
    )
    env = os.environ.copy()
    env["HERMES_HOME"] = str(base_home.expanduser())
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"SOUL.md generation failed via Hermes backend: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("SOUL.md generation failed via Hermes backend: hermes CLI not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SOUL.md generation failed via Hermes backend: timed out") from exc

    return sanitize_soul_markdown(completed.stdout)
