from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config/catalog_agent_codex_profile_v1.toml"
LAUNCHER = ROOT / "scripts/launch_catalog_codex_secure.ps1"
SANDBOX = ROOT / "scripts/install_catalog_agent_sandbox.ps1"


def _parameters(path: Path) -> set[str]:
    source = path.read_text("utf-8")
    block = re.search(r"(?s)param\((.*?)\)\s*Set-StrictMode", source)
    assert block
    return set(re.findall(r"\$(\w+)", block.group(1)))


def test_profile_disables_privileged_plugins() -> None:
    profile = tomllib.loads(PROFILE.read_text("utf-8"))
    for name in (
        "chrome@openai-bundled",
        "browser@openai-bundled",
        "computer-use@openai-bundled",
        "codex-app-tools@openai-bundled",
    ):
        assert profile["plugins"][name]["enabled"] is False
    assert "mcp_servers" not in profile
    assert "notify" not in profile
    assert profile["agents"] == {"max_threads": 1, "max_depth": 1}
