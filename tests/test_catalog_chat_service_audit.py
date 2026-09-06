"""Execute the actual read-only lifecycle audit against controlled OS responses."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_catalog_chat_service.ps1"


@pytest.mark.parametrize("fault, expected", [
    ("none", "CHAT_SERVICE_RUNNING"),
    ("missing", "CHAT_SERVICE_TASK_MISSING"),
    ("command", "CHAT_SERVICE_ACTION_INVALID"),
    ("principal", "CHAT_SERVICE_PRINCIPAL_INVALID"),
    ("owner", "CHAT_SERVICE_PROCESS_INVALID"),
    ("stopped", "CHAT_SERVICE_NOT_RUNNING"),
])
def test_lifecycle_audit_checks_actual_task_and_process(tmp_path, fault, expected):
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    fixture = tmp_path / "audit.ps1"
    fixture.write_text(r'''
$ErrorActionPreference = 'Stop'
$Fault = 'FAULT'
function Get-LocalUser { [pscustomobject]@{ SID = 'S-1-5-21-1-2-3-1002' } }
function Get-ScheduledTask {
    if ($Fault -eq 'missing') { return $null }
    $arguments = '-I -s -E "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz" --serve-chat'
    if ($Fault -eq 'command') { $arguments += ' --campaign-key unwanted' }
    [pscustomobject]@{
        TaskName = 'AURORA Catalog Chat Entry'
        State = $(if ($Fault -eq 'stopped') { 'Ready' } else { 'Running' })
        Principal = [pscustomobject]@{
            UserId = $(if ($Fault -eq 'principal') { 'HP' } else { 'S-1-5-21-1-2-3-1002' })
            RunLevel = 'Limited'
        }
        Actions = @([pscustomobject]@{
            Execute = 'C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe'
            Arguments = $arguments
            WorkingDirectory = 'C:\ProgramData\AURORA\CatalogRequester'
        })
    }
}
function Get-CimInstance {
    [pscustomobject]@{
        ProcessId = 4242
        ExecutablePath = 'C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe'
        CommandLine = '"C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe" -I -s -E "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz" --serve-chat'
    }
}
function Invoke-CimMethod {
    [pscustomobject]@{ ReturnValue = 0; User = $(if ($Fault -eq 'owner') { 'HP' } else { 'AURORAAgent' }); Domain = $env:COMPUTERNAME }
}
function Start-Process { throw 'audit must never start processes' }
function Set-ScheduledTask { throw 'audit must never change tasks' }
function Register-ScheduledTask { throw 'audit must never create tasks' }
. 'SCRIPT'
Get-CatalogChatServiceStatus | ConvertTo-Json -Compress
'''.replace("FAULT", fault).replace("SCRIPT", str(SCRIPT)), encoding="utf-8")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(fixture)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["reason_code"] == expected
    assert status["status"] == ("RUNNING" if fault == "none" else "BLOCKED")
    assert status["production_verified"] is False
