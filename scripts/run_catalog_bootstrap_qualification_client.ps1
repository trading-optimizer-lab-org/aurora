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
$FixedCommand = @'
foreach($n in @('GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN','GH_CONFIG_DIR','XDG_CONFIG_HOME')){Remove-Item -LiteralPath ("Env:"+$n) -ErrorAction SilentlyContinue}
& 'C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe' -I -s -E 'C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz' --campaign-key 'controller-bootstrap-qualification-v1'
exit $LASTEXITCODE
'@
$Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($FixedCommand))
$Process = Start-Process -FilePath "powershell.exe" -Credential $Credential -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardOutput $OutputPath -RedirectStandardError $ErrorPath `
    -ArgumentList @("-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", $Encoded)
$Credential = $null
$SecurePassword = $null
$Protected = $null
if ($Process.ExitCode -ne 0) {
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
