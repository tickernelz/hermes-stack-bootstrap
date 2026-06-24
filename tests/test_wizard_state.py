import argparse
import tempfile
import unittest
from pathlib import Path

import yaml

from hermes_stack_bootstrap.bootstrap_data import InstallerOptions
from hermes_stack_bootstrap.wizard_state import (
    WizardStateError,
    apply_profile_defaults,
    list_profiles,
    load_profile,
    profile_from_options,
    profile_path,
    save_profile,
)


class WizardV2StateTests(unittest.TestCase):
    def test_save_and_load_yaml_profile_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = InstallerOptions(
                base_home=Path("~/.hermes"),
                profile="default",
                install_mode="full",
                setup_hashmicro_provider=True,
                hashmicro_provider_name="xai-hashmicro",
                hashmicro_base_url="https://xai.hashmicro.co/v1",
                hashmicro_key_env="XAI_HASHMICRO_API_KEY",
                hashmicro_api_key="sk-secret",
                hmx_gitlab_token="glpat-secret",
                mnemosyne_embedding_api_key="embed-secret",
                hashmicro_main_model="gpt-5.5",
                hashmicro_main_context_length=272000,
                hashmicro_delegation_model="gpt-5.5",
                hashmicro_auxiliary_models={"summarization": "gpt-5.5"},
                install_hmx_knowledge=True,
                install_ponytail=True,
            )

            path = save_profile("default", profile_from_options(options), Path(tmp))
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)

            self.assertEqual(path, Path(tmp) / "default.yaml")
            self.assertEqual(data["version"], 1)
            self.assertEqual(data["provider"]["key_env"], "XAI_HASHMICRO_API_KEY")
            self.assertEqual(data["models"]["main"], "gpt-5.5")
            self.assertIn("hmx", data["skills"]["packs"])
            self.assertNotIn("sk-secret", text)
            self.assertNotIn("glpat-secret", text)
            self.assertNotIn("embed-secret", text)

            loaded = load_profile("default", Path(tmp))
            self.assertEqual(loaded.provider.provider_name, "xai-hashmicro")
            self.assertEqual(loaded.models.context, 272000)

    def test_list_profiles_and_path_reject_unsafe_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_profile("work", {"version": 1, "mode": "full"}, Path(tmp))
            save_profile("personal", {"version": 1, "mode": "full"}, Path(tmp))
            self.assertEqual(list_profiles(Path(tmp)), ["personal", "work"])
            self.assertEqual(profile_path("work", Path(tmp)), Path(tmp) / "work.yaml")
            with self.assertRaises(WizardStateError):
                profile_path("../bad", Path(tmp))

    def test_apply_profile_defaults_does_not_override_explicit_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_profile(
                "default",
                {
                    "version": 1,
                    "mode": "full",
                    "hermes_home": "/tmp/hermes",
                    "profile": "default",
                    "provider": {
                        "kind": "hashmicro",
                        "provider_name": "xai-hashmicro",
                        "base_url": "https://xai.hashmicro.co/v1",
                        "key_env": "XAI_HASHMICRO_API_KEY",
                    },
                    "models": {"main": "gpt-5.5", "delegation": "gpt-5.5", "context": 272000},
                    "components": {"install_config": True, "install_soul": True},
                    "skills": {"packs": ["hmx", "ponytail"], "conflict_policy": "ask"},
                    "verification": {"run_smoke": True, "create_soul": "ask"},
                },
                Path(tmp),
            )
            args = argparse.Namespace(
                install_mode="dry-run",
                home="",
                profile=None,
                setup_hashmicro_provider=False,
                hashmicro_provider_name="",
                hashmicro_base_url="",
                hashmicro_key_env="",
                main_model="manual-model",
                delegation_model="",
                main_context_length="",
                delegation_context_length="",
                aux_all_model="",
                aux_model=[],
                skip_config_env=True,
                skip_verify=True,
                generate_soul=False,
                install_superpowers=False,
                install_hmx_knowledge=False,
                install_impeccable=False,
                install_ponytail=False,
            )

            apply_profile_defaults(args, load_profile("default", Path(tmp)), {"--main-model"})

            self.assertEqual(args.install_mode, "full")
            self.assertEqual(args.home, "/tmp/hermes")
            self.assertEqual(args.main_model, "manual-model")
            self.assertEqual(args.main_context_length, "272000")
            self.assertTrue(args.setup_hashmicro_provider)
            self.assertTrue(args.install_hmx_knowledge)
            self.assertTrue(args.install_ponytail)
            self.assertTrue(args.generate_soul)
            self.assertFalse(args.skip_verify)


if __name__ == "__main__":
    unittest.main()
