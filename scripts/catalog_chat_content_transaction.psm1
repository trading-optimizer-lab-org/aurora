Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($null -eq ('CatalogChatContentNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public sealed class CatalogChatContentIdentity
{
    public readonly uint VolumeSerialNumber;
    public readonly ulong FileIndex;
    public readonly uint NumberOfLinks;

    public CatalogChatContentIdentity(uint volumeSerialNumber, ulong fileIndex, uint numberOfLinks)
    {
        VolumeSerialNumber = volumeSerialNumber;
        FileIndex = fileIndex;
        NumberOfLinks = numberOfLinks;
    }
}

public static class CatalogChatContentNative
{
    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_DISPOSITION_INFO
    {
        [MarshalAs(UnmanagedType.Bool)]
        public bool DeleteFile;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle hFile,
        out BY_HANDLE_FILE_INFORMATION lpFileInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetFileInformationByHandle(
        SafeFileHandle hFile,
        int FileInformationClass,
        IntPtr lpFileInformation,
        uint dwBufferSize);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    public static SafeFileHandle OpenForDelete(string path)
    {
        const uint genericRead = 0x80000000;
        const uint delete = 0x00010000;
        const uint shareRead = 0x00000001;
        const uint shareWrite = 0x00000002;
        const uint shareDelete = 0x00000004;
        const uint openExisting = 3;
        const uint normal = 0x00000080;
        SafeFileHandle handle = CreateFile(
            path,
            genericRead | delete,
            shareRead | shareWrite | shareDelete,
            IntPtr.Zero,
            openExisting,
            normal,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return handle;
    }

    public static CatalogChatContentIdentity GetIdentity(SafeFileHandle handle)
    {
        BY_HANDLE_FILE_INFORMATION information;
        if (!GetFileInformationByHandle(handle, out information))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        ulong index = ((ulong)information.FileIndexHigh << 32) | information.FileIndexLow;
        return new CatalogChatContentIdentity(
            information.VolumeSerialNumber,
            index,
            information.NumberOfLinks);
    }

    public static void DeleteByHandle(SafeFileHandle handle)
    {
        FILE_DISPOSITION_INFO information = new FILE_DISPOSITION_INFO { DeleteFile = true };
        int size = Marshal.SizeOf(typeof(FILE_DISPOSITION_INFO));
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(information, buffer, false);
            if (!SetFileInformationByHandle(handle, 4, buffer, (uint)size))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }
}
'@ | Out-Null
}

function Get-CatalogChatFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        return [IO.Path]::GetFullPath($Path)
    }
    catch {
        throw 'PATH_INVALID'
    }
}

function Normalize-CatalogChatRoot {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = Get-CatalogChatFullPath -Path $Path
    $trimmed = $full.TrimEnd([char[]]@('\', '/'))
    if ($trimmed -match '^[A-Za-z]:$') {
        return ($trimmed + '\')
    }
    return $trimmed
}

function Test-CatalogChatPathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Base
    )
    $candidateValue = (Normalize-CatalogChatRoot -Path $Candidate).TrimEnd('\')
    $baseValue = (Normalize-CatalogChatRoot -Path $Base).TrimEnd('\')
    return ($candidateValue.Equals($baseValue, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateValue.StartsWith($baseValue + '\', [StringComparison]::OrdinalIgnoreCase))
}

function Assert-CatalogChatOrdinaryDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    }
    catch {
        throw 'DIRECTORY_MISSING'
    }
    if (-not $item.PSIsContainer) {
        throw 'DIRECTORY_REQUIRED'
    }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'REPARSE_REJECTED'
    }
}

function Assert-CatalogChatOrdinaryFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    }
    catch {
        throw 'FILE_MISSING'
    }
    if ($item.PSIsContainer) {
        throw 'FILE_REQUIRED'
    }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'REPARSE_REJECTED'
    }
}

function Assert-CatalogChatParentChain {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    $parts = $RelativePath -split '[\\/]'
    $current = $Root
    for ($index = 0; $index -lt ($parts.Count - 1); $index++) {
        $current = [IO.Path]::Combine($current, $parts[$index])
        Assert-CatalogChatOrdinaryDirectory -Path $current
    }
}

function Assert-CatalogChatDirectoryAncestors {
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = Get-CatalogChatFullPath -Path $Path
    while ($true) {
        Assert-CatalogChatOrdinaryDirectory -Path $current
        $parent = [IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or $parent -ceq $current) {
            break
        }
        $current = $parent
    }
}

function Assert-CatalogChatSafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or $RelativePath.IndexOf([char]0) -ge 0) {
        throw 'PATH_INVALID'
    }
    if ([IO.Path]::IsPathRooted($RelativePath) -or $RelativePath.StartsWith('\') -or $RelativePath.StartsWith('/')) {
        throw 'PATH_ABSOLUTE'
    }
    if ($RelativePath.Contains(':') -or $RelativePath -match '[<>"|?*]') {
        throw 'PATH_ADS_OR_INVALID'
    }
    $parts = $RelativePath -split '[\\/]'
    $invalidParts = @($parts | Where-Object { $_ -eq '' -or $_ -eq '.' -or $_ -eq '..' })
    if ($parts.Count -eq 0 -or $invalidParts.Count -gt 0) {
        throw 'PATH_TRAVERSAL'
    }
    foreach ($part in $parts) {
        if ($part.EndsWith(' ') -or $part.EndsWith('.')) {
            throw 'PATH_AMBIGUOUS'
        }
        $device = $part.Split('.')[0].ToUpperInvariant()
        if ($device -in @('CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9')) {
            throw 'PATH_RESERVED_NAME'
        }
    }
}

function Get-CatalogChatIdentity {
    param([Parameter(Mandatory = $true)][IO.FileStream]$Stream)
    $identity = [CatalogChatContentNative]::GetIdentity($Stream.SafeFileHandle)
    if ($identity.NumberOfLinks -gt 1) {
        throw 'HARDLINK_REJECTED'
    }
    return ('{0}:{1}' -f $identity.VolumeSerialNumber, $identity.FileIndex)
}

function Read-CatalogChatStreamBytes {
    param([Parameter(Mandatory = $true)][IO.FileStream]$Stream)
    $Stream.Position = 0
    $buffer = New-Object IO.MemoryStream
    try {
        $Stream.CopyTo($buffer)
        [byte[]]$bytes = $buffer.ToArray()
        return ,$bytes
    }
    finally {
        $buffer.Dispose()
    }
}

function Get-CatalogChatBytesHash {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash($Bytes)
        return ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-CatalogChatAclSemantic {
    param([Parameter(Mandatory = $true)][string]$Path)
    $fileInfo = New-Object IO.FileInfo($Path)
    $security = $fileInfo.GetAccessControl()
    $sddl = $security.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::All)
    return (ConvertTo-CatalogChatAclSemantic -Sddl $sddl)
}

function ConvertTo-CatalogChatAclSemantic {
    param([Parameter(Mandatory = $true)][string]$Sddl)
    $descriptor = New-Object System.Security.AccessControl.RawSecurityDescriptor -ArgumentList $Sddl
    $dacl = @()
    if ($null -ne $descriptor.DiscretionaryAcl) {
        foreach ($ace in $descriptor.DiscretionaryAcl) {
            $raw = New-Object byte[] $ace.BinaryLength
            $ace.GetBinaryForm($raw, 0)
            $dacl += [Convert]::ToBase64String($raw)
        }
    }
    $sacl = @()
    if ($null -ne $descriptor.SystemAcl) {
        foreach ($ace in $descriptor.SystemAcl) {
            $raw = New-Object byte[] $ace.BinaryLength
            $ace.GetBinaryForm($raw, 0)
            $sacl += [Convert]::ToBase64String($raw)
        }
    }
    $canonical = [ordered]@{
        owner = [string]$descriptor.Owner.Value
        group = [string]$descriptor.Group.Value
        control_flags = [int]$descriptor.ControlFlags
        # ACE order affects Windows access checks; never sort it away.
        dacl = @($dacl)
        sacl = @($sacl)
    }
    return ($canonical | ConvertTo-Json -Depth 10 -Compress)
}

function Get-CatalogChatAclSddl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $fileInfo = New-Object IO.FileInfo($Path)
    $security = $fileInfo.GetAccessControl()
    return $security.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::All)
}

function Write-CatalogChatBytesInPlace {
    param(
        [Parameter(Mandatory = $true)][IO.FileStream]$Stream,
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $Stream.Position = 0
    $Stream.SetLength(0)
    if ($Bytes.Length -gt 0) {
        $Stream.Write($Bytes, 0, $Bytes.Length)
    }
    $Stream.Flush($true)
}

function Write-CatalogChatDurableBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][IO.FileMode]$Mode
    )
    $stream = [IO.FileStream]::new($Path, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        if ($Bytes.Length -gt 0) {
            $stream.Write($Bytes, 0, $Bytes.Length)
        }
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Write-CatalogChatDurableJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][IO.FileMode]$Mode
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes(($Value | ConvertTo-Json -Depth 50 -Compress))
    Write-CatalogChatDurableBytes -Path $Path -Bytes $bytes -Mode $Mode
}

function Open-CatalogChatNewTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    Assert-CatalogChatParentChain -Root $Root -RelativePath $RelativePath
    $stream = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::ReadWrite,
        ([IO.FileShare]::Read -bor [IO.FileShare]::Delete)
    )
    try {
        $identity = Get-CatalogChatIdentity -Stream $stream
        return ,([pscustomobject]@{ stream = $stream; identity = $identity })
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Restore-CatalogChatExistingBytes {
    param(
        [Parameter(Mandatory = $true)][IO.FileStream]$Stream,
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedHash,
        [Parameter(Mandatory = $true)][string]$ExpectedIdentity,
        [Parameter(Mandatory = $true)][string]$ExpectedAcl
    )
    $identity = Get-CatalogChatIdentity -Stream $Stream
    if ($identity -cne $ExpectedIdentity) {
        throw 'ROLLBACK_IDENTITY_MISMATCH'
    }
    $Stream.Position = 0
    $Stream.SetLength(0)
    if ($Bytes.Length -gt 0) {
        $Stream.Write($Bytes, 0, $Bytes.Length)
    }
    $Stream.Flush($true)
    $actual = Get-CatalogChatBytesHash -Bytes (Read-CatalogChatStreamBytes -Stream $Stream)
    if ($actual -cne $ExpectedHash) {
        throw 'ROLLBACK_CONTENT_HASH_MISMATCH'
    }
    $acl = Get-CatalogChatAclSemantic -Path $Path
    if ($acl -cne $ExpectedAcl) {
        throw 'ROLLBACK_ACL_CHANGED'
    }
}

function Invoke-CatalogChatRollback {
    param(
        [Parameter(Mandatory = $true)]$Prepared
    )
    $errors = New-Object 'System.Collections.Generic.List[string]'
    $deleted = New-Object 'System.Collections.Generic.List[string]'
    $items = @($Prepared | Where-Object { $_.attempted -or $_.created } | Sort-Object index -Descending)
    foreach ($record in $items) {
        try {
            if ($record.existed) {
                Restore-CatalogChatExistingBytes `
                    -Stream $record.stream `
                    -Bytes $record.old_bytes `
                    -Path $record.target_path `
                    -ExpectedHash $record.old_sha256 `
                    -ExpectedIdentity $record.identity_before `
                    -ExpectedAcl $record.acl_before
            }
            elseif ($record.created) {
                $currentIdentity = Get-CatalogChatIdentity -Stream $record.stream
                if ($currentIdentity -cne $record.identity_after) {
                    throw 'ROLLBACK_NEW_IDENTITY_MISMATCH'
                }
                $currentHash = Get-CatalogChatBytesHash -Bytes (Read-CatalogChatStreamBytes -Stream $record.stream)
                if ($currentHash -cne $record.sha256) {
                    throw 'ROLLBACK_NEW_CONTENT_HASH_MISMATCH'
                }
                $deleteHandle = [CatalogChatContentNative]::OpenForDelete($record.target_path)
                try {
                    $deleteIdentity = [CatalogChatContentNative]::GetIdentity($deleteHandle)
                    $deleteIdentityText = '{0}:{1}' -f $deleteIdentity.VolumeSerialNumber, $deleteIdentity.FileIndex
                    if ($deleteIdentityText -cne $record.identity_after) {
                        throw 'ROLLBACK_NEW_IDENTITY_MISMATCH'
                    }
                    [CatalogChatContentNative]::DeleteByHandle($deleteHandle)
                }
                finally {
                    $deleteHandle.Dispose()
                }
                $deleted.Add($record.relative_path)
            }
        }
        catch {
            $errors.Add([string]$_.Exception.Message)
        }
    }
    [pscustomobject]@{
        status = $(if ($errors.Count -eq 0) { 'ROLLED_BACK' } else { 'ROLLBACK_FAILED' })
        error = $(if ($errors.Count -eq 0) { $null } else { ($errors -join ';') })
        deleted_created_paths = @($deleted)
    }
}

function Get-CatalogChatResultFiles {
    param([Parameter(Mandatory = $true)]$Prepared)
    return @($Prepared | Sort-Object index | ForEach-Object {
        [pscustomobject]@{
            path = $_.relative_path
            existed_before = [bool]$_.existed
            created = [bool]$_.created
            identity_before = $_.identity_before
            identity_after = $_.identity_after
            acl_semantics_preserved = $_.acl_semantics_preserved
            old_sha256 = $_.old_sha256
            new_sha256 = $_.sha256
        }
    })
}

function New-CatalogChatBlockedResult {
    param(
        [Parameter(Mandatory = $true)][string]$Cause,
        $BackupRoot,
        $JournalPath,
        $Rollback,
        $Prepared,
        $CreatedPaths
    )
    [pscustomobject]@{
        status = 'BLOCKED'
        cause = $Cause
        backup_root = $BackupRoot
        journal_path = $JournalPath
        rollback = $Rollback
        created_paths = @($CreatedPaths)
        files = if ($null -eq $Prepared) { @() } else { @(Get-CatalogChatResultFiles -Prepared $Prepared) }
    }
}

function Invoke-CatalogChatContentTransaction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PayloadRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot,
        [Parameter(Mandatory = $true)][string]$BackupRoot,
        [Parameter(Mandatory = $true)][object[]]$Files
    )

    $prepared = New-Object 'System.Collections.Generic.List[object]'
    $createdPaths = New-Object 'System.Collections.Generic.List[string]'
    $journalPath = $null
    $backupFull = $null
    $journal = $null
    $rollback = $null

    try {
        if ($Files.Count -eq 0) {
            throw 'FILES_EMPTY'
        }
        $payloadFull = Normalize-CatalogChatRoot -Path $PayloadRoot
        $targetFull = Normalize-CatalogChatRoot -Path $TargetRoot
        $backupFull = Normalize-CatalogChatRoot -Path $BackupRoot
        Assert-CatalogChatDirectoryAncestors -Path $payloadFull
        Assert-CatalogChatDirectoryAncestors -Path $targetFull
        if ((Test-CatalogChatPathWithin -Candidate $payloadFull -Base $targetFull) -or
            (Test-CatalogChatPathWithin -Candidate $targetFull -Base $payloadFull)) {
            throw 'PAYLOAD_TARGET_OVERLAP'
        }
        if ((Test-Path -LiteralPath $backupFull)) {
            throw 'BACKUP_ROOT_EXISTS'
        }
        $backupParent = [IO.Path]::GetDirectoryName($backupFull)
        if ([string]::IsNullOrEmpty($backupParent)) {
            throw 'BACKUP_PARENT_INVALID'
        }
        Assert-CatalogChatDirectoryAncestors -Path $backupParent
        if ((Test-CatalogChatPathWithin -Candidate $backupFull -Base $payloadFull) -or
            (Test-CatalogChatPathWithin -Candidate $backupFull -Base $targetFull)) {
            throw 'BACKUP_ROOT_OVERLAP'
        }

        $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $index = 0
        foreach ($inputRecord in $Files) {
            $pathProperty = $inputRecord.PSObject.Properties['path']
            $hashProperty = $inputRecord.PSObject.Properties['sha256']
            $oldProperty = $inputRecord.PSObject.Properties['expected_old_sha256']
            if ($null -eq $pathProperty -or $null -eq $hashProperty -or $null -eq $oldProperty) {
                throw 'RECORD_INVALID'
            }
            $relativePath = [string]$pathProperty.Value
            Assert-CatalogChatSafeRelativePath -RelativePath $relativePath
            if (-not $seen.Add($relativePath)) {
                throw 'DUPLICATE_PATH'
            }
            $newHash = ([string]$hashProperty.Value).ToLowerInvariant()
            if ($newHash -notmatch '^[0-9a-f]{64}$') {
                throw 'NEW_HASH_INVALID'
            }
            $expectedOld = $oldProperty.Value
            if ($null -ne $expectedOld) {
                $expectedOld = ([string]$expectedOld).ToLowerInvariant()
                if ($expectedOld -notmatch '^[0-9a-f]{64}$') {
                    throw 'OLD_HASH_INVALID'
                }
            }

            Assert-CatalogChatParentChain -Root $payloadFull -RelativePath $relativePath
            $sourcePath = [IO.Path]::Combine($payloadFull, $relativePath)
            Assert-CatalogChatOrdinaryFile -Path $sourcePath
            $source = [IO.FileStream]::new($sourcePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            try {
                $sourceIdentity = Get-CatalogChatIdentity -Stream $source
                [byte[]]$newBytes = Read-CatalogChatStreamBytes -Stream $source
            }
            finally {
                $source.Dispose()
            }
            if ((Get-CatalogChatBytesHash -Bytes $newBytes) -cne $newHash) {
                throw 'NEW_HASH_MISMATCH'
            }

            Assert-CatalogChatParentChain -Root $targetFull -RelativePath $relativePath
            $targetPath = [IO.Path]::Combine($targetFull, $relativePath)
            $targetExists = Test-Path -LiteralPath $targetPath -PathType Leaf
            if ($targetExists) {
                if ($null -eq $expectedOld) {
                    throw 'EXPECTED_OLD_REQUIRED'
                }
                Assert-CatalogChatOrdinaryFile -Path $targetPath
                $targetStream = [IO.FileStream]::new($targetPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::Read)
                try {
                    $identity = Get-CatalogChatIdentity -Stream $targetStream
                    [byte[]]$oldBytes = Read-CatalogChatStreamBytes -Stream $targetStream
                    $oldHash = Get-CatalogChatBytesHash -Bytes $oldBytes
                    if ($oldHash -cne $expectedOld) {
                        $targetStream.Dispose()
                        throw 'OLD_HASH_MISMATCH'
                    }
                    $acl = Get-CatalogChatAclSemantic -Path $targetPath
                    [void]$prepared.Add([pscustomobject]@{
                        index = $index
                        relative_path = $relativePath
                        source_path = $sourcePath
                        target_path = $targetPath
                        sha256 = $newHash
                        expected_old_sha256 = $expectedOld
                        old_sha256 = $oldHash
                        new_bytes = $newBytes
                        old_bytes = $oldBytes
                        existed = $true
                        created = $false
                        attempted = $false
                        stream = $targetStream
                        identity_before = $identity
                        identity_after = $identity
                        acl_before = $acl
                        acl_semantics_preserved = $false
                    })
                }
                catch {
                    if ($null -ne $targetStream) {
                        $targetStream.Dispose()
                    }
                    throw
                }
            }
            else {
                if ($null -ne $expectedOld) {
                    throw 'TARGET_MISSING_EXPECTED_OLD'
                }
                [void]$prepared.Add([pscustomobject]@{
                    index = $index
                    relative_path = $relativePath
                    source_path = $sourcePath
                    target_path = $targetPath
                    sha256 = $newHash
                    expected_old_sha256 = $null
                    old_sha256 = $null
                    new_bytes = $newBytes
                    old_bytes = $null
                    existed = $false
                    created = $false
                    attempted = $false
                    stream = $null
                    identity_before = $null
                    identity_after = $null
                    acl_before = $null
                    acl_semantics_preserved = $true
                })
            }
            $index++
        }

        New-Item -ItemType Directory -Path $backupFull -ErrorAction Stop | Out-Null
        Assert-CatalogChatOrdinaryDirectory -Path $backupFull
        $journalPath = [IO.Path]::Combine($backupFull, 'journal.json')
        $journal = [ordered]@{
            schema_version = 1
            state = 'STARTED'
            cause = $null
            rollback = $null
            files = @($prepared.ToArray() | Sort-Object index | ForEach-Object {
                [ordered]@{
                    path = $_.relative_path
                    existed_before = [bool]$_.existed
                    old_sha256 = $_.old_sha256
                    new_sha256 = $_.sha256
                    identity_before = $_.identity_before
                    sddl = if ($_.existed) { Get-CatalogChatAclSddl -Path $_.target_path } else { $null }
                }
            })
            applied_paths = @()
            created_paths = @()
        }
        Write-CatalogChatDurableJson -Path $journalPath -Value $journal -Mode ([IO.FileMode]::CreateNew)

        $backupFiles = [IO.Path]::Combine($backupFull, 'files')
        New-Item -ItemType Directory -Path $backupFiles -ErrorAction Stop | Out-Null
        $manifest = [ordered]@{ schema_version = 1; files = @() }
        foreach ($record in @($prepared.ToArray() | Sort-Object index)) {
            $contentName = '{0:D4}.content.bin' -f $record.index
            if ($record.existed) {
                $contentPath = [IO.Path]::Combine($backupFiles, $contentName)
                Write-CatalogChatDurableBytes -Path $contentPath -Bytes $record.old_bytes -Mode ([IO.FileMode]::CreateNew)
            }
            $manifestFileEntry = [ordered]@{
                path = $record.relative_path
                existed_before = [bool]$record.existed
                sha256 = $record.old_sha256
                sddl = if ($record.existed) { Get-CatalogChatAclSddl -Path $record.target_path } else { $null }
                content_file = if ($record.existed) { ('files/' + $contentName) } else { $null }
            }
            $manifest.files += $manifestFileEntry
        }
        Write-CatalogChatDurableJson -Path ([IO.Path]::Combine($backupFull, 'manifest.json')) -Value $manifest -Mode ([IO.FileMode]::CreateNew)
        $journal['state'] = 'BACKUP_COMPLETE'
        Write-CatalogChatDurableJson -Path $journalPath -Value $journal -Mode ([IO.FileMode]::Create)

        foreach ($record in @($prepared.ToArray() | Sort-Object index)) {
            if ($record.existed) {
                $record.attempted = $true
                Write-CatalogChatBytesInPlace -Stream $record.stream -Bytes $record.new_bytes -Path $record.target_path
                $actual = Get-CatalogChatBytesHash -Bytes (Read-CatalogChatStreamBytes -Stream $record.stream)
                if ($actual -cne $record.sha256) {
                    throw 'NEW_CONTENT_HASH_MISMATCH'
                }
                $record.identity_after = Get-CatalogChatIdentity -Stream $record.stream
                if ($record.identity_after -cne $record.identity_before) {
                    throw 'INPLACE_IDENTITY_CHANGED'
                }
                $record.acl_semantics_preserved = ((Get-CatalogChatAclSemantic -Path $record.target_path) -ceq $record.acl_before)
                if (-not $record.acl_semantics_preserved) {
                    throw 'INPLACE_ACL_CHANGED'
                }
            }
            else {
                $record.attempted = $true
                $opened = Open-CatalogChatNewTarget -Path $record.target_path -Root $targetFull -RelativePath $record.relative_path
                $record.stream = $opened.stream
                $record.identity_after = $opened.identity
                $record.created = $true
                [void]$createdPaths.Add($record.relative_path)
                Write-CatalogChatBytesInPlace -Stream $record.stream -Bytes $record.new_bytes -Path $record.target_path
                $actual = Get-CatalogChatBytesHash -Bytes (Read-CatalogChatStreamBytes -Stream $record.stream)
                if ($actual -cne $record.sha256) {
                    throw 'NEW_CONTENT_HASH_MISMATCH'
                }
            }
            $journal['state'] = 'APPLYING'
            $journal['applied_paths'] = @($prepared.ToArray() | Where-Object { $_.attempted } | ForEach-Object { $_.relative_path })
            $journal['created_paths'] = @($createdPaths)
            Write-CatalogChatDurableJson -Path $journalPath -Value $journal -Mode ([IO.FileMode]::Create)
        }
        $journal['state'] = 'APPLIED'
        Write-CatalogChatDurableJson -Path $journalPath -Value $journal -Mode ([IO.FileMode]::Create)
        return [pscustomobject]@{
          status = 'APPLIED'
          cause = $null
          backup_root = $backupFull
          target_root = $targetFull
          backup_manifest_sha256 = Get-CatalogChatBytesHash -Bytes ([IO.File]::ReadAllBytes([IO.Path]::Combine($backupFull, 'manifest.json')))
            journal_path = $journalPath
            rollback = [pscustomobject]@{ status = 'NOT_NEEDED'; error = $null; deleted_created_paths = @() }
            created_paths = @($createdPaths)
            files = @(Get-CatalogChatResultFiles -Prepared $prepared.ToArray())
        }
    }
    catch {
        $cause = [string]$_.Exception.Message
        if ($null -ne $journalPath -and $null -ne $journal) {
            $journal['state'] = 'ROLLBACK_PENDING'
            $journal['cause'] = $cause
            $journal['rollback'] = [ordered]@{ status = 'PENDING'; error = $null; deleted_created_paths = @() }
            $journal['created_paths'] = @($createdPaths)
            try {
                Write-CatalogChatDurableJson -Path $journalPath -Value $journal -Mode ([IO.FileMode]::Create)
            }
            catch {
                $journal['rollback']['error'] = 'JOURNAL_CAUSE_WRITE_FAILED:' + [string]$_.Exception.Message
            }
            $rollback = Invoke-CatalogChatRollback -Prepared $prepared.ToArray()
            $journal['state'] = 'BLOCKED'
            $journal['rollback'] = [ordered]@{
                status = $rollback.status
                error = $rollback.error
                deleted_created_paths = @($rollback.deleted_created_paths)
            }
            try {
                Write-CatalogChatDurableJson -Path $journalPath -Value $journal -Mode ([IO.FileMode]::Create)
            }
            catch {
                if ($null -eq $rollback.error) {
                    $rollback.error = 'JOURNAL_FINAL_WRITE_FAILED:' + [string]$_.Exception.Message
                }
            }
        }
        else {
            $rollback = [pscustomobject]@{ status = 'NOT_REQUIRED'; error = $null; deleted_created_paths = @() }
        }
        return New-CatalogChatBlockedResult `
            -Cause $cause `
            -BackupRoot $backupFull `
            -JournalPath $journalPath `
            -Rollback $rollback `
            -Prepared $prepared.ToArray() `
            -CreatedPaths $createdPaths.ToArray()
    }
    finally {
        foreach ($record in $prepared.ToArray()) {
            if ($null -ne $record.stream) {
                try { $record.stream.Dispose() } catch { }
            }
        }
    }
}

function Undo-CatalogChatContentTransaction {
    <# Internal maintenance API, not an authorization or chat endpoint.
       Caller must retain the original APPLIED object in trusted maintenance
       state, stop consumers and authenticate roots/ACLs before this call.
       Never reconstruct Transaction from an untrusted request or journal.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$TargetRoot,
        [Parameter(Mandatory = $true)]$Transaction,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$Cause
    )
    $prepared = New-Object 'System.Collections.Generic.List[object]'
    $undoPath = $null
    $rollback = $null
    try {
        $root = Normalize-CatalogChatRoot -Path $TargetRoot
        if ($Transaction.status -cne 'APPLIED' -or $root -cne $Transaction.target_root) {
            throw 'ROLLBACK_TRANSACTION_INVALID'
        }
        Assert-CatalogChatDirectoryAncestors -Path $root
        $backup = Normalize-CatalogChatRoot -Path $Transaction.backup_root
        Assert-CatalogChatDirectoryAncestors -Path $backup
        $manifestPath = [IO.Path]::Combine($backup, 'manifest.json')
        Assert-CatalogChatOrdinaryFile -Path $manifestPath
        $manifestBytes = [IO.File]::ReadAllBytes($manifestPath)
        if ((Get-CatalogChatBytesHash -Bytes $manifestBytes) -cne $Transaction.backup_manifest_sha256) {
            throw 'ROLLBACK_BACKUP_MANIFEST_MISMATCH'
        }
        $manifest = [Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json
        $entries = @($manifest.files)
        $applied = @($Transaction.files)
        if ($entries.Count -eq 0 -or $entries.Count -ne $applied.Count) {
            throw 'ROLLBACK_BACKUP_INVENTORY_MISMATCH'
        }
        $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        # Hold every target open and validate the complete set before restoration.
        for ($index = 0; $index -lt $entries.Count; $index++) {
            $entry = $entries[$index]
            $expected = $applied[$index]
            $relative = [string]$entry.path
            Assert-CatalogChatSafeRelativePath -RelativePath $relative
            if (-not $seen.Add($relative.Replace('/', '\')) -or
                $relative -cne $expected.path -or
                $entry.existed_before -ne $expected.existed_before -or
                $entry.sha256 -cne $expected.old_sha256) {
                throw 'ROLLBACK_BACKUP_INVENTORY_MISMATCH'
            }
            Assert-CatalogChatParentChain -Root $root -RelativePath $relative
            $path = [IO.Path]::Combine($root, $relative)
            Assert-CatalogChatOrdinaryFile -Path $path
            $share = [IO.FileShare]::Read
            if (-not $entry.existed_before) { $share = $share -bor [IO.FileShare]::Delete }
            $stream = [IO.FileStream]::new($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, $share)
            $record = [pscustomobject]@{
                index = $index; relative_path = $relative; target_path = $path
                existed = [bool]$entry.existed_before; attempted = $true
                created = (-not [bool]$entry.existed_before); stream = $stream
                identity_before = $expected.identity_after; identity_after = $expected.identity_after
                sha256 = $expected.new_sha256; old_sha256 = $entry.sha256
                old_bytes = $null; acl_before = $null
            }
            [void]$prepared.Add($record)
            if ((Get-CatalogChatIdentity -Stream $stream) -cne $expected.identity_after) {
                throw 'ROLLBACK_CURRENT_IDENTITY_MISMATCH'
            }
            if ((Get-CatalogChatBytesHash -Bytes (Read-CatalogChatStreamBytes -Stream $stream)) -cne $expected.new_sha256) {
                throw 'ROLLBACK_CURRENT_HASH_MISMATCH'
            }
            if ($entry.existed_before) {
                $contentRelative = 'files/{0:D4}.content.bin' -f $index
                if ($entry.content_file -cne $contentRelative) { throw 'ROLLBACK_BACKUP_PATH_MISMATCH' }
                Assert-CatalogChatParentChain -Root $backup -RelativePath $contentRelative
                $contentPath = [IO.Path]::Combine($backup, $contentRelative)
                Assert-CatalogChatOrdinaryFile -Path $contentPath
                $record.old_bytes = [IO.File]::ReadAllBytes($contentPath)
                if ((Get-CatalogChatBytesHash -Bytes $record.old_bytes) -cne $entry.sha256) {
                    throw 'ROLLBACK_BACKUP_CONTENT_MISMATCH'
                }
                $record.acl_before = ConvertTo-CatalogChatAclSemantic -Sddl $entry.sddl
                if ((Get-CatalogChatAclSemantic -Path $path) -cne $record.acl_before) {
                    throw 'ROLLBACK_CURRENT_ACL_MISMATCH'
                }
            }
        }
        # Persist intent before any write. Journal is diagnostic, not authority.
        $undoPath = [IO.Path]::Combine($backup, 'post-apply-rollback.json')
        $undo = [ordered]@{ status = 'ROLLBACK_PENDING'; cause = $Cause; rollback = $null }
        Write-CatalogChatDurableJson -Path $undoPath -Value $undo -Mode ([IO.FileMode]::CreateNew)
        $rollback = Invoke-CatalogChatRollback -Prepared $prepared.ToArray()
        $undo.status = $rollback.status
        $undo.rollback = $rollback
        # Never truncate the durable intent/cause to publish the outcome. If this
        # new result file fails, the original intent still proves why we reverted.
        $resultPath = [IO.Path]::Combine($backup, 'post-apply-rollback.result.json')
        Write-CatalogChatDurableJson -Path $resultPath -Value $undo -Mode ([IO.FileMode]::CreateNew)
        return [pscustomobject]@{ status = $rollback.status; cause = $rollback.error; original_cause = $Cause; journal_path = $resultPath; intent_journal_path = $undoPath; rollback = $rollback }
    }
    catch {
        return [pscustomobject]@{ status = 'BLOCKED'; cause = [string]$_.Exception.Message; original_cause = $Cause; journal_path = $undoPath; rollback = $rollback }
    }
    finally {
        foreach ($record in $prepared.ToArray()) { $record.stream.Dispose() }
    }
}

Export-ModuleMember -Function Invoke-CatalogChatContentTransaction, Undo-CatalogChatContentTransaction
