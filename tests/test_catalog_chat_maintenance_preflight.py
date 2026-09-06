"""Execute the closed read-only Windows maintenance preflight against OS fixtures."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/preflight_catalog_chat_maintenance.ps1"
)


CASES = (
    ("missingpublicfile", "BLOCKED", "PREFLIGHT_PUBLIC_FILE_MISSING"),
    ("reparse", "BLOCKED", "PREFLIGHT_ROOT_REPARSE"),
    ("wrongwriter", "BLOCKED", "PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER"),
    ("wrongowner", "BLOCKED", "PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER"),
    ("ancestorwriter", "BLOCKED", "PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER"),
    ("trustedancestor", "PREFLIGHT", "PREFLIGHT_TASK_ABSENT"),
    ("denied", "BLOCKED", "PREFLIGHT_PUBLIC_FILE_OBSERVATION_UNAVAILABLE"),
    ("directoryisfile", "BLOCKED", "PREFLIGHT_DIRECTORY_TYPE_INVALID"),
    ("binreparse", "BLOCKED", "PREFLIGHT_DIRECTORY_REPARSE"),
    ("missingtask", "PREFLIGHT", "PREFLIGHT_TASK_ABSENT"),
    ("existingtask", "BLOCKED", "PREFLIGHT_TASK_EXISTS"),
    ("missingdefinition", "BLOCKED", "PREFLIGHT_PUBLIC_FILE_MISSING"),
    ("unsafedefinition", "BLOCKED", "PREFLIGHT_REGISTRY_DEFINITION_INVALID"),
)


@pytest.mark.parametrize("fault, expected_status, expected_reason", CASES)
def test_closed_read_only_preflight_uses_real_script_and_mocked_os_transport(
    tmp_path: Path, fault: str, expected_status: str, expected_reason: str
) -> None:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")

    fixture = tmp_path / "preflight.ps1"
    fixture.write_text(
        r'''
$ErrorActionPreference = 'Stop'
$global:FixtureFault = 'FAULT'
$global:FixtureRoot = 'C:\ProgramData\AURORA\CatalogRequester'
$global:FixturePublicFile = 'C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz'
$global:FixtureDirectories = @(
    $global:FixtureRoot,
    'C:\ProgramData\AURORA',
    'C:\ProgramData',
    'C:\',
    "$global:FixtureRoot\bin",
    "$global:FixtureRoot\receipts",
    "$global:FixtureRoot\config",
    "$global:FixtureRoot\chat-inbox",
    "$global:FixtureRoot\chat-intents",
    "$global:FixtureRoot\chat-replies"
    "$global:FixtureRoot\docs",
    "$global:FixtureRoot\docs\runbooks",
    "$global:FixtureRoot\schemas",
    "$global:FixtureRoot\config\catalog_campaign_definitions"
)

function Get-Item {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [switch]$Force)
    if (-not $Force) { throw 'Hidden paths must be inspected, not treated as missing' }
    if ($global:FixtureFault -eq 'denied' -and $LiteralPath -eq $global:FixturePublicFile) {
        throw [UnauthorizedAccessException]::new('fixture denied')
    }
    if ($global:FixtureFault -eq 'missingpublicfile' -and $LiteralPath -eq $global:FixturePublicFile) {
        throw [System.IO.FileNotFoundException]::new('fixture missing public file')
    }
    if ($global:FixtureFault -eq 'missingdefinition' -and $LiteralPath -like '*\catalog_campaign_definitions\example-v1.manifest.json') {
        throw [System.IO.FileNotFoundException]::new('fixture missing definition')
    }
    $isRoot = $LiteralPath -eq $global:FixtureRoot
    $isDirectory = $LiteralPath -in $global:FixtureDirectories
    if ($global:FixtureFault -eq 'directoryisfile' -and $LiteralPath -eq "$global:FixtureRoot\chat-intents") { $isDirectory = $false }
    $attributes = [System.IO.FileAttributes]::Normal
    if (($global:FixtureFault -eq 'reparse' -and $isRoot) -or
        ($global:FixtureFault -eq 'binreparse' -and $LiteralPath -eq "$global:FixtureRoot\bin")) {
        $attributes = [System.IO.FileAttributes]::ReparsePoint
    }
    [pscustomobject]@{
        FullName = $LiteralPath
        PSIsContainer = $isDirectory
        Attributes = $attributes
    }
}

function Get-Acl {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [switch]$Force)
    $access = @(
        [pscustomobject]@{
            IdentityReference = 'S-1-5-32-544'
            FileSystemRights = 'FullControl'
            AccessControlType = 'Allow'
            IsInherited = $false
            InheritanceFlags = 'None'
            PropagationFlags = 'None'
        },
        [pscustomobject]@{
            IdentityReference = 'S-1-5-18'
            FileSystemRights = 'FullControl'
            AccessControlType = 'Allow'
            IsInherited = $false
            InheritanceFlags = 'None'
            PropagationFlags = 'None'
        }
    )
    if (($global:FixtureFault -eq 'wrongwriter' -and $LiteralPath -eq $global:FixturePublicFile) -or
        ($global:FixtureFault -eq 'ancestorwriter' -and $LiteralPath -eq 'C:\ProgramData\AURORA')) {
        $access += [pscustomobject]@{
            IdentityReference = 'S-1-5-32-545'
            FileSystemRights = 'DeleteSubdirectoriesAndFiles'
            AccessControlType = 'Allow'
            IsInherited = $false
            InheritanceFlags = 'None'
            PropagationFlags = 'None'
        }
    }
    $ownerSid = 'S-1-5-32-544'
    if ($global:FixtureFault -eq 'wrongowner' -and $LiteralPath -eq $global:FixturePublicFile) { $ownerSid = 'S-1-5-21-1-2-3-1001' }
    if ($global:FixtureFault -eq 'trustedancestor' -and $LiteralPath -eq 'C:\') { $ownerSid = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464' }
    [pscustomobject]@{
        Owner = $ownerSid
        Sddl = "O:${ownerSid}G:BAD:(A;;FA;;;SY)(A;;FA;;;BA)"
        Access = $access
    }
}

function Get-FileHash {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [string]$Algorithm)
    [pscustomobject]@{ Path = $LiteralPath; Hash = ('A' * 64); Algorithm = $Algorithm }
}

function Get-CatalogChatFileHash {
    param([string]$Path)
    ('A' * 64)
}

function Get-CatalogChatRegistryText {
    if ($global:FixtureFault -eq 'unsafedefinition') {
        return '{"campaigns":[{"active":true,"campaign_key":"example-v1","definition_manifest_path":"../secrets/key.pem"}]}'
    }
    return '{"campaigns":[{"active":true,"campaign_key":"example-v1","definition_manifest_path":"config/catalog_campaign_definitions/example-v1.manifest.json"}]}'
}

function Get-LocalUser {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Name)
    $rid = @{ HP = 1001; AURORAAgent = 1014; AURORARequester = 1015 }[$Name]
    [pscustomobject]@{ Name = $Name; SID = "S-1-5-21-1-2-3-$rid" }
}

function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath)
    if ($global:FixtureFault -eq 'existingtask') {
        [pscustomobject]@{ TaskName = 'AURORA Catalog Chat Entry'; TaskPath = '\' }
    }
}

. 'SCRIPT'
Get-CatalogChatMaintenancePreflight | ConvertTo-Json -Depth 30 -Compress
'''.replace("FAULT", fault).replace("SCRIPT", str(SCRIPT)),
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(fixture)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == expected_status
    assert payload["reason_code"] == expected_reason
    assert payload["production_ready"] is False
    assert payload["candidate_approved"] is False
    assert payload["rollback_tested"] is False
    assert payload["inventory"]["task"]["task_name"] == (
        "AURORA Catalog Chat Entry"
    )


def test_preflight_inventory_has_exact_public_paths_hashes_acl_and_directory_states(
    tmp_path: Path,
) -> None:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    fixture = tmp_path / "inventory.ps1"
    fixture.write_text(
        r'''
$ErrorActionPreference = 'Stop'
$global:InventoryDirectories = @(
    'C:\ProgramData\AURORA\CatalogRequester',
    'C:\ProgramData\AURORA',
    'C:\ProgramData',
    'C:\',
    'C:\ProgramData\AURORA\CatalogRequester\chat-inbox',
    'C:\ProgramData\AURORA\CatalogRequester\chat-intents',
    'C:\ProgramData\AURORA\CatalogRequester\chat-replies',
    'C:\ProgramData\AURORA\CatalogRequester\config'
    'C:\ProgramData\AURORA\CatalogRequester\bin'
    'C:\ProgramData\AURORA\CatalogRequester\receipts'
    'C:\ProgramData\AURORA\CatalogRequester\docs'
    'C:\ProgramData\AURORA\CatalogRequester\docs\runbooks'
    'C:\ProgramData\AURORA\CatalogRequester\schemas'
    'C:\ProgramData\AURORA\CatalogRequester\config\catalog_campaign_definitions'
)
function Get-Item {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [switch]$Force)
    [pscustomobject]@{
        FullName = $LiteralPath
        PSIsContainer = $LiteralPath -in $global:InventoryDirectories
        Attributes = [System.IO.FileAttributes]::Normal
    }
}
function Get-Acl {
    [CmdletBinding()]
    param([string]$LiteralPath)
    [pscustomobject]@{
        Owner = 'S-1-5-32-544'
        Sddl = 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)'
        Access = @()
    }
}
function Get-CatalogChatFileHash { param([string]$Path) ('B' * 64) }
function Get-CatalogChatRegistryText { '{"campaigns":[{"active":true,"campaign_key":"example-v1","definition_manifest_path":"config/catalog_campaign_definitions/example-v1.manifest.json"}]}' }
function Get-LocalUser {
    [CmdletBinding()]
    param([string]$Name)
    [pscustomobject]@{ SID = 'S-1-5-21-1-2-3-4' }
}
function Get-ScheduledTask { }
. 'SCRIPT'
Get-CatalogChatMaintenancePreflight | ConvertTo-Json -Depth 30 -Compress
'''.replace("SCRIPT", str(SCRIPT)),
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(fixture)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["inventory"]["public_files"]
    paths = {item["relative_path"] for item in payload["inventory"]["public_files"]}
    assert paths == {
        "bin/catalog-requester-client.pyz",
        "bin/catalog-requester-client.manifest.json",
        "bin/catalog-requester-broker.pyz",
        "bin/catalog-requester-broker.manifest.json",
        "config/catalog_campaign_registry_v1.json",
        "config/production-enabled-v1.seal.json",
        "receipts/controller-bootstrap-v1.receipt.json",
        "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
        "config/catalog_run_prompt_policy_v1.json",
        "config/catalog_requester_v1.json",
        "config/catalog_controller_actors_v1.json",
        "config/catalog_github_controls_v1.json",
        "config/catalog_requester_public_key_v1.pem",
        "schemas/catalog_requester_app_manifest_v1.schema.json",
        "schemas/catalog_campaign_definition_manifest_v1.schema.json",
        "schemas/catalog_run_prompt_policy_v1.schema.json",
        "config/catalog_campaign_definitions/example-v1.manifest.json",
    }
    assert all(item["sha256"] == "b" * 64 for item in payload["inventory"]["public_files"])
    assert all(item["acl"]["sddl"] for item in payload["inventory"]["public_files"])
    assert {item["state"] for item in payload["inventory"]["directories"]} == {"existing"}
    assert len(payload["inventory"]["ancestors"]) == 3
    assert all(item["acl"]["sddl"] for item in payload["inventory"]["ancestors"])
