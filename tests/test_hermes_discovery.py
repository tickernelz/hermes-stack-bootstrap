import os
import stat
import tempfile
import unittest
from pathlib import Path

from hermes_stack_bootstrap.hermes_discovery import (
    discover_hermes_runtime,
    find_hermes_bins_from_path,
    infer_python_from_hermes_bin,
    scan_filesystem_for_hermes,
)


class HermesDiscoveryTests(unittest.TestCase):
    def make_executable(self, path: Path, content: str = "#!/bin/sh\nexit 0\n") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_find_hermes_bins_from_path_collects_all_path_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.make_executable(root / "one" / "hermes")
            second = self.make_executable(root / "two" / "hermes")
            env = {"PATH": os.pathsep.join([str(first.parent), str(second.parent)])}

            self.assertEqual(find_hermes_bins_from_path(env=env), [first, second])

    def test_infer_python_from_realpath_sibling_venv_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_bin = root / "shared" / "runtime" / "venv" / "bin"
            hermes = self.make_executable(real_bin / "hermes")
            python = self.make_executable(real_bin / "python")
            link_dir = root / "usr" / "local" / "bin"
            link_dir.mkdir(parents=True)
            symlink = link_dir / "hermes"
            symlink.symlink_to(hermes)

            self.assertEqual(infer_python_from_hermes_bin(symlink), python)

    def test_infer_python_from_bash_launcher_exec_target_sibling_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_bin = root / "hermes-agent" / "venv" / "bin"
            runtime_hermes = self.make_executable(runtime_bin / "hermes", "#!/usr/bin/env python3\nprint('real hermes')\n")
            python = self.make_executable(runtime_bin / "python")
            wrapper = self.make_executable(
                root / ".local" / "bin" / "hermes",
                f"#!/usr/bin/env bash\nunset PYTHONPATH\nexec \"{runtime_hermes}\" \"$@\"\n",
            )

            self.assertEqual(infer_python_from_hermes_bin(wrapper), python)

    def test_infer_python_from_bash_launcher_exec_target_env_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_bin = root / "apps" / "hermes" / "venv" / "bin"
            runtime_hermes = self.make_executable(runtime_bin / "hermes", "#!/usr/bin/env python3\nprint('real hermes')\n")
            python = self.make_executable(runtime_bin / "python3")
            wrapper = self.make_executable(
                root / "bin" / "hermes",
                f"#!/bin/sh\nHERMES_HOME=/home/lutfi22/.hermes exec {runtime_hermes} \"$@\"\n",
            )

            self.assertEqual(infer_python_from_hermes_bin(wrapper), python)

    def test_infer_python_from_absolute_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = self.make_executable(root / "runtime" / "python")
            hermes = self.make_executable(root / "bin" / "hermes", f"#!{python}\nprint('ok')\n")

            self.assertEqual(infer_python_from_hermes_bin(hermes), python)

    def test_infer_python_from_env_shebang_uses_python_not_env_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli_bin = root / "cli-bin"
            runtime_bin = root / "runtime-bin"
            hermes = self.make_executable(cli_bin / "hermes", "#!/usr/bin/env python3\nprint('ok')\n")
            python = self.make_executable(runtime_bin / "python3")
            env = {"PATH": os.pathsep.join([str(cli_bin), str(runtime_bin)])}

            self.assertEqual(infer_python_from_hermes_bin(hermes, env=env), python)

    def test_infer_python_from_env_shebang_supports_env_s_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = self.make_executable(root / "cli" / "hermes", "#!/usr/bin/env -S python3 -u\nprint('ok')\n")
            python = self.make_executable(root / "runtime" / "python3")
            env = {"PATH": os.pathsep.join([str(hermes.parent), str(python.parent)])}

            self.assertEqual(infer_python_from_hermes_bin(hermes, env=env), python)

    def test_infer_python_from_env_shebang_ignores_non_python_utility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = self.make_executable(root / "cli" / "hermes", "#!/usr/bin/env bash\necho ok\n")
            bash = self.make_executable(root / "runtime" / "bash")
            env = {"PATH": os.pathsep.join([str(hermes.parent), str(bash.parent)])}

            self.assertIsNone(infer_python_from_hermes_bin(hermes, env=env))

    def test_infer_python_from_absolute_shebang_ignores_non_python_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bash = self.make_executable(root / "runtime" / "bash")
            hermes = self.make_executable(root / "cli" / "hermes", f"#!{bash}\necho ok\n")

            self.assertIsNone(infer_python_from_hermes_bin(hermes))

    def test_bounded_filesystem_scan_finds_nested_hermes_without_opt_assumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = self.make_executable(root / "srv" / "shared" / "apps" / "hermes" / "current" / "bin" / "hermes")

            matches = scan_filesystem_for_hermes(roots=[root], deadline_seconds=1.0, max_results=5)

            self.assertIn(hermes, matches)

    def test_discover_runtime_uses_overrides_before_path_or_filesystem_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = self.make_executable(root / "custom" / "bin" / "hermes")
            python = self.make_executable(root / "custom" / "venv" / "bin" / "python")

            runtime = discover_hermes_runtime(
                base_home=Path("/home/lutfi22/.hermes"),
                hermes_bin=str(hermes),
                hermes_python=str(python),
                env={"PATH": ""},
                scan_filesystem=False,
            )

            self.assertEqual(runtime.hermes_bin, str(hermes))
            self.assertEqual(runtime.hermes_python, python)
            self.assertEqual(runtime.hermes_bin_source, "explicit")
            self.assertEqual(runtime.hermes_python_source, "explicit")


if __name__ == "__main__":
    unittest.main()
