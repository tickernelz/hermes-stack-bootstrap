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


class CliPlanTestsPart4(unittest.TestCase):
    def test_stage_skill_pack_prefixes_superpowers_skill_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            skill_dir = source / "skills" / "brainstorming"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: brainstorming\n"
                "description: Think first\n"
                "---\n\n"
                "Use test-driven-development when coding.\n"
                "Use superpowers:test-driven-development if namespace form is needed.\n"
                "See ../test-driven-development/testing-anti-patterns.md.\n",
                encoding="utf-8",
            )
            (skill_dir / "scripts").mkdir()
            (skill_dir / "references").mkdir()
            (skill_dir / "visual-companion.md").write_text("Use test-driven-development here too", encoding="utf-8")
            (skill_dir / "scripts" / "start-server.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
            (skill_dir / "references" / "guide.md").write_text("Ask for test-driven-development", encoding="utf-8")
            dest = Path(tmp) / "hermes" / "skills" / "vendor" / "obra-superpowers"
            spec = SkillPackSpec(
                "obra-superpowers",
                "https://example.invalid/superpowers",
                source_subdir="skills",
                skill_name_prefix="superpowers-",
                body_token_prefixes=("test-driven-development",),
            )

            stage_skill_pack(source, dest, spec)

            staged = dest / "superpowers-brainstorming"
            self.assertTrue((staged / "SKILL.md").exists())
            self.assertTrue((staged / "visual-companion.md").exists())
            self.assertTrue((staged / "scripts" / "start-server.sh").exists())
            self.assertTrue((staged / "references" / "guide.md").exists())
            content = (staged / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("name: superpowers-brainstorming", content)
            self.assertIn("superpowers-test-driven-development", content)
            self.assertIn("superpowers-test-driven-development if namespace form is needed", content)
            self.assertNotIn("superpowers:superpowers-", content)
            self.assertIn("../superpowers-test-driven-development/testing-anti-patterns.md", content)
            companion = (staged / "visual-companion.md").read_text(encoding="utf-8")
            reference = (staged / "references" / "guide.md").read_text(encoding="utf-8")
            script = (staged / "scripts" / "start-server.sh").read_text(encoding="utf-8")
            self.assertIn("superpowers-test-driven-development", companion)
            self.assertIn("superpowers-test-driven-development", reference)
            self.assertNotIn("superpowers-", script)
            self.assertFalse((dest / "package.json").exists())

    def test_stage_skill_pack_uses_configured_impeccable_skill_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            (source / "plugin" / "skills" / "impeccable" / "scripts").mkdir(parents=True)
            (source / "plugin" / "skills" / "impeccable" / "reference").mkdir(parents=True)
            (source / "plugin" / "skills" / "impeccable" / "templates").mkdir(parents=True)
            (source / "plugin" / "skills" / "impeccable" / "SKILL.md").write_text(
                "---\nname: impeccable\ndescription: Design skill\n---\n\nRun scripts/context.mjs.\n",
                encoding="utf-8",
            )
            (source / "plugin" / "skills" / "impeccable" / "scripts" / "context.mjs").write_text("ok", encoding="utf-8")
            (source / "plugin" / "skills" / "impeccable" / "reference" / "audit.md").write_text(
                "audit", encoding="utf-8"
            )
            (source / "plugin" / "skills" / "impeccable" / "templates" / "design.json").write_text(
                "{}", encoding="utf-8"
            )
            (source / ".claude" / "skills" / "impeccable").mkdir(parents=True)
            (source / ".claude" / "skills" / "impeccable" / "SKILL.md").write_text("wrong", encoding="utf-8")
            dest = Path(tmp) / "hermes" / "skills" / "vendor" / "impeccable"
            spec = SkillPackSpec("impeccable", "https://example.invalid/impeccable", source_subdir="plugin/skills")

            stage_skill_pack(source, dest, spec)

            self.assertTrue((dest / "impeccable" / "SKILL.md").exists())
            self.assertTrue((dest / "impeccable" / "scripts" / "context.mjs").exists())
            self.assertTrue((dest / "impeccable" / "reference" / "audit.md").exists())
            self.assertTrue((dest / "impeccable" / "templates" / "design.json").exists())
            self.assertFalse((dest / ".claude").exists())
            self.assertFalse((dest / "package.json").exists())

    def test_stage_skill_pack_discovers_private_repo_skills_when_no_source_subdir_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "README.md").write_text("not a skill", encoding="utf-8")
            (source / "skills" / "hmx-one").mkdir(parents=True)
            (source / "skills" / "hmx-one" / "SKILL.md").write_text(
                "---\nname: hmx-one\ndescription: HMX\n---\n",
                encoding="utf-8",
            )
            dest = Path(tmp) / "hermes" / "skills" / "vendor" / "hmx-knowledge"
            spec = SkillPackSpec("hmx-knowledge", "git@example.invalid:hmx.git")

            stage_skill_pack(source, dest, spec)

            self.assertTrue((dest / "hmx-one" / "SKILL.md").exists())
            self.assertFalse((dest / "README.md").exists())

    def test_install_optional_skills_uses_skill_pack_stagers(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=True,
            install_superpowers=True,
            install_hmx_knowledge=True,
            install_impeccable=True,
            install_ponytail=True,
            skip_lcm=True,
            skip_mnemosyne=True,
            skip_progress_tail=True,
            skip_config_env=True,
            skip_verify=True,
        )
        plan = build_plan(options)

        with patch("hermes_stack_bootstrap.cli.install_skill_pack") as install_pack:
            install_optional_skills(plan)

        calls = [(call.args[0].name, call.args[1]) for call in install_pack.call_args_list]
        self.assertEqual(
            calls,
            [
                ("obra-superpowers", Path("/tmp/hermes/skills/vendor/obra-superpowers")),
                ("hmx-knowledge", Path("/tmp/hermes/skills/vendor/hmx-knowledge")),
                ("impeccable", Path("/tmp/hermes/skills/vendor/impeccable")),
                ("ponytail", Path("/tmp/hermes/skills/vendor/ponytail")),
            ],
        )
        hmx_spec = install_pack.call_args_list[1].args[0]
        self.assertEqual(hmx_spec.source_subdir, "skills")

    def test_install_hmx_skill_pack_retries_https_with_gitlab_token_without_leaking_token(self):
        spec = SkillPackSpec(
            "hmx-knowledge",
            "git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git",
            source_subdir="skills",
        )
        dest = Path("/tmp/hermes/skills/vendor/hmx-knowledge")
        calls = []

        def fake_run(command, *, dry_run, env=None):
            calls.append((command, env))
            if len(calls) == 1:
                raise subprocess.CalledProcessError(128, command)

        with (
            patch("hermes_stack_bootstrap.cli.run_command", side_effect=fake_run),
            patch("hermes_stack_bootstrap.cli.stage_skill_pack") as stage,
        ):
            install_skill_pack(spec, dest, dry_run=False, gitlab_token="glpat-secret")

        self.assertEqual(calls[0][0][0:3], ["git", "clone", "--depth=1"])
        retry_command, retry_env = calls[1]
        self.assertEqual(retry_command[0:3], ["git", "clone", "--depth=1"])
        self.assertEqual(retry_command[3], "https://gitlab.com/hashmicro1/hmx/hmx-knowledge.git")
        rendered = " ".join(str(part) for part in retry_command)
        self.assertNotIn("glpat-secret", rendered)
        self.assertIn("GIT_ASKPASS", retry_env)
        self.assertIn("GIT_TERMINAL_PROMPT", retry_env)
        askpass_path = Path(retry_env["GIT_ASKPASS"])
        self.assertFalse(askpass_path.exists())
        stage.assert_called_once()

    def test_install_optional_skills_passes_hmx_gitlab_token_to_stager(self):
        options = InstallerOptions(
            base_home=Path("/tmp/hermes"),
            profile="default",
            yes=True,
            dry_run=False,
            install_hmx_knowledge=True,
            skip_lcm=True,
            skip_mnemosyne=True,
            skip_progress_tail=True,
            hmx_gitlab_token="glpat-secret",
        )
        plan = build_plan(options)

        with patch("hermes_stack_bootstrap.cli.install_skill_pack") as install_pack:
            install_optional_skills(plan)

        self.assertEqual(install_pack.call_args.kwargs["gitlab_token"], "glpat-secret")

    def test_full_online_env_merge_removes_stale_local_embedding_defaults_when_switching_modes(self):

        tui = FakeTui(
            [
                None,  # install mode
                None,
                None,
                False,  # skip HashMicro provider setup
                "hybrid",
                None,  # no lcm summary override
                None,  # no lcm expansion override
                False,  # skip Superpowers
                False,  # skip HMX knowledge
                False,  # skip Impeccable
                False,  # skip recommended Ponytail
            ]
        )
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], ui=tui)

        self.assertFalse(options.install_superpowers)
        self.assertFalse(options.install_hmx_knowledge)
        self.assertFalse(options.install_impeccable)
        self.assertFalse(options.install_ponytail)
        self.assertIn(("confirm", "Install Obra Superpowers skill pack?", False), tui.events)
        self.assertIn(("confirm", "Install HMX knowledge skill pack?", False), tui.events)
        self.assertIn(("confirm", "Install Impeccable design skill?", False), tui.events)
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
                    "--soul-communication",
                    "Blunt and concise",
                    "--soul-language",
                    "Bahasa Indonesia",
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
        self.assertEqual(options.soul_communication, "Blunt and concise")
        self.assertEqual(options.soul_language, "Bahasa Indonesia")
        self.assertEqual(options.soul_provider, "openrouter")
        self.assertEqual(options.soul_model, "anthropic/claude-sonnet-4")
        self.assertTrue(options.soul_overwrite)

    def test_apply_plan_soul_only_prompts_identity_after_plan_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=False,
                dry_run=False,
                install_mode="soul-only",
                skip_lcm=True,
                skip_mnemosyne=True,
                skip_progress_tail=True,
                skip_config_env=True,
                skip_verify=True,
                generate_soul=True,
            )
            plan = build_plan(options)
            tui = FakeTui(
                [
                    True,  # apply plan
                    "Gatot",
                    "Zhafron",
                    None,  # communication style default
                    None,  # language default
                ]
            )

            with patch("hermes_stack_bootstrap.cli.apply_soul_generation") as soul_mock:
                apply_plan(plan, tui)

        generated_plan = soul_mock.call_args.args[0]
        self.assertEqual(generated_plan.options.soul_agent_name, "Gatot")
        self.assertEqual(generated_plan.options.soul_user_name, "Zhafron")
        self.assertEqual(generated_plan.options.soul_communication, DEFAULT_SOUL_COMMUNICATION_STYLE)
        self.assertEqual(generated_plan.options.soul_language, DEFAULT_SOUL_LANGUAGE)
        text_prompts = [event[1] for event in tui.events if event[0] == "text"]
        self.assertIn("Agent name", text_prompts)
        self.assertIn("User name", text_prompts)
        self.assertIn("Communication style", text_prompts)
        self.assertIn("Language", text_prompts)
        self.assertNotIn("Agent role", text_prompts)
        self.assertNotIn("Behavior / personality", text_prompts)

    def test_wizard_rejects_noninteractive_generate_soul_when_required_answers_missing(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            with self.assertRaisesRegex(ValueError, "--soul-agent-name"):
                wizard(["--yes", "--generate-soul"])

    def test_wizard_uses_soul_style_and_language_defaults_when_omitted(self):
        with patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")):
            options = wizard(
                [
                    "--yes",
                    "--generate-soul",
                    "--soul-agent-name",
                    "Gatot",
                    "--soul-user-name",
                    "Zhafron",
                ]
            )

        self.assertEqual(options.soul_communication, DEFAULT_SOUL_COMMUNICATION_STYLE)
        self.assertEqual(options.soul_language, DEFAULT_SOUL_LANGUAGE)

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
        self.assertIn(
            "HERMES_HOME=/tmp/hermes hermes -p work chat --quiet --model gpt-5.1-mini -q '<generated SOUL.md prompt>'",
            commands,
        )

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

            with patch(
                "hermes_stack_bootstrap.cli.generate_soul_with_hermes", return_value="# Identity\n\nGenerated"
            ) as gen_mock:
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

            with patch(
                "hermes_stack_bootstrap.cli.generate_soul_with_hermes", side_effect=RuntimeError("backend failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "backend failed"):
                    apply_soul_generation(plan)

            self.assertEqual(soul_path.read_text(encoding="utf-8"), "old soul")
