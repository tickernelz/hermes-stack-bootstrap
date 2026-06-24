import tempfile
import unittest
from pathlib import Path

from scripts.check_file_line_limit import check_paths


class MaxFileLinesTests(unittest.TestCase):
    def test_allows_file_at_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.py"
            path.write_text("\n".join(str(i) for i in range(600)) + "\n", encoding="utf-8")

            self.assertEqual(check_paths([path], max_lines=600), [])

    def test_reports_files_over_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "too_big.py"
            path.write_text("\n".join(str(i) for i in range(601)) + "\n", encoding="utf-8")

            violations = check_paths([path], max_lines=600)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].path, path)
        self.assertEqual(violations[0].lines, 601)
        self.assertEqual(violations[0].max_lines, 600)

    def test_skips_binary_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "image.png"
            binary.write_bytes(b"\x89PNG\x00\xff")
            missing = Path(tmp) / "missing.py"

            self.assertEqual(check_paths([binary, missing], max_lines=600), [])


if __name__ == "__main__":
    unittest.main()
