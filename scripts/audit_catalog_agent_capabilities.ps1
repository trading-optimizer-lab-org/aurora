[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TargetIdentity = "AURORAAgent"
$AgentRoot = "C:\ProgramData\AURORA\CatalogAgent"
$CredentialPath = Join-Path $AgentRoot "credentials\catalog-agent-credential.dpapi"
$OutputPath = Join-Path $AgentRoot "profile\capability-audit-output.json"
$ErrorPath = Join-Path $AgentRoot "profile\capability-audit-error.txt"

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "BLOCKED_BOOTSTRAP_ADMIN_REQUIRED"
}
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) {
    throw "BLOCKED_CATALOG_AGENT_CREDENTIAL_MISSING"
}
Remove-Item -LiteralPath $OutputPath, $ErrorPath -Force -ErrorAction SilentlyContinue
$Protected = Get-Content -LiteralPath $CredentialPath -Raw
$SecurePassword = ConvertTo-SecureString -String $Protected
$Credential = [Management.Automation.PSCredential]::new(".\$TargetIdentity", $SecurePassword)
$FixedCommand = @'
$ErrorActionPreference='Stop'
function DeniedRead([string]$p){try{[IO.File]::ReadAllBytes($p)|Out-Null;return $false}catch{return $true}}
function DeniedList([string]$p){try{Get-ChildItem -LiteralPath $p -ErrorAction Stop|Out-Null;return $false}catch{return $true}}
function DeniedWrite([string]$p){try{[IO.File]::WriteAllText($p,'forbidden');Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue;return $false}catch{return $true}}
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($id)
$groups=(whoami.exe /groups /fo csv | Out-String)
$integrity=(($groups -match 'S-1-16-4096') -or ($groups -match 'S-1-16-8192')) -and -not (($groups -match 'S-1-16-12288') -or ($groups -match 'S-1-16-16384'))
$priv=(whoami.exe /priv /fo csv | Out-String)
$danger=@('SeDebugPrivilege','SeTakeOwnershipPrivilege') | Where-Object {$priv -match [Regex]::Escape($_)}
$forbiddenEnv=@('GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN','GH_CONFIG_DIR','AURORA_CATALOG_REQUESTER_PRIVATE_KEY','AURORA_CATALOG_AUDITOR_PRIVATE_KEY','AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN') | Where-Object {Test-Path ("Env:"+$_)}
$r=[ordered]@{
schema_version='1'; identity=$id.Name.Split('\')[-1]; is_admin=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
medium_or_lower_integrity=$integrity; enabled_dangerous_privileges=@($danger).Count
forbidden_environment_count=@($forbiddenEnv).Count
requester_key_read_denied=(DeniedRead 'C:\ProgramData\AURORA\CatalogRequester\secrets\requester-private-key.pem')
broker_code_read_denied=(DeniedRead 'C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-broker.pyz')
processing_list_denied=(DeniedList 'C:\ProgramData\AURORA\CatalogRequester\processing')
agent_credential_read_denied=(DeniedRead 'C:\ProgramData\AURORA\CatalogAgent\credentials\catalog-agent-credential.dpapi')
broker_write_denied=(DeniedWrite 'C:\ProgramData\AURORA\CatalogRequester\config\agent-forbidden.tmp')
elevated_helper_write_denied=(DeniedWrite 'C:\ProgramData\AURORA\CatalogAgent\agent-forbidden.tmp')
}
$r|ConvertTo-Json -Compress
'@
$Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($FixedCommand))
$Process = Start-Process -FilePath "powershell.exe" -Credential $Credential -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardOutput $OutputPath -RedirectStandardError $ErrorPath `
    -ArgumentList @("-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", $Encoded)
$Credential = $null
$SecurePassword = $null
$Protected = $null
if ($Process.ExitCode -ne 0) { throw "BLOCKED_CATALOG_AGENT_CAPABILITY_AUDIT_FAILED" }
$Lines = @(Get-Content -LiteralPath $OutputPath)
if ($Lines.Count -ne 1) { throw "BLOCKED_CATALOG_AGENT_CAPABILITY_AUDIT_INVALID" }
$Value = $Lines[0] | ConvertFrom-Json
$RequiredTrue = @(
    "medium_or_lower_integrity", "requester_key_read_denied", "broker_code_read_denied",
    "processing_list_denied", "agent_credential_read_denied", "broker_write_denied",
    "elevated_helper_write_denied"
)
if ($Value.identity -cne $TargetIdentity -or $Value.is_admin -ne $false `
    -or $Value.enabled_dangerous_privileges -ne 0 -or $Value.forbidden_environment_count -ne 0 `
    -or @($RequiredTrue | Where-Object {$Value.$_ -ne $true}).Count -ne 0) {
    throw "BLOCKED_CATALOG_AGENT_CAPABILITY_AUDIT_INVALID"
}
$Lines[0]
