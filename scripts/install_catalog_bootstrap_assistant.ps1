[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Confirm = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedConfirmation = "AURORA_CATALOG_BOOTSTRAP_ASSISTANT_V1"
$InstallRoot = "C:\ProgramData\AURORA\CatalogBootstrap"
$Repository = "trading-optimizer-lab-org/aurora"
$Branch = "main"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AllowedRemotes = @(
    "https://github.com/trading-optimizer-lab-org/aurora.git",
    "git@github.com:trading-optimizer-lab-org/aurora.git",
    "ssh://git@github.com/trading-optimizer-lab-org/aurora.git"
)

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$Receipt = [ordered]@{
    schema_version = "1"
    mode = if ($Apply) { "apply" } else { "dry_run" }
    mutation_performed = $false
    production_enabled = $false
    install_root = $InstallRoot
    repository = $Repository
}

if (-not $Apply) {
    $Receipt | ConvertTo-Json -Compress
    exit 0
}
if ($Confirm -cne $ExpectedConfirmation) {
    throw "CONFIRMATION_REQUIRED:$ExpectedConfirmation"
}
if (-not (Test-IsAdministrator)) {
    throw "BLOCKED_BOOTSTRAP_ADMIN_REQUIRED"
}
if (Test-Path -LiteralPath (Join-Path $RepoRoot ".git\index.lock")) {
    throw "BLOCKED_BOOTSTRAP_GIT_WRITER_ACTIVE"
}
$Remote = (& git -C $RepoRoot remote get-url origin).Trim()
if ($AllowedRemotes -cnotcontains $Remote) {
    throw "BLOCKED_BOOTSTRAP_REMOTE_INVALID"
}
if ((& git -C $RepoRoot branch --show-current).Trim() -cne $Branch) {
    throw "BLOCKED_BOOTSTRAP_BRANCH_INVALID"
}
& git -C $RepoRoot fetch origin main --quiet
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_BOOTSTRAP_FETCH_FAILED" }
$Head = (& git -C $RepoRoot rev-parse HEAD).Trim()
$ProtectedHead = (& git -C $RepoRoot rev-parse origin/main).Trim()
if ($Head -cne $ProtectedHead) {
    throw "BLOCKED_BOOTSTRAP_NOT_PROTECTED_HEAD"
}
if (@(& git -C $RepoRoot status --porcelain=v1 --untracked-files=no).Count -ne 0) {
    throw "BLOCKED_BOOTSTRAP_TRACKED_TREE_DIRTY"
}
$ControllerValue = (& gh variable get CATALOG_CONTROLLER_ENABLED --repo $Repository).Trim()
if ($ControllerValue -cne "false") {
    throw "BLOCKED_BOOTSTRAP_CONTROLLER_NOT_DISABLED"
}

$BuildRoot = Join-Path ([IO.Path]::GetTempPath()) ("aurora-bootstrap-build-" + [Guid]::NewGuid().ToString("N"))
$BuildOne = Join-Path $BuildRoot "one"
$BuildTwo = Join-Path $BuildRoot "two"
New-Item -ItemType Directory -Path $BuildOne, $BuildTwo | Out-Null
try {
    & "C:\Python314\python.exe" (Join-Path $RepoRoot "scripts\build_catalog_bootstrap_assistant.py") --output $BuildOne
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED_BOOTSTRAP_BUILD_FAILED" }
    & "C:\Python314\python.exe" (Join-Path $RepoRoot "scripts\build_catalog_bootstrap_assistant.py") --output $BuildTwo
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED_BOOTSTRAP_BUILD_FAILED" }
    foreach ($Name in @("catalog-bootstrap-assistant.pyz", "catalog-bootstrap-application-manifest-v1.json")) {
        $FirstHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $BuildOne $Name)).Hash
        $SecondHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $BuildTwo $Name)).Hash
        if ($FirstHash -cne $SecondHash) { throw "BLOCKED_BOOTSTRAP_BUILD_NONDETERMINISTIC" }
    }
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    & icacls.exe $InstallRoot /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED_BOOTSTRAP_ACL_FAILED" }
    foreach ($Directory in @("state", "secrets", "receipts")) {
        New-Item -ItemType Directory -Path (Join-Path $InstallRoot $Directory) -Force | Out-Null
    }
    $Context = [ordered]@{
        repository = $Repository
        source_commit_sha = $Head
        source_root = $RepoRoot
    }
    [IO.File]::WriteAllText(
        (Join-Path $InstallRoot "install-context-v1.json"),
        (($Context | ConvertTo-Json -Compress) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    Copy-Item -LiteralPath (Join-Path $BuildOne "catalog-bootstrap-assistant.pyz") -Destination $InstallRoot -Force
    Copy-Item -LiteralPath (Join-Path $BuildOne "catalog-bootstrap-application-manifest-v1.json") -Destination $InstallRoot -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "scripts\start_catalog_bootstrap_assistant.ps1") -Destination $InstallRoot -Force
    foreach ($ScriptName in @(
        "apply_catalog_github_controls.py",
        "audit_catalog_github_controls.py",
        "build_catalog_requester_apps.py",
        "install_catalog_agent_sandbox.ps1",
        "install_catalog_requester_broker.ps1",
        "launch_catalog_codex_secure.ps1"
    )) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot "scripts\$ScriptName") -Destination $InstallRoot -Force
    }
    if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot "venv\Scripts\python.exe"))) {
        & "C:\Python314\python.exe" -m venv (Join-Path $InstallRoot "venv")
    }
    & (Join-Path $InstallRoot "venv\Scripts\python.exe") -m pip install --require-hashes -r (Join-Path $RepoRoot "requirements\catalog-bootstrap-win-py314.lock")
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED_BOOTSTRAP_DEPENDENCY_INSTALL_FAILED" }
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Instalar controlador AURORA.lnk"))
    $Shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$InstallRoot\start_catalog_bootstrap_assistant.ps1`""
    $Shortcut.WorkingDirectory = $InstallRoot
    $Shortcut.Save()
    $Receipt.mutation_performed = $true
    $Receipt.installed_archive_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $InstallRoot "catalog-bootstrap-assistant.pyz")).Hash.ToLowerInvariant()
}
finally {
    if (Test-Path -LiteralPath $BuildRoot) { Remove-Item -LiteralPath $BuildRoot -Recurse -Force }
}
$Receipt | ConvertTo-Json -Compress
