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
        return SoulAnswers(
            agent_name="Gatot",
            user_name="Zhafron",
            role="generalist senior operator",
            behavior="direct, skeptical, useful",
            communication="casual Indonesian, concise",
            focus="software engineering and operations",
            avoid="sycophancy, fake certainty, overengineering",
            language="match user language",
        )

    def test_build_soul_prompt_includes_answers_and_hermes_boundaries(self):
        prompt = build_soul_prompt(self.answers())

        self.assertIn("Agent name: Gatot", prompt)
        self.assertIn("User name: Zhafron", prompt)
        self.assertIn("software engineering and operations", prompt)
        self.assertIn("Output only the final SOUL.md Markdown", prompt)
        self.assertIn("Do not include project-specific commands", prompt)
        self.assertIn("API keys", prompt)
        self.assertIn("SOUL.md is Hermes' primary identity file", prompt)

    def test_sanitize_soul_markdown_strips_code_fences(self):
        raw = "```md\n# Identity\n\nGatot is direct.\n```\n"

        self.assertEqual(sanitize_soul_markdown(raw), "# Identity\n\nGatot is direct.")

    def test_sanitize_soul_markdown_rejects_empty_preamble_and_oversized_output(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            sanitize_soul_markdown("   ")
        with self.assertRaisesRegex(ValueError, "preamble"):
            sanitize_soul_markdown("Here is the SOUL.md:\n# Identity\n")
        with self.assertRaisesRegex(ValueError, "too large"):
            sanitize_soul_markdown("# Identity\n" + ("x" * 13000))

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
            stdout="```md\n# Identity\n\nGenerated soul.\n```\n",
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

        self.assertEqual(soul, "# Identity\n\nGenerated soul.")
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
