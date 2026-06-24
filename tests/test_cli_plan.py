import io
import subprocess
import tempfile
import unittest
import urllib.error
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
    resolve_progress_tail_ref,
    main,
    stage_skill_pack,
    validate_runtime_options,
    merge_config_and_env,
)
from hermes_stack_bootstrap.hermes_models import ProviderChoice
from hermes_stack_bootstrap.provider_setup import AUXILIARY_TASKS
from hermes_stack_bootstrap.soul_generator import DEFAULT_SOUL_COMMUNICATION_STYLE, DEFAULT_SOUL_LANGUAGE
from tests.helpers import FakeTui


class CliPlanTestsPart1(unittest.TestCase):
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

    def test_plugin_skill_only_plan_skips_config_env_and_mnemosyne_verify(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            install_mode="plugin-skill-only",
            skip_mnemosyne=True,
            skip_config_env=True,
            install_superpowers=True,
        )

        plan = build_plan(options)
        titles = [step.title for step in plan.steps]
        commands = [step.command for step in plan.steps if step.command]

        self.assertNotIn("Merge config.yaml safely", titles)
        self.assertNotIn("Merge .env values", titles)
        self.assertFalse(any("mnemosyne" in command.lower() for command in commands))
        self.assertIn("Verify", titles)
        self.assertIn("hermes plugins list --plain --no-bundled", commands)
        self.assertNotIn("hermes mnemosyne stats", "\n".join(commands))

    def test_apply_plan_prompts_for_soul_after_install_and_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=False,
                dry_run=False,
                install_mode="plugin-skill-only",
                skip_lcm=True,
                skip_mnemosyne=True,
                skip_progress_tail=True,
                skip_config_env=True,
            )
            plan = build_plan(options)
            tui = FakeTui(
                [
                    True,  # apply plan
                    True,  # generate SOUL after install
                    "Gatot",
                    "Zhafron",
                    None,  # communication style default
                    None,  # language default
                ]
            )
            calls = []

            def record(name):
                def inner(*_args, **_kwargs):
                    calls.append(name)

                return inner

            with (
                patch("hermes_stack_bootstrap.cli.install_lcm", side_effect=record("install_lcm")),
                patch("hermes_stack_bootstrap.cli.install_mnemosyne", side_effect=record("install_mnemosyne")),
                patch("hermes_stack_bootstrap.cli.install_progress_tail", side_effect=record("install_progress_tail")),
                patch(
                    "hermes_stack_bootstrap.cli.install_optional_skills", side_effect=record("install_optional_skills")
                ),
                patch("hermes_stack_bootstrap.cli.merge_config_and_env", side_effect=record("merge_config_and_env")),
                patch("hermes_stack_bootstrap.cli.run_verification", side_effect=record("verify")),
                patch("hermes_stack_bootstrap.cli.apply_soul_generation", side_effect=record("soul")) as soul_mock,
            ):
                apply_plan(plan, tui)

        self.assertEqual(calls[-2:], ["verify", "soul"])
        generated_plan = soul_mock.call_args.args[0]
        self.assertTrue(generated_plan.options.generate_soul)
        self.assertEqual(generated_plan.options.soul_agent_name, "Gatot")
        self.assertEqual(generated_plan.options.soul_user_name, "Zhafron")
        self.assertEqual(generated_plan.options.soul_communication, DEFAULT_SOUL_COMMUNICATION_STYLE)
        self.assertEqual(generated_plan.options.soul_language, DEFAULT_SOUL_LANGUAGE)
        soul_prompts = [event[1] for event in tui.events if event[0] == "select"]
        self.assertIn("Generate SOUL.md with Hermes AI backend now?", soul_prompts)

    def test_apply_plan_existing_soul_overwrite_prompt_happens_after_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            soul_path = Path(tmp) / "SOUL.md"
            soul_path.write_text("old soul", encoding="utf-8")
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=False,
                dry_run=False,
                generate_soul=True,
                soul_agent_name="Gatot",
                soul_user_name="Zhafron",
                hermes_python=Path("/tmp/hermes-python"),
            )
            plan = build_plan(options)
            tui = FakeTui(
                [
                    True,  # apply plan
                    True,  # overwrite SOUL.md after install/verify
                ]
            )

            def record(name):
                def inner(*_args, **_kwargs):
                    tui.events.append(("call", name))

                return inner

            with (
                patch("hermes_stack_bootstrap.cli.install_lcm", side_effect=record("install_lcm")),
                patch("hermes_stack_bootstrap.cli.install_mnemosyne", side_effect=record("install_mnemosyne")),
                patch("hermes_stack_bootstrap.cli.install_progress_tail", side_effect=record("install_progress_tail")),
                patch(
                    "hermes_stack_bootstrap.cli.install_optional_skills", side_effect=record("install_optional_skills")
                ),
                patch("hermes_stack_bootstrap.cli.merge_config_and_env", side_effect=record("merge_config_and_env")),
                patch("hermes_stack_bootstrap.cli.run_verification", side_effect=record("verify")),
                patch("hermes_stack_bootstrap.cli.apply_soul_generation", side_effect=record("soul")),
            ):
                apply_plan(plan, tui)

        verify_index = tui.events.index(("call", "verify"))
        overwrite_index = next(
            index
            for index, event in enumerate(tui.events)
            if event[0] == "select" and str(event[1]).startswith("SOUL.md already exists")
        )
        soul_index = tui.events.index(("call", "soul"))
        self.assertLess(verify_index, overwrite_index)
        self.assertLess(overwrite_index, soul_index)

    def test_apply_soul_generation_shows_status_while_hermes_backend_runs(self):
        valid_soul = "\n\n".join(
            [
                "# Identity\n\nGatot.",
                "# Operating Posture\n\nOperate.",
                "# Critical Judgment\n\nJudge.",
                "# Tool Use\n\nUse tools.",
                "# Execution Protocol\n\nExecute.",
                "# Verification\n\nVerify.",
                "# Context Management\n\nManage context.",
                "# Delegation\n\nDelegate.",
                "# Communication\n\nCommunicate.",
                "# Memory and Learning\n\nRemember.",
                "# Safety Boundaries\n\nStay safe.",
                "# What to Avoid\n\nAvoid fluff.",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=True,
                dry_run=False,
                generate_soul=True,
                soul_agent_name="Gatot",
                soul_user_name="Zhafron",
            )
            plan = build_plan(options)
            tui = FakeTui([])

            def generate_with_status_assertion(**_kwargs):
                self.assertIn(("status_start", "Generating SOUL.md with Hermes AI backend..."), tui.events)
                self.assertNotIn(("status_stop", "Generating SOUL.md with Hermes AI backend..."), tui.events)
                return valid_soul

            with patch(
                "hermes_stack_bootstrap.cli.generate_soul_with_hermes", side_effect=generate_with_status_assertion
            ):
                apply_soul_generation(plan, tui)

            self.assertIn(("status_stop", "Generating SOUL.md with Hermes AI backend..."), tui.events)
            self.assertEqual((Path(tmp) / "SOUL.md").read_text(encoding="utf-8"), valid_soul + "\n")

    def test_progress_tail_ref_defaults_to_latest_release(self):
        self.assertEqual(PROGRESS_TAIL_REF, "latest")

    def test_progress_tail_latest_resolves_from_git_tags_not_github_api(self):
        completed = SimpleNamespace(stdout=("abc\trefs/tags/v0.1.91\ndef\trefs/tags/v0.1.93\nghi\trefs/tags/v0.1.92\n"))
        api_error = urllib.error.HTTPError(
            "https://api.github.com/repos/tickernelz/hermes-progress-tail/releases/latest",
            403,
            "rate limit exceeded",
            hdrs=None,
            fp=None,
        )

        with (
            patch("subprocess.run", return_value=completed) as run,
            patch("urllib.request.urlopen", side_effect=api_error) as urlopen,
        ):
            self.assertEqual(resolve_progress_tail_ref("latest"), "v0.1.93")

        run.assert_called_once()
        urlopen.assert_not_called()

    def test_progress_tail_latest_falls_back_to_main_when_tag_resolution_fails(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(128, ["git", "ls-remote"])):
            self.assertEqual(resolve_progress_tail_ref("latest"), "main")

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
            "stage skills from https://github.com/obra/superpowers into /tmp/hermes/skills/vendor/obra-superpowers",
            default_commands,
        )
        self.assertIn(
            "stage skills from https://github.com/obra/superpowers into /tmp/hermes/profiles/work/skills/vendor/obra-superpowers",
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
