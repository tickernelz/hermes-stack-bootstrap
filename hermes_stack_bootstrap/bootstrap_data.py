"""Shared data types and constants for hermes-stack-bootstrap."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .env_template import DEFAULT_LCM_SUMMARY_MODEL
from .provider_setup import (
    HASHMICRO_BASE_URL,
    HASHMICRO_DEFAULT_REASONING_EFFORT,
    HASHMICRO_KEY_ENV,
    HASHMICRO_PROVIDER_NAME,
)
from .soul_generator import DEFAULT_SOUL_COMMUNICATION_STYLE, DEFAULT_SOUL_LANGUAGE

LCM_REPO = "https://github.com/stephenschoettler/hermes-lcm"
PROGRESS_TAIL_REPO = "tickernelz/hermes-progress-tail"
PROGRESS_TAIL_REF = os.environ.get("HERMES_STACK_PROGRESS_TAIL_REF", "latest")
LATEST_PROGRESS_TAIL_TAG_PLACEHOLDER = "${LATEST_HERMES_PROGRESS_TAIL_TAG}"
SUPERPOWERS_REPO = "https://github.com/obra/superpowers"
HMX_KNOWLEDGE_REPO = os.environ.get(
    "HMX_KNOWLEDGE_GIT_URL",
    "git@gitlab.com:hashmicro1/hmx/hmx-knowledge.git",
)
IMPECCABLE_REPO = "https://github.com/pbakaus/impeccable"
PONYTAIL_REPO = "https://github.com/DietrichGebert/ponytail"
REPO_ROOT_SKILL_INSTALL_MARKERS = (".git", "package.json", "skills")
SENSITIVE_ENV_KEYS = {"MNEMOSYNE_EMBEDDING_API_KEY", "XAI_HASHMICRO_API_KEY", "GITLAB_TOKEN"}
INSTALL_MODE_LABELS = {
    "full": "Full process",
    "plugin-skill-only": "Plugin & skill only",
    "soul-only": "Generate SOUL.md only",
}
INSTALL_MODE_VALUES = {label: mode for mode, label in INSTALL_MODE_LABELS.items()}
INSTALL_MODE_CHOICES = tuple(INSTALL_MODE_LABELS)


@dataclass(frozen=True)
class SkillPackSpec:
    name: str
    repo_url: str
    source_subdir: str = ""
    skill_name_prefix: str = ""
    body_token_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstallerOptions:
    base_home: Path
    profile: str
    hermes_bin: str = "hermes"
    hermes_bin_source: str = "default"
    hermes_python: Path | None = None
    hermes_python_source: str = "profile-local default"
    yes: bool = False
    dry_run: bool = False
    install_mode: str = "full"
    summary_model: str = ""
    lcm_summary_model: str = DEFAULT_LCM_SUMMARY_MODEL
    lcm_expansion_model: str = ""
    mnemosyne_mode: str = "hybrid"
    mnemosyne_host_llm_provider: str = ""
    mnemosyne_host_llm_model: str = ""
    mnemosyne_embedding_api_url: str = ""
    mnemosyne_embedding_api_key: str = ""
    mnemosyne_embedding_model: str = ""
    mnemosyne_embedding_dim: str = ""
    skip_lcm: bool = False
    skip_mnemosyne: bool = False
    skip_progress_tail: bool = False
    skip_config_env: bool = False
    skip_verify: bool = False
    progress_tail_ref: str = PROGRESS_TAIL_REF
    install_superpowers: bool = False
    install_hmx_knowledge: bool = False
    install_impeccable: bool = False
    install_ponytail: bool = False
    hmx_knowledge_url: str = HMX_KNOWLEDGE_REPO
    hmx_gitlab_token: str = ""
    setup_hashmicro_provider: bool = False
    hashmicro_base_url: str = HASHMICRO_BASE_URL
    hashmicro_provider_name: str = HASHMICRO_PROVIDER_NAME
    hashmicro_key_env: str = HASHMICRO_KEY_ENV
    hashmicro_api_key: str = ""
    hashmicro_main_model: str = ""
    hashmicro_main_context_length: int = 0
    hashmicro_delegation_model: str = ""
    hashmicro_delegation_context_length: int = 0
    hashmicro_auxiliary_models: Mapping[str, str] = dataclasses.field(default_factory=dict)
    hashmicro_auxiliary_context_lengths: Mapping[str, int] = dataclasses.field(default_factory=dict)
    hashmicro_reasoning_effort: str = ""
    hashmicro_available_models: Sequence[str] = dataclasses.field(default_factory=tuple)
    generate_soul: bool = False
    soul_agent_name: str = ""
    soul_user_name: str = ""
    soul_role: str = ""
    soul_behavior: str = ""
    soul_communication: str = DEFAULT_SOUL_COMMUNICATION_STYLE
    soul_focus: str = ""
    soul_avoid: str = ""
    soul_language: str = DEFAULT_SOUL_LANGUAGE
    soul_provider: str = ""
    soul_model: str = ""
    soul_overwrite: bool = False


@dataclass(frozen=True)
class PlanStep:
    title: str
    command: str = ""
    notes: str = ""


@dataclass(frozen=True)
class InstallPlan:
    options: InstallerOptions
    target_home: Path
    config_path: Path
    env_path: Path
    steps: tuple[PlanStep, ...]


SUPERPOWERS_SKILL_TOKENS = (
    "brainstorming",
    "dispatching-parallel-agents",
    "executing-plans",
    "finishing-a-development-branch",
    "receiving-code-review",
    "requesting-code-review",
    "subagent-driven-development",
    "systematic-debugging",
    "test-driven-development",
    "using-git-worktrees",
    "using-superpowers",
    "verification-before-completion",
    "writing-plans",
    "writing-skills",
)
SUPERPOWERS_SKILL_PACK = SkillPackSpec(
    name="obra-superpowers",
    repo_url=SUPERPOWERS_REPO,
    source_subdir="skills",
    skill_name_prefix="superpowers-",
    body_token_prefixes=SUPERPOWERS_SKILL_TOKENS,
)
HMX_KNOWLEDGE_SKILL_PACK = SkillPackSpec(name="hmx-knowledge", repo_url=HMX_KNOWLEDGE_REPO, source_subdir="skills")
IMPECCABLE_SKILL_PACK = SkillPackSpec(name="impeccable", repo_url=IMPECCABLE_REPO, source_subdir="plugin/skills")
PONYTAIL_SKILL_PACK = SkillPackSpec(name="ponytail", repo_url=PONYTAIL_REPO, source_subdir="skills")
