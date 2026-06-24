import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_stack_bootstrap.bootstrap_utils import atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_text_writes_tmp_then_replaces_target(self):
        target = Path("/tmp/hermes/config.yaml")
        calls = []

        def fake_write_text(self, text, encoding=None):
            calls.append(("write_text", self, text, encoding))
            return len(text)

        def fake_replace(self, destination):
            calls.append(("replace", self, destination))
            return destination

        with (
            patch.object(Path, "mkdir") as mkdir,
            patch.object(Path, "write_text", fake_write_text),
            patch.object(Path, "replace", fake_replace),
        ):
            atomic_write_text(target, "content", encoding="utf-8")

        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        self.assertEqual(
            calls,
            [
                ("write_text", Path("/tmp/hermes/config.tmp"), "content", "utf-8"),
                ("replace", Path("/tmp/hermes/config.tmp"), target),
            ],
        )

    def test_atomic_write_text_replaces_file_on_disk_and_removes_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".env"
            target.write_text("old\n", encoding="utf-8")

            atomic_write_text(target, "new\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertFalse((Path(tmp) / ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
