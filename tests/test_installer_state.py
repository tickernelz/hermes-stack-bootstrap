import argparse
import json
import tempfile
import unittest
from pathlib import Path

from hermes_stack_bootstrap.bootstrap_data import InstallerOptions
from hermes_stack_bootstrap.bootstrap_state import (
    apply_saved_state,
    load_env_values,
    save_options_state,
    state_path_for,
)


class InstallerStateTests(unittest.TestCase):
    def test_state_path_lives_in_target_home(self):
        self.assertEqual(
            state_path_for(Path("/tmp/hermes")),
            Path("/tmp/hermes") / ".hermes-stack-bootstrap.json",
        )

    def test_apply_saved_state_sets_defaults_without_overriding_explicit_flags(self):
        args = argparse.Namespace(
            install_mode="full",
            profile=None,
            mnemosyne_mode="hybrid",
            install_superpowers=False,
            install_hmx_knowledge=False,
            install_impeccable=False,
            install_ponytail=False,
            setup_hashmicro_provider=False,
            main_model="",
            main_context_length="",
            delegation_model="",
            delegation_context_length="",
            aux_all_model="",
            aux_all_context_length="",
            hashmicro_reasoning_effort="xhigh",
            generate_soul=False,
            soul_agent_name="",
            soul_user_name="",
        )
        state = {
            "install_mode": "plugin-skill-only",
            "profile": "work,client",
            "mnemosyne_mode": "full-local",
            "install_superpowers": True,
            "install_hmx_knowledge": True,
            "install_impeccable": True,
            "install_ponytail": True,
            "setup_hashmicro_provider": True,
            "main_model": "gpt-5.5",
            "main_context_length": "272000",
            "delegation_model": "gpt-5.5",
            "delegation_context_length": "272000",
            "aux_all_model": "gpt-5.4-mini",
            "aux_all_context_length": "409600",
            "hashmicro_reasoning_effort": "high",
            "generate_soul": True,
            "soul_agent_name": "Jono",
            "soul_user_name": "Zhafron",
        }

        apply_saved_state(args, state, explicit_flags={"--main-model", "--install-ponytail"})

        self.assertEqual(args.install_mode, "plugin-skill-only")
        self.assertEqual(args.profile, ["work,client"])
        self.assertEqual(args.mnemosyne_mode, "full-local")
        self.assertTrue(args.install_superpowers)
        self.assertTrue(args.install_hmx_knowledge)
        self.assertTrue(args.install_impeccable)
        self.assertFalse(args.install_ponytail)
        self.assertTrue(args.setup_hashmicro_provider)
        self.assertEqual(args.main_model, "")
        self.assertEqual(args.main_context_length, "272000")
        self.assertEqual(args.hashmicro_reasoning_effort, "high")
        self.assertTrue(args.generate_soul)
        self.assertEqual(args.soul_agent_name, "Jono")

    def test_save_options_state_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".hermes-stack-bootstrap.json"
            options = InstallerOptions(
                base_home=Path(tmp),
                profile="default",
                hmx_gitlab_token="glpat-secret",
                hashmicro_api_key="sk-secret",
                mnemosyne_embedding_api_key="embed-secret",
                install_hmx_knowledge=True,
                install_ponytail=True,
                setup_hashmicro_provider=True,
                hashmicro_main_model="gpt-5.5",
                hashmicro_main_context_length=272000,
            )

            save_options_state(path, options)

            data = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(data)
            self.assertTrue(data["install_hmx_knowledge"])
            self.assertTrue(data["install_ponytail"])
            self.assertEqual(data["main_model"], "gpt-5.5")
            self.assertEqual(data["main_context_length"], "272000")
            self.assertNotIn("glpat-secret", serialized)
            self.assertNotIn("sk-secret", serialized)
            self.assertNotIn("embed-secret", serialized)

    def test_load_env_values_reads_existing_profile_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                'XAI_HASHMICRO_API_KEY="sk-old"\nGITLAB_TOKEN=glpat-old\nPLAIN=value\n',
                encoding="utf-8",
            )

            self.assertEqual(
                load_env_values(env_path),
                {"XAI_HASHMICRO_API_KEY": "sk-old", "GITLAB_TOKEN": "glpat-old", "PLAIN": "value"},
            )


if __name__ == "__main__":
    unittest.main()
