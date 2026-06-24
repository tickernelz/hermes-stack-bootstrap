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
                'case "$1" in\n'
                '  -m) exec "' + system_python + '" "$@" ;;\n'
                '  *) exec "' + system_python + '" "$@" ;;\n'
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

    def test_interactive_bootstrap_installs_tui_dependencies_in_temp_venv_not_runtime(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli_bin = root / "cli-bin"
            runtime_bin = root / "runtime-bin"
            cli_bin.mkdir()
            runtime_bin.mkdir()
            runtime_log = root / "runtime-python.log"
            bootstrap_log = root / "bootstrap-python.log"
            fake_python = runtime_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                f"RUNTIME_LOG={str(runtime_log)!r}\n"
                f"BOOTSTRAP_LOG={str(bootstrap_log)!r}\n"
                'if [ "$1" = "-c" ]; then echo deps-fingerprint; exit 0; fi\n'
                'printf \'%s\\n\' "runtime:$*" >> "$RUNTIME_LOG"\n'
                'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then echo \'runtime pip must not run\' >&2; exit 88; fi\n'
                'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
                '  venv_dir="$3"\n'
                '  mkdir -p "$venv_dir/bin"\n'
                '  cat > "$venv_dir/bin/python" <<EOF\n'
                "#!/bin/sh\n"
                f"BOOTSTRAP_LOG={str(bootstrap_log)!r}\n"
                'printf \'%s\\n\' "bootstrap:\\$*" >> "\\$BOOTSTRAP_LOG"\n'
                'if [ "\\$1" = "-m" ] && [ "\\$2" = "pip" ]; then exit 0; fi\n'
                'if [ "\\$1" = "-m" ] && [ "\\$2" = "hermes_stack_bootstrap" ]; then exit 0; fi\n'
                "exit 64\n"
                "EOF\n"
                '  chmod +x "$venv_dir/bin/python"\n'
                "  exit 0\n"
                "fi\n"
                "exit 64\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            hermes = cli_bin / "hermes"
            hermes.write_text(
                "#!/bin/sh\n"
                'if [ "$1 $2" = "config path" ]; then echo \''
                + str(root / "home" / ".hermes" / "config.yaml")
                + "'; fi\n",
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

            self.assertEqual(completed.returncode, 0, msg=f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
            runtime_log_text = runtime_log.read_text(encoding="utf-8")
            bootstrap_log_text = bootstrap_log.read_text(encoding="utf-8")
            self.assertIn("runtime:-m venv", runtime_log_text)
            self.assertNotIn("runtime:-m pip install", runtime_log_text)
            self.assertIn("bootstrap:-m pip install", bootstrap_log_text)
            self.assertIn("PyYAML>=6", bootstrap_log_text)
            self.assertIn("rich>=13", bootstrap_log_text)
            self.assertIn("prompt_toolkit>=3", bootstrap_log_text)
            self.assertIn("bootstrap:-m hermes_stack_bootstrap", bootstrap_log_text)
            self.assertLess(
                bootstrap_log_text.index("bootstrap:-m pip install"),
                bootstrap_log_text.index("bootstrap:-m hermes_stack_bootstrap"),
            )

    def test_interactive_bootstrap_reports_clear_tui_dependency_install_failure(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_bin = root / "runtime-bin"
            runtime_bin.mkdir()
            fake_python = runtime_bin / "python3"
            log_path = root / "bootstrap-python.log"
            fake_python.write_text(
                "#!/bin/sh\n"
                f"LOG={str(log_path)!r}\n"
                'if [ "$1" = "-c" ]; then echo deps-fingerprint; exit 0; fi\n'
                'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
                '  venv_dir="$3"\n'
                '  mkdir -p "$venv_dir/bin"\n'
                '  cat > "$venv_dir/bin/python" <<EOF\n'
                "#!/bin/sh\n"
                f"LOG={str(log_path)!r}\n"
                'printf \'%s\\n\' "bootstrap:\\$*" >> "\\$LOG"\n'
                'if [ "\\$1" = "-m" ] && [ "\\$2" = "pip" ]; then echo \'pip exploded\' >&2; exit 23; fi\n'
                "exit 64\n"
                "EOF\n"
                '  chmod +x "$venv_dir/bin/python"\n'
                "  exit 0\n"
                "fi\n"
                "exit 64\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            env = os.environ.copy()
            env["HERMES_STACK_PYTHON"] = str(fake_python)
            env["HERMES_STACK_SOURCE_DIR"] = str(project_root)
            env["HOME"] = str(root / "home")

            completed = subprocess.run(
                ["bash", str(project_root / "install.sh"), "--dry-run"],
                env=env,
                cwd=project_root,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Failed to install TUI bootstrap dependencies", completed.stderr)
            self.assertIn(str(fake_python), completed.stderr)
            self.assertIn("-m pip install", completed.stderr)

    def test_source_dir_bootstrap_exits_after_local_run_without_archive_download(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_python = root / "python3"
            log_path = root / "python.log"
            fake_python.write_text(
                "#!/bin/sh\n"
                f"LOG={str(log_path)!r}\n"
                'printf \'%s\\n\' "$*" >> "$LOG"\n'
                'if [ "$1" = "-m" ] && [ "$2" = "hermes_stack_bootstrap" ]; then exit 0; fi\n'
                "exit 64\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            env = os.environ.copy()
            env["HERMES_STACK_SOURCE_DIR"] = str(project_root)
            env["HERMES_STACK_PYTHON"] = str(fake_python)
            env["HERMES_STACK_REPO"] = "invalid/should-not-download"
            env["HOME"] = str(root / "home")

            completed = subprocess.run(
                ["bash", str(project_root / "install.sh"), "--yes", "--dry-run"],
                env=env,
                cwd=project_root,
                text=True,
                capture_output=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, msg=f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
            self.assertIn("-m hermes_stack_bootstrap", log_path.read_text(encoding="utf-8"))
            self.assertNotIn("Downloading hermes-stack-bootstrap", completed.stdout)


if __name__ == "__main__":
    unittest.main()
