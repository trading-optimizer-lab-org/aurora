[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TargetIdentity = "AURORAAgent"
$AgentRoot = "C:\ProgramData\AURORA\CatalogAgent"
$CredentialPath = Join-Path $AgentRoot "credentials\catalog-agent-credential.dpapi"
$OutputPath = Join-Path $AgentRoot "profile\bootstrap-qualification-output.json"
$ErrorPath = Join-Path $AgentRoot "profile\bootstrap-qualification-error.txt"
$Python = "C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe"
$Application = "C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz"
$Campaign = "controller-bootstrap-qualification-v1"

function Get-BootstrapQualificationClientProcessPlan {
    [CmdletBinding()]
    param()

    [PSCustomObject][ordered]@{
        file_path = $Python
        argument_list = @(
            "-I"
            "-s"
            "-E"
            $Application
            "--campaign-key"
            "controller-bootstrap-qualification-v1"
        )
        forbidden_environment_names = @(
            "GH_TOKEN"
            "GITHUB_TOKEN"
            "GH_ENTERPRISE_TOKEN"
            "GITHUB_ENTERPRISE_TOKEN"
            "GH_CONFIG_DIR"
            "XDG_CONFIG_HOME"
        )
    }
}

function Invoke-BootstrapQualificationClient {
    [CmdletBinding()]
    param()

    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "BLOCKED_BOOTSTRAP_ADMIN_REQUIRED"
    }
    foreach ($Path in @($CredentialPath, $Python, $Application)) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "BLOCKED_BOOTSTRAP_QUALIFICATION_RUNTIME_MISSING"
        }
    }
    Remove-Item -LiteralPath $OutputPath, $ErrorPath -Force -ErrorAction SilentlyContinue
    $Protected = Get-Content -LiteralPath $CredentialPath -Raw
    $SecurePassword = ConvertTo-SecureString -String $Protected
    $Credential = [Management.Automation.PSCredential]::new(".\$TargetIdentity", $SecurePassword)
    $Plan = Get-BootstrapQualificationClientProcessPlan
    $SavedEnvironment = [ordered]@{}
    $Process = $null
    try {
        foreach ($Name in $Plan.forbidden_environment_names) {
            if (Test-Path -LiteralPath "Env:$Name") {
                $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
            }
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        }
        $Process = Start-Process -FilePath $Plan.file_path -Credential $Credential -WindowStyle Hidden -Wait -PassThru `
            -RedirectStandardOutput $OutputPath -RedirectStandardError $ErrorPath `
            -ArgumentList $Plan.argument_list
    }
    finally {
        foreach ($Name in $Plan.forbidden_environment_names) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        }
        foreach ($Entry in $SavedEnvironment.GetEnumerator()) {
            Set-Item -LiteralPath "Env:$($Entry.Key)" -Value $Entry.Value
        }
        $Credential = $null
        $SecurePassword = $null
        $Protected = $null
    }

    if ($null -eq $Process -or $Process.ExitCode -ne 0) {
        throw "BLOCKED_BOOTSTRAP_QUALIFICATION_CLIENT_FAILED"
    }
    $Lines = @(Get-Content -LiteralPath $OutputPath)
    if ($Lines.Count -ne 1) {
        throw "BLOCKED_BOOTSTRAP_QUALIFICATION_OUTPUT_INVALID"
    }
    $Value = $Lines[0] | ConvertFrom-Json
    if ($Value.campaign_key -cne $Campaign) {
        throw "BLOCKED_BOOTSTRAP_QUALIFICATION_OUTPUT_INVALID"
    }
    $Lines[0]
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-BootstrapQualificationClient
}
