import unittest

from hermes_stack_bootstrap.env_template import build_env_values, managed_env_keys, merge_env_text, render_env_block


class EnvTemplateTests(unittest.TestCase):
    def test_build_env_values_defaults_to_full_local_mnemosyne_without_remote_api_secrets(self):
        values = build_env_values(
            home="/tmp/hermes",
            lcm_summary_model="lokal_sub2api/gpt-5.4-mini",
            lcm_expansion_model="lokal_sub2api/gpt-5.4-mini",
        )

        self.assertEqual(values["LCM_SUMMARY_MODEL"], "lokal_sub2api/gpt-5.4-mini")
        self.assertEqual(values["LCM_EXPANSION_MODEL"], "lokal_sub2api/gpt-5.4-mini")
        self.assertEqual(values["MNEMOSYNE_DATA_DIR"], "/tmp/hermes/mnemosyne/data")
        self.assertEqual(values["MNEMOSYNE_FORCE_LOCAL"], "1")
        self.assertEqual(values["MNEMOSYNE_EMBEDDING_MODEL"], "BAAI/bge-small-en-v1.5")
        self.assertEqual(values["MNEMOSYNE_EMBEDDING_DIM"], "384")
        self.assertEqual(values["MNEMOSYNE_LLM_ENABLED"], "true")
        self.assertEqual(values["MNEMOSYNE_LLM_MAX_TOKENS"], "2048")
        self.assertEqual(values["MNEMOSYNE_LLM_REPO"], "openbmb/MiniCPM5-1B-GGUF")
        self.assertEqual(values["MNEMOSYNE_LLM_FILE"], "MiniCPM5-1B-Q4_K_M.gguf")
        self.assertEqual(values["MNEMOSYNE_VEC_TYPE"], "int8")
        self.assertEqual(values["MNEMOSYNE_WM_MAX_ITEMS"], "10000")
        self.assertEqual(values["MNEMOSYNE_WM_TTL_HOURS"], "48")
        self.assertEqual(values["MNEMOSYNE_SLEEP_BATCH"], "3000")
        self.assertEqual(values["MNEMOSYNE_EP_LIMIT"], "50000")
        self.assertNotIn("MNEMOSYNE_HOST_LLM_ENABLED", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_URL", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_KEY", values)
        self.assertNotIn("MNEMOSYNE_LLM_API_KEY", values)
        self.assertNotIn("MNEMOSYNE_LLM_BASE_URL", values)

    def test_build_env_values_defaults_lcm_models_to_hermes_auxiliary(self):
        values = build_env_values(home="/tmp/hermes")

        self.assertNotIn("LCM_SUMMARY_MODEL", values)
        self.assertNotIn("LCM_EXPANSION_MODEL", values)

    def test_build_env_values_hybrid_uses_local_embeddings_and_hermes_host_llm(self):
        values = build_env_values(
            home="/tmp/hermes",
            mnemosyne_mode="hybrid",
            mnemosyne_host_llm_provider="openrouter",
            mnemosyne_host_llm_model="anthropic/claude-sonnet-4",
        )

        self.assertEqual(values["MNEMOSYNE_EMBEDDING_MODEL"], "BAAI/bge-small-en-v1.5")
        self.assertEqual(values["MNEMOSYNE_EMBEDDING_DIM"], "384")
        self.assertEqual(values["MNEMOSYNE_HOST_LLM_ENABLED"], "true")
        self.assertEqual(values["MNEMOSYNE_HOST_LLM_PROVIDER"], "openrouter")
        self.assertEqual(values["MNEMOSYNE_HOST_LLM_MODEL"], "anthropic/claude-sonnet-4")
        self.assertEqual(values["MNEMOSYNE_HOST_LLM_N_CTX"], "32000")
        self.assertNotIn("MNEMOSYNE_FORCE_LOCAL", values)
        self.assertNotIn("MNEMOSYNE_LLM_REPO", values)
        self.assertNotIn("MNEMOSYNE_LLM_FILE", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_KEY", values)

    def test_build_env_values_full_online_leaves_embeddings_for_user_and_uses_hermes_host_llm(self):
        values = build_env_values(
            home="/tmp/hermes",
            mnemosyne_mode="full-online",
            mnemosyne_host_llm_model="gpt-5.1-mini",
        )

        self.assertEqual(values["MNEMOSYNE_HOST_LLM_ENABLED"], "true")
        self.assertEqual(values["MNEMOSYNE_HOST_LLM_MODEL"], "gpt-5.1-mini")
        self.assertNotIn("MNEMOSYNE_EMBEDDING_MODEL", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_DIM", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_URL", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_KEY", values)
        self.assertNotIn("MNEMOSYNE_FORCE_LOCAL", values)
        self.assertNotIn("MNEMOSYNE_LLM_REPO", values)

    def test_build_env_values_accepts_lcm_model_overrides(self):
        values = build_env_values(
            home="/tmp/hermes",
            lcm_summary_model="custom/summary",
            lcm_expansion_model="custom/expansion",
        )

        self.assertEqual(values["LCM_SUMMARY_MODEL"], "custom/summary")
        self.assertEqual(values["LCM_EXPANSION_MODEL"], "custom/expansion")

    def test_build_env_values_accepts_legacy_summary_model_override(self):
        values = build_env_values(home="/tmp/hermes", summary_model="custom/gpt-mini")

        self.assertEqual(values["LCM_SUMMARY_MODEL"], "custom/gpt-mini")
        self.assertEqual(values["LCM_EXPANSION_MODEL"], "custom/gpt-mini")

    def test_render_env_block_is_stable_and_shell_style(self):
        block = render_env_block({"B": "two words", "A": "1"})

        self.assertEqual(block, 'A=1\nB="two words"\n')

    def test_merge_env_text_removes_managed_keys_that_are_not_in_selected_mode(self):
        existing = "\n".join(
            [
                "MNEMOSYNE_LLM_REPO=openbmb/MiniCPM5-1B-GGUF",
                "MNEMOSYNE_LLM_FILE=MiniCPM5-1B-Q4_K_M.gguf",
                "MNEMOSYNE_FORCE_LOCAL=1",
                "MNEMOSYNE_EMBEDDING_MODEL=text-embedding-3-small",
                "MNEMOSYNE_EMBEDDING_DIM=1536",
                "MNEMOSYNE_EMBEDDING_API_KEY=keep-user-secret",
                "UNRELATED=value",
            ]
        )
        values = build_env_values(home="/tmp/hermes", mnemosyne_mode="full-online")

        merged = merge_env_text(existing, values, managed_keys=managed_env_keys())

        self.assertNotIn("MNEMOSYNE_LLM_REPO=", merged)
        self.assertNotIn("MNEMOSYNE_LLM_FILE=", merged)
        self.assertNotIn("MNEMOSYNE_FORCE_LOCAL=", merged)
        self.assertIn("MNEMOSYNE_EMBEDDING_MODEL=text-embedding-3-small", merged)
        self.assertIn("MNEMOSYNE_EMBEDDING_DIM=1536", merged)
        self.assertIn("MNEMOSYNE_EMBEDDING_API_KEY=keep-user-secret", merged)
        self.assertIn("UNRELATED=value", merged)
        self.assertIn("MNEMOSYNE_HOST_LLM_ENABLED=true", merged)


if __name__ == "__main__":
    unittest.main()
