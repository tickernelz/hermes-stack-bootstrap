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


class CliPlanTestsPart3(unittest.TestCase):
    def test_merge_config_and_env_persists_hmx_gitlab_token_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=True,
                dry_run=False,
                install_hmx_knowledge=True,
                hmx_gitlab_token="glpat-secret",
            )
            plan = build_plan(options)

            merge_config_and_env(plan)

            env_text = (Path(tmp) / ".env").read_text(encoding="utf-8")

        self.assertIn("GITLAB_TOKEN=glpat-secret", env_text)

    def test_merge_config_and_env_does_not_persist_gitlab_token_when_hmx_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=True,
                dry_run=False,
                install_hmx_knowledge=False,
                hmx_gitlab_token="ambient-token",
            )
            plan = build_plan(options)

            merge_config_and_env(plan)

            env_text = (Path(tmp) / ".env").read_text(encoding="utf-8")

        self.assertNotIn("GITLAB_TOKEN", env_text)

    def test_dry_run_redacts_hmx_gitlab_token_preview(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                yes=True,
                dry_run=True,
                install_hmx_knowledge=True,
                hmx_gitlab_token="glpat-secret",
            )
            plan = build_plan(options)

            merge_config_and_env(plan)

        output = stdout.getvalue()
        self.assertIn('GITLAB_TOKEN="<redacted>"', output)
        self.assertNotIn("glpat-secret", output)

    def test_interactive_wizard_guides_hashmicro_provider_and_model_routing(self):
        tui = FakeTui(
            [
                None,  # install mode
                None,  # base home
                None,  # profiles
                True,  # setup recommended HashMicro provider
                "hm-secret",  # HashMicro API key
                "gpt-5.5",  # main model
                None,  # reasoning effort = xhigh default
                None,  # main context length = live default for gpt-5.5
                "gpt-5.5-medium",  # delegation model
                None,  # delegation context length = live default for gpt-5.5-medium
                "gpt-5.4-mini",  # auxiliary default model
                None,  # auxiliary default context length
                False,  # do not customize per auxiliary task
                "hybrid",  # Mnemosyne mode
                None,  # Mnemosyne provider = default
                "gpt-5.5",  # LCM summary model
                "gpt-5.5-medium",  # LCM expansion model
                False,  # skip Superpowers
                False,  # skip HMX knowledge
                False,  # skip Impeccable
                False,  # skip Ponytail
            ]
        )
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
            patch(
                "hermes_stack_bootstrap.cli.fetch_openai_compatible_model_metadata",
                return_value=(
                    ["gpt-5.5", "gpt-5.5-medium", "gpt-5.5-xhigh", "gpt-5.4-mini"],
                    {"gpt-5.5": 272000, "gpt-5.5-medium": 400000, "gpt-5.5-xhigh": 400000, "gpt-5.4-mini": 409600},
                ),
            ),
        ):
            options = wizard([], ui=tui, env={})

        self.assertTrue(options.setup_hashmicro_provider)
        self.assertEqual(options.hashmicro_api_key, "hm-secret")
        self.assertEqual(options.hashmicro_main_model, "gpt-5.5")
        self.assertEqual(options.hashmicro_main_context_length, 400000)
        self.assertEqual(options.hashmicro_delegation_model, "gpt-5.5-medium")
        self.assertEqual(options.hashmicro_delegation_context_length, 400000)
        self.assertEqual(options.hashmicro_reasoning_effort, "xhigh")
        self.assertEqual(set(options.hashmicro_auxiliary_models), set(AUXILIARY_TASKS))
        self.assertEqual(options.hashmicro_auxiliary_models["compression"], "gpt-5.4-mini")
        self.assertEqual(options.hashmicro_auxiliary_context_lengths["compression"], 409600)
        prompts = [event[1] for event in tui.events if event[0] in {"select", "confirm", "password"}]
        self.assertLess(prompts.index("Configure recommended xAI HashMicro provider?"), prompts.index("Mnemosyne mode"))
        self.assertIn("HashMicro main model", prompts)
        self.assertIn("HashMicro reasoning effort", prompts)
        self.assertIn("HashMicro delegation model", prompts)
        self.assertIn("HashMicro default auxiliary model", prompts)
        text_prompts = [event[1] for event in tui.events if event[0] == "text"]
        self.assertIn("HashMicro main context length", text_prompts)
        self.assertIn("HashMicro delegation context length", text_prompts)
        self.assertIn("HashMicro default auxiliary context length", text_prompts)
        step_titles = [event[1] for event in tui.events if event[0] == "step"]
        self.assertEqual(
            step_titles[:6],
            [
                "1. Install scope",
                "2. Hermes target/runtime",
                "3. Recommended provider setup",
                "4. Model routing",
                "5. Stack components",
                "6. Skill packs and credentials",
            ],
        )

    def test_interactive_wizard_captures_hmx_gitlab_token_when_installing_hmx(self):
        tui = FakeTui(
            [
                "Plugin & skill only",
                None,  # base home
                None,  # profiles
                False,  # skip Superpowers
                True,  # install HMX knowledge
                "glpat-secret",  # GitLab token
                False,  # skip Impeccable
                False,  # skip Ponytail
            ]
        )
        with (
            patch("hermes_stack_bootstrap.cli.detect_base_home", return_value=Path("/srv/hermes")),
            patch("hermes_stack_bootstrap.cli.provider_choices", return_value=[]),
        ):
            options = wizard([], ui=tui, env={})

        self.assertTrue(options.install_hmx_knowledge)
        self.assertEqual(options.hmx_gitlab_token, "glpat-secret")
        self.assertIn(("password", "HMX GitLab token (hidden; empty to use SSH/credential helper only)"), tui.events)

    def test_wizard_picks_mnemosyne_and_lcm_models_from_detected_hermes_providers(self):
        providers = [
            ProviderChoice(
                "openrouter", "OpenRouter — 2 models", ("anthropic/claude-sonnet-4", "google/gemini-3-flash")
            ),
            ProviderChoice("custom:lokal", "Lokal — 1 model", ("gpt-5.4-mini",)),
        ]
        tui = FakeTui(
            [
                None,  # install mode
                None,  # base home
                None,  # profiles
                False,  # skip HashMicro provider setup
                "hybrid",
                "OpenRouter — 2 models",
                "anthropic/claude-sonnet-4",
                "google/gemini-3-flash",
                None,  # expansion same as summary
                False,  # skip Superpowers
                False,  # skip HMX knowledge
                False,  # skip Impeccable
                False,  # skip Ponytail
            ]
        )
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
        tui = FakeTui(
            [
                None,  # install mode
                None,
                None,
                False,  # skip HashMicro provider setup
                "full-online",
                "https://embeddings.example/v1",
                "secret-from-prompt",
                "text-embedding-3-small",
                "1536",
                "",  # lcm summary
                "",  # lcm expansion
                False,  # skip Superpowers
                False,  # skip HMX knowledge
                False,  # skip Impeccable
                False,  # skip Ponytail
            ]
        )
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
            "stage skills from https://github.com/obra/superpowers into /tmp/hermes/skills/vendor/obra-superpowers",
            commands,
        )
        self.assertIn(
            "stage skills from git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git into /tmp/hermes/skills/vendor/hmx-knowledge",
            commands,
        )
        self.assertIn(
            "stage skills from https://github.com/pbakaus/impeccable into /tmp/hermes/skills/vendor/impeccable",
            commands,
        )
        self.assertIn(
            "stage skills from https://github.com/DietrichGebert/ponytail into /tmp/hermes/skills/vendor/ponytail",
            commands,
        )
        self.assertNotIn(
            "git clone --depth=1 https://github.com/obra/superpowers /tmp/hermes/skills/vendor/obra-superpowers",
            commands,
        )
        self.assertNotIn(
            "git clone --depth=1 git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git /tmp/hermes/skills/vendor/hmx-knowledge",
            commands,
        )
        self.assertNotIn(
            "git clone --depth=1 https://github.com/pbakaus/impeccable /tmp/hermes/skills/vendor/impeccable",
            commands,
        )
        self.assertNotIn(
            "git clone --depth=1 https://github.com/DietrichGebert/ponytail /tmp/hermes/skills/vendor/ponytail",
            commands,
        )

    def test_stage_skill_pack_replaces_incorrect_repo_root_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source_skills = source / "skills"
            (source_skills / "ponytail").mkdir(parents=True)
            (source_skills / "ponytail-review").mkdir(parents=True)
            (source_skills / "ponytail" / "SKILL.md").write_text("ponytail", encoding="utf-8")
            (source_skills / "ponytail-review" / "SKILL.md").write_text("review", encoding="utf-8")
            (source / "package.json").write_text("{}", encoding="utf-8")
            (source / "commands").mkdir()

            dest = Path(tmp) / "hermes" / "skills" / "vendor" / "ponytail"
            (dest / "skills" / "wrong").mkdir(parents=True)
            (dest / "skills" / "wrong" / "SKILL.md").write_text("wrong", encoding="utf-8")
            (dest / "package.json").write_text("{}", encoding="utf-8")
            (dest / "commands").mkdir()
            spec = SkillPackSpec("ponytail", "https://example.invalid/ponytail", source_subdir="skills")

            self.assertTrue(is_repo_root_skill_install(dest))

            stage_skill_pack(source, dest, spec)

            backups = list((dest.parent.parent.parent / "backups").glob("ponytail-repo-root-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "package.json").exists())
            self.assertTrue((backups[0] / "commands").exists())
            self.assertFalse((dest / "package.json").exists())
            self.assertFalse((dest / "commands").exists())
            self.assertFalse((dest / "skills").exists())
            self.assertEqual((dest / "ponytail" / "SKILL.md").read_text(encoding="utf-8"), "ponytail")
            self.assertEqual((dest / "ponytail-review" / "SKILL.md").read_text(encoding="utf-8"), "review")

    def test_stage_skill_pack_preserves_non_upstream_custom_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            (source / "skills" / "ponytail").mkdir(parents=True)
            (source / "skills" / "ponytail" / "SKILL.md").write_text("fresh", encoding="utf-8")

            dest = Path(tmp) / "hermes" / "skills" / "vendor" / "ponytail"
            (dest / "ponytail").mkdir(parents=True)
            (dest / "ponytail" / "SKILL.md").write_text("old", encoding="utf-8")
            (dest / "my-custom-skill").mkdir()
            (dest / "my-custom-skill" / "SKILL.md").write_text("custom", encoding="utf-8")
            spec = SkillPackSpec("ponytail", "https://example.invalid/ponytail", source_subdir="skills")

            stage_skill_pack(source, dest, spec)

            self.assertEqual((dest / "ponytail" / "SKILL.md").read_text(encoding="utf-8"), "fresh")
            self.assertEqual((dest / "my-custom-skill" / "SKILL.md").read_text(encoding="utf-8"), "custom")
            self.assertFalse((dest.parent.parent.parent / "backups").exists())
