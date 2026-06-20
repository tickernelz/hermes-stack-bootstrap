import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap.soul_generator import (
    SoulAnswers,
    build_hermes_soul_command,
    build_soul_prompt,
    generate_soul_with_hermes,
    sanitize_soul_markdown,
)


class SoulGeneratorTests(unittest.TestCase):
    def answers(self) -> SoulAnswers:
        return SoulAnswers(agent_name="Gatot", user_name="Zhafron")

    def valid_soul(self) -> str:
        return "\n\n".join(
            [
                "# Identity\n\nGatot is direct.",
                "# Operating Posture\n\nActs as a senior operator.",
                "# Critical Judgment\n\nSeparates facts from assumptions.",
                "# Tool Use\n\nUses tools when they improve correctness.",
                "# Execution Protocol\n\nKeeps work scoped and practical.",
                "# Verification\n\nNo completion claim without evidence.",
                "# Context Management\n\nKeeps context high-signal.",
                "# Delegation\n\nTreats subagent output as claims.",
                "# Communication\n\nDirect and concise.",
                "# Memory and Learning\n\nStores only durable facts.",
                "# Safety Boundaries\n\nProtects secrets and asks before destructive actions.",
                "# What to Avoid\n\nAvoids sycophancy and fake certainty.",
            ]
        )

    def test_build_soul_prompt_includes_names_agentic_contract_and_hermes_boundaries(self):
        prompt = build_soul_prompt(self.answers())

        self.assertIn("Agent name: Gatot", prompt)
        self.assertIn("User name: Zhafron", prompt)
        self.assertIn("critical senior operator", prompt)
        self.assertIn("helpful skeptic", prompt)
        self.assertIn("Maximize effective tool use, not performative tool use", prompt)
        self.assertIn("No completion claim without evidence", prompt)
        self.assertIn("context management", prompt)
        self.assertIn("Subagent outputs are claims, not truth", prompt)
        self.assertIn("Do not include project-specific commands", prompt)
        self.assertIn("API keys", prompt)
        self.assertIn("SOUL.md is Hermes' primary identity file", prompt)
        self.assertNotIn("Agent role:", prompt)

    def test_build_soul_prompt_requests_powerful_but_compact_soul_sections(self):
        prompt = build_soul_prompt(self.answers())

        for heading in (
            "# Identity",
            "# Operating Posture",
            "# Critical Judgment",
            "# Tool Use",
            "# Execution Protocol",
            "# Verification",
            "# Context Management",
            "# Delegation",
            "# Communication",
            "# Memory and Learning",
            "# Safety Boundaries",
            "# What to Avoid",
        ):
            self.assertIn(heading, prompt)

        self.assertIn("Use this Markdown structure exactly", prompt)
        self.assertIn("Do not rename headings", prompt)
        self.assertIn("Output only the final SOUL.md Markdown", prompt)
        self.assertIn("No preamble", prompt)
        self.assertIn("No code fence", prompt)
        self.assertIn("Keep it compact", prompt)

    def test_sanitize_soul_markdown_strips_code_fences(self):
        raw = f"```md\n{self.valid_soul()}\n```\n"

        self.assertEqual(sanitize_soul_markdown(raw), self.valid_soul())

    def test_sanitize_soul_markdown_rejects_empty_preamble_and_oversized_output(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            sanitize_soul_markdown("   ")
        with self.assertRaisesRegex(ValueError, "preamble"):
            sanitize_soul_markdown(f"Here is the SOUL.md:\n{self.valid_soul()}")
        with self.assertRaisesRegex(ValueError, "too large"):
            sanitize_soul_markdown(self.valid_soul() + ("x" * 13000))

    def test_sanitize_soul_markdown_rejects_missing_required_behavior_sections(self):
        weak_soul = "# Identity\n\nGatot is helpful and direct."

        with self.assertRaisesRegex(ValueError, "required section"):
            sanitize_soul_markdown(weak_soul)

    def test_build_hermes_soul_command_uses_profile_provider_model_and_quiet_chat(self):
        command = build_hermes_soul_command(
            profile="work",
            provider="openrouter",
            model="anthropic/claude-sonnet-4",
            prompt="generate",
        )

        self.assertEqual(
            command,
            [
                "hermes",
                "-p",
                "work",
                "chat",
                "--quiet",
                "--provider",
                "openrouter",
                "--model",
                "anthropic/claude-sonnet-4",
                "-q",
                "generate",
            ],
        )

    def test_generate_soul_with_hermes_uses_hermes_home_and_sanitizes_stdout(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"```md\n{self.valid_soul()}\n```\n",
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as run_mock:
            soul = generate_soul_with_hermes(
                base_home=Path("/tmp/hermes"),
                profile="default",
                provider="",
                model="",
                answers=self.answers(),
            )

        self.assertEqual(soul, self.valid_soul())
        kwargs = run_mock.call_args.kwargs
        self.assertEqual(kwargs["env"]["HERMES_HOME"], "/tmp/hermes")
        self.assertEqual(run_mock.call_args.args[0][:3], ["hermes", "chat", "--quiet"])

    def test_generate_soul_with_hermes_failure_is_not_silent(self):
        failure = subprocess.CalledProcessError(
            returncode=2,
            cmd=["hermes", "chat"],
            stderr="provider missing",
        )
        with patch("subprocess.run", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "SOUL.md generation failed via Hermes backend"):
                generate_soul_with_hermes(
                    base_home=Path("/tmp/hermes"),
                    profile="default",
                    provider="",
                    model="",
                    answers=self.answers(),
                )


if __name__ == "__main__":
    unittest.main()
