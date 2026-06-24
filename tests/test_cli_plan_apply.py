import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from hermes_stack_bootstrap.cli import (
    PROGRESS_TAIL_REF,
    InstallerOptions,
    TuiDependencyError,
    apply_plan,
    apply_soul_generation,
    base_home_from_config_path,
    build_plan,
    build_plans,
    install_mnemosyne,
    install_skill_pack,
    SkillPackSpec,
    install_optional_skills,
    is_repo_root_skill_install,
    mnemosyne_packages_satisfied,
    mnemosyne_runtime_needs_sudo,
    parse_profiles,
    print_plan,
    main,
    stage_skill_pack,
    validate_runtime_options,
    wizard,
    merge_config_and_env,
)
from hermes_stack_bootstrap.hermes_discovery import HermesRuntime
from hermes_stack_bootstrap.hermes_models import ProviderChoice
from hermes_stack_bootstrap.provider_setup import AUXILIARY_TASKS
from hermes_stack_bootstrap.soul_generator import DEFAULT_SOUL_COMMUNICATION_STYLE, DEFAULT_SOUL_LANGUAGE


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

    def step(self, title: str) -> None:
        self.events.append(("step", title))

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

    def multi_select(self, prompt: str, choices, defaults=()):
        self.events.append(("multi_select", prompt, tuple(choices), tuple(defaults)))
        answer = self._pop()
        return tuple(defaults) if answer is None else tuple(answer)

    def password(self, prompt: str) -> str:
        self.events.append(("password", prompt))
        return self._pop()

    def status(self, message: str):
        events = self.events

        class StatusRecorder:
            def __enter__(self):
                events.append(("status_start", message))

            def __exit__(self, exc_type, exc, tb):
                events.append(("status_stop", message))
                return False

        return StatusRecorder()

    def runtime_summary(self, runtime) -> None:
        self.events.append(("runtime", runtime.hermes_bin, runtime.hermes_python))


class CliPlanTestsPart2(unittest.TestCase):
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
        self.assertEqual(
            install_args[:3],
            [r"C:\Users\Nix\AppData\Local\hermes\hermes-agent\venv\Scripts\python", "-m", "mnemosyne.install"],
        )
        self.assertEqual(
            run_command.call_args_list[1].kwargs["env"]["HERMES_HOME"], "C:/Users/Nix/AppData/Local/hermes"
        )

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
        self.assertEqual(
            commands,
            [
                [
                    str(plan.options.hermes_python or Path("/tmp/hermes/hermes-agent/venv/bin/python")),
                    "-m",
                    "mnemosyne.install",
                ]
            ],
        )
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
            [
                "sudo",
                "/opt/hermes/venv/bin/python",
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--no-cache-dir",
                "mnemosyne-memory[embeddings]",
                "sqlite-vec",
            ],
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
            patch("pathlib.Path.read_text", return_value='{"install": []}'),
        ):
            named_tmp.return_value.__enter__.return_value.name = "/tmp/report.json"
            self.assertTrue(
                mnemosyne_packages_satisfied(Path("/venv/bin/python"), ["mnemosyne-memory[embeddings]", "sqlite-vec"])
            )

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
        tui = FakeTui([None, None, "Skip Mnemosyne", None, False, "", "", False, False, False, False])
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
            tui = FakeTui(
                [
                    None,
                    None,
                    "Paste runtime Python path",
                    str(runtime_python),
                    None,
                    False,
                    "hybrid",
                    "",
                    "",
                    False,
                    False,
                    False,
                    False,
                ]
            )
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

    def test_wizard_accepts_noninteractive_hashmicro_provider_setup(self):
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch(
                "hermes_stack_bootstrap.cli.fetch_openai_compatible_model_metadata",
                return_value=(
                    ["gpt-5.5", "gpt-5.5-medium", "gpt-5.5-xhigh", "gpt-5.4-mini"],
                    {"gpt-5.5": 272000, "gpt-5.5-medium": 400000, "gpt-5.5-xhigh": 400000, "gpt-5.4-mini": 409600},
                ),
            ),
        ):
            options = wizard(
                [
                    "--yes",
                    "--setup-hashmicro-provider",
                    "--main-model",
                    "gpt-5.5",
                    "--main-context-length",
                    "400000",
                    "--delegation-model",
                    "gpt-5.5-medium",
                    "--delegation-context-length",
                    "400000",
                    "--aux-all-model",
                    "gpt-5.4-mini",
                    "--aux-all-context-length",
                    "409600",
                    "--aux-model",
                    "compression=gpt-5.5-medium",
                    "--aux-context-length",
                    "compression=400000",
                    "--skip-mnemosyne",
                ],
                env={"XAI_HASHMICRO_API_KEY": "secret-from-env"},
            )

        self.assertTrue(options.setup_hashmicro_provider)
        self.assertEqual(options.hashmicro_api_key, "secret-from-env")
        self.assertEqual(options.hashmicro_main_model, "gpt-5.5")
        self.assertEqual(options.hashmicro_main_context_length, 400000)
        self.assertEqual(options.hashmicro_delegation_model, "gpt-5.5-medium")
        self.assertEqual(options.hashmicro_delegation_context_length, 400000)
        self.assertEqual(options.hashmicro_auxiliary_models["vision"], "gpt-5.4-mini")
        self.assertEqual(options.hashmicro_auxiliary_context_lengths["vision"], 409600)
        self.assertEqual(options.hashmicro_auxiliary_models["compression"], "gpt-5.5-medium")
        self.assertEqual(options.hashmicro_auxiliary_context_lengths["compression"], 400000)
        self.assertEqual(options.hashmicro_reasoning_effort, "xhigh")

    def test_wizard_uses_272k_for_hashmicro_gpt55_codex_even_if_endpoint_reports_400k(self):
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch(
                "hermes_stack_bootstrap.cli.fetch_openai_compatible_model_metadata",
                return_value=(
                    ["codex/gpt-5.5", "codex/gpt-5.5-xhigh"],
                    {"codex/gpt-5.5": 400000, "codex/gpt-5.5-xhigh": 400000},
                ),
            ),
        ):
            options = wizard(
                [
                    "--yes",
                    "--setup-hashmicro-provider",
                    "--main-model",
                    "codex/gpt-5.5",
                    "--delegation-model",
                    "codex/gpt-5.5",
                    "--skip-mnemosyne",
                ],
                env={"XAI_HASHMICRO_API_KEY": "secret-from-env"},
            )

        self.assertEqual(options.hashmicro_main_context_length, 272000)
        self.assertEqual(options.hashmicro_delegation_context_length, 272000)

    def test_merge_config_and_env_applies_hashmicro_provider_without_leaking_secret_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=True,
                dry_run=False,
                setup_hashmicro_provider=True,
                hashmicro_api_key="super-secret",
                hashmicro_main_model="gpt-5.5",
                hashmicro_main_context_length=400000,
                hashmicro_delegation_model="gpt-5.5-medium",
                hashmicro_delegation_context_length=400000,
                hashmicro_auxiliary_models={"compression": "gpt-5.4-mini"},
                hashmicro_auxiliary_context_lengths={"compression": 409600},
                hashmicro_reasoning_effort="xhigh",
                hashmicro_available_models=("gpt-5.5", "gpt-5.5-medium", "gpt-5.5-xhigh", "gpt-5.4-mini"),
            )
            plan = build_plan(options)

            merge_config_and_env(plan)

            config_text = (Path(tmp) / "config.yaml").read_text(encoding="utf-8")
            config = yaml.safe_load(config_text)
            env_text = (Path(tmp) / ".env").read_text(encoding="utf-8")

        provider = next(item for item in config["custom_providers"] if item["name"] == "xai-hashmicro")
        self.assertEqual(provider["models"]["gpt-5.5-xhigh"]["context_length"], 400000)
        self.assertEqual(provider["models"]["gpt-5.4-mini"]["context_length"], 409600)
        self.assertEqual(config["model"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(config["model"]["default"], "gpt-5.5-xhigh")
        self.assertNotIn("context_length", config["model"])
        self.assertEqual(config["delegation"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(config["delegation"]["model"], "gpt-5.5-xhigh")
        self.assertEqual(config["delegation"]["reasoning_effort"], "xhigh")
        self.assertEqual(config["agent"]["reasoning_effort"], "xhigh")
        self.assertEqual(config["auxiliary"]["compression"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(config["auxiliary"]["compression"]["model"], "gpt-5.4-mini")
        self.assertNotIn("context_length", config["auxiliary"]["compression"])
        self.assertIn("XAI_HASHMICRO_API_KEY=super-secret", env_text)
        self.assertNotIn("super-secret", config_text)
