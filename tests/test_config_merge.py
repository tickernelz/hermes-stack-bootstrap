import unittest

from hermes_stack_bootstrap.config_merge import build_target_config


class ConfigMergeTests(unittest.TestCase):
    def test_build_target_config_enables_only_required_stack_without_clobbering_existing_values(self):
        existing = {
            "plugins": {"enabled": ["existing-plugin"]},
            "context": {"engine": "default", "keep": "value"},
            "memory": {"provider": "builtin", "memory_enabled": True, "custom": 42},
            "display": {"streaming": True},
        }

        merged = build_target_config(existing)

        self.assertEqual(
            merged["plugins"]["enabled"],
            ["existing-plugin", "hermes-lcm", "mnemosyne"],
        )
        self.assertEqual(merged["context"], {"engine": "lcm", "keep": "value"})
        self.assertEqual(merged["memory"]["provider"], "mnemosyne")
        self.assertIs(merged["memory"]["memory_enabled"], False)
        self.assertIs(merged["memory"]["user_profile_enabled"], False)
        self.assertEqual(merged["memory"]["custom"], 42)
        self.assertEqual(merged["memory"]["mnemosyne"]["vector_type"], "int8")
        self.assertEqual(merged["display"], {"streaming": True})

    def test_build_target_config_enables_memory_toolset_for_telegram(self):
        existing = {"platform_toolsets": {"telegram": ["file", "terminal"]}}

        merged = build_target_config(existing)

        self.assertEqual(merged["platform_toolsets"]["telegram"], ["file", "terminal", "memory"])

    def test_build_target_config_copies_cli_toolsets_when_telegram_missing(self):
        existing = {"platform_toolsets": {"cli": ["web", "file", "terminal"]}}

        merged = build_target_config(existing)

        self.assertEqual(
            merged["platform_toolsets"]["telegram"],
            ["web", "file", "terminal", "memory"],
        )
        self.assertEqual(merged["platform_toolsets"]["cli"], ["web", "file", "terminal"])

    def test_build_target_config_uses_top_level_toolsets_when_platform_cli_missing(self):
        existing = {"toolsets": ["web", "browser", "terminal"]}

        merged = build_target_config(existing)

        self.assertEqual(
            merged["platform_toolsets"]["telegram"],
            ["web", "browser", "terminal", "memory"],
        )

    def test_build_target_config_falls_back_to_full_cli_toolset_when_no_cli_toolsets_exist(self):
        merged = build_target_config({})

        self.assertEqual(merged["platform_toolsets"]["telegram"], ["hermes-cli", "memory"])

    def test_build_target_config_repairs_legacy_memory_only_telegram_toolset(self):
        existing = {
            "toolsets": ["web", "terminal"],
            "platform_toolsets": {"telegram": ["memory"]},
        }

        first = build_target_config(existing)
        second = build_target_config(first)

        self.assertEqual(second["platform_toolsets"]["telegram"], ["web", "terminal", "memory"])

    def test_build_target_config_keeps_existing_rich_telegram_toolset_idempotent(self):
        existing = {"platform_toolsets": {"telegram": ["file", "memory"]}}

        first = build_target_config(existing)
        second = build_target_config(first)

        self.assertEqual(second["platform_toolsets"]["telegram"], ["file", "memory"])

    def test_build_target_config_is_idempotent(self):
        existing = {
            "plugins": {"enabled": ["mnemosyne", "hermes-lcm"]},
            "context": {"engine": "lcm"},
            "memory": {
                "provider": "mnemosyne",
                "memory_enabled": False,
                "user_profile_enabled": False,
            },
        }

        first = build_target_config(existing)
        second = build_target_config(first)

        self.assertEqual(second, first)
        self.assertEqual(second["plugins"]["enabled"], ["mnemosyne", "hermes-lcm"])


if __name__ == "__main__":
    unittest.main()
