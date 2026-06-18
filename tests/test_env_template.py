import unittest

from hermes_stack_bootstrap.env_template import build_env_values, render_env_block


class EnvTemplateTests(unittest.TestCase):
    def test_build_env_values_defaults_to_local_mnemosyne_without_remote_api_secrets(self):
        values = build_env_values(home="/tmp/hermes")

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
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_URL", values)
        self.assertNotIn("MNEMOSYNE_EMBEDDING_API_KEY", values)
        self.assertNotIn("MNEMOSYNE_LLM_API_KEY", values)
        self.assertNotIn("MNEMOSYNE_LLM_BASE_URL", values)

    def test_build_env_values_accepts_summary_model_override(self):
        values = build_env_values(home="/tmp/hermes", summary_model="custom/gpt-mini")

        self.assertEqual(values["LCM_SUMMARY_MODEL"], "custom/gpt-mini")
        self.assertEqual(values["LCM_EXPANSION_MODEL"], "custom/gpt-mini")

    def test_render_env_block_is_stable_and_shell_style(self):
        block = render_env_block({"B": "two words", "A": "1"})

        self.assertEqual(block, 'A=1\nB="two words"\n')


if __name__ == "__main__":
    unittest.main()
