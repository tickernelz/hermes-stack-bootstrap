import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_stack_bootstrap.cli import (
    PROGRESS_TAIL_REF,
    InstallerOptions,
    TuiDependencyError,
    apply_soul_generation,
    base_home_from_config_path,
    build_plan,
    build_plans,
    install_mnemosyne,
    mnemosyne_packages_satisfied,
    mnemosyne_runtime_needs_sudo,
    parse_profiles,
    print_plan,
    main,
    validate_runtime_options,
    wizard,
)
from hermes_stack_bootstrap.hermes_discovery import HermesRuntime
from hermes_stack_bootstrap.hermes_models import ProviderChoice


class FakeTui:
    def __init__(self, answers):
        self.answers = list(answers)
        self.events = []

    def _pop(self):
        if not self.answers:
            raise AssertionError("FakeTui ran out of answers")
        return self.answers.pop(0)

    def banner(self, title: str, subtitle: str) -> None:
        self.events.append(("banner", title, subtitle))

    def text(self, prompt: str, default: str = "") -> str:
        self.events.append(("text", prompt, default))
        answer = self._pop()
        return default if answer is None else answer

    def confirm(self, prompt: str, default: bool = False) -> bool:
        self.events.append(("confirm", prompt, default))
        answer = self._pop()
        return default if answer is None else bool(answer)

    def select(self, prompt: str, choices, default: str = "") -> str:
        self.events.append(("select", prompt, tuple(choices), default))
        answer = self._pop()
        return default if answer is None else answer

    def password(self, prompt: str) -> str:
        self.events.append(("password", prompt))
        return self._pop()

    def runtime_summary(self, runtime) -> None:
        self.events.append(("runtime", runtime.hermes_bin, runtime.hermes_python))


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
        self.assertEqual(options.mnemosyne_mode, "hybrid")

    def test_wizard_allows_manual_base_home_override(self):
        tui = FakeTui(["/opt/hermes", "work", "full-local", "", "", False, False])
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], ui=tui)

        self.assertEqual(options.base_home, Path("/opt/hermes"))
        self.assertEqual(options.profile, "work")

    def test_interactive_wizard_requires_tui_dependencies_without_injected_ui(self):
        with patch(
            "hermes_stack_bootstrap.cli.create_tui",
            side_effect=TuiDependencyError(
                "TUI dependencies are required: install with `python -m pip install rich prompt_toolkit`"
            ),
        ):
            with self.assertRaisesRegex(TuiDependencyError, "prompt_toolkit"):
                wizard([])

    def test_progress_tail_ref_defaults_to_latest_release(self):
        self.assertEqual(PROGRESS_TAIL_REF, "latest")

    def test_main_reports_tui_dependency_errors_without_traceback(self):
        buffer = io.StringIO()
        with (
            patch(
                "hermes_stack_bootstrap.cli.wizard",
                side_effect=TuiDependencyError("Interactive install requires TUI dependencies: prompt_toolkit"),
            ),
            patch("sys.stderr", buffer),
        ):
            code = main([])

        self.assertEqual(code, 1)
        self.assertIn("Error: Interactive install requires TUI dependencies", buffer.getvalue())
        self.assertNotIn("Traceback", buffer.getvalue())

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
            "/tmp/hermes/hermes-agent/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[embeddings]' sqlite-vec",
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
            "/srv/shared/hermes/runtime/venv/bin/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[embeddings]' sqlite-vec",
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

    def test_build_plan_normalizes_windows_python_path_for_git_bash_commands(self):
        options = InstallerOptions(
            base_home=Path("C:/Users/Nix/AppData/Local/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            hermes_python=Path(r"C:\Users\Nix\AppData\Local\hermes\hermes-agent\venv\Scripts\python"),
            hermes_python_source="discovered",
            mnemosyne_mode="hybrid",
        )

        plan = build_plan(options)
        commands = [step.command for step in plan.steps if step.command]

        self.assertIn(
            "/c/Users/Nix/AppData/Local/hermes/hermes-agent/venv/Scripts/python -m pip install --upgrade --no-cache-dir 'mnemosyne-memory[embeddings]' sqlite-vec",
            commands,
        )
        self.assertIn(
            "HERMES_HOME=/c/Users/Nix/AppData/Local/hermes /c/Users/Nix/AppData/Local/hermes/hermes-agent/venv/Scripts/python -m mnemosyne.install",
            commands,
        )

    def test_install_mnemosyne_uses_argument_vector_for_windows_python_path(self):
        options = InstallerOptions(
            base_home=Path("C:/Users/Nix/AppData/Local/hermes"),
            profile="default",
            yes=True,
            dry_run=False,
            hermes_python=Path(r"C:\Users\Nix\AppData\Local\hermes\hermes-agent\venv\Scripts\python"),
            hermes_python_source="discovered",
            mnemosyne_mode="hybrid",
        )
        plan = build_plan(options)

        with (
            patch("hermes_stack_bootstrap.cli.mnemosyne_packages_satisfied", return_value=False),
            patch("hermes_stack_bootstrap.cli.mnemosyne_runtime_needs_sudo", return_value=False),
            patch("hermes_stack_bootstrap.cli.run_command") as run_command,
        ):
            install_mnemosyne(plan)

        pip_args = run_command.call_args_list[0].args[0]
        install_args = run_command.call_args_list[1].args[0]
        self.assertIsInstance(pip_args, list)
        self.assertEqual(
            pip_args,
            [
                r"C:\Users\Nix\AppData\Local\hermes\hermes-agent\venv\Scripts\python",
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--no-cache-dir",
                "mnemosyne-memory[embeddings]",
                "sqlite-vec",
            ],
        )
        self.assertEqual(install_args[:3], [r"C:\Users\Nix\AppData\Local\hermes\hermes-agent\venv\Scripts\python", "-m", "mnemosyne.install"])
        self.assertEqual(run_command.call_args_list[1].kwargs["env"]["HERMES_HOME"], "C:/Users/Nix/AppData/Local/hermes")

    def test_install_mnemosyne_skips_pip_when_packages_are_already_satisfied(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=False,
            mnemosyne_mode="hybrid",
        )
        plan = build_plan(options)

        with (
            patch("hermes_stack_bootstrap.cli.mnemosyne_packages_satisfied", return_value=True),
            patch("hermes_stack_bootstrap.cli.run_command") as run_command,
        ):
            install_mnemosyne(plan)

        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(commands, [[str(plan.options.hermes_python or Path("/tmp/hermes/hermes-agent/venv/bin/python")), "-m", "mnemosyne.install"]])
        self.assertEqual(run_command.call_args_list[0].kwargs["env"]["HERMES_HOME"], "/tmp/hermes")

    def test_install_mnemosyne_uses_sudo_when_shared_runtime_is_not_writable(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=False,
            dry_run=False,
            hermes_python=Path("/opt/hermes/venv/bin/python"),
            mnemosyne_mode="hybrid",
        )
        plan = build_plan(options)

        with (
            patch("hermes_stack_bootstrap.cli.mnemosyne_packages_satisfied", return_value=False),
            patch("hermes_stack_bootstrap.cli.mnemosyne_runtime_needs_sudo", return_value=True),
            patch("hermes_stack_bootstrap.cli.run_command") as run_command,
        ):
            install_mnemosyne(plan)

        self.assertEqual(run_command.call_args_list[0].args[0], ["sudo", "-v"])
        self.assertEqual(
            run_command.call_args_list[1].args[0],
            ["sudo", "/opt/hermes/venv/bin/python", "-m", "pip", "install", "--upgrade", "--no-cache-dir", "mnemosyne-memory[embeddings]", "sqlite-vec"],
        )

    def test_install_mnemosyne_fails_actionably_when_sudo_needed_noninteractive(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=False,
            hermes_python=Path("/opt/hermes/venv/bin/python"),
            mnemosyne_mode="hybrid",
        )
        plan = build_plan(options)

        with (
            patch("hermes_stack_bootstrap.cli.mnemosyne_packages_satisfied", return_value=False),
            patch("hermes_stack_bootstrap.cli.mnemosyne_runtime_needs_sudo", return_value=True),
        ):
            with self.assertRaisesRegex(PermissionError, "sudo /opt/hermes/venv/bin/python -m pip install"):
                install_mnemosyne(plan)

    def test_mnemosyne_packages_satisfied_parses_pip_dry_run_report(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch("subprocess.run", return_value=completed),
            patch("tempfile.NamedTemporaryFile") as named_tmp,
            patch("pathlib.Path.read_text", return_value='{\"install\": []}'),
        ):
            named_tmp.return_value.__enter__.return_value.name = "/tmp/report.json"
            self.assertTrue(mnemosyne_packages_satisfied(Path("/venv/bin/python"), ["mnemosyne-memory[embeddings]", "sqlite-vec"]))

    def test_mnemosyne_runtime_needs_sudo_detects_non_writable_runtime_paths(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='["/opt/hermes/venv/lib/python/site-packages", "/opt/hermes/venv/bin"]',
            stderr="",
        )
        with (
            patch("subprocess.run", return_value=completed),
            patch("os.access", return_value=False),
        ):
            self.assertTrue(mnemosyne_runtime_needs_sudo(Path("/opt/hermes/venv/bin/python")))

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
        tui = FakeTui([None, "Skip Mnemosyne", None, "", "", False, False])
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/home/lutfi22/.hermes")),
            patch("hermes_stack_bootstrap.cli.discover_hermes_runtime", return_value=missing_runtime),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], ui=tui)

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
            tui = FakeTui([None, "Paste runtime Python path", str(runtime_python), None, "hybrid", "", "", False, False])
            with (
                patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/home/lutfi22/.hermes")),
                patch("hermes_stack_bootstrap.cli.discover_hermes_runtime", return_value=missing_runtime),
                patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
            ):
                options = wizard([], ui=tui)

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

    def test_wizard_picks_mnemosyne_and_lcm_models_from_detected_hermes_providers(self):
        providers = [
            ProviderChoice("openrouter", "OpenRouter — 2 models", ("anthropic/claude-sonnet-4", "google/gemini-3-flash")),
            ProviderChoice("custom:lokal", "Lokal — 1 model", ("gpt-5.4-mini",)),
        ]
        tui = FakeTui([
            None,  # base home
            None,  # profiles
            "hybrid",
            "OpenRouter — 2 models",
            "anthropic/claude-sonnet-4",
            "google/gemini-3-flash",
            None,  # expansion same as summary
            False,
            False,
        ])
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=providers),
        ):
            options = wizard([], ui=tui)

        self.assertEqual(options.mnemosyne_host_llm_provider, "openrouter")
        self.assertEqual(options.mnemosyne_host_llm_model, "anthropic/claude-sonnet-4")
        self.assertEqual(options.lcm_summary_model, "google/gemini-3-flash")
        self.assertEqual(options.lcm_expansion_model, "google/gemini-3-flash")
        select_prompts = [event[1] for event in tui.events if event[0] == "select"]
        self.assertIn("Mnemosyne host LLM provider", select_prompts)
        self.assertIn("Mnemosyne host LLM model", select_prompts)
        self.assertIn("LCM summary model", select_prompts)

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
        tui = FakeTui([
            None,
            None,
            "full-online",
            "https://embeddings.example/v1",
            "secret-from-prompt",
            "text-embedding-3-small",
            "1536",
            "",
            "",
            False,
            False,
        ])
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], env={}, ui=tui)

        self.assertIn(("password", "Mnemosyne embedding API key (hidden; empty if endpoint needs no key)"), tui.events)
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
            install_ponytail=True,
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
        self.assertIn(
            "git clone --depth=1 https://github.com/DietrichGebert/ponytail /tmp/hermes/skills/vendor/ponytail",
            commands,
        )

    def test_interactive_wizard_recommends_ponytail_by_default(self):
        tui = FakeTui([
            None,
            None,
            "hybrid",
            None,  # no lcm summary override
            None,  # no lcm expansion override
            None,  # recommended Ponytail default accepted
            False,  # no SOUL
        ])
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], ui=tui)

        self.assertTrue(options.install_ponytail)
        self.assertIn(("confirm", "Install strongly recommended Ponytail skill pack?", True), tui.events)

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
        tui = FakeTui([
            None,
            None,
            "hybrid",
            None,
            None,
            None,
            True,
            "Gatot",
            "Zhafron",
        ])
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], ui=tui)

        self.assertTrue(options.generate_soul)
        self.assertEqual(options.soul_agent_name, "Gatot")
        self.assertEqual(options.soul_user_name, "Zhafron")
        text_prompts = [event[1] for event in tui.events if event[0] == "text"]
        self.assertIn("Agent name", text_prompts)
        self.assertIn("User name", text_prompts)
        self.assertNotIn("Agent role", text_prompts)
        self.assertNotIn("Behavior / personality", text_prompts)

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
