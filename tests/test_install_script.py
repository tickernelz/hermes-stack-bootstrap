import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InstallScriptTests(unittest.TestCase):
    def test_curl_pipe_bootstrap_uses_python_from_env_shebang_not_usr_bin_env(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli_bin = root / "cli-bin"
            runtime_bin = root / "runtime-bin"
            cli_bin.mkdir()
            runtime_bin.mkdir()
            system_python = shutil.which("python3") or sys.executable
            fake_python = runtime_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  -m) exec \"" + system_python + "\" \"$@\" ;;\n"
                "  *) exec \"" + system_python + "\" \"$@\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            hermes = cli_bin / "hermes"
            hermes.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "if sys.argv[1:] == ['config', 'path']:\n"
                "    print('" + str(root / "home" / ".hermes" / "config.yaml") + "')\n"
                "else:\n"
                "    print('fake hermes')\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)

            env = os.environ.copy()
            env.pop("HERMES_BIN", None)
            env.pop("HERMES_STACK_PYTHON", None)
            env.pop("HERMES_HOME", None)
            env["PATH"] = str(cli_bin) + os.pathsep + str(runtime_bin) + os.pathsep + env.get("PATH", "")
            env["HOME"] = str(root / "home")
            env["HERMES_STACK_SOURCE_DIR"] = str(project_root)

            completed = subprocess.run(
                [
                    "bash",
                    str(project_root / "install.sh"),
                    "--dry-run",
                    "--yes",
                    "--skip-lcm",
                    "--skip-mnemosyne",
                    "--skip-progress-tail",
                ],
                env=env,
                cwd=project_root,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                msg=f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}",
            )
            self.assertNotIn("/usr/bin/env: invalid option", completed.stderr)
            self.assertIn(f"Hermes Python       : {fake_python}", completed.stdout)


if __name__ == "__main__":
    unittest.main()
