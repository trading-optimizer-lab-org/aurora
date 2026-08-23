from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_catalog_bootstrap_assistant.ps1"
STARTER = ROOT / "scripts/start_catalog_bootstrap_assistant.ps1"
QUALIFICATION_CLIENT = ROOT / "scripts/run_catalog_bootstrap_qualification_client.ps1"
CAPABILITY_AUDIT = ROOT / "scripts/audit_catalog_agent_capabilities.ps1"


def _parameters(path: Path) -> set[str]:
    source = path.read_text("utf-8")
    block = re.search(r"(?s)param\((.*?)\)\s*Set-StrictMode", source)
    assert block
    return set(re.findall(r"\$(\w+)", block.group(1)))


def test_installer_is_nonmutating_by_default() -> None:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(INSTALLER)],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["mode"] == "dry_run"
    assert receipt["mutation_performed"] is False
    assert receipt["production_enabled"] is False


def test_no_secret_or_arbitrary_parameters() -> None:
    assert _parameters(INSTALLER) == {"Apply", "Confirm"}
    assert _parameters(STARTER) == set()
    assert _parameters(QUALIFICATION_CLIENT) == set()
    assert _parameters(CAPABILITY_AUDIT) == set()


def test_installer_has_exact_confirmation_and_reproducible_gate() -> None:
    source = INSTALLER.read_text("utf-8")
    assert "AURORA_CATALOG_BOOTSTRAP_ASSISTANT_V1" in source
    assert source.count("build_catalog_bootstrap_assistant.py") >= 2
    assert "BLOCKED_BOOTSTRAP_BUILD_NONDETERMINISTIC" in source
    assert "status --porcelain=v1 --untracked-files=no" in source
    assert "@(& git -C $RepoRoot status --porcelain=v1 --untracked-files=no).Count" in source
    assert "CATALOG_CONTROLLER_ENABLED" in source
    assert '$Branch = "main"' in source
    assert "origin/main" in source
    assert "BLOCKED_BOOTSTRAP_NOT_PROTECTED_HEAD" in source
    assert "Invoke-Expression" not in source


def test_starter_has_fixed_uac_target_and_no_visible_fallback() -> None:
    source = STARTER.read_text("utf-8")
    assert "C:\\ProgramData\\AURORA\\CatalogBootstrap" in source
    assert "-Verb RunAs" in source
    assert "--installed-root" in source
    assert "AURORA_CATALOG_BOOTSTRAP_ASSISTANT_V1" not in source
    assert "Invoke-Expression" not in source


def test_qualification_client_is_fixed_unprivileged_and_nonproduction() -> None:
    source = QUALIFICATION_CLIENT.read_text("utf-8")
    assert source.count("controller-bootstrap-qualification-v1") >= 2
    assert "AURORAAgent" in source
    assert "--campaign-key" in source
    assert "gh " not in source.casefold()
    assert "Start-Process" in source and "-Credential" in source
    assert "Invoke-Expression" not in source


def test_agent_capability_audit_proves_negative_boundaries_from_agent_identity() -> None:
    source = CAPABILITY_AUDIT.read_text("utf-8")
    for marker in (
        "AURORAAgent",
        "requester_key_read_denied",
        "broker_code_read_denied",
        "processing_list_denied",
        "agent_credential_read_denied",
        "broker_write_denied",
        "elevated_helper_write_denied",
        "medium_or_lower_integrity",
        "enabled_dangerous_privileges",
    ):
        assert marker in source
    assert "Start-Process" in source and "-Credential" in source
    assert "Invoke-Expression" not in source
