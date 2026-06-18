import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap.cli import (
    PROGRESS_TAIL_REF,
    InstallerOptions,
    apply_soul_generation,
    base_home_from_config_path,
    build_plan,
    build_plans,
    parse_profiles,
    print_plan,
    validate_runtime_options,
    wizard,
)
from hermes_stack_bootstrap.hermes_discovery import HermesRuntime


class CliPlanTests(unittest.TestCase):
    def test_base_home_from_config_path_supports_default_profile(self):
        self.assertEqual(
            base_home_from_config_path("/mnt/hermes-runtime/config.yaml"),
            Path("/mnt/hermes-runtime"),
        )

    def test_base_home_from_config_path_supports_named_profile(self):
        self.assertEqual(
            base_home_from_config_path("/srv/hermes/profiles/work/config.yaml"),
            Path("/srv/hermes"),
        )

    def test_wizard_uses_detected_base_home_noninteractive(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(["--yes"])

        self.assertEqual(options.base_home, Path("/srv/hermes"))
        self.assertEqual(options.profile, "default")

    def test_wizard_allows_manual_base_home_override(self):
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("builtins.input", side_effect=["/opt/hermes", "work", "", "", "", "n"]),
        ):
            options = wizard([])

        self.assertEqual(options.base_home, Path("/opt/hermes"))
        self.assertEqual(options.profile, "work")

    def test_progress_tail_ref_defaults_to_latest_release(self):
        self.assertEqual(PROGRESS_TAIL_REF, "latest")

    def test_parse_profiles_accepts_repeated_and_comma_separated_values(self):
        self.assertEqual(
            parse_profiles(["default,work", "client", "work"]),
            ("default", "work", "client"),
        )

    def test_build_plans_targets_multiple_profiles(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default,work",
            yes=True,
            dry_run=True,
            skip_lcm=True,
            skip_mnemosyne=True,
            skip_progress_tail=True,
            install_superpowers=True,
        )

        plans = build_plans(options)

        self.assertEqual([plan.options.profile for plan in plans], ["default", "work"])
        self.assertEqual(plans[0].target_home, Path("/tmp/hermes"))
        self.assertEqual(plans[1].target_home, Path("/tmp/hermes/profiles/work"))
        default_commands = [step.command for step in plans[0].steps if step.command]
        work_commands = [step.command for step in plans[1].steps if step.command]
        self.assertIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/skills/vendor/obra-superpowers",
            default_commands,
        )
        self.assertIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/profiles/work/skills/vendor/obra-superpowers",
            work_commands,
        )

    def test_build_plan_targets_default_home_and_uses_upstream_install_commands(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            lcm_summary_model="lokal_sub2api/gpt-5.4-mini",
            lcm_expansion_model="lokal_sub2api/gpt-5.4-mini",
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "git clone https://github.com/stephenschoettler/hermes-lcm /tmp/hermes/plugins/hermes-lcm",
            commands,
        )
        self.assertIn(
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[all]' sqlite-vec",
            commands,
        )
        self.assertIn(
            "HERMES_HOME=/tmp/hermes /tmp/hermes/hermes-agent/venv/bin/python -m mnemosyne.install",
            commands,
        )
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-progress-tail/${LATEST_HERMES_PROGRESS_TAIL_TAG}/install.sh | env HPT_INTERACTIVE=0 HERMES_HOME=/tmp/hermes bash",
            commands,
        )

    def test_build_plan_can_use_global_runtime_python_with_user_profile_home(self):
        options = InstallerOptions(
            base_home=Path("/home/lutfi22/.hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            hermes_bin="/usr/local/bin/hermes",
            hermes_bin_source="path",
            hermes_python=Path("/srv/shared/hermes/runtime/venv/bin/python"),
            hermes_python_source="discovered",
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "/srv/shared/hermes/runtime/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[all]' sqlite-vec",
            commands,
        )
        self.assertIn(
            "HERMES_HOME=/home/lutfi22/.hermes /srv/shared/hermes/runtime/venv/bin/python -m mnemosyne.install",
            commands,
        )
        self.assertIn(
            "/usr/local/bin/hermes memory status && /usr/local/bin/hermes mnemosyne stats && /usr/local/bin/hermes plugins list --plain --no-bundled",
            commands,
        )

    def test_build_plan_uses_mode_specific_mnemosyne_install_commands(self):
        hybrid = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            mnemosyne_mode="hybrid",
        )
        online = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            mnemosyne_mode="full-online",
        )

        hybrid_commands = [step.command for step in build_plan(hybrid).steps if step.command]
        online_commands = [step.command for step in build_plan(online).steps if step.command]

        self.assertIn(
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[embeddings]' sqlite-vec",
            hybrid_commands,
        )
        self.assertIn(
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir mnemosyne-memory sqlite-vec numpy",
            online_commands,
        )

    def test_wizard_accepts_global_runtime_overrides_from_environment(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/home/lutfi22/.hermes")):
            options = wizard(
                ["--yes", "--skip-mnemosyne"],
                env={
                    "HERMES_BIN": "/usr/local/bin/hermes",
                    "HERMES_STACK_PYTHON": "/srv/shared/hermes/venv/bin/python",
                },
            )

        self.assertEqual(options.base_home, Path("/home/lutfi22/.hermes"))
        self.assertEqual(options.hermes_bin, "/usr/local/bin/hermes")
        self.assertEqual(options.hermes_python, Path("/srv/shared/hermes/venv/bin/python"))
        self.assertEqual(options.hermes_bin_source, "explicit")
        self.assertEqual(options.hermes_python_source, "explicit")

    def test_validate_runtime_options_requires_python_when_mnemosyne_needed(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            hermes_python=None,
            skip_mnemosyne=False,
        )

        with self.assertRaisesRegex(ValueError, "Python environment that runs Hermes"):
            validate_runtime_options(options)

    def test_validate_runtime_options_allows_missing_python_when_mnemosyne_skipped(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            hermes_python=None,
            skip_mnemosyne=True,
        )

        validate_runtime_options(options)

    def test_wizard_prompts_to_skip_mnemosyne_when_runtime_python_missing(self):
        missing_runtime = HermesRuntime(
            hermes_bin="/usr/local/bin/hermes",
            hermes_bin_source="PATH",
            hermes_python=None,
            hermes_python_source="not found",
        )
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/home/lutfi22/.hermes")),
            patch("hermes_stack_bootstrap.cli.discover_hermes_runtime", return_value=missing_runtime),
            patch("builtins.input", side_effect=["", "s", "", "", "", "n"]),
        ):
            options = wizard([])

        self.assertTrue(options.skip_mnemosyne)
        self.assertIsNone(options.hermes_python)
        self.assertEqual(options.hermes_python_source, "not found")

    def test_wizard_accepts_manual_runtime_python_when_discovery_misses(self):
        missing_runtime = HermesRuntime(
            hermes_bin="/usr/local/bin/hermes",
            hermes_bin_source="PATH",
            hermes_python=None,
            hermes_python_source="not found",
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime_python = Path(tmp) / "venv" / "bin" / "python"
            runtime_python.parent.mkdir(parents=True)
            runtime_python.write_text("#!/bin/sh\n", encoding="utf-8")
            runtime_python.chmod(0o755)
            with (
                patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/home/lutfi22/.hermes")),
                patch("hermes_stack_bootstrap.cli.discover_hermes_runtime", return_value=missing_runtime),
                patch("builtins.input", side_effect=["", str(runtime_python), "", "hybrid", "", "", "", "", "n"]),
            ):
                options = wizard([])

        self.assertFalse(options.skip_mnemosyne)
        self.assertEqual(options.hermes_python, runtime_python)
        self.assertEqual(options.hermes_python_source, "manual prompt")

    def test_wizard_accepts_mnemosyne_and_lcm_model_options(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(
                [
                    "--yes",
                    "--mnemosyne-mode",
                    "hybrid",
                    "--mnemosyne-llm-provider",
                    "openrouter",
                    "--mnemosyne-llm-model",
                    "anthropic/claude-sonnet-4",
                    "--lcm-summary-model",
                    "openrouter/google/gemini-2.5-flash",
                    "--lcm-expansion-model",
                    "openrouter/anthropic/claude-sonnet-4",
                ]
            )

        self.assertEqual(options.mnemosyne_mode, "hybrid")
        self.assertEqual(options.mnemosyne_host_llm_provider, "openrouter")
        self.assertEqual(options.mnemosyne_host_llm_model, "anthropic/claude-sonnet-4")
        self.assertEqual(options.lcm_summary_model, "openrouter/google/gemini-2.5-flash")
        self.assertEqual(options.lcm_expansion_model, "openrouter/anthropic/claude-sonnet-4")

    def test_wizard_accepts_full_online_embedding_options_from_environment(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(
                [
                    "--yes",
                    "--mnemosyne-mode",
                    "full-online",
                ],
                env={
                    "MNEMOSYNE_EMBEDDING_API_URL": "https://embeddings.example/v1",
                    "MNEMOSYNE_EMBEDDING_API_KEY": "secret-from-env",
                    "MNEMOSYNE_EMBEDDING_MODEL": "text-embedding-3-small",
                    "MNEMOSYNE_EMBEDDING_DIM": "1536",
                },
            )

        self.assertEqual(options.mnemosyne_mode, "full-online")
        self.assertEqual(options.mnemosyne_embedding_api_url, "https://embeddings.example/v1")
        self.assertEqual(options.mnemosyne_embedding_api_key, "secret-from-env")
        self.assertEqual(options.mnemosyne_embedding_model, "text-embedding-3-small")
        self.assertEqual(options.mnemosyne_embedding_dim, "1536")

    def test_wizard_prompts_for_full_online_embedding_api_key_without_echo(self):
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch(
                "builtins.input",
                side_effect=[
                    "",
                    "",
                    "full-online",
                    "openrouter",
                    "gpt-5.1-mini",
                    "https://embeddings.example/v1",
                    "text-embedding-3-small",
                    "1536",
                    "",
                    "",
                    "n",
                ],
            ),
            patch("getpass.getpass", return_value="secret-from-prompt") as getpass_mock,
        ):
            options = wizard([], env={})

        getpass_mock.assert_called_once()
        self.assertEqual(options.mnemosyne_embedding_api_url, "https://embeddings.example/v1")
        self.assertEqual(options.mnemosyne_embedding_api_key, "secret-from-prompt")
        self.assertEqual(options.mnemosyne_embedding_model, "text-embedding-3-small")
        self.assertEqual(options.mnemosyne_embedding_dim, "1536")

    def test_wizard_rejects_partial_full_online_embedding_config(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            with self.assertRaisesRegex(ValueError, "requires --mnemosyne-embedding-api-url"):
                wizard(
                    [
                        "--yes",
                        "--mnemosyne-mode",
                        "full-online",
                    ],
                    env={"MNEMOSYNE_EMBEDDING_API_KEY": "secret-without-url"},
                )

    def test_print_plan_shows_runtime_discovery_paths(self):
        options = InstallerOptions(
            base_home=Path("/home/lutfi22/.hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            hermes_bin="/usr/local/bin/hermes",
            hermes_bin_source="path",
            hermes_python=Path("/srv/shared/hermes/venv/bin/python"),
            hermes_python_source="bounded filesystem scan",
            skip_lcm=True,
            skip_mnemosyne=True,
            skip_progress_tail=True,
        )
        plan = build_plan(options)
        buffer = io.StringIO()

        with patch("sys.stdout", buffer):
            print_plan(plan)

        output = buffer.getvalue()
        self.assertIn("Hermes profile base", output)
        self.assertIn("/home/lutfi22/.hermes", output)
        self.assertIn("Hermes CLI", output)
        self.assertIn("/usr/local/bin/hermes", output)
        self.assertIn("Hermes Python", output)
        self.assertIn("/srv/shared/hermes/venv/bin/python", output)
        self.assertIn("bounded filesystem scan", output)

    def test_plan_output_never_prints_embedding_api_key_value(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            mnemosyne_mode="full-online",
            mnemosyne_embedding_api_key="do-not-print-this-secret",
        )
        plan = build_plan(options)
        buffer = io.StringIO()

        with patch("sys.stdout", buffer):
            print_plan(plan)

        output = buffer.getvalue()
        self.assertNotIn("do-not-print-this-secret", output)

    def test_build_plan_targets_named_profile_for_progress_tail(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="work",
            yes=True,
            dry_run=True,
            summary_model="",
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "git clone https://github.com/stephenschoettler/hermes-lcm /tmp/hermes/profiles/work/plugins/hermes-lcm",
            commands,
        )
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/tickernelz/hermes-progress-tail/${LATEST_HERMES_PROGRESS_TAIL_TAG}/install.sh | env HPT_INTERACTIVE=0 HERMES_HOME=/tmp/hermes HPT_PROFILES=work bash",
            commands,
        )
        self.assertIn(
            "hermes -p work memory status && hermes -p work mnemosyne stats && hermes -p work plugins list --plain --no-bundled",
            commands,
        )

    def test_build_plan_can_include_optional_skill_repositories(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            install_superpowers=True,
            install_hmx_knowledge=True,
            install_impeccable=True,
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/skills/vendor/obra-superpowers",
            commands,
        )
        self.assertIn(
            "git clone --depth=1 git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git /tmp/hermes/skills/vendor/hmx-knowledge",
            commands,
        )
        self.assertIn(
            "git clone --depth=1 https://github.com/pbakaus/impeccable /tmp/hermes/skills/vendor/impeccable",
            commands,
        )

    def test_wizard_accepts_noninteractive_soul_generation_options(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(
                [
                    "--yes",
                    "--generate-soul",
                    "--soul-agent-name",
                    "Gatot",
                    "--soul-user-name",
                    "Zhafron",
                    "--soul-role",
                    "generalist senior operator",
                    "--soul-behavior",
                    "direct, skeptical, useful",
                    "--soul-communication",
                    "casual Indonesian, concise",
                    "--soul-focus",
                    "software engineering and operations",
                    "--soul-avoid",
                    "sycophancy and fake certainty",
                    "--soul-language",
                    "match user language",
                    "--soul-provider",
                    "openrouter",
                    "--soul-model",
                    "anthropic/claude-sonnet-4",
                    "--soul-overwrite",
                ]
            )

        self.assertTrue(options.generate_soul)
        self.assertEqual(options.soul_agent_name, "Gatot")
        self.assertEqual(options.soul_user_name, "Zhafron")
        self.assertEqual(options.soul_provider, "openrouter")
        self.assertEqual(options.soul_model, "anthropic/claude-sonnet-4")
        self.assertTrue(options.soul_overwrite)

    def test_wizard_prompts_for_interactive_soul_answers(self):
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch(
                "builtins.input",
                side_effect=[
                    "",
                    "",
                    "",
                    "",
                    "",
                    "y",
                    "Gatot",
                    "Zhafron",
                    "generalist senior operator",
                    "direct, skeptical, useful",
                    "casual Indonesian, concise",
                    "software engineering and operations",
                    "sycophancy and fake certainty",
                    "match user language",
                    "openrouter",
                    "anthropic/claude-sonnet-4",
                ],
            ),
        ):
            options = wizard([])

        self.assertTrue(options.generate_soul)
        self.assertEqual(options.soul_agent_name, "Gatot")
        self.assertEqual(options.soul_user_name, "Zhafron")
        self.assertEqual(options.soul_role, "generalist senior operator")
        self.assertEqual(options.soul_behavior, "direct, skeptical, useful")
        self.assertEqual(options.soul_communication, "casual Indonesian, concise")
        self.assertEqual(options.soul_focus, "software engineering and operations")
        self.assertEqual(options.soul_avoid, "sycophancy and fake certainty")
        self.assertEqual(options.soul_language, "match user language")
        self.assertEqual(options.soul_provider, "openrouter")
        self.assertEqual(options.soul_model, "anthropic/claude-sonnet-4")

    def test_wizard_rejects_noninteractive_generate_soul_when_required_answers_missing(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            with self.assertRaisesRegex(ValueError, "--soul-agent-name"):
                wizard(["--yes", "--generate-soul"])

    def test_build_plan_includes_soul_generation_step(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="work",
            yes=True,
            dry_run=True,
            generate_soul=True,
            soul_agent_name="Gatot",
            soul_user_name="Zhafron",
            soul_role="operator",
            soul_behavior="direct",
            soul_communication="concise",
            soul_focus="engineering",
            soul_avoid="sycophancy",
            soul_language="match user",
            soul_model="gpt-5.1-mini",
        )

        plan = build_plan(options)
        titles = [step.title for step in plan.steps]
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn("Generate SOUL.md with Hermes AI backend", titles)
        self.assertIn("HERMES_HOME=/tmp/hermes hermes -p work chat --quiet --model gpt-5.1-mini -q '<generated SOUL.md prompt>'", commands)

    def test_apply_soul_generation_writes_generated_soul_and_backs_up_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_home = Path(tmp) / "profiles" / "work"
            target_home.mkdir(parents=True)
            soul_path = target_home / "SOUL.md"
            soul_path.write_text("old soul", encoding="utf-8")
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="work",
                yes=True,
                dry_run=False,
                generate_soul=True,
                soul_agent_name="Gatot",
                soul_user_name="Zhafron",
                soul_role="operator",
                soul_behavior="direct",
                soul_communication="concise",
                soul_focus="engineering",
                soul_avoid="sycophancy",
                soul_language="match user",
                soul_overwrite=True,
            )
            plan = build_plan(options)

            with patch("hermes_stack_bootstrap.cli.generate_soul_with_hermes", return_value="# Identity\n\nGenerated") as gen_mock:
                apply_soul_generation(plan)

            self.assertEqual(soul_path.read_text(encoding="utf-8"), "# Identity\n\nGenerated\n")
            backups = list((target_home / "backups").glob("hermes-stack-bootstrap-*/SOUL.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "old soul")
            gen_mock.assert_called_once()

    def test_apply_soul_generation_failure_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_home = Path(tmp)
            soul_path = target_home / "SOUL.md"
            soul_path.write_text("old soul", encoding="utf-8")
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=True,
                dry_run=False,
                generate_soul=True,
                soul_agent_name="Gatot",
                soul_user_name="Zhafron",
                soul_role="operator",
                soul_behavior="direct",
                soul_communication="concise",
                soul_focus="engineering",
                soul_avoid="sycophancy",
                soul_language="match user",
                soul_overwrite=True,
            )
            plan = build_plan(options)

            with patch("hermes_stack_bootstrap.cli.generate_soul_with_hermes", side_effect=RuntimeError("backend failed")):
                with self.assertRaisesRegex(RuntimeError, "backend failed"):
                    apply_soul_generation(plan)

            self.assertEqual(soul_path.read_text(encoding="utf-8"), "old soul")


if __name__ == "__main__":
    unittest.main()
