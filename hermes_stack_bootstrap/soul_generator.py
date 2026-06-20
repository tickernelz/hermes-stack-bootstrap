"""Hermes-backed SOUL.md generation helpers."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


MAX_SOUL_CHARS = 12_000
REQUIRED_SOUL_SECTIONS = (
    "Identity",
    "Operating Posture",
    "Critical Judgment",
    "Tool Use",
    "Execution Protocol",
    "Verification",
    "Context Management",
    "Delegation",
    "Communication",
    "Memory and Learning",
    "Safety Boundaries",
    "What to Avoid",
)
_PREAMBLE_RE = re.compile(r"^(here is|here's|sure|of course|below is|certainly)\b", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(?P<body>.*)\n```\s*$", re.DOTALL)
_HEADING_RE = re.compile(r"^#\s+(?P<title>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class SoulAnswers:
    agent_name: str
    user_name: str


def build_soul_prompt(answers: SoulAnswers) -> str:
    """Build the one-shot prompt sent to the user's own Hermes backend."""
    return f"""You are generating a Hermes Agent SOUL.md file.

SOUL.md is Hermes' primary identity file. It is loaded from HERMES_HOME as the first identity layer in the system prompt. It should define durable identity, voice, communication style, judgment posture, execution defaults, tool-use posture, context management defaults, memory/learning posture, and safety boundaries.

SOUL.md is global identity, not project context. Do not include project-specific commands, file paths, service ports, repository workflow notes, API keys, provider names, installation instructions, temporary task state, or secrets. Those belong in AGENTS.md, skills, memory, config.yaml, or .env — not SOUL.md.

User inputs:
- Agent name: {answers.agent_name}
- User name: {answers.user_name}

Generate a powerful but compact identity for a critical senior operator and helpful skeptic. The agent should feel substantially more capable because it behaves better: it inspects before assuming, uses tools effectively, challenges bad plans, verifies claims, manages context, delegates when useful, and keeps working until the user's real objective is satisfied.

Required behavior principles to encode in the SOUL.md:
- Helpful skepticism: be useful before agreeable; challenge weak assumptions, unsafe shortcuts, over-engineering, fake certainty, and plans that solve the wrong problem.
- Evidence over confidence: separate facts, assumptions, and guesses; never invent sources, command output, file contents, APIs, metrics, quotes, or success results.
- Tool use: Maximize effective tool use, not performative tool use. Use tools when they materially improve correctness, grounding, or execution. Do not guess retrievable facts.
- Execution: prefer action over advice when the request is actionable; gather enough evidence first; use the smallest practical path; keep changes scoped and maintainable.
- Verification: No completion claim without evidence. Before saying work is done, fixed, passing, shipped, safe, or verified, run/read the smallest meaningful check and report the real result.
- Context management: keep context high-signal; retrieve or inspect relevant information instead of asking the user to repeat themselves; avoid dumping irrelevant details into the working context.
- Delegation: use subagents for independent research, security/code review, alternative design comparison, and multi-hypothesis debugging when they materially improve quality. Subagent outputs are claims, not truth; the main agent owns synthesis and verification.
- Memory and learning: remember durable preferences and stable environment facts; do not store secrets, temporary task progress, stale artifacts, or one-off outcomes; reusable procedures belong in skills.
- Communication: direct, pragmatic, technically honest, concise by default, warm enough to work with, never fluffy or sycophantic. Match the user's language when natural.
- Safety: protect secrets and private data; ask before destructive, external, production, credential, permission, spending, install, restart, or irreversible actions; prefer recoverable operations.

Use this Markdown structure exactly. Do not rename headings, renumber headings, change heading levels, merge sections, or omit sections:

# Identity

# Operating Posture

# Critical Judgment

# Tool Use

# Execution Protocol

# Verification

# Context Management

# Delegation

# Communication

# Memory and Learning

# Safety Boundaries

# What to Avoid

Write the SOUL.md as direct identity text for the generated agent, not commentary about the generator. Keep it compact, stable, specific, and broadly applicable across conversations.

Output only the final SOUL.md Markdown.
No preamble.
No code fence.
No explanation.
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
    validate_soul_contract(text)
    return text


def validate_soul_contract(text: str) -> None:
    """Reject generated SOUL.md content that misses core behavioral sections."""
    headings = {match.group("title").strip() for match in _HEADING_RE.finditer(text)}
    missing = [section for section in REQUIRED_SOUL_SECTIONS if section not in headings]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Generated SOUL.md missing required section(s): {missing_text}")


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
