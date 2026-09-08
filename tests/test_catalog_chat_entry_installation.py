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
function New-ScheduledTaskSettingsSet { param([switch]$Hidden, $MultipleInstances, [switch]$StartWhenAvailable, $ExecutionTimeLimit) [pscustomobject]@{} }
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


@pytest.mark.parametrize("kind, working_directory, accepted", [
    ("broker", "", True),
    ("broker", r"C:\ProgramData\AURORA\CatalogRequester", True),
    ("broker", r"C:\Users\Public", False),
    ("chat", "", False),
    ("chat", r"C:\ProgramData\AURORA\CatalogRequester", True),
])
def test_native_task_action_preserves_original_broker_working_directory(
    tmp_path: Path, kind: str, working_directory: str, accepted: bool,
) -> None:
    # Construct native task objects, without registering or starting a task.
    script = r'''
$env:PSModulePath = 'C:\Windows\System32\WindowsPowerShell\v1.0\Modules'
. 'INSTALLER'
function Get-LocalUser { param($Name) [pscustomobject]@{ SID = 'S-1-5-21-1-2-3-1015' } }
$root = 'C:\ProgramData\AURORA\CatalogRequester'
if ('KIND' -eq 'broker') {
    $execute = $root + '\broker-venv\Scripts\pythonw.exe'
    $arguments = '-I -s -E "' + $root + '\bin\catalog-requester-broker.pyz"'
    $expected = Get-CatalogChatEntryExpectedBrokerAction
} else {
    $execute = $root + '\client-venv\Scripts\python.exe'
    $arguments = '-I -s -E "' + $root + '\bin\catalog-requester-client.pyz" --serve-chat'
    $expected = Get-CatalogChatEntryExpectedChatAction
}
$parameters = @{ Execute = $execute; Argument = $arguments }
if ('WORKING_DIRECTORY' -ne '') { $parameters.WorkingDirectory = 'WORKING_DIRECTORY' }
$action = New-ScheduledTaskAction @parameters
$principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-21-1-2-3-1015' -LogonType Password -RunLevel Limited
$task = New-ScheduledTask -Action $action -Principal $principal
$accepted = Test-CatalogChatEntryTaskAction -Task $task -ExpectedAction $expected -IdentityName 'AURORARequester'
@{ accepted = $accepted } | ConvertTo-Json -Compress
'''.replace("INSTALLER", str(INSTALLER).replace("'", "''"))
    script = script.replace("WORKING_DIRECTORY", working_directory).replace("KIND", kind)
    assert _run_ps(tmp_path, script)["accepted"] is accepted


@pytest.mark.parametrize("executable_path, command, owner_status, affected", [
    (r"C:\Python314\python.exe", r'"C:\Python314\python.exe" C:\tools\efficient_runner.py wait fixture', 0, False),
    (r"C:\Python314\python.exe", r'"C:\Python314\python.exe" C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz', 0, True),
    (r"C:\Python314\python.exe", "", 0, True),
    (r"C:\Python314\python.exe", r'"C:\Python314\python.exe" C:\tools\worker.py', 2, True),
    (r"C:\ProgramData\AURORA_backup\python.exe", r'"C:\ProgramData\AURORA_backup\python.exe" C:\tools\worker.py', 0, False),
    (r"C:\Python314\python.exe", r'"C:\Python314\python.exe" C:\tools\worker.py --label CatalogRequester', 0, False),
    (r"C:\Python314\python.exe", r'"C:\Python314\python.exe" catalog-requester-client.pyz', 0, True),
])
def test_affected_work_distinguishes_unrelated_python_from_unobservable_work(
    tmp_path: Path, executable_path: str, command: str, owner_status: int, affected: bool,
) -> None:
    script = r'''
. 'INSTALLER'
function Get-ScheduledTask { param($TaskPath) @() }
function Get-LocalUser {
    param($Name)
    $sid = if ($Name -eq 'AURORARequester') { 'S-1-5-21-1-2-3-1015' } else { 'S-1-5-21-1-2-3-1014' }
    [pscustomobject]@{ SID = $sid }
}
function Get-CimInstance {
    param($ClassName, $Filter)
    [pscustomobject]@{
        ProcessId = 100; ParentProcessId = 50; Name = 'python.exe'
        ExecutablePath = 'EXECUTABLE_PATH'; CommandLine = 'COMMAND'
        CreationDate = [datetime]'2026-09-07T14:00:00Z'
    }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName)
    if ($MethodName -ne 'GetOwnerSid') { throw 'UNEXPECTED_PROCESS_OPERATION' }
    [pscustomobject]@{ ReturnValue = OWNER_STATUS; Sid = 'S-1-5-21-1-2-3-1001' }
}
$work = @(Get-CatalogChatEntryAffectedWork -AllowAuthenticatedBroker)
@{ affected = $work.Count -gt 0 } | ConvertTo-Json -Compress
'''.replace("INSTALLER", str(INSTALLER).replace("'", "''"))
    script = script.replace("COMMAND", command.replace("'", "''")).replace("OWNER_STATUS", str(owner_status))
    script = script.replace("EXECUTABLE_PATH", executable_path.replace("'", "''"))
    assert _run_ps(tmp_path, script)["affected"] is affected


@pytest.mark.parametrize("scenario, affected", [
    ("native_child", False),
    ("root_only", True),
    ("wrong_owner", True),
    ("changed_command", True),
    ("orphan", True),
    ("reused_parent_pid", True),
    ("revalidated_parent_reused", True),
    ("hidden_command", True),
    ("hidden_creation", True),
    ("wrong_base_runtime", True),
    ("unauthenticated_task", True),
])
def test_affected_work_authenticates_native_broker_launcher_child(
    tmp_path: Path, scenario: str, affected: bool,
) -> None:
    script = r'''
. 'INSTALLER'
function Get-CatalogChatEntryBrokerBasePythonw { 'C:\Python314\pythonw.exe' }
function Get-LocalUser {
    param($Name)
    $sid = if ($Name -eq 'AURORARequester') { 'S-1-5-21-1-2-3-1015' } else { 'S-1-5-21-1-2-3-1014' }
    [pscustomobject]@{ SID = $sid }
}
function Get-ScheduledTask {
    param($TaskPath)
    if ('SCENARIO' -eq 'unauthenticated_task') { return }
    [pscustomobject]@{
        TaskName = 'AURORA Catalog Requester Broker'; State = 'Running'
        Principal = [pscustomobject]@{ UserId = 'AURORARequester'; RunLevel = 'Limited'; LogonType = 'Password' }
        Actions = @([pscustomobject]@{
            Execute = 'C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts\pythonw.exe'
            Arguments = '-I -s -E "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-broker.pyz"'
            WorkingDirectory = $null
        })
    }
}
$command = '"C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts\pythonw.exe" -I -s -E "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-broker.pyz"'
$root = [pscustomobject]@{
    ProcessId = 100; ParentProcessId = 50; Name = 'pythonw.exe'
    ExecutablePath = 'C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts\pythonw.exe'
    CommandLine = $command; CreationDate = [datetime]'2026-09-07T14:00:00Z'
    OwnerSid = 'S-1-5-21-1-2-3-1015'
}
$child = [pscustomobject]@{
    ProcessId = 101; ParentProcessId = 100; Name = 'pythonw.exe'
    ExecutablePath = 'C:\Python314\pythonw.exe'
    CommandLine = $command; CreationDate = [datetime]'2026-09-07T14:00:02Z'
    OwnerSid = 'S-1-5-21-1-2-3-1015'
}
switch ('SCENARIO') {
    'wrong_owner' { $child.OwnerSid = 'S-1-5-21-1-2-3-1001' }
    'changed_command' { $child.CommandLine += ' --unexpected' }
    'orphan' { $child.ParentProcessId = 99 }
    'reused_parent_pid' { $root.CreationDate = [datetime]'2026-09-07T14:00:03Z' }
    'hidden_command' { $child.CommandLine = $null }
    'hidden_creation' { $child.CreationDate = $null }
    'wrong_base_runtime' { $child.ExecutablePath = 'C:\Users\Public\pythonw.exe' }
}
$global:ProcessFixture = @($root, $child)
if ('SCENARIO' -eq 'root_only') { $global:ProcessFixture = @($root) }
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($Filter -match '^ProcessId\s*=\s*(\d+)$') {
        if ('SCENARIO' -eq 'revalidated_parent_reused') {
            $global:ProcessFixture[0].CreationDate = [datetime]'2026-09-07T14:00:03Z'
        }
        $global:ProcessFixture | Where-Object ProcessId -eq ([int]$Matches[1])
    } else { $global:ProcessFixture }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName)
    if ($MethodName -ne 'GetOwnerSid') { throw 'UNEXPECTED_PROCESS_OPERATION' }
    [pscustomobject]@{ ReturnValue = 0; Sid = $InputObject.OwnerSid }
}
$work = @(Get-CatalogChatEntryAffectedWork -AllowAuthenticatedBroker)
@{ affected = $work.Count -gt 0 } | ConvertTo-Json -Compress
'''.replace("INSTALLER", str(INSTALLER).replace("'", "''"))
    assert _run_ps(tmp_path, script.replace("SCENARIO", scenario))["affected"] is affected


def test_candidate_pin_mismatch_blocks_before_any_live_mutation(tmp_path: Path) -> None:
    candidate, _, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", "0" * 64),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "CANDIDATE_HASH_MISMATCH"
    assert outcome["calls"] == []


@pytest.mark.parametrize("owner_sid, accepted", [
    ("S-1-5-32-544", True),
    ("S-1-5-32-545", False),
])
def test_protected_owner_uses_native_account_identity_not_english_name(
    tmp_path: Path, owner_sid: str, accepted: bool,
) -> None:
    # Resolve the actual OS-localised name; only observation I/O is replaced.
    script = r'''
function Get-CatalogChatEntryAclObservation {
    param([string]$Path)
    $owner = ([Security.Principal.SecurityIdentifier]::new('OWNER_SID')).Translate(
        [Security.Principal.NTAccount]).Value
    return [pscustomobject]@{
        observation_available = $true
        owner = $owner
        sddl = 'O:OWNER_SIDG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)'
        unauthorized_effective_writers = @()
    }
}
. 'INSTALLER'
try {
    $null = Assert-CatalogChatEntryProtectedAcl -LogicalPath 'fixture'
    @{ accepted = $true } | ConvertTo-Json -Compress
} catch {
    @{ accepted = $false; reason = $_.Exception.Message } | ConvertTo-Json -Compress
}
'''.replace("OWNER_SID", owner_sid).replace("INSTALLER", str(INSTALLER))
    outcome = _run_ps(tmp_path, script)
    assert outcome["accepted"] is accepted, outcome
    if not accepted:
        assert outcome["reason"] == "PROTECTED_ACL_OWNER_INVALID"


def test_mismatched_existing_task_blocks_before_content_transaction(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="mismatch",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "TASK_ACTION_MISMATCH"
    assert "register" not in outcome["calls"]
    assert "start" not in outcome["calls"]
    assert outcome["target_config"] == "old config\n"


def test_live_baseline_pin_mismatch_blocks_before_verification_or_mutation(tmp_path: Path) -> None:
    candidate, _, live, _ = _candidate_fixture(tmp_path)
    candidate_data = json.loads((candidate / "candidate.json").read_text(encoding="utf-8"))
    candidate_data["baseline_file_sha256"]["config/production-enabled-v1.seal.json"] = "0" * 64
    candidate_json = json.dumps(
        candidate_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"
    (candidate / "candidate.json").write_bytes(candidate_json)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", _sha256(candidate_json)),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "BASELINE_SEAL_HASH_MISMATCH"
    assert outcome["calls"] == []
    assert outcome["target_config"] == "old config\n"


def test_installed_public_key_change_blocks_before_content_transaction(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    (live / "CatalogRequester/config/catalog_requester_public_key_v1.pem").write_bytes(
        b"-----BEGIN PUBLIC KEY-----\nrotated-key\n"
    )
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "INSTALLED_KEY_MISMATCH"
    assert outcome["calls"] == []
    assert outcome["target_config"] == "old config\n"


def test_positive_controlled_install_uses_real_transaction_and_fixed_task_action(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED"
    assert outcome["result"]["production_verified"] is False
    assert outcome["result"]["task"]["action"]["arguments"].endswith("--serve-chat")
    assert outcome["calls"].count("register") == 1
    assert outcome["calls"].count("start") == 1
    assert outcome["calls"].count("verify:client") >= 2
    assert outcome["calls"].count("verify:broker") >= 2
    assert outcome["target_config"] == "candidate requester config\n"
    assert (tmp_path / "AURORA-CatalogChatMaintenance" / "manifest.json").is_file()


@pytest.mark.parametrize("failure", [None, "postverify", "cas", "pending_intent", "busy_lock", "frozen_candidate"])
def test_lineage_files_share_application_transaction_and_rollback(tmp_path: Path, failure: str | None) -> None:
    import base64

    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    original_config = (live / "CatalogRequester/config/catalog_requester_v1.json").read_bytes()
    rows = []
    (live / 'CatalogRequester/chat-intents/.service.lock').touch()
    for directory, suffix in (("launch-tickets", "ticket"), ("campaign-status", "journal"), ("campaign-status", "status")):
        relative = f"CatalogRequester/{directory}/example-v1.{suffix}.json"
        path = live / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old lineage\n")
        new = b"new lineage\n"
        rows.append({"path": relative, "expected_old_sha256": _sha256(path.read_bytes()),
            "sha256": _sha256(new), "content_base64": base64.b64encode(new).decode()})
    if failure == "cas":
        rows[-1]["expected_old_sha256"] = "f" * 64
    outcome = _run_ps(tmp_path, _transport_fixture(installer=INSTALLER, candidate=candidate,
        live=live, task_mode="absent", broker_running=True, fail_postverify=failure == "postverify",
        lineage_idle_failure=failure == "pending_intent", lineage_hold_lock=failure == "busy_lock",
        check_candidate_freeze=failure == "frozen_candidate",
        lineage_records=rows).replace("EXPECTED_HASH", candidate_hash))
    if failure == "frozen_candidate":
        failure = None
    expected = "BLOCKED" if failure else "INSTALLED_NOT_QUALIFIED"
    assert outcome["result"]["status"] == expected, outcome
    assert outcome["calls"].index("stop-broker") < outcome["calls"].index("prepare-lineage")
    for row in rows:
        assert (live / row["path"]).read_bytes() == (b"old lineage\n" if failure else b"new lineage\n")
    if failure:
        assert (live / "CatalogRequester/config/catalog_requester_v1.json").read_bytes() == original_config
    if failure == "postverify":
        assert outcome["result"]["rollback"]["status"] == "ROLLED_BACK", outcome
    elif failure is None:
        installed = {row["path"] for row in outcome["result"]["transaction"]["files"]}
        assert {row["path"] for row in rows} <= installed
        assert "CatalogChatSender/submit_catalog_chat_intent.py" in installed


def test_new_maintenance_receipt_is_protected_before_postinstall_verification(
    tmp_path: Path,
) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED"
    receipt_acl_calls = [
        call
        for call in outcome["calls"]
        if call.endswith("requester-maintenance-v1.receipt.json")
    ]
    assert len(receipt_acl_calls) == 1


def test_new_receipt_security_has_fixed_narrow_native_acl(tmp_path: Path) -> None:
    script = r'''
function Get-LocalUser {
    param([string]$Name)
    $sid = @{
        AURORAAgent = 'S-1-5-21-1-2-3-1014'
        AURORARequester = 'S-1-5-21-1-2-3-1015'
    }[$Name]
    [pscustomobject]@{ SID = $sid }
}
. 'INSTALLER'
try {
    $security = New-CatalogChatEntryMaintenanceReceiptSecurity
    $rules = @($security.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    [pscustomobject]@{
        available = $true
        protected = [bool]$security.AreAccessRulesProtected
        owner = $security.GetOwner([Security.Principal.SecurityIdentifier]).Value
        rules = @($rules | ForEach-Object {
            [pscustomobject]@{
                sid = $_.IdentityReference.Value
                rights = [string]$_.FileSystemRights
                inherited = [bool]$_.IsInherited
            }
        })
    } | ConvertTo-Json -Depth 10 -Compress
} catch {
    @{ available = $false; reason = $_.Exception.Message } | ConvertTo-Json -Compress
}
'''.replace("INSTALLER", str(INSTALLER).replace("'", "''"))
    outcome = _run_ps(tmp_path, script)
    assert outcome["available"] is True, outcome
    assert outcome["protected"] is True
    assert outcome["owner"] == "S-1-5-32-544"
    assert sorted(rule["sid"] for rule in outcome["rules"]) == sorted(
        [
            "S-1-5-18",
            "S-1-5-32-544",
            "S-1-5-21-1-2-3-1014",
            "S-1-5-21-1-2-3-1015",
        ]
    )
    assert all(rule["inherited"] is False for rule in outcome["rules"])
    rights_by_sid = {rule["sid"]: rule["rights"] for rule in outcome["rules"]}
    assert rights_by_sid["S-1-5-18"] == "FullControl"
    assert rights_by_sid["S-1-5-32-544"] == "FullControl"
    assert rights_by_sid["S-1-5-21-1-2-3-1014"].startswith("ReadAndExecute")
    assert rights_by_sid["S-1-5-21-1-2-3-1015"].startswith("ReadAndExecute")


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


def test_existing_maintenance_receipt_acl_is_preserved(tmp_path: Path) -> None:
    candidate, candidate_hash, live, requester = _candidate_fixture(
        tmp_path, maintenance_receipt_present=True
    )
    before = (requester / "receipts/requester-maintenance-v1.receipt.json").read_bytes()
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED"
    assert (requester / "receipts/requester-maintenance-v1.receipt.json").read_bytes() != before
    assert not any(
        call.endswith("requester-maintenance-v1.receipt.json") for call in outcome["calls"]
    )


def test_receipt_acl_failure_rolls_back_created_receipt_before_task_creation(
    tmp_path: Path,
) -> None:
    candidate, candidate_hash, live, requester = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            receipt_acl_failure=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    result = outcome["result"]
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "RECEIPT_ACL_FAILED"
    assert result["cause"] == "TEST_RECEIPT_ACL_FAILURE"
    assert "register" not in outcome["calls"]
    assert "start" not in outcome["calls"]
    assert not (requester / "receipts/requester-maintenance-v1.receipt.json").exists()
    assert outcome["target_config"] == "old config\n"
    assert result["rollback"]["status"] == "ROLLED_BACK"


@pytest.mark.parametrize("case", ["nonowned", "changed"])
def test_receipt_ownership_guard_rejects_nonowned_or_changed_file(
    tmp_path: Path, case: str
) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    script = _transport_fixture(
        installer=INSTALLER,
        candidate=candidate,
        live=live,
        task_mode="absent",
    ).replace("EXPECTED_HASH", candidate_hash)
    injected = r'''
$relative = 'CatalogRequester/receipts/requester-maintenance-v1.receipt.json'
if ('CASE' -eq 'nonowned') {
    $transaction = [pscustomobject]@{
        status = 'APPLIED'
        created_paths = @('CatalogRequester/receipts/other.receipt.json')
        files = @([pscustomobject]@{
            path = $relative; created = $false; new_sha256 = ('A' * 64); identity_after = 'not-used'
        })
    }
} else {
    $physical = Join-Path $global:LiveRoot $relative
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($physical)) | Out-Null
    [IO.File]::WriteAllText($physical, 'before', [Text.UTF8Encoding]::new($false))
    $logical = Join-Path 'C:\ProgramData\AURORA' $relative
    $expectedHash = Get-CatalogChatEntryFileHash -LogicalPath $logical
    $identity = Get-CatalogChatEntryFileIdentity -LogicalPath $logical
    [IO.File]::WriteAllText($physical, 'changed', [Text.UTF8Encoding]::new($false))
    $transaction = [pscustomobject]@{
        status = 'APPLIED'
        created_paths = @($relative)
        files = @([pscustomobject]@{
            path = $relative; created = $true; new_sha256 = $expectedHash
            identity_after = ($identity -replace ':[^:]+$', '')
        })
    }
}
try {
    Assert-CatalogChatEntryMaintenanceReceiptOwnership -Transaction $transaction -ExpectedHash $transaction.files[0].new_sha256
    @{ rejected = $false } | ConvertTo-Json -Compress
} catch {
    @{ rejected = $true; reason = $_.Exception.Message } | ConvertTo-Json -Compress
}
exit
'''.replace("CASE", case)
    script = script.replace(
        "$result = Invoke-CatalogChatEntryInstallation",
        injected + "`n$result = Invoke-CatalogChatEntryInstallation",
    )
    outcome = _run_ps(tmp_path, script)
    assert outcome["rejected"] is True, outcome


def test_first_install_provisions_only_chat_config_and_missing_directories(tmp_path: Path) -> None:
    candidate, candidate_hash, live, live_requester = _candidate_fixture(
        tmp_path, chat_dirs_present=False, config_present=False
    )
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED"
    assert len(outcome["result"]["resources"]) == 4
    assert json.loads(
        (live_requester / "config/chat-entry-v1.json").read_text(encoding="utf-8")
    ) == {"schema_version": "1", "sender_sid": "S-1-5-21-1-2-3-1001"}
    for name in ("chat-inbox", "chat-intents", "chat-replies"):
        assert (live_requester / name).is_dir()


def test_first_install_creates_missing_public_sender_directory(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    sender = live / "CatalogChatSender"
    # This fixture's sender directory is empty, not an installed application.
    sender.rmdir()
    outcome = _run_ps(tmp_path, _transport_fixture(
        installer=INSTALLER, candidate=candidate, live=live, task_mode="absent",
    ).replace("EXPECTED_HASH", candidate_hash))
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED", outcome
    assert (sender / "submit_catalog_chat_intent.py").read_bytes() == b"sender\n"
    assert any(item["path"].endswith("CatalogChatSender") for item in outcome["result"]["resources"])


def test_existing_valid_chat_resources_are_not_modified(tmp_path: Path) -> None:
    candidate, candidate_hash, live, live_requester = _candidate_fixture(tmp_path)
    config_before = (live_requester / "config/chat-entry-v1.json").read_bytes()
    directory_names = ("chat-inbox", "chat-intents", "chat-replies")
    directory_markers = {
        name: (live_requester / name).stat().st_mtime_ns for name in directory_names
    }
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED"
    assert (live_requester / "config/chat-entry-v1.json").read_bytes() == config_before
    assert {
        name: (live_requester / name).stat().st_mtime_ns for name in directory_names
    } == directory_markers
    assert [call for call in outcome["calls"] if call.startswith("acl:")] == [
        r"acl:C:\ProgramData\AURORA\CatalogRequester\receipts\requester-maintenance-v1.receipt.json"
    ]


def test_acl_failure_after_config_creation_cleans_owned_file(tmp_path: Path) -> None:
    candidate, candidate_hash, live, requester = _candidate_fixture(tmp_path, config_present=False)
    script = _transport_fixture(
        installer=INSTALLER, candidate=candidate, live=live, task_mode="absent",
    ).replace("EXPECTED_HASH", candidate_hash)
    script = script.replace('$global:Calls.Add("acl:$Path")',
                            'throw "TEST_RESOURCE_ACL_FAILURE"')
    outcome = _run_ps(tmp_path, script)
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "TEST_RESOURCE_ACL_FAILURE"
    assert not (requester / "config/chat-entry-v1.json").exists()
    assert outcome["target_config"] == "old config\n"


@pytest.mark.parametrize("stop_again_fails", [False, True])
def test_final_result_failure_stops_resumed_broker_before_undo(tmp_path: Path, stop_again_fails: bool) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    script = _transport_fixture(
        installer=INSTALLER, candidate=candidate, live=live,
        task_mode="absent", broker_running=True,
    ).replace("EXPECTED_HASH", candidate_hash)
    script = script.replace("$result = Invoke-CatalogChatEntryInstallation",
        'function Get-CatalogChatEntryTaskOutput { param($Task) '
        + ('$global:BrokerStopFailure = $true; ' if stop_again_fails else '')
        + 'throw "TEST_FINAL_RESULT_FAILURE" }\n'
        +
        "$result = Invoke-CatalogChatEntryInstallation")
    outcome = _run_ps(tmp_path, script)
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "TEST_FINAL_RESULT_FAILURE"
    assert outcome["calls"].count("stop-broker") == 2, outcome
    if stop_again_fails:
        assert outcome["target_config"] == "candidate requester config\n"
        assert outcome["result"]["rollback"]["status"] == "BLOCKED_BROKER_STOP"
        assert outcome["result"]["rollback"]["content_undo"] == "NOT_ATTEMPTED"
    else:
        assert outcome["target_config"] == "old config\n"
        assert outcome["result"]["rollback"]["status"] == "ROLLED_BACK"


@pytest.mark.parametrize("defect, accepted", [
    ("none", True),
    ("missing_file_delete", False),
    ("delete_on_inbox", False),
    ("delete_on_subdirectories", False),
    ("write_dacl", False),
    ("agent_delete", False),
])
def test_inbox_acl_requires_file_only_sender_delete(
    tmp_path: Path, defect: str, accepted: bool,
) -> None:
    script = r'''
. 'INSTALLER_PATH'
function Get-LocalUser {
    param([string]$Name)
    $sid = @{ HP = 'S-1-5-21-1-2-3-1001'; AURORAAgent = 'S-1-5-21-1-2-3-1014' }[$Name]
    [pscustomobject]@{ SID = $sid }
}
function Get-CatalogChatEntryAclObservation {
    param([string]$Path)
    $rules = @(
        [pscustomobject]@{ identity='S-1-5-18'; rights='FullControl'; access_type='Allow'; is_inherited=$false; inheritance_flags='ContainerInherit, ObjectInherit'; propagation_flags='None' },
        [pscustomobject]@{ identity='S-1-5-32-544'; rights='FullControl'; access_type='Allow'; is_inherited=$false; inheritance_flags='ContainerInherit, ObjectInherit'; propagation_flags='None' },
        [pscustomobject]@{ identity='S-1-5-21-1-2-3-1001'; rights='ReadAndExecute, Write, Synchronize'; access_type='Allow'; is_inherited=$false; inheritance_flags='ContainerInherit, ObjectInherit'; propagation_flags='None' },
        [pscustomobject]@{ identity='S-1-5-21-1-2-3-1014'; rights='ReadAndExecute'; access_type='Allow'; is_inherited=$false; inheritance_flags='ContainerInherit, ObjectInherit'; propagation_flags='None' }
    )
    $delete = [pscustomobject]@{ identity='S-1-5-21-1-2-3-1001'; rights='Delete, Synchronize'; access_type='Allow'; is_inherited=$false; inheritance_flags='ObjectInherit'; propagation_flags='InheritOnly' }
    switch ('DEFECT') {
        'delete_on_inbox' { $delete.propagation_flags = 'None' }
        'delete_on_subdirectories' { $delete.inheritance_flags = 'ContainerInherit, ObjectInherit' }
        'write_dacl' { $delete.rights = 'Delete, ChangePermissions, Synchronize' }
        'agent_delete' { $delete.identity = 'S-1-5-21-1-2-3-1014' }
    }
    if ('DEFECT' -cne 'missing_file_delete') { $rules += $delete }
    [pscustomobject]@{ observation_available=$true; owner='S-1-5-32-544'; sddl='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)'; access_rules=$rules }
}
try {
    [void](Assert-CatalogChatEntryResourceAcl -LogicalPath 'test-inbox' -Kind inbox)
    [pscustomobject]@{accepted=$true;cause=$null} | ConvertTo-Json -Compress
}
catch { [pscustomobject]@{accepted=$false;cause=$_.Exception.Message} | ConvertTo-Json -Compress }
'''.replace("INSTALLER_PATH", str(INSTALLER)).replace("DEFECT", defect)
    outcome = _run_ps(tmp_path, script)
    assert outcome["accepted"] is accepted, outcome


def test_incorrect_chat_resource_acl_blocks_before_payload_bytes(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            bad_resource_acl=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "RESOURCE_ACL_RULES_INVALID"
    assert outcome["calls"] == []
    assert outcome["target_config"] == "old config\n"


def test_running_authenticated_broker_is_paused_verified_and_resumed(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            broker_running=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "INSTALLED_NOT_QUALIFIED"
    assert "disable-broker" in outcome["calls"]
    assert "stop-broker" in outcome["calls"]
    assert "enable-broker" in outcome["calls"]
    assert "start-broker" in outcome["calls"]
    assert outcome["calls"].index("stop-broker") < outcome["calls"].index("verify:client", 2)
    assert outcome["result"]["broker_resume"]["status"] == "RESTORED"


def test_postinstall_failure_rolls_back_before_resuming_running_broker(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            fail_postverify=True,
            broker_running=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["rollback"]["status"] == "ROLLED_BACK"
    assert outcome["calls"].index("stop-broker") < outcome["calls"].index("verify:client", 2)
    assert outcome["calls"].index("start-broker") > outcome["calls"].index("verify:client", 2)
    assert outcome["target_config"] == "old config\n"


def test_undo_blocked_keeps_running_broker_stopped(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            fail_postverify=True,
            undo_blocked=True,
            broker_running=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["rollback"]["status"] == "BLOCKED"
    assert "start-broker" not in outcome["calls"]
    assert outcome["result"]["broker_resume"] is None
    assert outcome["target_config"] == "drifted config"


def test_broker_stop_failure_writes_no_payload(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            broker_running=True,
            broker_stop_failure=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "BROKER_STOP_FAILED"
    assert "stop-broker" in outcome["calls"]
    assert "register" not in outcome["calls"]
    assert outcome["target_config"] == "old config\n"


def test_chat_stop_failure_prevents_undo_and_broker_resume(tmp_path: Path) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            broker_running=True,
            chat_stop_failure=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    result = outcome["result"]
    assert result["status"] == "BLOCKED"
    assert result["rollback"]["status"] == "BLOCKED_CONSUMER_STOP"
    assert "CHAT_TASK_STOP_FAILED" in result["rollback"]["cause"]
    assert "start-broker" not in outcome["calls"]
    assert result["rollback"]["content_undo"] == "NOT_ATTEMPTED"
    assert outcome["target_config"] == "candidate requester config\n"


def test_postinstall_failure_stops_owned_task_undoes_applied_transaction_and_keeps_cause(
    tmp_path: Path,
) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            fail_postverify=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["reason_code"] == "POSTINSTALL_VERIFY_FAILED"
    assert "TEST_POSTVERIFY_FAILURE" in outcome["result"]["cause"]
    assert outcome["result"]["rollback"]["status"] == "ROLLED_BACK"
    # Post-verification fails before TASK_START; never launch merely to stop it.
    assert "start" not in outcome["calls"]
    assert "stop" not in outcome["calls"]
    assert "unregister" in outcome["calls"]
    assert outcome["target_config"] == "old config\n"


def test_undo_blocked_state_is_propagated_without_claiming_rollback(
    tmp_path: Path,
) -> None:
    candidate, candidate_hash, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(
        tmp_path,
        _transport_fixture(
            installer=INSTALLER,
            candidate=candidate,
            live=live,
            task_mode="absent",
            fail_postverify=True,
            undo_blocked=True,
        ).replace("EXPECTED_HASH", candidate_hash),
    )
    result = outcome["result"]
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "POSTINSTALL_VERIFY_FAILED"
    assert "TEST_POSTVERIFY_FAILURE" in result["cause"]
    assert result["rollback"]["status"] == "BLOCKED"
    assert result["rollback"]["status"] != "ROLLED_BACK"
    assert result["rollback"]["cause"] == result["rollback"]["result"]["cause"]
    assert "start" not in outcome["calls"]
    assert "stop" not in outcome["calls"]
    assert "unregister" in outcome["calls"]
    assert outcome["target_config"] == "drifted config"


def test_review_partial_transaction_rollback_failure_never_resumes_broker(tmp_path: Path) -> None:
    candidate, digest, live, _ = _candidate_fixture(tmp_path)
    script = _transport_fixture(installer=INSTALLER, candidate=candidate, live=live,
                                task_mode="absent", broker_running=True).replace("EXPECTED_HASH", digest)
    injected = '''
function Invoke-CatalogChatContentTransaction {
    param($PayloadRoot, $TargetRoot, $BackupRoot, $Files)
    [IO.File]::WriteAllText((Join-Path $TargetRoot 'CatalogRequester/config/catalog_requester_v1.json'), 'partial-content')
    [pscustomobject]@{ status='BLOCKED'; cause='TEST_PARTIAL_WRITE'; rollback=[pscustomobject]@{status='ROLLBACK_FAILED'; error='TEST_RESTORE_FAILED'} }
}
'''
    script = script.replace("$result = Invoke-CatalogChatEntryInstallation", injected + "$result = Invoke-CatalogChatEntryInstallation")
    outcome = _run_ps(tmp_path, script)
    assert "start-broker" not in outcome["calls"], outcome
    assert outcome["result"]["rollback"]["status"] == "ROLLBACK_FAILED"
    assert outcome["result"]["rollback"]["error"] == "TEST_RESTORE_FAILED"
    assert outcome["target_config"] == "partial-content"


def test_review_existing_chat_start_error_after_start_cannot_undo(tmp_path: Path) -> None:
    candidate, digest, live, _ = _candidate_fixture(tmp_path)
    outcome = _run_ps(tmp_path, _transport_fixture(
        installer=INSTALLER, candidate=candidate, live=live, task_mode="exact",
        chat_stop_failure=True,
    ).replace("EXPECTED_HASH", digest))
    assert outcome["result"]["rollback"]["status"] == "BLOCKED_CONSUMER_STOP", outcome
    assert outcome["target_config"] == "candidate requester config\n"


def test_review_disabled_broker_remains_disabled_after_start_failure(tmp_path: Path) -> None:
    candidate, digest, live, _ = _candidate_fixture(tmp_path)
    script = _transport_fixture(installer=INSTALLER, candidate=candidate, live=live,
        task_mode="absent", broker_running=True, broker_start_failure=True).replace("EXPECTED_HASH", digest)
    script = script.replace('$global:BrokerEnabled = $true', '$global:BrokerEnabled = $false', 1)
    script = script.replace('result = $result', 'result = $result\n    broker_enabled = $global:BrokerEnabled')
    outcome = _run_ps(tmp_path, script)
    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["broker_enabled"] is False, outcome


def test_review_existing_sender_without_user_read_is_rejected(tmp_path: Path) -> None:
    candidate, digest, live, _ = _candidate_fixture(tmp_path)
    script = _transport_fixture(installer=INSTALLER, candidate=candidate, live=live,
                                task_mode="absent").replace("EXPECTED_HASH", digest)
    script = script.replace('access_rules = $rules',
        "access_rules = @($rules | Where-Object { $Path -notlike '*CatalogChatSender' -or $_.identity -ne 'S-1-5-21-1-2-3-1001' })")
    outcome = _run_ps(tmp_path, script)
    assert outcome["result"]["status"] == "BLOCKED", outcome
    assert outcome["calls"] == []


def test_review_candidate_registry_requires_campaign_array(tmp_path: Path) -> None:
    script = f". '{str(INSTALLER).replace(chr(39), chr(39) * 2)}'\n" + '''
try {
    $null = Get-CatalogChatEntryActiveDefinitionPaths -RegistryText '{"schema_version":"1","campaigns":{"active":true,"campaign_key":"example-v1","definition_manifest_path":"config/catalog_campaign_definitions/example-v1.manifest.json"}}'
    @{ rejected = $false } | ConvertTo-Json -Compress
} catch {
    @{ rejected = ($_.Exception.Message -eq 'CANDIDATE_REGISTRY_INVALID') } | ConvertTo-Json -Compress
}
'''
    assert _run_ps(tmp_path, script)["rejected"] is True
