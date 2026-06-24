import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


class InstallShellTests(unittest.TestCase):
    def make_fake_python(self, root: Path, log: Path) -> Path:
        runtime = root / "fake-python"
        runtime.write_text(
            textwrap.dedent(
                f"""\
#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "-c" ]]; then
  printf 'deps-fingerprint\n'
  exit 0
fi
printf 'runtime %s\\n' "$*" >> {log}
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "venv" ]]; then
  venv_dir="${{3:?}}"
  mkdir -p "$venv_dir/bin"
  cat > "$venv_dir/bin/python" <<'PY'
#!/usr/bin/env bash
set -euo pipefail
printf 'bootstrap %s\\n' "$*" >> {log}
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "pip" ]]; then
  printf 'pip-virtual-env=%s\\n' "${{VIRTUAL_ENV:-}}" >> {log}
  printf 'pip-pythonpath=%s\\n' "${{PYTHONPATH:-}}" >> {log}
  printf 'pip-version-check=%s\\n' "${{PIP_DISABLE_PIP_VERSION_CHECK:-}}" >> {log}
  printf 'pip-install\\n' >> {log}
  exit 0
fi
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "hermes_stack_bootstrap" ]]; then
  printf 'module-run\\n' >> {log}
  exit 0
fi
exit 0
PY
  chmod +x "$venv_dir/bin/python"
  exit 0
fi
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "hermes_stack_bootstrap" ]]; then
  printf 'module-run-runtime\\n' >> {log}
  exit 0
fi
exit 0
"""
            ),
            encoding="utf-8",
        )
        runtime.chmod(0o755)
        return runtime

    def run_installer(self, tmp: Path, log: Path, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        runtime = self.make_fake_python(tmp, log)
        source = tmp / "source"
        source.mkdir(exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "HERMES_STACK_SOURCE_DIR": str(source),
                "HERMES_STACK_PYTHON": str(runtime),
                "HERMES_BIN": "/bin/true",
                "HERMES_HOME": str(tmp / "hermes-home"),
                "HERMES_STACK_BOOTSTRAP_CACHE_DIR": str(tmp / "cache"),
                "PYTHONPATH": "/should/not/leak",
            }
        )
        return subprocess.run(
            ["bash", str(INSTALL_SH), *(args or [])],
            cwd=tmp,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )

    def test_interactive_bootstrap_reuses_cached_installer_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log = tmp / "calls.log"

            self.run_installer(tmp, log)
            self.run_installer(tmp, log)

            lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("pip-install"), 1)
        self.assertIn(str(tmp / "cache" / "bootstrap-venv-py-unknown"), "\n".join(line for line in lines if line.startswith("pip-virtual-env=")))
        self.assertIn("pip-pythonpath=", lines)
        self.assertIn("pip-version-check=1", lines)
        self.assertEqual(len([line for line in lines if line.startswith("runtime -m venv")]), 1)
        self.assertEqual(lines.count("module-run"), 2)

    def test_recreate_flag_forces_cached_installer_venv_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log = tmp / "calls.log"

            self.run_installer(tmp, log)
            env_extra = {"HERMES_STACK_RECREATE_BOOTSTRAP_VENV": "1"}
            original_environ = os.environ.copy()
            try:
                os.environ.update(env_extra)
                self.run_installer(tmp, log)
            finally:
                os.environ.clear()
                os.environ.update(original_environ)

            lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("pip-install"), 2)
        self.assertEqual(len([line for line in lines if line.startswith("runtime -m venv")]), 2)

    def test_stale_dependency_marker_recreates_cached_installer_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log = tmp / "calls.log"

            self.run_installer(tmp, log)
            marker = tmp / "cache" / "bootstrap-venv-py-unknown" / ".hermes-stack-bootstrap-deps.sha256"
            marker.write_text("stale", encoding="utf-8")
            self.run_installer(tmp, log)

            lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("pip-install"), 2)
        self.assertEqual(len([line for line in lines if line.startswith("runtime -m venv")]), 2)

    def test_corrupt_cached_installer_venv_is_recreated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log = tmp / "calls.log"

            self.run_installer(tmp, log)
            cached_python = tmp / "cache" / "bootstrap-venv-py-unknown" / "bin" / "python"
            cached_python.unlink()
            self.run_installer(tmp, log)

            lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("pip-install"), 2)
        self.assertEqual(len([line for line in lines if line.startswith("runtime -m venv")]), 2)

    def test_noninteractive_yes_dry_run_skips_bootstrap_dependency_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log = tmp / "calls.log"

            self.run_installer(tmp, log, ["--yes", "--dry-run"])

            lines = log.read_text(encoding="utf-8").splitlines()
        self.assertNotIn("pip-install", lines)
        self.assertFalse(any(line.startswith("runtime -m venv") for line in lines))
        self.assertIn("module-run-runtime", lines)


if __name__ == "__main__":
    unittest.main()
