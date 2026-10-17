"""Black-box tests for the protected T07 catalog chat entry installer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_catalog_chat_entry.ps1"
COMMIT = "a" * 40


PUBLIC_INPUTS = (
    "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md",
    "config/catalog_run_prompt_policy_v1.json",
    "config/catalog_campaign_registry_v1.json",
    "config/catalog_requester_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_controls_v1.json",
    "config/catalog_requester_public_key_v1.pem",
    "schemas/catalog_requester_app_manifest_v1.schema.json",
    "schemas/catalog_campaign_definition_manifest_v1.schema.json",
    "schemas/catalog_run_prompt_policy_v1.schema.json",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _candidate_fixture(
    tmp_path: Path,
    *,
    chat_dirs_present: bool = True,
    config_present: bool = True,
    maintenance_receipt_present: bool = False,
) -> tuple[Path, str, Path, Path]:
    candidate = tmp_path / "candidate"
    payload = candidate / "payload"
    requester = payload / "CatalogRequester"
    sender = payload / "CatalogChatSender"
    registry = {
        "schema_version": "1",
        "campaigns": [
            {
                "active": True,
                "campaign_key": "example-v1",
                "definition_manifest_path": (
                    "config/catalog_campaign_definitions/example-v1.manifest.json"
                ),
            }
        ],
    }
    registry_bytes = json.dumps(
        registry, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    files: dict[str, bytes] = {
        "config/catalog_campaign_registry_v1.json": registry_bytes,
        "config/catalog_requester_v1.json": b"candidate requester config\n",
        "config/catalog_controller_actors_v1.json": b"actors\n",
        "config/catalog_github_controls_v1.json": b"controls\n",
        "config/catalog_lineage_transitions_v1.json": b'{"schema_version":"1","transitions":[]}\n',
        "config/catalog_requester_public_key_v1.pem": b"-----BEGIN PUBLIC KEY-----\nfixed-key\n",
        "schemas/catalog_requester_app_manifest_v1.schema.json": b"schema-app\n",
        "schemas/catalog_campaign_definition_manifest_v1.schema.json": b"schema-campaign\n",
        "schemas/catalog_run_prompt_policy_v1.schema.json": b"schema-policy\n",
        "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md": b"prompt\n",
        "config/catalog_run_prompt_policy_v1.json": b"policy\n",
        "config/catalog_campaign_definitions/example-v1.manifest.json": b"definition\n",
        "bin/catalog-requester-client.pyz": b"client-pyz\n",
        "bin/catalog-requester-client.manifest.json": b"client-manifest\n",
        "bin/catalog-requester-broker.pyz": b"broker-pyz\n",
        "bin/catalog-requester-broker.manifest.json": b"broker-manifest\n",
        "config/production-enabled-v1.seal.json": b"new-seal\n",
        "receipts/requester-maintenance-v1.receipt.json": b"new-maintenance\n",
    }
    for relative, data in files.items():
        path = requester / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (sender / "submit_catalog_chat_intent.py").parent.mkdir(parents=True, exist_ok=True)
    (sender / "submit_catalog_chat_intent.py").write_bytes(b"sender\n")
    (sender / "catalog_campaign_registry_v1.json").write_bytes(registry_bytes)

    candidate_records = []
    for path in sorted(payload.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            candidate_records.append(
                {
                    "path": path.relative_to(payload).as_posix(),
                    "sha256": _sha256(data),
                    "size_bytes": len(data),
                }
            )

    live = tmp_path / "AURORA"
    live_requester = live / "CatalogRequester"
    live_sender = live / "CatalogChatSender"
    for directory in (
        live,
        live_requester,
        live_requester / "bin",
        live_requester / "config",
        live_requester / "config/catalog_campaign_definitions",
        live_requester / "docs/runbooks",
        live_requester / "schemas",
        live_requester / "receipts",
        live_requester / "client-venv/Scripts",
        live_requester / "broker-venv/Scripts",
        live_sender,
        live / "CatalogAgent/credentials",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if chat_dirs_present:
        for name in ("chat-inbox", "chat-intents", "chat-replies"):
            (live_requester / name).mkdir(parents=True, exist_ok=True)

    ready = b"historical-ready\n"
    old_seal = b"old-seal\n"
    (live_requester / "receipts/controller-bootstrap-v1.receipt.json").write_bytes(ready)
    (live_requester / "config/production-enabled-v1.seal.json").write_bytes(old_seal)
    for relative, data in files.items():
        if relative in {
            "config/production-enabled-v1.seal.json",
            "receipts/requester-maintenance-v1.receipt.json",
        }:
            continue
        target = live_requester / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            data
            if relative != "config/catalog_requester_v1.json"
            else b"old config\n"
        )
    if config_present:
        (live_requester / "config/chat-entry-v1.json").write_bytes(
            b'{"schema_version":"1","sender_sid":"S-1-5-21-1-2-3-1001"}\n'
        )
    previous_receipt = b"pre-existing-maintenance-receipt\n"
    if maintenance_receipt_present:
        (live_requester / "receipts/requester-maintenance-v1.receipt.json").write_bytes(
            previous_receipt
        )
    (live_requester / "client-venv/Scripts/python.exe").write_bytes(b"client-runtime\n")
    (live_requester / "broker-venv/Scripts/python.exe").write_bytes(b"broker-runtime-console\n")
    (live_requester / "broker-venv/Scripts/pythonw.exe").write_bytes(b"broker-runtime\n")

    candidate_data = {
        "schema_version": "1",
        "status": "CANDIDATE",
        "protected_commit_sha": COMMIT,
        "two_builds_identical": True,
        "applications_verified_unsealed": True,
        "production_verified": False,
        "installation_authorized_by_this_file": False,
        "applications_verified_sealed_against_baseline": True,
        "baseline_file_sha256": {
            "receipts/controller-bootstrap-v1.receipt.json": _sha256(ready),
            "config/production-enabled-v1.seal.json": _sha256(old_seal),
            **(
                {
                    "receipts/requester-maintenance-v1.receipt.json": _sha256(
                        previous_receipt
                    )
                }
                if maintenance_receipt_present
                else {}
            ),
        },
        "files": [
            *[
                {
                    **record,
                    "path": record["path"],
                }
                for record in candidate_records
            ],
        ],
    }
    candidate_json = json.dumps(
        candidate_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / "candidate.json").write_bytes(candidate_json)
    return candidate, _sha256(candidate_json), live, live_requester


def _transport_fixture(
    *,
    installer: Path,
    candidate: Path,
    live: Path,
    task_mode: str,
    fail_postverify: bool = False,
    undo_blocked: bool = False,
    broker_running: bool = False,
    broker_stop_failure: bool = False,
    broker_start_failure: bool = False,
    chat_stop_failure: bool = False,
    bad_resource_acl: bool = False,
    receipt_acl_failure: bool = False,
    lineage_records: list[dict] | None = None,
    lineage_idle_failure: bool = False,
    lineage_hold_lock: bool = False,
    check_candidate_freeze: bool = False,
) -> str:
    return (r'''
$ErrorActionPreference = 'Stop'
$global:LiveRoot = 'LIVE_ROOT'
$global:CandidateFixtureRoot = 'CANDIDATE_ROOT'
$global:BackupRoot = Join-Path (Split-Path $global:LiveRoot -Parent) 'AURORA-CatalogChatMaintenance'
$global:TaskMode = 'TASK_MODE'
$global:FailPostVerify = FAIL_POSTVERIFY
$global:UndoBlocked = UNDO_BLOCKED
$global:BrokerRunning = BROKER_RUNNING
$global:BrokerStopFailure = BROKER_STOP_FAILURE
$global:BrokerStartFailure = BROKER_START_FAILURE
$global:ChatStopFailure = CHAT_STOP_FAILURE
$global:BadResourceAcl = BAD_RESOURCE_ACL
$global:ReceiptAclFailure = RECEIPT_ACL_FAILURE_PLACEHOLDER
$global:TaskExists = $false
$global:TaskState = 'Ready'
$global:BrokerState = if ($global:BrokerRunning) { 'Running' } else { 'Ready' }
$global:BrokerEnabled = $true
$global:VerifierCalls = 0
$global:MaintenanceReceiptAclProtected = $false
$global:MaintenanceReceiptExistedBefore = [IO.File]::Exists((Join-Path $global:LiveRoot 'CatalogRequester/receipts/requester-maintenance-v1.receipt.json'))
$global:Calls = [System.Collections.Generic.List[string]]::new()
$global:FixedDirectories = @(
    'C:\', 'C:\ProgramData', 'C:\ProgramData\AURORA',
    'C:\ProgramData\AURORA\CatalogRequester',
    'C:\ProgramData\AURORA\CatalogRequester\bin',
    'C:\ProgramData\AURORA\CatalogRequester\config',
    'C:\ProgramData\AURORA\CatalogRequester\config\catalog_campaign_definitions',
    'C:\ProgramData\AURORA\CatalogRequester\docs',
    'C:\ProgramData\AURORA\CatalogRequester\docs\runbooks',
    'C:\ProgramData\AURORA\CatalogRequester\schemas',
    'C:\ProgramData\AURORA\CatalogRequester\receipts',
    'C:\ProgramData\AURORA\CatalogRequester\client-venv',
    'C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts',
    'C:\ProgramData\AURORA\CatalogRequester\broker-venv',
    'C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts',
    'C:\ProgramData\AURORA\CatalogAgent',
    'C:\ProgramData\AURORA\CatalogAgent\credentials'
)

function Test-CatalogChatEntryAdministrator { $true }
function Resolve-CatalogChatEntryPhysicalPath {
    param([Parameter(Mandatory = $true)][string]$LogicalPath)
    if ($LogicalPath -eq 'C:\ProgramData\AURORA-CatalogChatMaintenance') { return $global:BackupRoot }
    if ($LogicalPath.StartsWith('C:\ProgramData\AURORA-CatalogChatMaintenance\', [StringComparison]::OrdinalIgnoreCase)) {
        return (Join-Path $global:BackupRoot $LogicalPath.Substring('C:\ProgramData\AURORA-CatalogChatMaintenance\'.Length))
    }
    if ($LogicalPath -eq 'C:\ProgramData\AURORA') { return $global:LiveRoot }
    if ($LogicalPath.StartsWith('C:\ProgramData\AURORA\', [StringComparison]::OrdinalIgnoreCase)) {
        return (Join-Path $global:LiveRoot $LogicalPath.Substring('C:\ProgramData\AURORA\'.Length))
    }
    return $LogicalPath
}
function Get-CatalogChatEntryPathObservation {
    param([Parameter(Mandatory = $true)][string]$Path)
    $physical = Resolve-CatalogChatEntryPhysicalPath $Path
    if ([IO.Directory]::Exists($physical)) {
        return [pscustomobject]@{ observation_available = $true; exists = $true; is_directory = $true; is_reparse = $false; path = $Path }
    }
    if ([IO.File]::Exists($physical)) {
        return [pscustomobject]@{ observation_available = $true; exists = $true; is_directory = $false; is_reparse = $false; path = $Path }
    }
    return [pscustomobject]@{ observation_available = $true; exists = $false; is_directory = $false; is_reparse = $false; path = $Path }
}
function Get-CatalogChatEntryAclObservation {
    param([Parameter(Mandatory = $true)][string]$Path)
    $unauthorized = @()
    $rules = @(
        [pscustomobject]@{ identity = 'S-1-5-32-544'; rights = 'FullControl'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' },
        [pscustomobject]@{ identity = 'S-1-5-18'; rights = 'FullControl'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' }
    )
    if ($Path -like '*requester-maintenance-v1.receipt.json') {
        if ($global:MaintenanceReceiptExistedBefore) {
            # A pre-existing receipt has a deliberately different, valid ACL.
            $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'Modify'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' }
            $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1001'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' }
        }
        elseif ($global:MaintenanceReceiptAclProtected) {
            $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' }
            $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1015'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' }
        }
        else {
            # This models the real boundary: a new file inherits requester write.
            $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $true; inheritance_flags = 'ObjectInherit'; propagation_flags = 'None' }
            $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1015'; rights = 'Modify'; access_type = 'Allow'; is_inherited = $true; inheritance_flags = 'ObjectInherit'; propagation_flags = 'None' }
            $unauthorized = @('S-1-5-21-1-2-3-1015')
        }
    }
    elseif ($Path -like '*CatalogChatSender') {
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1001'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ContainerInherit, ObjectInherit'; propagation_flags = 'None' }
    }
    elseif ($Path -like '*chat-entry-v1.json') {
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'None'; propagation_flags = 'None' }
    }
    elseif ($Path -like '*chat-inbox') {
        foreach ($rule in $rules) { $rule.inheritance_flags = 'ContainerInherit, ObjectInherit' }
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1001'; rights = 'ReadAndExecute, Write, Synchronize'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ContainerInherit, ObjectInherit'; propagation_flags = 'None' }
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1001'; rights = 'Delete, Synchronize'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ObjectInherit'; propagation_flags = 'InheritOnly' }
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ContainerInherit, ObjectInherit'; propagation_flags = 'None' }
    }
    elseif ($Path -like '*chat-intents') {
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'Modify'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ContainerInherit, ObjectInherit'; propagation_flags = 'None' }
    }
    elseif ($Path -like '*chat-replies') {
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1014'; rights = 'Modify'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ContainerInherit, ObjectInherit'; propagation_flags = 'None' }
        $rules += [pscustomobject]@{ identity = 'S-1-5-21-1-2-3-1001'; rights = 'ReadAndExecute'; access_type = 'Allow'; is_inherited = $false; inheritance_flags = 'ContainerInherit, ObjectInherit'; propagation_flags = 'None' }
    }
    if ($global:BadResourceAcl -and ($Path -like '*chat-entry-v1.json' -or $Path -like '*chat-inbox' -or $Path -like '*chat-intents' -or $Path -like '*chat-replies')) {
        $rules = @()
    }
    return [pscustomobject]@{
        observation_available = $true
        owner = 'S-1-5-32-544'
        sddl = 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)'
        unauthorized_effective_writers = $unauthorized
        effective_writers = @('S-1-5-18', 'S-1-5-32-544')
        access_rules = $rules
    }
}
function Set-CatalogChatEntryAcl {
    param([string]$Path, $AclObject)
    if ($Path -like '*requester-maintenance-v1.receipt.json') {
        if ($global:ReceiptAclFailure) { throw 'TEST_RECEIPT_ACL_FAILURE' }
        $global:MaintenanceReceiptAclProtected = $true
    }
    $global:Calls.Add("acl:$Path")
}
function Get-CatalogChatEntryAffectedWork { param([switch]$AllowAuthenticatedBroker) @() }
function Get-CatalogChatEntryCredential {
    $secure = New-Object Security.SecureString
    foreach ($character in 'test-secret'.ToCharArray()) { $secure.AppendChar($character) }
    $secure.MakeReadOnly()
    return [PSCredential]::new('AURORAAgent', $secure)
}
function Invoke-CatalogChatEntryVerifierProcess {
    param([string]$RuntimePython, [string]$ApplicationKind, [string]$VerificationRoot, [string]$ExpectedCommitSha)
    $global:VerifierCalls++
    if ($global:VerifierCalls -eq 1) { $global:VerifiedCandidateRoot = $VerificationRoot }
    if (CHECK_CANDIDATE_FREEZE -and $global:VerifierCalls -le 2) {
        $writeBlocked = $false
        try { [IO.File]::WriteAllBytes((Join-Path $VerificationRoot "bin/catalog-requester-$ApplicationKind.pyz"), [byte[]]@(0)) }
        catch [IO.IOException] { $writeBlocked = $true }
        if (-not $writeBlocked) { throw 'TEST_VERIFIED_PAYLOAD_MUTABLE' }
    }
    $global:Calls.Add("verify:$ApplicationKind")
    foreach ($relative in @("bin/catalog-requester-$ApplicationKind.pyz", "bin/catalog-requester-$ApplicationKind.manifest.json", 'receipts/controller-bootstrap-v1.receipt.json')) {
        if (-not [IO.File]::Exists((Join-Path $VerificationRoot $relative))) {
            throw "TEST_VERIFIER_INPUT_MISSING:$relative"
        }
    }
    if ($global:FailPostVerify -and $global:VerifierCalls -ge 3) {
        if ($global:UndoBlocked) {
            [IO.File]::WriteAllText((Join-Path $global:LiveRoot 'CatalogRequester/config/catalog_requester_v1.json'), 'drifted config', [Text.UTF8Encoding]::new($false))
        }
        throw 'TEST_POSTVERIFY_FAILURE'
    }
    return [pscustomobject]@{ application_kind = $ApplicationKind; protected_commit_sha = $ExpectedCommitSha }
}
function Get-Item {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [switch]$Force)
    if ([IO.Directory]::Exists($LiteralPath)) {
        return [pscustomobject]@{ FullName = $LiteralPath; PSIsContainer = $true; Attributes = [IO.FileAttributes]::Normal }
    }
    if ([IO.File]::Exists($LiteralPath)) {
        return [pscustomobject]@{ FullName = $LiteralPath; PSIsContainer = $false; Attributes = [IO.FileAttributes]::Normal; Length = ([IO.FileInfo]::new($LiteralPath)).Length }
    }
    if ($LiteralPath -in $global:FixedDirectories) {
        return [pscustomobject]@{ FullName = $LiteralPath; PSIsContainer = $true; Attributes = [IO.FileAttributes]::Normal }
    }
    if ($LiteralPath -like '*chat-entry-v1.json' -or
        $LiteralPath -like '*chat-inbox' -or $LiteralPath -like '*chat-intents' -or $LiteralPath -like '*chat-replies') {
        throw [IO.FileNotFoundException]::new($LiteralPath)
    }
    return [pscustomobject]@{ FullName = $LiteralPath; PSIsContainer = $false; Attributes = [IO.FileAttributes]::Normal; Length = 32 }
}
function Get-Acl {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [switch]$Force)
    $access = @(
        [pscustomobject]@{ IdentityReference = 'S-1-5-32-544'; FileSystemRights = 'FullControl'; AccessControlType = 'Allow'; IsInherited = $false; InheritanceFlags = 'None'; PropagationFlags = 'None' },
        [pscustomobject]@{ IdentityReference = 'S-1-5-18'; FileSystemRights = 'FullControl'; AccessControlType = 'Allow'; IsInherited = $false; InheritanceFlags = 'None'; PropagationFlags = 'None' }
    )
    return [pscustomobject]@{ Owner = 'S-1-5-32-544'; Sddl = 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)'; Access = $access }
}
function Get-FileHash { param([string]$LiteralPath, [string]$Algorithm) [pscustomobject]@{ Hash = ('A' * 64); Path = $LiteralPath; Algorithm = $Algorithm } }
function Get-CatalogChatFileHash { param([string]$Path) ('A' * 64) }
function Get-CatalogChatRegistryText { '{"schema_version":"1","campaigns":[{"active":true,"campaign_key":"example-v1","definition_manifest_path":"config/catalog_campaign_definitions/example-v1.manifest.json"}]}' }
function Get-LocalUser {
    [CmdletBinding()]
    param([string]$Name)
    $sid = @{ HP = 'S-1-5-21-1-2-3-1001'; AURORAAgent = 'S-1-5-21-1-2-3-1014'; AURORARequester = 'S-1-5-21-1-2-3-1015' }[$Name]
    return [pscustomobject]@{ Name = $Name; SID = $sid }
}
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskPath)
    if ($global:TaskMode -eq 'mismatch') {
        return [pscustomobject]@{
            TaskName = 'AURORA Catalog Chat Entry'; TaskPath = '\'; State = 'Ready'
            Principal = [pscustomobject]@{ UserId = 'HP'; RunLevel = 'Highest'; LogonType = 'Password' }
            Actions = @([pscustomobject]@{ Execute = 'C:\bad.exe'; Arguments = 'bad'; WorkingDirectory = 'C:\bad' })
        }
    }
    if ($global:TaskExists -or $global:TaskMode -eq 'exact') {
        Write-Output ([pscustomobject]@{
            TaskName = 'AURORA Catalog Chat Entry'; TaskPath = '\'; State = $global:TaskState
            Principal = [pscustomobject]@{ UserId = 'S-1-5-21-1-2-3-1014'; RunLevel = 'Limited'; LogonType = 'Password' }
            Actions = @([pscustomobject]@{
                Execute = 'C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe'
                Arguments = '-I -s -E "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz" --serve-chat'
                WorkingDirectory = 'C:\ProgramData\AURORA\CatalogRequester'
            })
        })
    }
    if ($global:BrokerRunning -or $global:BrokerState -eq 'Running') {
        Write-Output ([pscustomobject]@{
            TaskName = 'AURORA Catalog Requester Broker'; TaskPath = '\'; State = $global:BrokerState
            Principal = [pscustomobject]@{ UserId = 'S-1-5-21-1-2-3-1015'; RunLevel = 'Limited'; LogonType = 'Password' }
            Actions = @([pscustomobject]@{
                Execute = 'C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts\pythonw.exe'
                Arguments = '-I -s -E "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-broker.pyz"'
                WorkingDirectory = 'C:\ProgramData\AURORA\CatalogRequester'
            })
            Settings = [pscustomobject]@{
                Enabled = [string]$global:BrokerEnabled; Hidden = 'True'; MultipleInstances = 'IgnoreNew'
                RestartCount = '999'; RestartInterval = '00:01:00'; StartWhenAvailable = 'True'
            }
        })
    }
}
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) [pscustomobject]@{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel } }
function New-ScheduledTaskSettingsSet { param([switch]$Hidden, $MultipleInstances, [switch]$StartWhenAvailable, $ExecutionTimeLimit, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries) [pscustomobject]@{} }
function New-ScheduledTaskTrigger { param([switch]$AtStartup) [pscustomobject]@{} }
function New-ScheduledTask { param($Action, $Principal, $Settings, $Trigger) [pscustomobject]@{ Actions = @($Action); Principal = $Principal; Settings = $Settings; Triggers = @($Trigger) } }
function Register-ScheduledTask {
    [CmdletBinding()]
    param($TaskName, $TaskPath, $InputObject, $User, $Password)
    $global:Calls.Add('register')
    $global:TaskExists = $true; $global:TaskMode = 'exact'; $global:TaskState = 'Ready'
}
function Disable-ScheduledTask {
    [CmdletBinding()]
    param($TaskName, $TaskPath)
    if ($TaskName -ceq 'AURORA Catalog Requester Broker') { $global:Calls.Add('disable-broker'); $global:BrokerEnabled = $false }
}
function Enable-ScheduledTask {
    [CmdletBinding()]
    param($TaskName, $TaskPath)
    if ($TaskName -ceq 'AURORA Catalog Requester Broker') { $global:Calls.Add('enable-broker'); $global:BrokerEnabled = $true }
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param($TaskName, $TaskPath)
    if ($TaskName -ceq 'AURORA Catalog Requester Broker') {
        $global:Calls.Add('start-broker')
        if ($global:BrokerStartFailure) { throw 'TEST_BROKER_START_FAILURE' }
        $global:BrokerState = 'Running'
    }
    else {
        $global:Calls.Add('start')
        $global:TaskState = 'Running'
        if ($global:ChatStopFailure) { throw 'TEST_CHAT_START_FAILURE_AFTER_START' }
    }
}
function Stop-ScheduledTask {
    [CmdletBinding()]
    param($TaskName, $TaskPath)
    if ($TaskName -ceq 'AURORA Catalog Requester Broker') {
        $global:Calls.Add('stop-broker')
        if ($global:BrokerStopFailure) { throw 'TEST_BROKER_STOP_FAILURE' }
        $global:BrokerState = 'Ready'
    }
    else {
        $global:Calls.Add('stop')
        if ($global:ChatStopFailure) { throw 'TEST_CHAT_STOP_FAILURE' }
        $global:TaskState = 'Ready'
    }
}
function Unregister-ScheduledTask { [CmdletBinding()] param($TaskName, $TaskPath, $Confirm) $global:Calls.Add('unregister'); $global:TaskExists = $false; $global:TaskMode = 'absent' }
function Start-Sleep { param([int]$Milliseconds) }
function Invoke-CatalogChatEntryLineageProcess {
    param($RuntimePython, $VerificationRoot, $BrokerRoot)
    $global:Calls.Add('prepare-lineage')
    if (CHECK_CANDIDATE_FREEZE -and $VerificationRoot -cne $global:VerifiedCandidateRoot) { throw 'TEST_LINEAGE_NOT_USING_VERIFIED_COPY' }
    return ('LINEAGE_RESPONSE' | ConvertFrom-Json)
}
function Invoke-CatalogChatEntryIdleProcess {
    param($Candidate, $Runtime, $VerificationRoot)
    if (CHECK_CANDIDATE_FREEZE -and $VerificationRoot -cne $global:VerifiedCandidateRoot) { throw 'TEST_IDLE_NOT_USING_VERIFIED_COPY' }
    $global:Calls.Add('check-chat-idle')
    $path = Join-Path $global:LiveRoot 'CatalogRequester/chat-intents/.service.lock'
    $other = $null
    try { $other = [IO.File]::Open($path, 'Open', 'ReadWrite', 'None') }
    catch [IO.IOException] {
        if (LINEAGE_IDLE_FAILURE) { throw 'LINEAGE_CHAT_NOT_IDLE' }
        return
    }
    if ($null -ne $other) { $other.Dispose() }
    throw 'TEST_CHAT_LOCK_NOT_HELD'
}

. 'INSTALLER'
$busyLock = $null
if (LINEAGE_HOLD_LOCK) {
    $busyLock = [IO.File]::Open((Join-Path $global:LiveRoot 'CatalogRequester/chat-intents/.service.lock'), 'Open', 'ReadWrite', 'None')
}
$result = Invoke-CatalogChatEntryInstallation -CandidateRoot $global:CandidateFixtureRoot -ExpectedCandidateSha256 'EXPECTED_HASH' -ExpectedApprovedCommitSha 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' -Apply -Confirm 'AURORA_CATALOG_CHAT_ENTRY_V1'
if ($null -ne $busyLock) { $busyLock.Dispose() }
[pscustomobject]@{
    result = $result
    calls = @($global:Calls)
    target_config = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path $global:LiveRoot 'CatalogRequester/config/catalog_requester_v1.json')))
} | ConvertTo-Json -Depth 50 -Compress
'''.replace("INSTALLER", str(installer).replace("'", "''"))
        .replace("CANDIDATE_ROOT", str(candidate).replace("'", "''"))
        .replace("LIVE_ROOT", str(live).replace("'", "''"))
        .replace("TASK_MODE", task_mode)
        .replace("FAIL_POSTVERIFY", "$true" if fail_postverify else "$false")
        .replace("UNDO_BLOCKED", "$true" if undo_blocked else "$false")
        .replace("BROKER_RUNNING", "$true" if broker_running else "$false")
        .replace("BROKER_STOP_FAILURE", "$true" if broker_stop_failure else "$false")
        .replace("BROKER_START_FAILURE", "$true" if broker_start_failure else "$false")
    .replace("CHAT_STOP_FAILURE", "$true" if chat_stop_failure else "$false")
    .replace("BAD_RESOURCE_ACL", "$true" if bad_resource_acl else "$false")
      .replace("RECEIPT_ACL_FAILURE_PLACEHOLDER", "$true" if receipt_acl_failure else "$false")
      .replace("LINEAGE_IDLE_FAILURE", "$true" if lineage_idle_failure else "$false")
      .replace("LINEAGE_HOLD_LOCK", "$true" if lineage_hold_lock else "$false")
      .replace("CHECK_CANDIDATE_FREEZE", "$true" if check_candidate_freeze else "$false")
      .replace("LINEAGE_RESPONSE", json.dumps({"schema_version": "1", "records": lineage_records or []}).replace("'", "''")))


def _run_ps(tmp_path: Path, script: str) -> dict:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    fixture = tmp_path / "installer-fixture.ps1"
    fixture.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(fixture)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_temp_receipt_reproduces_inherited_requester_write_boundary(tmp_path: Path) -> None:
    script = r'''
$ErrorActionPreference = 'Stop'
$env:PSModulePath = Join-Path $PSHOME 'Modules'
$root = 'TEMP_ROOT'
$receipts = Join-Path $root 'receipts'
New-Item -ItemType Directory -Path $receipts -Force | Out-Null
$requesterSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-21-1-2-3-1015')
$agentSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-21-1-2-3-1014')
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$security = New-Object System.Security.AccessControl.DirectorySecurity
$security.SetAccessRuleProtection($true, $false)
foreach ($entry in @(
    [pscustomobject]@{ sid = $currentSid; rights = [Security.AccessControl.FileSystemRights]::FullControl },
    [pscustomobject]@{ sid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18'); rights = [Security.AccessControl.FileSystemRights]::FullControl },
    [pscustomobject]@{ sid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'); rights = [Security.AccessControl.FileSystemRights]::FullControl }
)) {
    $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $entry.sid, $entry.rights,
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow))
}
$security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $agentSid, [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow))
$security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $requesterSid, [Security.AccessControl.FileSystemRights]::Modify,
    [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow))
Set-Acl -LiteralPath $receipts -AclObject $security
$receipt = Join-Path $receipts 'requester-maintenance-v1.receipt.json'
New-Item -ItemType File -Path $receipt | Out-Null
$acl = Get-Acl -LiteralPath $receipt
$requesterRules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | Where-Object {
    [string]$_.IdentityReference.Value -eq $requesterSid.Value
})
if ($requesterRules.Count -ne 1) { throw 'EXPECTED_ONE_INHERITED_REQUESTER_RULE' }
$requesterRule = $requesterRules[0]
[pscustomobject]@{
    inherited = [bool]$requesterRule.IsInherited
    requester_has_write = (([long]$requesterRule.FileSystemRights -band
        [long][Security.AccessControl.FileSystemRights]::Write) -eq
        [long][Security.AccessControl.FileSystemRights]::Write)
} | ConvertTo-Json -Compress
Remove-Item -LiteralPath $root -Recurse -Force
'''.replace("TEMP_ROOT", str(tmp_path / "native-acl-boundary").replace("'", "''"))
    outcome = _run_ps(tmp_path, script)
    assert outcome == {"inherited": True, "requester_has_write": True}
