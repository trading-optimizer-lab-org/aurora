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


def test_launcher_accepts_no_path_or_arguments() -> None:
    assert _parameters(LAUNCHER) == set()
    source = LAUNCHER.read_text("utf-8")
    assert "OpenAI.Codex_2p2nqsd0c76g0" in source
    assert "CN=50BDFD77-8903-4850-9FFE-6E8522F64D5B" in source
    assert "AURORAAgent" in source
    assert "-Verb RunAs" not in source


def test_sandbox_persists_only_dpapi_protected_launcher_credential() -> None:
    source = SANDBOX.read_text("utf-8")
    assert "ConvertFrom-SecureString" in source
    assert "catalog-agent-credential.dpapi" in source
    assert "CatalogAgent\\profile\\config.toml" in source
    assert "SetEnvironmentVariable" not in source


def test_launcher_allows_hp_codex_only_alongside_protected_agent() -> None:
    source = LAUNCHER.read_text("utf-8")
    assert "BLOCKED_CATALOG_CODEX_HP_PROCESS_ACTIVE" not in source
    assert "Win32_Process" in source
    assert "GetOwner" in source
    assert "AURORAAgent" in source
    assert '$_.User -notin @($TargetIdentity, "HP")' in source
    assert 'Where-Object { $_.User -eq $TargetIdentity }' in source
    assert "CODEX_HOME" in source
    assert "GH_TOKEN" in source
