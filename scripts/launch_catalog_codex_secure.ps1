[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TargetIdentity = "AURORAAgent"
$PackageFamily = "OpenAI.Codex_2p2nqsd0c76g0"
$ExpectedPublisher = "CN=50BDFD77-8903-4850-9FFE-6E8522F64D5B"
$AgentRoot = "C:\ProgramData\AURORA\CatalogAgent"
$CredentialPath = Join-Path $AgentRoot "credentials\catalog-agent-credential.dpapi"
$ProfileRoot = Join-Path $AgentRoot "profile"
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name.Split("\")[-1]

function Get-CodeProcessOwners {
    $Rows = @()
    foreach ($Process in (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @("ChatGPT.exe", "codex.exe") })) {
        $Owner = Invoke-CimMethod -InputObject $Process -MethodName GetOwner
        $Rows += [pscustomobject]@{ ProcessId = $Process.ProcessId; Name = $Process.Name; User = $Owner.User }
    }
    return $Rows
}

if ($CurrentIdentity -cne $TargetIdentity) {
    if ((Get-CodeProcessOwners | Where-Object { $_.User -eq "HP" }).Count -ne 0) {
        throw "BLOCKED_CATALOG_CODEX_HP_PROCESS_ACTIVE"
    }
    if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) {
        throw "BLOCKED_CATALOG_AGENT_CREDENTIAL_MISSING"
    }
    $Protected = Get-Content -LiteralPath $CredentialPath -Raw
    $SecurePassword = ConvertTo-SecureString -String $Protected
    $Credential = [Management.Automation.PSCredential]::new(".\$TargetIdentity", $SecurePassword)
    Start-Process -FilePath "powershell.exe" -Credential $Credential -WindowStyle Hidden -ArgumentList @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath
    )
    exit 0
}

$Principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "BLOCKED_CATALOG_AGENT_IS_ADMIN"
}
foreach ($Name in @("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_CONFIG_DIR")) {
    Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
}
$env:CODEX_HOME = $ProfileRoot
$Package = Get-AppxPackage -Name "OpenAI.Codex"
if ($null -eq $Package) {
    $MachinePackage = Get-AppxPackage -AllUsers -Name "OpenAI.Codex" | Select-Object -First 1
    if ($null -eq $MachinePackage -or $MachinePackage.Publisher -cne $ExpectedPublisher) {
        throw "BLOCKED_CATALOG_CODEX_PACKAGE_INVALID"
    }
    Add-AppxPackage -Register (Join-Path $MachinePackage.InstallLocation "AppxManifest.xml") -DisableDevelopmentMode
    $Package = Get-AppxPackage -Name "OpenAI.Codex"
}
if ($Package.PackageFamilyName -cne $PackageFamily -or $Package.Publisher -cne $ExpectedPublisher) {
    throw "BLOCKED_CATALOG_CODEX_PACKAGE_INVALID"
}
Start-Process -FilePath "explorer.exe" -ArgumentList "shell:AppsFolder\$PackageFamily!App"
Start-Sleep -Seconds 10
$Foreign = Get-CodeProcessOwners | Where-Object { $_.User -ne $TargetIdentity }
if ($Foreign.Count -ne 0) {
    throw "BLOCKED_CATALOG_CODEX_PROCESS_OWNER_INVALID"
}
