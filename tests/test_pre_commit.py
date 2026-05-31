"""Pre-commit configuration sanity tests.

Verify .pre-commit-config.yaml exists at the repository root and is valid YAML.
Skips gracefully if PyYAML isn't installed.

Run: pytest aurora/tests/test_pre_commit.py -v
"""
from __future__ import annotations
from pathlib import Path
import pytest


# Repo root: this file is at <repo>/tests/test_pre_commit.py
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"


def test_pre_commit_config_exists():
    """The .pre-commit-config.yaml must exist at the repo root."""
    assert CONFIG_PATH.exists(), (
        f".pre-commit-config.yaml missing at expected location: {CONFIG_PATH}"
    )
    assert CONFIG_PATH.is_file(), f"{CONFIG_PATH} is not a regular file"


def test_pre_commit_config_parses_as_yaml():
    """The .pre-commit-config.yaml must be valid YAML."""
    yaml = pytest.importorskip("yaml")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"top-level YAML not a mapping: {type(data)}"
    assert "repos" in data, "missing 'repos' key in pre-commit config"
    assert isinstance(data["repos"], list), "'repos' must be a list"
    assert len(data["repos"]) >= 1, "'repos' list is empty"


def test_pre_commit_config_has_standard_hooks():
    """Config should reference the standard pre-commit-hooks repo and ruff."""
    yaml = pytest.importorskip("yaml")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    repo_urls = [r.get("repo", "") for r in data["repos"]]
    assert any("pre-commit/pre-commit-hooks" in url for url in repo_urls), (
        "expected pre-commit/pre-commit-hooks in repos list"
    )
    assert any("ruff" in url for url in repo_urls), (
        "expected ruff (astral-sh/ruff-pre-commit) in repos list"
    )

    # Sanity: each repo block has hooks list
    for r in data["repos"]:
        assert "hooks" in r, f"repo block missing 'hooks': {r}"
        assert isinstance(r["hooks"], list), "'hooks' must be a list"
        assert len(r["hooks"]) >= 1, f"empty hooks list for repo {r.get('repo')}"
        for h in r["hooks"]:
            assert "id" in h, f"hook missing 'id': {h}"
