[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$InstallRoot = "C:\ProgramData\AURORA\CatalogBootstrap"
$Python = Join-Path $InstallRoot "venv\Scripts\python.exe"
$Archive = Join-Path $InstallRoot "catalog-bootstrap-assistant.pyz"
$ManifestPath = Join-Path $InstallRoot "catalog-bootstrap-application-manifest-v1.json"
foreach ($Path in @($Python, $Archive, $ManifestPath)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "BLOCKED_BOOTSTRAP_INSTALLED_FILE_MISSING"
    }
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$ArchiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
if ($ArchiveHash -cne $Manifest.archive_sha256) {
    throw "BLOCKED_BOOTSTRAP_INSTALLED_HASH_MISMATCH"
}
$Arguments = @($Archive, "--installed-root", $InstallRoot)
Start-Process -FilePath $Python -ArgumentList $Arguments -Verb RunAs -WindowStyle Hidden
