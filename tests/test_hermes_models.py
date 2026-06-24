import unittest
from unittest.mock import patch

from hermes_stack_bootstrap.hermes_models import ProviderChoice, model_choices_for_provider, provider_choices


class HermesModelsTests(unittest.TestCase):
    def test_provider_choices_use_hermes_authenticated_provider_inventory(self):
        inventory = [
            {
                "slug": "openrouter",
                "name": "OpenRouter",
                "models": ["anthropic/claude-sonnet-4", "openai/gpt-5.4-mini"],
                "total_models": 2,
            },
            {"slug": "custom:lokal", "name": "Lokal", "models": ["gpt-5.4-mini"], "total_models": 1},
        ]
        with patch("hermes_stack_bootstrap.hermes_models.list_hermes_authenticated_providers", return_value=inventory):
            choices = provider_choices()

        self.assertEqual(
            choices,
            [
                ProviderChoice(
                    "openrouter", "OpenRouter — 2 models", ("anthropic/claude-sonnet-4", "openai/gpt-5.4-mini")
                ),
                ProviderChoice("custom:lokal", "Lokal — 1 model", ("gpt-5.4-mini",)),
            ],
        )

    def test_provider_choices_can_use_selected_runtime_python_inventory(self):
        inventory = [
            {"slug": "openrouter", "name": "OpenRouter", "models": ["m"], "total_models": 1},
        ]
        with (
            patch(
                "hermes_stack_bootstrap.hermes_models._provider_rows_from_runtime", return_value=inventory
            ) as runtime_rows,
            patch("hermes_stack_bootstrap.hermes_models.list_hermes_authenticated_providers") as local_rows,
        ):
            choices = provider_choices("/srv/hermes/venv/bin/python")

        runtime_rows.assert_called_once()
        local_rows.assert_not_called()
        self.assertEqual(choices, [ProviderChoice("openrouter", "OpenRouter — 1 model", ("m",))])

    def test_provider_choices_fall_back_to_empty_list_when_hermes_modules_are_unavailable(self):
        with patch(
            "hermes_stack_bootstrap.hermes_models.list_hermes_authenticated_providers",
            side_effect=ImportError("no hermes"),
        ):
            self.assertEqual(provider_choices(), [])

    def test_model_choices_for_provider_uses_inventory_then_provider_catalog(self):
        choices = [ProviderChoice("openrouter", "OpenRouter", ("a", "b"))]
        self.assertEqual(model_choices_for_provider("openrouter", choices), ("a", "b"))
        with patch("hermes_stack_bootstrap.hermes_models.provider_model_ids", return_value=["fallback"]):
            self.assertEqual(model_choices_for_provider("anthropic", choices), ("fallback",))

    def test_model_choices_for_provider_prefers_selected_runtime_python_catalog(self):
        with (
            patch(
                "hermes_stack_bootstrap.hermes_models._provider_model_ids_from_runtime", return_value=("runtime",)
            ) as runtime_models,
            patch("hermes_stack_bootstrap.hermes_models.provider_model_ids") as local_models,
        ):
            self.assertEqual(model_choices_for_provider("anthropic", [], "/srv/hermes/venv/bin/python"), ("runtime",))

        runtime_models.assert_called_once()
        local_models.assert_not_called()


if __name__ == "__main__":
    unittest.main()
