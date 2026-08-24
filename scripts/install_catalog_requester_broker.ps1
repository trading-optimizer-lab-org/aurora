[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Confirm = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TargetIdentity = "AURORARequester"
$AgentIdentity = "AURORAAgent"
$BrokerRoot = "C:\ProgramData\AURORA\CatalogRequester"
$TaskName = "AURORA Catalog Requester Broker"
$ExpectedConfirmation = "AURORA_CATALOG_REQUESTER_BROKER_V1"
$SystemAcl = "*S-1-5-18"
$AdministratorsAcl = "*S-1-5-32-544"
$SourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$StagingRoot = "C:\ProgramData\AURORA\BootstrapStaging"
$StagedApps = Join-Path $StagingRoot "requester-apps"
$StagedPrivateKey = Join-Path $StagingRoot "requester-private-key.pem"
$ClientApplication = Join-Path $StagedApps "catalog-requester-client.pyz"
$BrokerApplication = Join-Path $StagedApps "catalog-requester-broker.pyz"
$InstalledPrivateKey = Join-Path $BrokerRoot "secrets\requester-private-key.pem"
$AppBindingPath = Join-Path $BrokerRoot "secrets\requester-app-binding-v1.json"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-ClosedAcl {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$AllowedSids,
        [string[]]$ReadOnlySids = @(),
        [Parameter(Mandatory)][string]$ReasonCode
    )

    $Acl = Get-Acl -LiteralPath $Path
    if (-not $Acl.AreAccessRulesProtected) {
        throw $ReasonCode
    }
    $Rules = @($Acl.GetAccessRules(
        $true,
        $false,
        [Security.Principal.SecurityIdentifier]
    ))
    $Observed = @()
    $ForbiddenReadOnlyRights = (
        [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Modify -bor
        [Security.AccessControl.FileSystemRights]::FullControl -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    )
    foreach ($Rule in $Rules) {
        if ($Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
            throw $ReasonCode
        }
        $Sid = $Rule.IdentityReference.Value
        if ($Sid -notin $AllowedSids) {
            throw $ReasonCode
        }
        if (
            $Sid -in $ReadOnlySids -and
            ($Rule.FileSystemRights -band $ForbiddenReadOnlyRights)
        ) {
            throw $ReasonCode
        }
        $Observed += $Sid
    }
    $UniqueObserved = @($Observed | Sort-Object -Unique)
    $UniqueAllowed = @($AllowedSids | Sort-Object -Unique)
    if (
        $Observed.Count -ne $UniqueObserved.Count -or
        $UniqueObserved.Count -ne $UniqueAllowed.Count -or
        (Compare-Object -ReferenceObject $UniqueAllowed -DifferenceObject $UniqueObserved)
    ) {
        throw $ReasonCode
    }
}

function New-SecretPassword {
    $bytes = [byte[]]::new(48)
    $Generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Generator.GetBytes($bytes)
    }
    finally {
        $Generator.Dispose()
    }
    $plain = [Convert]::ToBase64String($bytes) + "!aA7"
    try {
        return ConvertTo-SecureString -String $plain -AsPlainText -Force
    }
    finally {
        $plain = $null
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function Initialize-LocalSecurityPolicyType {
    if ("AuroraLocalSecurityPolicy" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;

public static class AuroraLocalSecurityPolicy
{
    private const uint PolicyLookupNames = 0x00000800;
    private const uint PolicyCreateAccount = 0x00000010;
    private const uint StatusObjectNameNotFound = 0xC0000034;

    [StructLayout(LayoutKind.Sequential)]
    private struct LsaObjectAttributes
    {
        public uint Length;
        public IntPtr RootDirectory;
        public IntPtr Attributes;
        public IntPtr SecurityDescriptor;
        public IntPtr SecurityQualityOfService;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct LsaUnicodeString
    {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [DllImport("advapi32.dll")]
    private static extern uint LsaOpenPolicy(
        IntPtr systemName,
        ref LsaObjectAttributes objectAttributes,
        uint desiredAccess,
        out IntPtr policyHandle);

    [DllImport("advapi32.dll")]
    private static extern uint LsaAddAccountRights(
        IntPtr policyHandle,
        IntPtr accountSid,
        LsaUnicodeString[] userRights,
        uint countOfRights);

    [DllImport("advapi32.dll")]
    private static extern uint LsaRemoveAccountRights(
        IntPtr policyHandle,
        IntPtr accountSid,
        [MarshalAs(UnmanagedType.Bool)] bool allRights,
        LsaUnicodeString[] userRights,
        uint countOfRights);

    [DllImport("advapi32.dll")]
    private static extern uint LsaEnumerateAccountRights(
        IntPtr policyHandle,
        IntPtr accountSid,
        out IntPtr userRights,
        out uint countOfRights);

    [DllImport("advapi32.dll")]
    private static extern uint LsaClose(IntPtr policyHandle);

    [DllImport("advapi32.dll")]
    private static extern uint LsaFreeMemory(IntPtr buffer);

    [DllImport("advapi32.dll")]
    private static extern uint LsaNtStatusToWinError(uint status);

    private static void ThrowIfError(uint status)
    {
        if (status != 0)
        {
            throw new Win32Exception((int)LsaNtStatusToWinError(status));
        }
    }

    private static IntPtr OpenPolicy()
    {
        LsaObjectAttributes attributes = new LsaObjectAttributes();
        attributes.Length = (uint)Marshal.SizeOf(typeof(LsaObjectAttributes));
        IntPtr handle;
        ThrowIfError(LsaOpenPolicy(
            IntPtr.Zero,
            ref attributes,
            PolicyLookupNames | PolicyCreateAccount,
            out handle));
        return handle;
    }

    private static byte[] SidBytes(string sidText)
    {
        SecurityIdentifier sid = new SecurityIdentifier(sidText);
        byte[] bytes = new byte[sid.BinaryLength];
        sid.GetBinaryForm(bytes, 0);
        return bytes;
    }

    private static LsaUnicodeString Right(string value, out IntPtr buffer)
    {
        buffer = Marshal.StringToHGlobalUni(value);
        LsaUnicodeString result = new LsaUnicodeString();
        result.Buffer = buffer;
        result.Length = checked((ushort)(value.Length * 2));
        result.MaximumLength = checked((ushort)((value.Length + 1) * 2));
        return result;
    }

    public static void AddRight(string sidText, string right)
    {
        IntPtr policy = OpenPolicy();
        byte[] sid = SidBytes(sidText);
        GCHandle sidHandle = GCHandle.Alloc(sid, GCHandleType.Pinned);
        IntPtr rightBuffer = IntPtr.Zero;
        try
        {
            LsaUnicodeString[] rights = new LsaUnicodeString[] {
                Right(right, out rightBuffer)
            };
            ThrowIfError(LsaAddAccountRights(
                policy, sidHandle.AddrOfPinnedObject(), rights, 1));
        }
        finally
        {
            if (rightBuffer != IntPtr.Zero) Marshal.FreeHGlobal(rightBuffer);
            sidHandle.Free();
            LsaClose(policy);
        }
    }

    public static void RemoveRight(string sidText, string right)
    {
        IntPtr policy = OpenPolicy();
        byte[] sid = SidBytes(sidText);
        GCHandle sidHandle = GCHandle.Alloc(sid, GCHandleType.Pinned);
        IntPtr rightBuffer = IntPtr.Zero;
        try
        {
            LsaUnicodeString[] rights = new LsaUnicodeString[] {
                Right(right, out rightBuffer)
            };
            ThrowIfError(LsaRemoveAccountRights(
                policy, sidHandle.AddrOfPinnedObject(), false, rights, 1));
        }
        finally
        {
            if (rightBuffer != IntPtr.Zero) Marshal.FreeHGlobal(rightBuffer);
            sidHandle.Free();
            LsaClose(policy);
        }
    }

    public static string[] GetRights(string sidText)
    {
        IntPtr policy = OpenPolicy();
        byte[] sid = SidBytes(sidText);
        GCHandle sidHandle = GCHandle.Alloc(sid, GCHandleType.Pinned);
        IntPtr rightsBuffer = IntPtr.Zero;
        try
        {
            uint count;
            uint status = LsaEnumerateAccountRights(
                policy, sidHandle.AddrOfPinnedObject(), out rightsBuffer, out count);
            if (status == StatusObjectNameNotFound) return new string[0];
            ThrowIfError(status);
            List<string> rights = new List<string>();
            int size = Marshal.SizeOf(typeof(LsaUnicodeString));
            for (uint index = 0; index < count; index++)
            {
                IntPtr item = IntPtr.Add(rightsBuffer, checked((int)index * size));
                LsaUnicodeString value = (LsaUnicodeString)Marshal.PtrToStructure(
                    item, typeof(LsaUnicodeString));
                rights.Add(Marshal.PtrToStringUni(value.Buffer, value.Length / 2));
            }
            return rights.ToArray();
        }
        finally
        {
            if (rightsBuffer != IntPtr.Zero) LsaFreeMemory(rightsBuffer);
            sidHandle.Free();
            LsaClose(policy);
        }
    }
}
'@
}

function Set-BatchOnlyLogonRights {
    param([Parameter(Mandatory)][string]$Sid)

    $RequiredRights = @(
        "SeBatchLogonRight",
        "SeDenyInteractiveLogonRight",
        "SeDenyRemoteInteractiveLogonRight",
        "SeDenyNetworkLogonRight",
        "SeDenyServiceLogonRight"
    )
    $DangerousRights = @(
        "SeDebugPrivilege",
        "SeTakeOwnershipPrivilege",
        "SeImpersonatePrivilege",
        "SeAssignPrimaryTokenPrivilege",
        "SeTcbPrivilege",
        "SeBackupPrivilege",
        "SeRestorePrivilege",
        "SeLoadDriverPrivilege"
    )
    $Observed = @([AuroraLocalSecurityPolicy]::GetRights($Sid))
    foreach ($Right in $RequiredRights) {
        if ($Right -notin $Observed) {
            [AuroraLocalSecurityPolicy]::AddRight($Sid, $Right)
        }
    }
    $Observed = @([AuroraLocalSecurityPolicy]::GetRights($Sid))
    foreach ($Right in $Observed) {
        if ($Right -notin $RequiredRights) {
            [AuroraLocalSecurityPolicy]::RemoveRight($Sid, $Right)
        }
    }
    $Readback = @([AuroraLocalSecurityPolicy]::GetRights($Sid))
    if (
        "SeDenyBatchLogonRight" -in $Readback -or
        @($DangerousRights | Where-Object { $_ -in $Readback }).Count -ne 0 -or
        (Compare-Object `
            -ReferenceObject @($RequiredRights | Sort-Object) `
            -DifferenceObject @($Readback | Sort-Object))
    ) {
        throw "BLOCKED_REQUESTER_BROKER_LOGON_RIGHTS_INVALID"
    }
}

function Invoke-VerifiedRequesterBuild {
    param(
        [Parameter(Mandatory)][string]$OutputDirectory,
        [Parameter(Mandatory)][string]$ExpectedCommit
    )

    & $Python -I -s -E (Join-Path $SourceRoot "scripts\build_catalog_requester_apps.py") `
        --source-root $SourceRoot --output-dir $OutputDirectory `
        --expected-commit-sha $ExpectedCommit
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BUILD_FAILED"
    }
}

$Directories = @(
    "bin",
    "config",
    "secrets",
    "inbox",
    "processing",
    "receipts",
    "launch-tickets",
    "campaign-status",
    "logs",
    "schemas",
    "client-venv",
    "broker-venv"
)
$Plan = [ordered]@{
    schema_version = "1"
    mode = if ($Apply) { "apply" } else { "dry_run" }
    mutation_performed = $false
    production_enabled = $false
    target_identity = $TargetIdentity
    target_is_non_admin = $true
    broker_root = $BrokerRoot
    source_root = $SourceRoot
    task_name = $TaskName
    task_window_style = "hidden"
    directories = $Directories
    client_application = "catalog-requester-client.pyz"
    broker_application = "catalog-requester-broker.pyz"
    client_python_arguments = "-I -s -E C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-client.pyz"
    broker_python_arguments = "-I -s -E C:\ProgramData\AURORA\CatalogRequester\bin\catalog-requester-broker.pyz"
    task_start_verification = "external bootstrap must use Start-Process -WindowStyle Hidden and verify task"
    requester_private_key_destination = "C:\ProgramData\AURORA\CatalogRequester\secrets\requester-private-key.pem"
    requester_private_key_contents_recorded = $false
    qualification_only_before_production_seal = $true
}

if (-not $Apply) {
    $Plan | ConvertTo-Json -Depth 8 -Compress
    exit 0
}

if ($Confirm -cne $ExpectedConfirmation) {
    throw "CONFIRMATION_REQUIRED:$ExpectedConfirmation"
}
if ($env:OS -ne "Windows_NT") {
    throw "BLOCKED_REQUESTER_BROKER_WINDOWS_REQUIRED"
}
if (-not (Test-IsAdministrator)) {
    throw "BLOCKED_REQUESTER_BROKER_ADMIN_BOOTSTRAP_REQUIRED"
}
$ExistingProductionSeal = Join-Path $BrokerRoot "config\production-enabled-v1.seal.json"
$ExistingProductionSealItem = Get-Item -LiteralPath $ExistingProductionSeal `
    -Force -ErrorAction SilentlyContinue
if ($null -ne $ExistingProductionSealItem) {
    throw "BLOCKED_REQUESTER_BROKER_PRODUCTION_ALREADY_SEALED"
}
$Head = (& git -C $SourceRoot rev-parse HEAD 2>$null)
$Status = (& git -C $SourceRoot status --porcelain=v1 --untracked-files=no 2>$null)
if ($LASTEXITCODE -ne 0 -or $Head -notmatch "^[0-9a-f]{40}$" -or $Status) {
    throw "BLOCKED_REQUESTER_BROKER_SOURCE_NOT_CLEAN"
}
$Origin = (& git -C $SourceRoot remote get-url origin 2>$null)
if ($Origin -notin @(
    "https://github.com/trading-optimizer-lab-org/aurora.git",
    "git@github.com:trading-optimizer-lab-org/aurora.git"
)) {
    throw "BLOCKED_UNEXPECTED_REPOSITORY"
}
$Python = "C:\Python314\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "BLOCKED_REQUESTER_BROKER_PYTHON314_MISSING"
}
Initialize-LocalSecurityPolicyType

$RequiredStaged = @(
    $ClientApplication,
    (Join-Path $StagedApps "catalog-requester-client.manifest.json"),
    $BrokerApplication,
    (Join-Path $StagedApps "catalog-requester-broker.manifest.json"),
    (Join-Path $SourceRoot "config\catalog_requester_public_key_v1.pem")
)
foreach ($Required in $RequiredStaged) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "BLOCKED_REQUESTER_BROKER_STAGED_INPUT_MISSING:$Required"
    }
}
$StagingItem = Get-Item -LiteralPath $StagingRoot -Force
if (-not $StagingItem.PSIsContainer -or `
    ($StagingItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "BLOCKED_REQUESTER_BROKER_STAGING_PATH_INVALID"
}
& icacls.exe $StagingRoot /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_STAGING_ACL_FAILED"
}
Assert-ClosedAcl -Path $StagingRoot `
    -AllowedSids @("S-1-5-18", "S-1-5-32-544") `
    -ReasonCode "BLOCKED_REQUESTER_BROKER_STAGING_ACL_NOT_CLOSED"
$BuildA = Join-Path $StagingRoot ("verified-requester-build-a-" + [Guid]::NewGuid().ToString("N"))
$BuildB = Join-Path $StagingRoot ("verified-requester-build-b-" + [Guid]::NewGuid().ToString("N"))
$ExpectedApplicationFiles = @(
    "catalog-requester-client.pyz",
    "catalog-requester-client.manifest.json",
    "catalog-requester-broker.pyz",
    "catalog-requester-broker.manifest.json"
)
$ObservedStagedApplicationFiles = @(
    Get-ChildItem -LiteralPath $StagedApps -Force |
        ForEach-Object { $_.Name } |
        Sort-Object
)
if (Compare-Object `
    -ReferenceObject @($ExpectedApplicationFiles | Sort-Object) `
    -DifferenceObject $ObservedStagedApplicationFiles) {
    throw "BLOCKED_REQUESTER_BROKER_STAGED_APPLICATION_SET_INVALID"
}
$StagingAclPaths = @($StagedApps)
foreach ($ApplicationFile in $ExpectedApplicationFiles) {
    $StagingAclPaths += (Join-Path $StagedApps $ApplicationFile)
}
if (Test-Path -LiteralPath $StagedPrivateKey) {
    $StagingAclPaths += $StagedPrivateKey
}
foreach ($StagingAclPath in $StagingAclPaths) {
    $StagingAclItem = Get-Item -LiteralPath $StagingAclPath -Force
    if ($StagingAclItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "BLOCKED_REQUESTER_BROKER_STAGED_ITEM_PATH_INVALID:$StagingAclPath"
    }
    $StagingGrant = if ($StagingAclItem.PSIsContainer) {
        @("${SystemAcl}:(OI)(CI)(F)", "${AdministratorsAcl}:(OI)(CI)(F)")
    }
    else {
        @("${SystemAcl}:(F)", "${AdministratorsAcl}:(F)")
    }
    & icacls.exe $StagingAclPath /inheritance:r /grant:r $StagingGrant | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_STAGED_ITEM_ACL_FAILED:$StagingAclPath"
    }
    Assert-ClosedAcl -Path $StagingAclPath `
        -AllowedSids @("S-1-5-18", "S-1-5-32-544") `
        -ReasonCode "BLOCKED_REQUESTER_BROKER_STAGED_ITEM_ACL_NOT_CLOSED"
}
try {
    Invoke-VerifiedRequesterBuild -OutputDirectory $BuildA -ExpectedCommit $Head
    Invoke-VerifiedRequesterBuild -OutputDirectory $BuildB -ExpectedCommit $Head
    foreach ($ApplicationFile in $ExpectedApplicationFiles) {
        $HashA = (Get-FileHash -LiteralPath (Join-Path $BuildA $ApplicationFile) -Algorithm SHA256).Hash
        $HashB = (Get-FileHash -LiteralPath (Join-Path $BuildB $ApplicationFile) -Algorithm SHA256).Hash
        if ($HashA -cne $HashB) {
            throw "BLOCKED_REQUESTER_BUILD_NONDETERMINISTIC:$ApplicationFile"
        }
        $StagedHash = (Get-FileHash -LiteralPath (Join-Path $StagedApps $ApplicationFile) -Algorithm SHA256).Hash
        if ($HashA -cne $StagedHash) {
            throw "BLOCKED_REQUESTER_STAGED_APPLICATION_MISMATCH:$ApplicationFile"
        }
    }
}
finally {
    foreach ($BuildDirectory in @($BuildA, $BuildB)) {
        if (Test-Path -LiteralPath $BuildDirectory) {
            $ResolvedBuild = (Resolve-Path -LiteralPath $BuildDirectory).Path
            $ResolvedStaging = (Resolve-Path -LiteralPath $StagingRoot).Path
            if (-not $ResolvedBuild.StartsWith($ResolvedStaging + "\", [StringComparison]::OrdinalIgnoreCase)) {
                throw "BLOCKED_REQUESTER_BROKER_STAGING_PATH_INVALID"
            }
            Remove-Item -LiteralPath $ResolvedBuild -Recurse -Force
        }
    }
}
$InstalledPrivateKeyExists = Test-Path -LiteralPath $InstalledPrivateKey -PathType Leaf
$StagedPrivateKeyExists = Test-Path -LiteralPath $StagedPrivateKey -PathType Leaf
if (-not $InstalledPrivateKeyExists -and -not $StagedPrivateKeyExists) {
    throw "BLOCKED_REQUESTER_BROKER_STAGED_INPUT_MISSING:$StagedPrivateKey"
}
foreach ($PrivateKeyPath in @($InstalledPrivateKey, $StagedPrivateKey)) {
    if (Test-Path -LiteralPath $PrivateKeyPath) {
        $PrivateKeyItem = Get-Item -LiteralPath $PrivateKeyPath -Force
        if (-not $PrivateKeyItem.PSIsContainer -and `
            ($PrivateKeyItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "BLOCKED_REQUESTER_PRIVATE_KEY_PATH_INVALID:$PrivateKeyPath"
        }
    }
}
$MachineAppId = [Environment]::GetEnvironmentVariable(
    "AURORA_CATALOG_REQUESTER_APP_ID",
    "Machine"
)
$MachineInstallationId = [Environment]::GetEnvironmentVariable(
    "AURORA_CATALOG_REQUESTER_INSTALLATION_ID",
    "Machine"
)
$ExistingAppId = $null
$ExistingInstallationId = $null
$BindingItem = Get-Item -LiteralPath $AppBindingPath -Force `
    -ErrorAction SilentlyContinue
if ($null -ne $BindingItem) {
    if ($BindingItem.PSIsContainer -or `
        ($BindingItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "BLOCKED_REQUESTER_APP_BINDING_INVALID"
    }
    $ExistingRequesterUser = Get-LocalUser -Name $TargetIdentity `
        -ErrorAction SilentlyContinue
    if ($null -eq $ExistingRequesterUser) {
        throw "BLOCKED_REQUESTER_APP_BINDING_INVALID"
    }
    Assert-ClosedAcl -Path $AppBindingPath `
        -AllowedSids @(
            "S-1-5-18",
            "S-1-5-32-544",
            $ExistingRequesterUser.SID.Value
        ) `
        -ReadOnlySids @($ExistingRequesterUser.SID.Value) `
        -ReasonCode "BLOCKED_REQUESTER_APP_BINDING_EXISTING_ACL_INVALID"
    try {
        $ExistingBindingBytes = [IO.File]::ReadAllBytes($AppBindingPath)
        if ($ExistingBindingBytes.Length -gt 4096) {
            throw "BLOCKED_REQUESTER_APP_BINDING_INVALID"
        }
        $StrictUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $ExistingBindingText = $StrictUtf8.GetString($ExistingBindingBytes)
        $ExistingBinding = $ExistingBindingText | ConvertFrom-Json
    }
    catch {
        throw "BLOCKED_REQUESTER_APP_BINDING_INVALID"
    }
    $BindingProperties = @($ExistingBinding.PSObject.Properties.Name | Sort-Object)
    if (
        (Compare-Object `
            -ReferenceObject @("app_id", "installation_id", "schema_version") `
            -DifferenceObject $BindingProperties) -or
        [string]$ExistingBinding.schema_version -cne "1" -or
        [string]$ExistingBinding.app_id -notmatch "^[1-9][0-9]*$" -or
        [string]$ExistingBinding.installation_id -notmatch "^[1-9][0-9]*$"
    ) {
        throw "BLOCKED_REQUESTER_APP_BINDING_INVALID"
    }
    try {
        $ExistingAppIdNumber = [Int64]$ExistingBinding.app_id
        $ExistingInstallationIdNumber = [Int64]$ExistingBinding.installation_id
    }
    catch {
        throw "BLOCKED_REQUESTER_APP_BINDING_INVALID"
    }
    $CanonicalExistingBinding = [ordered]@{
        app_id = $ExistingAppIdNumber
        installation_id = $ExistingInstallationIdNumber
        schema_version = "1"
    }
    $CanonicalExistingBytes = $StrictUtf8.GetBytes(
        (($CanonicalExistingBinding | ConvertTo-Json -Depth 4 -Compress) + "`n")
    )
    if (
        [Convert]::ToBase64String($ExistingBindingBytes) -cne
        [Convert]::ToBase64String($CanonicalExistingBytes)
    ) {
        throw "BLOCKED_REQUESTER_APP_BINDING_NONCANONICAL"
    }
    $ExistingAppId = [string]$ExistingAppIdNumber
    $ExistingInstallationId = [string]$ExistingInstallationIdNumber
}
if (-not [string]::IsNullOrWhiteSpace($MachineAppId) -and `
    $MachineAppId -notmatch "^[1-9][0-9]*$") {
    throw "BLOCKED_REQUESTER_BROKER_APP_BINDING_MISSING:AURORA_CATALOG_REQUESTER_APP_ID"
}
if (-not [string]::IsNullOrWhiteSpace($MachineInstallationId) -and `
    $MachineInstallationId -notmatch "^[1-9][0-9]*$") {
    throw "BLOCKED_REQUESTER_BROKER_APP_BINDING_MISSING:AURORA_CATALOG_REQUESTER_INSTALLATION_ID"
}
if ($null -ne $ExistingAppId) {
    if (
        (-not [string]::IsNullOrWhiteSpace($MachineAppId) -and `
            $MachineAppId -cne $ExistingAppId) -or
        (-not [string]::IsNullOrWhiteSpace($MachineInstallationId) -and `
            $MachineInstallationId -cne $ExistingInstallationId)
    ) {
        throw "BLOCKED_REQUESTER_APP_ROTATION_UNSAFE"
    }
    $RequesterAppId = [Int64]$ExistingAppId
    $RequesterInstallationId = [Int64]$ExistingInstallationId
}
else {
    if ([string]::IsNullOrWhiteSpace($MachineAppId)) {
        throw "BLOCKED_REQUESTER_BROKER_APP_BINDING_MISSING:AURORA_CATALOG_REQUESTER_APP_ID"
    }
    if ([string]::IsNullOrWhiteSpace($MachineInstallationId)) {
        throw "BLOCKED_REQUESTER_BROKER_APP_BINDING_MISSING:AURORA_CATALOG_REQUESTER_INSTALLATION_ID"
    }
    $RequesterAppId = [Int64]$MachineAppId
    $RequesterInstallationId = [Int64]$MachineInstallationId
}

$ExistingScheduledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $ExistingScheduledTask -and $ExistingScheduledTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    $StopDeadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 250
        $ExistingScheduledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } while (
        $ExistingScheduledTask.State -eq "Running" -and
        [DateTime]::UtcNow -lt $StopDeadline
    )
    if ($ExistingScheduledTask.State -eq "Running") {
        throw "BLOCKED_REQUESTER_BROKER_TASK_STILL_RUNNING"
    }
}

$Existing = Get-LocalUser -Name $TargetIdentity -ErrorAction SilentlyContinue
$AgentUser = Get-LocalUser -Name $AgentIdentity -ErrorAction SilentlyContinue
if ($null -eq $AgentUser -or -not $AgentUser.Enabled) {
    throw "BLOCKED_AGENT_SANDBOX_IDENTITY_MISSING"
}
$TaskPassword = New-SecretPassword
if ($null -eq $Existing) {
    New-LocalUser -Name $TargetIdentity -Password $TaskPassword `
        -AccountNeverExpires -PasswordNeverExpires `
        -UserMayNotChangePassword -Description "AURORA catalog requester broker" | Out-Null
}
else {
    Set-LocalUser -Name $TargetIdentity -Password $TaskPassword `
        -AccountNeverExpires -PasswordNeverExpires $true `
        -UserMayChangePassword $false
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
    throw "BLOCKED_REQUESTER_BROKER_ACCOUNT_IS_ADMIN"
}
Set-BatchOnlyLogonRights -Sid $InstalledUser.SID.Value

if (-not (Test-Path -LiteralPath $BrokerRoot)) {
    New-Item -ItemType Directory -Path $BrokerRoot | Out-Null
}
foreach ($Directory in $Directories) {
    $Path = Join-Path $BrokerRoot $Directory
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}
foreach ($PublicDirectory in @(
    "docs\runbooks",
    "config\catalog_campaign_definitions"
)) {
    $Path = Join-Path $BrokerRoot $PublicDirectory
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

& icacls.exe $BrokerRoot /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
    "${TargetIdentity}:(RX)" "${AgentIdentity}:(RX)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED"
}
foreach ($ImmutableDirectory in @("bin", "config", "docs", "schemas", "broker-venv")) {
    & icacls.exe (Join-Path $BrokerRoot $ImmutableDirectory) /inheritance:r /grant:r `
        "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
        "${TargetIdentity}:(OI)(CI)(RX)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:$ImmutableDirectory"
    }
}
foreach ($ServiceWritableDirectory in @("processing", "logs")) {
    & icacls.exe (Join-Path $BrokerRoot $ServiceWritableDirectory) /inheritance:r /grant:r `
        "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
        "${TargetIdentity}:(OI)(CI)(M)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:$ServiceWritableDirectory"
    }
}
& icacls.exe (Join-Path $BrokerRoot "secrets") /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
    "${TargetIdentity}:(OI)(CI)(R)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:secrets"
}
if ($InstalledPrivateKeyExists) {
    $InstalledPrivateKeyItem = Get-Item -LiteralPath $InstalledPrivateKey -Force
    if ($InstalledPrivateKeyItem.PSIsContainer -or `
        ($InstalledPrivateKeyItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "BLOCKED_REQUESTER_PRIVATE_KEY_PATH_INVALID:$InstalledPrivateKey"
    }
    Assert-ClosedAcl -Path $InstalledPrivateKey `
        -AllowedSids @(
            "S-1-5-18",
            "S-1-5-32-544",
            $InstalledUser.SID.Value
        ) `
        -ReadOnlySids @($InstalledUser.SID.Value) `
        -ReasonCode "BLOCKED_REQUESTER_PRIVATE_KEY_EXISTING_ACL_INVALID"
}
foreach ($PublicStateDirectory in @("receipts", "launch-tickets", "campaign-status")) {
    & icacls.exe (Join-Path $BrokerRoot $PublicStateDirectory) /inheritance:r /grant:r `
        "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
        "${TargetIdentity}:(OI)(CI)(M)" "${AgentIdentity}:(OI)(CI)(RX)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:$PublicStateDirectory"
    }
}
& icacls.exe (Join-Path $BrokerRoot "inbox") /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
    "${TargetIdentity}:(OI)(CI)(F)" "${AgentIdentity}:(WD,REA,RA,X,S)" `
    "*S-1-3-4:(OI)(IO)(RC)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:inbox"
}
& icacls.exe (Join-Path $BrokerRoot "client-venv") /inheritance:r /grant:r `
    "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
    "${AgentIdentity}:(OI)(CI)(RX)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:client-venv"
}
foreach ($AgentPublicDirectory in @("config", "docs", "schemas", "bin")) {
    & icacls.exe (Join-Path $BrokerRoot $AgentPublicDirectory) /grant:r `
        "${AgentIdentity}:(RX)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:$AgentPublicDirectory"
    }
}
foreach ($AgentPublicTree in @("config", "docs", "schemas")) {
    & icacls.exe (Join-Path $BrokerRoot $AgentPublicTree) /inheritance:r /grant:r `
        "${SystemAcl}:(OI)(CI)(F)" "${AdministratorsAcl}:(OI)(CI)(F)" `
        "${TargetIdentity}:(OI)(CI)(RX)" "${AgentIdentity}:(OI)(CI)(RX)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:$AgentPublicTree"
    }
}

$ClientVenv = Join-Path $BrokerRoot "client-venv"
$BrokerVenv = Join-Path $BrokerRoot "broker-venv"
foreach ($VenvRoot in @($ClientVenv, $BrokerVenv)) {
    $VenvItem = Get-Item -LiteralPath $VenvRoot -Force
    if (-not $VenvItem.PSIsContainer -or `
        ($VenvItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or `
        (Resolve-Path -LiteralPath $VenvRoot).Path -cne `
            [IO.Path]::GetFullPath($VenvRoot)) {
        throw "BLOCKED_REQUESTER_VENV_PATH_INVALID:$VenvRoot"
    }
}
& $Python -I -s -E -m venv --clear $ClientVenv
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_CLIENT_VENV_CREATE_FAILED"
}
& $Python -I -s -E -m venv --clear $BrokerVenv
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_VENV_CREATE_FAILED"
}
& (Join-Path $ClientVenv "Scripts\python.exe") -I -s -E -m pip install `
    --isolated --disable-pip-version-check --no-cache-dir `
    --only-binary=:all: --no-deps --require-hashes `
    -r (Join-Path $SourceRoot "requirements\catalog-requester-client-win-py314.lock")
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_REQUESTER_CLIENT_DEPENDENCY_INSTALL_FAILED" }
& (Join-Path $BrokerVenv "Scripts\python.exe") -I -s -E -m pip install `
    --isolated --disable-pip-version-check --no-cache-dir `
    --only-binary=:all: --no-deps --require-hashes `
    -r (Join-Path $SourceRoot "requirements\catalog-requester-broker-win-py314.lock")
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_REQUESTER_BROKER_DEPENDENCY_INSTALL_FAILED" }
& (Join-Path $ClientVenv "Scripts\python.exe") -I -s -E -m pip check
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_REQUESTER_CLIENT_DEPENDENCY_CHECK_FAILED" }
& (Join-Path $BrokerVenv "Scripts\python.exe") -I -s -E -m pip check
if ($LASTEXITCODE -ne 0) { throw "BLOCKED_REQUESTER_BROKER_DEPENDENCY_CHECK_FAILED" }

$DependencyInventoryVerifier = @'
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
import re
import sys


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


lock_path = Path(sys.argv[1]).resolve(strict=True)
lock_bytes = lock_path.read_bytes()
if not lock_bytes.endswith(b"\n") or b"\x00" in lock_bytes:
    raise ValueError("dependency lock is not canonical text")
lock_text = lock_bytes.decode("utf-8")
requirement = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)(?:\s+\\)?$"
)
expected: dict[str, str] = {}
for line in lock_text.splitlines():
    match = requirement.fullmatch(line)
    if match is None:
        continue
    name = canonical_name(match.group(1))
    version = match.group(2)
    if name in expected or not version:
        raise ValueError("dependency lock inventory is ambiguous")
    expected[name] = version
if not expected:
    raise ValueError("dependency lock inventory is empty")

observed: dict[str, str] = {}
site_roots: set[Path] = set()
for distribution in metadata.distributions():
    raw_name = distribution.metadata.get("Name")
    if not isinstance(raw_name, str) or not raw_name:
        raise ValueError("installed distribution has no name")
    name = canonical_name(raw_name)
    if name in observed:
        raise ValueError("installed distribution is duplicated")
    if distribution.read_text("direct_url.json") is not None:
        raise ValueError("editable, VCS, or local dependency is forbidden")
    observed[name] = distribution.version
    site_root = Path(distribution.locate_file("")).resolve()
    if site_root.name.casefold() == "site-packages":
        site_roots.add(site_root)

if set(observed) != set(expected) | {"pip"}:
    raise ValueError("installed package set differs from the lock")
if any(observed[name] != version for name, version in expected.items()):
    raise ValueError("installed package version differs from the lock")
if "aurora" in observed:
    raise ValueError("full AURORA installation is forbidden")
if any(any(site_root.glob("*.pth")) for site_root in site_roots):
    raise ValueError("site path injection is forbidden")

payload = json.dumps(
    {
        "lock_sha256": sha256(lock_bytes).hexdigest(),
        "packages": sorted(observed.items()),
    },
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
).encode("ascii")
print(sha256(payload).hexdigest())
'@
$ClientDependencyLock = Join-Path $SourceRoot `
    "requirements\catalog-requester-client-win-py314.lock"
$BrokerDependencyLock = Join-Path $SourceRoot `
    "requirements\catalog-requester-broker-win-py314.lock"
$DependencyVerifierPath = Join-Path $StagingRoot `
    ("dependency-inventory-verifier-" + [Guid]::NewGuid().ToString("N") + ".py")
[IO.File]::WriteAllText(
    $DependencyVerifierPath,
    $DependencyInventoryVerifier,
    [Text.UTF8Encoding]::new($false)
)
& icacls.exe $DependencyVerifierPath /inheritance:r /grant:r `
    "${SystemAcl}:(F)" "${AdministratorsAcl}:(F)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_VERIFIER_ACL_APPLY_FAILED"
}
try {
    $ClientDependencyInventory = @(& (Join-Path $ClientVenv "Scripts\python.exe") `
        -I -s -E $DependencyVerifierPath $ClientDependencyLock)
    $ClientDependencyInventoryExitCode = $LASTEXITCODE
    $BrokerDependencyInventory = @(& (Join-Path $BrokerVenv "Scripts\python.exe") `
        -I -s -E $DependencyVerifierPath $BrokerDependencyLock)
    $BrokerDependencyInventoryExitCode = $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $DependencyVerifierPath -Force -ErrorAction SilentlyContinue
}
if ($ClientDependencyInventoryExitCode -ne 0 -or `
    $ClientDependencyInventory.Count -ne 1 -or `
    $ClientDependencyInventory[0] -notmatch "^[0-9a-f]{64}$") {
    throw "BLOCKED_REQUESTER_CLIENT_DEPENDENCY_INVENTORY_INVALID"
}
if ($BrokerDependencyInventoryExitCode -ne 0 -or `
    $BrokerDependencyInventory.Count -ne 1 -or `
    $BrokerDependencyInventory[0] -notmatch "^[0-9a-f]{64}$") {
    throw "BLOCKED_REQUESTER_BROKER_DEPENDENCY_INVENTORY_INVALID"
}

$FingerprintVerifier = @'
from hashlib import sha256
from pathlib import Path
import sys
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

private_key = serialization.load_pem_private_key(Path(sys.argv[1]).read_bytes(), password=None)
public_key = serialization.load_pem_public_key(Path(sys.argv[2]).read_bytes())
if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
    raise ValueError("requester private key must be RSA >= 2048 bits")
if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
    raise ValueError("requester public key must be RSA >= 2048 bits")
private_der = private_key.public_key().public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
public_der = public_key.public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
probe = b"AURORA_REQUESTER_INSTALLER_KEY_PROBE_V1"
signature = private_key.sign(
    probe,
    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
    hashes.SHA256(),
)
public_key.verify(
    signature,
    probe,
    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
    hashes.SHA256(),
)
print(sha256(private_der).hexdigest())
print(sha256(public_der).hexdigest())
'@
$KeyToVerify = if ($StagedPrivateKeyExists) {
    $StagedPrivateKey
}
else {
    $InstalledPrivateKey
}
$FingerprintVerifierPath = Join-Path $StagingRoot `
    ("fingerprint-verifier-" + [Guid]::NewGuid().ToString("N") + ".py")
[IO.File]::WriteAllText(
    $FingerprintVerifierPath,
    $FingerprintVerifier,
    [Text.UTF8Encoding]::new($false)
)
& icacls.exe $FingerprintVerifierPath /inheritance:r /grant:r `
    "${SystemAcl}:(F)" "${AdministratorsAcl}:(F)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_VERIFIER_ACL_APPLY_FAILED"
}
try {
    $FingerprintLines = @(& (Join-Path $BrokerVenv "Scripts\python.exe") `
        -I -s -E $FingerprintVerifierPath $KeyToVerify `
        (Join-Path $SourceRoot "config\catalog_requester_public_key_v1.pem"))
    $FingerprintExitCode = $LASTEXITCODE
    if ($InstalledPrivateKeyExists -and $StagedPrivateKeyExists) {
        $InstalledFingerprintLines = @(& (Join-Path $BrokerVenv "Scripts\python.exe") `
            -I -s -E $FingerprintVerifierPath $InstalledPrivateKey `
            (Join-Path $SourceRoot "config\catalog_requester_public_key_v1.pem"))
        $InstalledFingerprintExitCode = $LASTEXITCODE
    }
}
finally {
    Remove-Item -LiteralPath $FingerprintVerifierPath -Force -ErrorAction SilentlyContinue
}
if ($FingerprintExitCode -ne 0 -or $FingerprintLines.Count -ne 2 `
    -or $FingerprintLines[0] -cne $FingerprintLines[1]) {
    throw "BLOCKED_REQUESTER_PRIVATE_PUBLIC_KEY_MISMATCH"
}
if ($InstalledPrivateKeyExists -and $StagedPrivateKeyExists) {
    if ($InstalledFingerprintExitCode -ne 0 `
        -or $InstalledFingerprintLines.Count -ne 2 `
        -or $InstalledFingerprintLines[0] -cne $InstalledFingerprintLines[1] `
        -or $InstalledFingerprintLines[0] -cne $FingerprintLines[0]) {
        throw "BLOCKED_REQUESTER_KEY_ROTATION_UNSAFE"
    }
}
$ActorConfig = Get-Content -LiteralPath `
    (Join-Path $SourceRoot "config\catalog_controller_actors_v1.json") `
    -Raw | ConvertFrom-Json
if ($ActorConfig.production_enabled -ne $true `
    -or $ActorConfig.request_actors.Count -ne 1 `
    -or [string]$ActorConfig.requester_public_key_sha256 -cne $FingerprintLines[0]) {
    throw "BLOCKED_REQUESTER_PUBLIC_IDENTITY_BINDING_INVALID"
}

Copy-Item -LiteralPath $ClientApplication `
    -Destination (Join-Path $BrokerRoot "bin\catalog-requester-client.pyz") -Force
Copy-Item -LiteralPath $BrokerApplication `
    -Destination (Join-Path $BrokerRoot "bin\catalog-requester-broker.pyz") -Force
Copy-Item -LiteralPath (Join-Path $StagedApps "catalog-requester-client.manifest.json") `
    -Destination (Join-Path $BrokerRoot "bin\catalog-requester-client.manifest.json") -Force
Copy-Item -LiteralPath (Join-Path $StagedApps "catalog-requester-broker.manifest.json") `
    -Destination (Join-Path $BrokerRoot "bin\catalog-requester-broker.manifest.json") -Force
foreach ($ClientReadableFile in @(
    "catalog-requester-client.pyz",
    "catalog-requester-client.manifest.json",
    "catalog-requester-broker.manifest.json"
)) {
    & icacls.exe (Join-Path $BrokerRoot "bin\$ClientReadableFile") /inheritance:r /grant:r `
        "${SystemAcl}:(F)" "${AdministratorsAcl}:(F)" "${TargetIdentity}:(RX)" `
        "${AgentIdentity}:(RX)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:$ClientReadableFile"
    }
}
& icacls.exe (Join-Path $BrokerRoot "bin\catalog-requester-broker.pyz") `
    /inheritance:r /grant:r "${SystemAcl}:(F)" "${AdministratorsAcl}:(F)" `
    "${TargetIdentity}:(RX)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_BROKER_ACL_APPLY_FAILED:catalog-requester-broker.pyz"
}
foreach ($Relative in @(
    "config\catalog_requester_v1.json",
    "config\catalog_controller_actors_v1.json",
    "config\catalog_github_controls_v1.json",
    "config\catalog_campaign_registry_v1.json",
    "config\catalog_run_prompt_policy_v1.json",
    "config\catalog_requester_public_key_v1.pem",
    "schemas\catalog_requester_app_manifest_v1.schema.json",
    "schemas\catalog_campaign_definition_manifest_v1.schema.json",
    "schemas\catalog_run_prompt_policy_v1.schema.json",
    "docs\runbooks\CATALOG_RUN_MASTER_PROMPT.md"
)) {
    Copy-Item -LiteralPath (Join-Path $SourceRoot $Relative) `
        -Destination (Join-Path $BrokerRoot $Relative) -Force
}
$Registry = Get-Content -LiteralPath `
    (Join-Path $SourceRoot "config\catalog_campaign_registry_v1.json") `
    -Raw | ConvertFrom-Json
foreach ($Campaign in $Registry.campaigns) {
    if ($Campaign.active -ne $true) { continue }
    $Relative = [string]$Campaign.definition_manifest_path
    if ($Relative -notmatch "^config/catalog_campaign_definitions/[a-z0-9-]+\.manifest\.json$") {
        throw "BLOCKED_REQUESTER_BROKER_MANIFEST_PATH_INVALID"
    }
    Copy-Item -LiteralPath (Join-Path $SourceRoot ($Relative -replace "/", "\")) `
        -Destination (Join-Path $BrokerRoot ($Relative -replace "/", "\")) -Force
}
if ($StagedPrivateKeyExists) {
    if ($InstalledPrivateKeyExists) {
        Remove-Item -LiteralPath $StagedPrivateKey -Force
    }
    else {
        Move-Item -LiteralPath $StagedPrivateKey -Destination $InstalledPrivateKey
    }
}
& icacls.exe $InstalledPrivateKey /inheritance:r /grant:r `
    "${SystemAcl}:(F)" "${AdministratorsAcl}:(F)" "${TargetIdentity}:(R)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_PRIVATE_KEY_ACL_APPLY_FAILED"
}
$AppBinding = [ordered]@{
    app_id = $RequesterAppId
    installation_id = $RequesterInstallationId
    schema_version = "1"
}
$Utf8NoBom = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText(
    $AppBindingPath,
    (($AppBinding | ConvertTo-Json -Depth 4 -Compress) + "`n"),
    $Utf8NoBom
)
& icacls.exe $AppBindingPath /inheritance:r /grant:r `
    "${SystemAcl}:(F)" "${AdministratorsAcl}:(F)" "${TargetIdentity}:(R)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED_REQUESTER_APP_BINDING_ACL_APPLY_FAILED"
}
$TargetSid = $InstalledUser.SID.Value
$AgentSid = $AgentUser.SID.Value
$SystemAndAdministrators = @("S-1-5-18", "S-1-5-32-544")
$ServiceOnly = @($SystemAndAdministrators + $TargetSid)
$AgentOnly = @($SystemAndAdministrators + $AgentSid)
$ServiceAndAgent = @($SystemAndAdministrators + $TargetSid + $AgentSid)
$ServiceReadOnly = @($TargetSid)
$AgentReadOnly = @($AgentSid)
$ServiceAndAgentReadOnly = @($TargetSid, $AgentSid)
$AclExpectations = @(
    @{ Path = $BrokerRoot; Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "bin"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "config"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "docs"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "schemas"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "secrets"); Sids = $ServiceOnly; ReadOnlySids = $ServiceReadOnly },
    @{ Path = (Join-Path $BrokerRoot "inbox"); Sids = @($ServiceAndAgent + "S-1-3-4"); ReadOnlySids = @() },
    @{ Path = (Join-Path $BrokerRoot "processing"); Sids = $ServiceOnly; ReadOnlySids = @() },
    @{ Path = (Join-Path $BrokerRoot "logs"); Sids = $ServiceOnly; ReadOnlySids = @() },
    @{ Path = (Join-Path $BrokerRoot "receipts"); Sids = $ServiceAndAgent; ReadOnlySids = $AgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "launch-tickets"); Sids = $ServiceAndAgent; ReadOnlySids = $AgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "campaign-status"); Sids = $ServiceAndAgent; ReadOnlySids = $AgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "client-venv"); Sids = $AgentOnly; ReadOnlySids = $AgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "broker-venv"); Sids = $ServiceOnly; ReadOnlySids = $ServiceReadOnly },
    @{ Path = (Join-Path $BrokerRoot "bin\catalog-requester-client.pyz"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "bin\catalog-requester-client.manifest.json"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = (Join-Path $BrokerRoot "bin\catalog-requester-broker.pyz"); Sids = $ServiceOnly; ReadOnlySids = $ServiceReadOnly },
    @{ Path = (Join-Path $BrokerRoot "bin\catalog-requester-broker.manifest.json"); Sids = $ServiceAndAgent; ReadOnlySids = $ServiceAndAgentReadOnly },
    @{ Path = $InstalledPrivateKey; Sids = $ServiceOnly; ReadOnlySids = $ServiceReadOnly },
    @{ Path = $AppBindingPath; Sids = $ServiceOnly; ReadOnlySids = $ServiceReadOnly }
)
foreach ($Expectation in $AclExpectations) {
    Assert-ClosedAcl -Path $Expectation.Path -AllowedSids $Expectation.Sids `
        -ReadOnlySids $Expectation.ReadOnlySids `
        -ReasonCode "BLOCKED_REQUESTER_BROKER_ACL_NOT_CLOSED"
}
$AclRelativePaths = @(
    ".",
    "bin",
    "config",
    "docs",
    "schemas",
    "secrets",
    "inbox",
    "processing",
    "receipts",
    "launch-tickets",
    "campaign-status",
    "client-venv",
    "broker-venv",
    "bin\catalog-requester-client.pyz",
    "bin\catalog-requester-client.manifest.json",
    "bin\catalog-requester-broker.pyz",
    "bin\catalog-requester-broker.manifest.json",
    "secrets\requester-private-key.pem",
    "secrets\requester-app-binding-v1.json"
)
$AclRecords = @()
foreach ($RelativePath in $AclRelativePaths) {
    $AbsolutePath = if ($RelativePath -eq ".") {
        $BrokerRoot
    }
    else {
        Join-Path $BrokerRoot $RelativePath
    }
    $AclRecords += [ordered]@{
        path = ($RelativePath -replace "\\", "/")
        sddl = (Get-Acl -LiteralPath $AbsolutePath).Sddl
    }
}
$AclBaseline = [ordered]@{
    schema_version = "1"
    records = $AclRecords
}
$AclBaselinePath = Join-Path $BrokerRoot "config\acl-baseline-v1.json"
[IO.File]::WriteAllText(
    $AclBaselinePath,
    (($AclBaseline | ConvertTo-Json -Depth 8 -Compress) + "`n"),
    $Utf8NoBom
)
foreach ($VariableName in @(
    "AURORA_CATALOG_REQUESTER_APP_ID",
    "AURORA_CATALOG_REQUESTER_INSTALLATION_ID",
    "AURORA_CATALOG_REQUESTER_PRIVATE_KEY_PATH"
)) {
    [Environment]::SetEnvironmentVariable($VariableName, $null, "Machine")
    if ($null -ne [Environment]::GetEnvironmentVariable($VariableName, "Machine")) {
        throw "BLOCKED_REQUESTER_MACHINE_ENVIRONMENT_NOT_CLEARED:$VariableName"
    }
    Remove-Item -LiteralPath ("Env:" + $VariableName) -ErrorAction SilentlyContinue
}

$BrokerPython = Join-Path $BrokerVenv "Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $BrokerPython -PathType Leaf)) {
    throw "BLOCKED_REQUESTER_BROKER_PYTHONW_MISSING"
}
$BrokerPyz = Join-Path $BrokerRoot "bin\catalog-requester-broker.pyz"
$Action = New-ScheduledTaskAction -Execute $BrokerPython -Argument "-I -s -E `"$BrokerPyz`""
$Principal = New-ScheduledTaskPrincipal -UserId $TargetIdentity -LogonType Password -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Task = New-ScheduledTask -Action $Action -Principal $Principal -Settings $Settings -Trigger $Trigger
$Credential = [PSCredential]::new(".\$TargetIdentity", $TaskPassword)
Register-ScheduledTask -TaskName $TaskName -InputObject $Task `
    -User $Credential.UserName -Password $Credential.GetNetworkCredential().Password -Force | Out-Null
$RegisteredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$RegisteredActions = @($RegisteredTask.Actions)
if (
    $RegisteredActions.Count -ne 1 -or
    $RegisteredActions[0].Execute -cne $BrokerPython -or
    $RegisteredActions[0].Arguments -cne "-I -s -E `"$BrokerPyz`"" -or
    [string]$RegisteredTask.Principal.UserId -notmatch "(^|\\)AURORARequester$" -or
    [string]$RegisteredTask.Principal.LogonType -cne "Password" -or
    [string]$RegisteredTask.Principal.RunLevel -cne "Limited" -or
    [string]$RegisteredTask.Settings.MultipleInstances -cne "IgnoreNew" -or
    [int]$RegisteredTask.Settings.RestartCount -ne 999 -or
    [bool]$RegisteredTask.Settings.DisallowStartIfOnBatteries -or
    [bool]$RegisteredTask.Settings.StopIfGoingOnBatteries -or
    -not [bool]$RegisteredTask.Settings.StartWhenAvailable
) {
    throw "BLOCKED_REQUESTER_BROKER_TASK_READBACK_INVALID"
}
$Credential = $null
$TaskPassword = $null

$Plan.mutation_performed = $true
$Plan.installed_commit_sha = $Head
$Plan.target_sid = (Get-LocalUser -Name $TargetIdentity).SID.Value
$Plan.client_dependency_lock_sha256 = (
    Get-FileHash -LiteralPath $ClientDependencyLock -Algorithm SHA256
).Hash.ToLowerInvariant()
$Plan.broker_dependency_lock_sha256 = (
    Get-FileHash -LiteralPath $BrokerDependencyLock -Algorithm SHA256
).Hash.ToLowerInvariant()
$Plan.client_dependency_inventory_sha256 = $ClientDependencyInventory[0]
$Plan.broker_dependency_inventory_sha256 = $BrokerDependencyInventory[0]
$Plan.requester_app_binding_sha256 = (
    Get-FileHash -LiteralPath $AppBindingPath -Algorithm SHA256
).Hash.ToLowerInvariant()
$Plan.production_enabled = $false
$Plan | ConvertTo-Json -Depth 8 -Compress
