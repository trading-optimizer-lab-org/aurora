[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Confirm = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TargetIdentity = "AURORAAgent"
$InstallRoot = "C:\ProgramData\AURORA\CatalogAgent"
$BrokerRoot = "C:\ProgramData\AURORA\CatalogRequester"
$CredentialRoot = Join-Path $InstallRoot "credentials"
$CredentialPath = Join-Path $CredentialRoot "catalog-agent-credential.dpapi"
$ProfileRoot = Join-Path $InstallRoot "profile"
$ProfilePath = "C:\ProgramData\AURORA\CatalogAgent\profile\config.toml"
$ExpectedConfirmation = "AURORA_CATALOG_AGENT_SANDBOX_V1"
$SystemAcl = "*S-1-5-18"
$AdministratorsAcl = "*S-1-5-32-544"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-SecretPassword {
    $bytes = [byte[]]::new(48)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $plain = [Convert]::ToBase64String($bytes) + "!aA7"
    try {
        return ConvertTo-SecureString -String $plain -AsPlainText -Force
    }
    finally {
        $plain = $null
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

$Plan = [ordered]@{
    schema_version = "1"
    mode = if ($Apply) { "apply" } else { "dry_run" }
    mutation_performed = $false
    production_enabled = $false
    target_identity = $TargetIdentity
    target_is_non_admin = $true
    install_root = $InstallRoot
    broker_root = $BrokerRoot
    repository_access = "unproven_until_codex_host_audit"
    broker_access = [ordered]@{
        status = "unproven_until_broker_installer_and_codex_host_audit"
    }
    browser_profile_or_connector = "unproven_until_codex_host_audit"
    inherited_user_credentials = "unproven_until_codex_host_audit"
    final_capability_result = "BLOCKED_AGENT_SANDBOX_NOT_ENFORCEABLE_UNTIL_CODEX_HOST_RESTART"
}

if (-not $Apply) {
    $Plan | ConvertTo-Json -Depth 8 -Compress
    exit 0
}

if ($Confirm -cne $ExpectedConfirmation) {
    throw "CONFIRMATION_REQUIRED:$ExpectedConfirmation"
}
if ($env:OS -ne "Windows_NT") {
    throw "BLOCKED_AGENT_SANDBOX_WINDOWS_REQUIRED"
}
if (-not (Test-IsAdministrator)) {
    throw "BLOCKED_AGENT_SANDBOX_ADMIN_BOOTSTRAP_REQUIRED"
}
if (-not (Get-Command Get-LocalUser -ErrorAction SilentlyContinue)) {
    throw "BLOCKED_AGENT_SANDBOX_LOCAL_ACCOUNT_API_UNAVAILABLE"
}

$Existing = Get-LocalUser -Name $TargetIdentity -ErrorAction SilentlyContinue
$Password = New-SecretPassword
try {
    if ($null -eq $Existing) {
        New-LocalUser -Name $TargetIdentity -Password $Password `
            -AccountNeverExpires -PasswordNeverExpires `
            -UserMayNotChangePassword -Description "AURORA isolated Codex agent" | Out-Null
    }
    else {
        Set-LocalUser -Name $TargetIdentity -Password $Password
    }
}
finally {
    $PasswordForStorage = $Password
    $Password = $null
}

$AdminGroup = Get-LocalGroup -SID "S-1-5-32-544"
$AdminMember = Get-LocalGroupMember -Group $AdminGroup -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "\\$([Regex]::Escape($TargetIdentity))$" }
if ($null -ne $AdminMember) {
    Remove-LocalGroupMember -Group $AdminGroup -Member $TargetIdentity
}
$InstalledUser = Get-LocalUser -Name $TargetIdentity
if (-not $InstalledUser.Enabled) {
    Enable-LocalUser -Name $TargetIdentity
}
$AdminReadback = Get-LocalGroupMember -Group $AdminGroup -ErrorAction SilentlyContinue |
    Where-Object { $_.SID -eq (Get-LocalUser -Name $TargetIdentity).SID }
if ($null -ne $AdminReadback) {
    throw "BLOCKED_AGENT_SANDBOX_ACCOUNT_IS_ADMIN"
}

if (-not (Test-Path -LiteralPath $InstallRoot)) {
    New-Item -ItemType Directory -Path $InstallRoot | Out-Null
}
& icacls.exe $InstallRoot /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
    "${TargetIdentity}:(OI)(CI)(RX)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_AGENT_SANDBOX_ACL_APPLY_FAILED"
}
New-Item -ItemType Directory -Path $CredentialRoot, $ProfileRoot -Force | Out-Null
& icacls.exe $CredentialRoot /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_AGENT_SANDBOX_CREDENTIAL_ACL_FAILED" }
& icacls.exe $ProfileRoot /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
    "${TargetIdentity}:(OI)(CI)(M)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_AGENT_SANDBOX_PROFILE_ACL_FAILED" }
$ProtectedPassword = ConvertFrom-SecureString -SecureString $PasswordForStorage
[IO.File]::WriteAllText($CredentialPath, $ProtectedPassword, [Text.UTF8Encoding]::new($false))
$PasswordForStorage = $null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\config\catalog_agent_codex_profile_v1.toml") `
    -Destination $ProfilePath -Force

$User = Get-LocalUser -Name $TargetIdentity
$Plan.mutation_performed = $true
$Plan.target_sid = $User.SID.Value
$Plan.account_enabled = $User.Enabled
$Plan.final_capability_result = "PREPARED_RESTART_AND_PROCESS_AUDIT_REQUIRED"
$Plan | ConvertTo-Json -Depth 8 -Compress
exit 0
