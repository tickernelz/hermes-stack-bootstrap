import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

SECRET_VALUES = ("sk-xxx", "glpat-secret-token", "hmx-secret-key", "embed-secret-key")


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def make_fakebin(tmp: Path, hermes_home: Path) -> Path:
    fakebin = tmp / "fakebin"
    fakebin.mkdir()
    write_executable(
        fakebin / "hermes",
        f"""#!/usr/bin/env sh
if [ "$1" = "config" ] && [ "$2" = "path" ]; then
  printf '%s\n' '{hermes_home}/config.yaml'
  exit 0
fi
if [ "$1" = "chat" ]; then
  printf '%s\n' '# Test Agent SOUL'
  exit 0
fi
printf '%s\n' "fake hermes $*"
""",
    )
    write_executable(
        fakebin / "curl",
        """#!/usr/bin/env sh
printf '%s\n' '#!/usr/bin/env sh'
printf '%s\n' 'mkdir -p "$HERMES_HOME/progress-tail-installed"'
printf '%s\n' 'exit 0'
""",
    )
    write_executable(
        fakebin / "git",
        """#!/usr/bin/env python3
import pathlib, sys
args = sys.argv[1:]
if args[:3] == ['ls-remote', '--tags', '--refs']:
    print('abc123\\trefs/tags/v9.9.9')
    sys.exit(0)
if 'clone' in args:
    dest = pathlib.Path(args[-1])
    dest.mkdir(parents=True, exist_ok=True)
    url = args[-2] if len(args) >= 2 else ''
    if 'superpowers' in url:
        skill = dest / 'skills' / 'brainstorming'
        skill.mkdir(parents=True, exist_ok=True)
        (skill / 'SKILL.md').write_text('---\\nname: brainstorming\\n---\\n', encoding='utf-8')
    elif 'hmx' in url or 'gitlab.com' in url:
        skill = dest / 'skills' / 'hmx'
        skill.mkdir(parents=True, exist_ok=True)
        (skill / 'SKILL.md').write_text('---\\nname: hmx\\n---\\n', encoding='utf-8')
    elif 'impeccable' in url:
        skill = dest / 'plugin' / 'skills' / 'impeccable'
        skill.mkdir(parents=True, exist_ok=True)
        (skill / 'SKILL.md').write_text('---\\nname: impeccable\\n---\\n', encoding='utf-8')
    elif 'ponytail' in url:
        skill = dest / 'skills' / 'ponytail'
        skill.mkdir(parents=True, exist_ok=True)
        (skill / 'SKILL.md').write_text('---\\nname: ponytail\\n---\\n', encoding='utf-8')
    sys.exit(0)
if '-C' in args and 'pull' in args:
    sys.exit(0)
sys.exit(0)
""",
    )
    return fakebin


def run_installer(
    hermes_home: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    fakebin = make_fakebin(hermes_home.parent, hermes_home)
    env = os.environ.copy()
    env.update(
        {
            "HERMES_STACK_SOURCE_DIR": str(REPO_ROOT),
            "HERMES_STACK_PYTHON": str(PYTHON),
            "HERMES_BIN": str(fakebin / "hermes"),
            "HERMES_HOME": str(hermes_home),
            "HERMES_STACK_SKIP_BOOTSTRAP_DEPS": "1",
            "PATH": f"{fakebin}:{env.get('PATH', '')}",
            "GITLAB_TOKEN": "glpat-secret-token",
            "XAI_HASHMICRO_API_KEY": "hmx-secret-key",
            "MNEMOSYNE_EMBEDDING_API_KEY": "embed-secret-key",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", "install.sh", "--yes", "--home", str(hermes_home), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def assert_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def assert_no_secret_leak(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    for secret in SECRET_VALUES:
        assert secret not in combined


def test_full_install_dry_run_all_components_reports_actions_and_redacts_secrets():
    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir(parents=True)
        (hermes_home / "config.yaml").write_text("plugins:\n  enabled: []\n", encoding="utf-8")
        (hermes_home / ".env").write_text("EXISTING=1\n", encoding="utf-8")

        # Skip Mnemosyne since no Hermes Python available in test env
        result = run_installer(hermes_home, "--dry-run", "--skip-mnemosyne", "--install-superpowers", "--install-ponytail")

        assert_success(result)
        assert "Dry run        : True" in result.stdout
        assert "DRY-RUN" in result.stdout
        assert "git clone https://github.com/stephenschoettler/hermes-lcm" in result.stdout
        # Mnemosyne skipped, so no pip install expected
        assert "hermes-lcm" in result.stdout
        assert "progress-tail" in result.stdout
        # Verify actual secret values are not leaked (env var names like XAI_HASHMICRO_API_KEY are OK)
        assert "hmx-secret-key" not in result.stdout
        assert "sk-xxx" not in result.stdout
        assert "glpat-secret-token" not in result.stdout
        assert "embed-secret-key" not in result.stdout
        assert_no_secret_leak(result)


def test_apply_config_env_creates_backups_and_writes_expected_state_with_external_steps_skipped():
    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir(parents=True)
        (hermes_home / "config.yaml").write_text("plugins:\n  enabled:\n    - old\n", encoding="utf-8")
        (hermes_home / ".env").write_text("OLD=1\n", encoding="utf-8")

        result = run_installer(
            hermes_home,
            "--skip-lcm",
            "--skip-mnemosyne",
            "--skip-progress-tail",
            "--skip-verify",
        )

        assert_success(result)
        backups = list((hermes_home / "backups").glob("hermes-stack-bootstrap-*"))
        assert len(backups) == 1
        assert (backups[0] / "config.yaml").exists()
        assert (backups[0] / ".env").exists()
        config = (hermes_home / "config.yaml").read_text(encoding="utf-8")
        env_text = (hermes_home / ".env").read_text(encoding="utf-8")
        assert "hermes-lcm" in config
        assert "mnemosyne" in config
        assert "LCM_CONTEXT_THRESHOLD=0.8" in env_text
        assert "MNEMOSYNE_VEC_TYPE=int8" in env_text
        assert_no_secret_leak(result)


def test_plugin_skill_only_mode_stages_optional_skills_but_skips_config_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir(parents=True)
        (hermes_home / "config.yaml").write_text("unchanged: true\n", encoding="utf-8")

        result = run_installer(
            hermes_home,
            "--install-mode",
            "plugin-skill-only",
            "--install-superpowers",
            "--install-ponytail",
            "--skip-verify",
        )

        assert_success(result)
        assert "Config/.env merge skipped" in result.stdout
        assert (
            hermes_home / "skills" / "vendor" / "obra-superpowers" / "superpowers-brainstorming" / "SKILL.md"
        ).exists()
        assert (hermes_home / "skills" / "vendor" / "ponytail" / "ponytail" / "SKILL.md").exists()
        assert (hermes_home / "config.yaml").read_text(encoding="utf-8") == "unchanged: true\n"
        assert_no_secret_leak(result)


def test_soul_only_mode_dry_run_skips_stack_and_does_not_write_soul():
    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir(parents=True)

        result = run_installer(
            hermes_home,
            "--dry-run",
            "--install-mode",
            "soul-only",
            "--soul-agent-name",
            "Hermes",
            "--soul-user-name",
            "User",
        )

        assert_success(result)
        assert "Install mode   : Generate SOUL.md only" in result.stdout
        assert "DRY-RUN would generate SOUL.md" in result.stdout
        assert "git clone https://github.com/stephenschoettler/hermes-lcm" not in result.stdout
        assert not (hermes_home / "SOUL.md").exists()
        assert_no_secret_leak(result)


def test_hashmicro_provider_setup_dry_run_writes_provider_preview_without_key_leak():
    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir(parents=True)

        result = run_installer(
            hermes_home,
            "--dry-run",
            "--skip-lcm",
            "--skip-mnemosyne",
            "--skip-progress-tail",
            "--skip-verify",
            "--setup-hashmicro-provider",
            "--main-model",
            "gpt-5.5",
            "--delegation-model",
            "gpt-5.5-mini",
            "--aux-all-model",
            "gpt-5.5-nano",
        )

        assert_success(result)
        assert "xai-hashmicro" in result.stdout
        assert "https://xai.hashmicro.co/v1" in result.stdout
        assert "XAI_HASHMICRO_API_KEY" in result.stdout
        assert "<redacted>" in result.stdout
        assert "hmx-secret-key" not in result.stdout
        assert_no_secret_leak(result)


def test_optional_skill_packs_are_staged_from_fake_git_repositories():
    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir(parents=True)

        result = run_installer(
            hermes_home,
            "--install-mode",
            "plugin-skill-only",
            "--install-superpowers",
            "--install-hmx-knowledge",
            "--install-impeccable",
            "--install-ponytail",
            "--skip-verify",
        )

        assert_success(result)
        assert (
            hermes_home / "skills" / "vendor" / "obra-superpowers" / "superpowers-brainstorming" / "SKILL.md"
        ).exists()
        assert (hermes_home / "skills" / "vendor" / "hmx-knowledge" / "hmx" / "SKILL.md").exists()
        assert (hermes_home / "skills" / "vendor" / "impeccable" / "impeccable" / "SKILL.md").exists()
        assert (hermes_home / "skills" / "vendor" / "ponytail" / "ponytail" / "SKILL.md").exists()
        assert_no_secret_leak(result)
