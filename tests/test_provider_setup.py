import json
import unittest
from unittest.mock import patch

from hermes_stack_bootstrap.provider_setup import (
    AUXILIARY_TASKS,
    HashmicroProviderSetup,
    build_hashmicro_env_values,
    default_hashmicro_context_length,
    fetch_openai_compatible_models,
    hashmicro_model_with_reasoning_effort,
    merge_hashmicro_provider_config,
    parse_aux_context_length_overrides,
    parse_aux_model_overrides,
    parse_openai_compatible_model_contexts_response,
    secret_env_keys,
)


class ProviderSetupTests(unittest.TestCase):
    def test_parse_openai_compatible_models_response(self):
        payload = json.dumps(
            {
                "object": "list",
                "data": [
                    {"id": "gpt-5.5", "context_length": 1000000},
                    {"id": "gpt-5.5-high", "max_context_length": 1000000},
                    {"name": "fallback-name", "context_window": 128000},
                    {"id": "input-only-limit", "max_input_tokens": 64000},
                    "literal-model",
                ],
            }
        ).encode()

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return payload

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            models = fetch_openai_compatible_models("https://xai.hashmicro.co/v1", "secret", timeout=7)

        self.assertEqual(models, ["gpt-5.5", "gpt-5.5-high", "fallback-name", "input-only-limit", "literal-model"])
        self.assertEqual(
            parse_openai_compatible_model_contexts_response(payload),
            {"gpt-5.5": 1000000, "gpt-5.5-high": 1000000, "fallback-name": 128000},
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://xai.hashmicro.co/v1/models")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertEqual(request.headers["Accept"], "application/json")

    def test_merge_hashmicro_provider_config_sets_named_provider_and_routes_models(self):
        existing = {
            "custom_providers": [
                {"name": "other", "base_url": "https://other.example/v1", "key_env": "OTHER_KEY"},
                {
                    "name": "xai-hashmicro",
                    "base_url": "https://old.example/v1",
                    "key_env": "OLD_KEY",
                    "models": {"old": {}},
                },
            ],
            "model": {"provider": "openrouter", "default": "old-main", "context_length": 123, "keep": "value"},
            "delegation": {"provider": "openrouter", "model": "old-child", "max_iterations": 77},
            "auxiliary": {
                "compression": {
                    "provider": "custom",
                    "model": "old",
                    "context_length": 123,
                    "base_url": "https://stale.example/v1",
                    "api_key": "stale",
                },
                "vision": {"provider": "auto", "model": ""},
            },
        }
        setup = HashmicroProviderSetup(
            enabled=True,
            api_key="secret",
            main_model="gpt-5.5",
            delegation_model="gpt-5.5-medium",
            auxiliary_models={"compression": "gpt-5.4-mini", "vision": "gpt-5.5"},
            model_context_lengths={"gpt-5.5": 1000000, "gpt-5.5-medium": 1000000, "gpt-5.4-mini": 400000},
            reasoning_effort="xhigh",
        )

        merged = merge_hashmicro_provider_config(existing, setup)

        providers = merged["custom_providers"]
        self.assertEqual(len(providers), 2)
        self.assertEqual(providers[1]["name"], "xai-hashmicro")
        self.assertEqual(providers[1]["base_url"], "https://xai.hashmicro.co/v1")
        self.assertEqual(providers[1]["key_env"], "XAI_HASHMICRO_API_KEY")
        self.assertEqual(providers[1]["api_mode"], "chat_completions")
        self.assertIs(providers[1]["discover_models"], True)
        self.assertEqual(providers[1]["models"]["gpt-5.5"]["context_length"], 1000000)
        self.assertEqual(providers[1]["models"]["gpt-5.5-medium"]["context_length"], 1000000)
        self.assertEqual(providers[1]["models"]["gpt-5.4-mini"]["context_length"], 400000)
        self.assertEqual(merged["model"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(merged["model"]["default"], "gpt-5.5")
        self.assertNotIn("context_length", merged["model"])
        self.assertEqual(merged["model"]["keep"], "value")
        self.assertEqual(merged["delegation"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(merged["delegation"]["model"], "gpt-5.5-medium")
        self.assertEqual(merged["delegation"]["reasoning_effort"], "xhigh")
        self.assertEqual(merged["delegation"]["max_iterations"], 77)
        self.assertEqual(merged["agent"]["reasoning_effort"], "xhigh")
        self.assertEqual(merged["auxiliary"]["compression"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(merged["auxiliary"]["compression"]["model"], "gpt-5.4-mini")
        self.assertNotIn("context_length", merged["auxiliary"]["compression"])
        self.assertEqual(merged["auxiliary"]["compression"]["base_url"], "")
        self.assertEqual(merged["auxiliary"]["compression"]["api_key"], "")
        self.assertEqual(merged["auxiliary"]["vision"]["provider"], "custom:xai-hashmicro")
        self.assertEqual(merged["auxiliary"]["vision"]["model"], "gpt-5.5")
        self.assertNotIn("context_length", merged["auxiliary"]["vision"])

    def test_build_hashmicro_env_values_writes_only_supplied_secret(self):
        setup = HashmicroProviderSetup(enabled=True, api_key="secret")

        self.assertEqual(build_hashmicro_env_values(setup), {"XAI_HASHMICRO_API_KEY": "secret"})
        self.assertEqual(
            secret_env_keys({"XAI_HASHMICRO_API_KEY": "secret", "SAFE": "value"}), {"XAI_HASHMICRO_API_KEY"}
        )
        self.assertEqual(build_hashmicro_env_values(HashmicroProviderSetup(enabled=True, api_key="")), {})

    def test_parse_aux_model_overrides_validates_task_names_and_shape(self):
        parsed = parse_aux_model_overrides(["compression=gpt-5.4-mini", "vision=gpt-5.5"])

        self.assertEqual(parsed, {"compression": "gpt-5.4-mini", "vision": "gpt-5.5"})
        with self.assertRaisesRegex(ValueError, "task=model"):
            parse_aux_model_overrides(["compression"])
        with self.assertRaisesRegex(ValueError, "Unknown auxiliary task"):
            parse_aux_model_overrides(["not_a_task=gpt"])

    def test_hashmicro_context_defaults_cover_model_families_and_reasoning_suffixes(self):
        self.assertEqual(default_hashmicro_context_length("gpt-5.5"), 272000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.5-xhigh"), 272000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.5-reasoning-xhigh"), 272000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.5-codex"), 272000)
        self.assertEqual(default_hashmicro_context_length("codex/gpt-5.5-xhigh"), 272000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.4"), 200000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.4-reasoning-high"), 200000)
        self.assertEqual(default_hashmicro_context_length("gpt-5.4-mini"), 409600)
        self.assertEqual(default_hashmicro_context_length("gpt-5.4-mini-xhigh"), 409600)
        self.assertEqual(default_hashmicro_context_length("gpt-5.4-mini-reasoning-high"), 409600)
        self.assertEqual(default_hashmicro_context_length("unknown-model"), 0)

    def test_hashmicro_reasoning_effort_suffixes_only_known_or_available_model_ids(self):
        self.assertEqual(hashmicro_model_with_reasoning_effort("gpt-5.5", "xhigh"), "gpt-5.5-xhigh")
        self.assertEqual(hashmicro_model_with_reasoning_effort("gpt-5.5-medium", "xhigh"), "gpt-5.5-xhigh")
        self.assertEqual(hashmicro_model_with_reasoning_effort("gpt-5.5", "low"), "gpt-5.5")
        self.assertEqual(hashmicro_model_with_reasoning_effort("codex/gpt-5.5", "low"), "codex/gpt-5.5-low")
        self.assertEqual(hashmicro_model_with_reasoning_effort("gpt-5.4-mini", "high"), "gpt-5.4-mini")
        self.assertEqual(
            hashmicro_model_with_reasoning_effort("gpt-5.4-mini", "high", ["gpt-5.4-mini-high"]),
            "gpt-5.4-mini-high",
        )

    def test_parse_aux_context_length_overrides_validates_task_and_positive_integer(self):
        parsed = parse_aux_context_length_overrides(["compression=400000", "vision=272000"])

        self.assertEqual(parsed, {"compression": 400000, "vision": 272000})
        with self.assertRaisesRegex(ValueError, "task=context_length"):
            parse_aux_context_length_overrides(["compression"])
        with self.assertRaisesRegex(ValueError, "positive integer"):
            parse_aux_context_length_overrides(["compression=0"])
        with self.assertRaisesRegex(ValueError, "Unknown auxiliary task"):
            parse_aux_context_length_overrides(["not_a_task=400000"])

    def test_auxiliary_task_list_matches_expected_hermes_slots(self):
        self.assertIn("compression", AUXILIARY_TASKS)
        self.assertIn("background_review", AUXILIARY_TASKS)
        self.assertNotIn("session_search", AUXILIARY_TASKS)


if __name__ == "__main__":
    unittest.main()
