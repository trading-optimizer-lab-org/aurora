[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:CatalogChatMaintenanceRoot = 'C:\ProgramData\AURORA\CatalogRequester'
$script:CatalogChatMaintenanceTaskName = 'AURORA Catalog Chat Entry'

# This is the exact public receipt path used by _FINAL_BOOTSTRAP_RECEIPT_NAME in
# infra/sp500_megarun/catalog_requester.py, joined with broker.receipts.
$script:CatalogChatMaintenancePublicFiles = @(
    [ordered]@{ relative_path = 'bin/catalog-requester-client.pyz'; kind = 'application' },
    [ordered]@{ relative_path = 'bin/catalog-requester-client.manifest.json'; kind = 'manifest' },
    [ordered]@{ relative_path = 'bin/catalog-requester-broker.pyz'; kind = 'application' },
    [ordered]@{ relative_path = 'bin/catalog-requester-broker.manifest.json'; kind = 'manifest' },
    [ordered]@{ relative_path = 'config/catalog_campaign_registry_v1.json'; kind = 'registry' },
    [ordered]@{ relative_path = 'config/production-enabled-v1.seal.json'; kind = 'production_config' },
    [ordered]@{ relative_path = 'receipts/controller-bootstrap-v1.receipt.json'; kind = 'production_finalization_receipt' },
    [ordered]@{ relative_path = 'docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md'; kind = 'public_input' },
    [ordered]@{ relative_path = 'config/catalog_run_prompt_policy_v1.json'; kind = 'public_input' },
    [ordered]@{ relative_path = 'config/catalog_requester_v1.json'; kind = 'public_input' },
    [ordered]@{ relative_path = 'config/catalog_controller_actors_v1.json'; kind = 'public_input' },
    [ordered]@{ relative_path = 'config/catalog_github_controls_v1.json'; kind = 'public_input' },
    [ordered]@{ relative_path = 'config/catalog_requester_public_key_v1.pem'; kind = 'public_input' },
    [ordered]@{ relative_path = 'schemas/catalog_requester_app_manifest_v1.schema.json'; kind = 'public_input' },
    [ordered]@{ relative_path = 'schemas/catalog_campaign_definition_manifest_v1.schema.json'; kind = 'public_input' },
    [ordered]@{ relative_path = 'schemas/catalog_run_prompt_policy_v1.schema.json'; kind = 'public_input' }
)

$script:CatalogChatMaintenanceDirectories = @(
    [ordered]@{ relative_path = 'bin'; service_writers = $false },
    [ordered]@{ relative_path = 'receipts'; service_writers = $true },
    [ordered]@{ relative_path = 'chat-inbox'; service_writers = $true },
    [ordered]@{ relative_path = 'chat-intents'; service_writers = $true },
    [ordered]@{ relative_path = 'chat-replies'; service_writers = $true },
    [ordered]@{ relative_path = 'config'; service_writers = $false },
    [ordered]@{ relative_path = 'docs'; service_writers = $false },
    [ordered]@{ relative_path = 'docs/runbooks'; service_writers = $false },
    [ordered]@{ relative_path = 'schemas'; service_writers = $false },
    [ordered]@{ relative_path = 'config/catalog_campaign_definitions'; service_writers = $false }
)

# A narrow transport seam keeps the actual script executable while allowing
# tests to replace only the OS hash observation. No content other than the
# public file hash is consumed here.
if ($null -eq (Get-Command -Name Get-CatalogChatFileHash -CommandType Function -ErrorAction SilentlyContinue)) {
    function Get-CatalogChatFileHash {
        param([Parameter(Mandatory = $true)][string]$Path)
        $hash = Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop
        return [string]$hash.Hash
    }
}

if ($null -eq (Get-Command -Name Get-CatalogChatRegistryText -CommandType Function -ErrorAction SilentlyContinue)) {
    function Get-CatalogChatRegistryText {
        $path = Join-Path $script:CatalogChatMaintenanceRoot 'config\catalog_campaign_registry_v1.json'
        foreach ($parent in @($script:CatalogChatMaintenanceRoot, (Join-Path $script:CatalogChatMaintenanceRoot 'config'))) {
            $observed = Get-CatalogChatPathObservation -Path $parent
            if (-not $observed.observation_available -or -not $observed.exists -or
                -not $observed.is_directory -or $observed.is_reparse) { throw 'PREFLIGHT_REGISTRY_UNAVAILABLE' }
        }
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if ($item.PSIsContainer -or (Test-CatalogChatReparsePoint -Item $item) -or
            $item.Length -gt 1048576) { throw 'PREFLIGHT_REGISTRY_UNAVAILABLE' }
        $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            if ($stream.Length -gt 1048576) { throw 'PREFLIGHT_REGISTRY_UNAVAILABLE' }
            $reader = [IO.StreamReader]::new($stream, [Text.UTF8Encoding]::new($false, $true))
            try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally { $stream.Dispose() }
    }
}

function Get-CatalogChatDefinitionFiles {
    $registry = Get-CatalogChatRegistryText | ConvertFrom-Json -ErrorAction Stop
    $property = $registry.PSObject.Properties['campaigns']
    if ($null -eq $property) { throw 'PREFLIGHT_REGISTRY_DEFINITION_INVALID' }
    $campaigns = $property.Value # Preserve an empty/single-element JSON array.
    if ($null -eq $campaigns -or $campaigns -isnot [array] -or $campaigns.Count -gt 256) {
        throw 'PREFLIGHT_REGISTRY_DEFINITION_INVALID'
    }
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $records = @()
    foreach ($campaign in $campaigns) {
        $active = Get-CatalogChatProperty -InputObject $campaign -Name 'active'
        if ($active -isnot [bool]) { throw 'PREFLIGHT_REGISTRY_DEFINITION_INVALID' }
        if (-not $active) { continue }
        $key = Get-CatalogChatProperty -InputObject $campaign -Name 'campaign_key'
        $path = Get-CatalogChatProperty -InputObject $campaign -Name 'definition_manifest_path'
        if ($key -isnot [string] -or $key.Length -gt 128 -or
            $key -cnotmatch '^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+$' -or
            $path -isnot [string] -or $path -cne "config/catalog_campaign_definitions/$key.manifest.json" -or
            -not $seen.Add($path)) { throw 'PREFLIGHT_REGISTRY_DEFINITION_INVALID' }
        $records += [ordered]@{ relative_path = $path; kind = 'campaign_definition' }
    }
    return $records
}

function Get-CatalogChatProperty {
    param(
        [Parameter(Mandatory = $false)][AllowNull()][object]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $InputObject) {
        return $null
    }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Test-CatalogChatReparsePoint {
    param([Parameter(Mandatory = $false)][AllowNull()][object]$Item)
    if ($null -eq $Item) {
        return $false
    }
    $explicit = Get-CatalogChatProperty -InputObject $Item -Name 'IsReparsePoint'
    if ($null -ne $explicit) {
        return [bool]$explicit
    }
    $linkType = Get-CatalogChatProperty -InputObject $Item -Name 'LinkType'
    if (-not [string]::IsNullOrWhiteSpace([string]$linkType)) {
        return $true
    }
    $attributes = Get-CatalogChatProperty -InputObject $Item -Name 'Attributes'
    if ($null -eq $attributes) {
        return $false
    }
    try {
        $fileAttributes = [System.IO.FileAttributes]$attributes
        return (($fileAttributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
    }
    catch {
        return $false
    }
}

function Get-CatalogChatPathObservation {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $items = @(Get-Item -LiteralPath $Path -Force -ErrorAction Stop)
    }
    catch {
        $missing = $_.CategoryInfo.Category -eq [Management.Automation.ErrorCategory]::ObjectNotFound -or
            $_.Exception -is [IO.FileNotFoundException]
        return [pscustomobject][ordered]@{
            path = $Path
            observation_available = [bool]$missing
            exists = $false
            is_directory = $false
            is_reparse = $false
        }
    }
    if ($items.Count -eq 0) {
        return [pscustomobject][ordered]@{
            path = $Path
            observation_available = $true
            exists = $false
            is_directory = $false
            is_reparse = $false
        }
    }
    if ($items.Count -ne 1) {
        return [pscustomobject][ordered]@{
            path = $Path
            observation_available = $false
            exists = $false
            is_directory = $false
            is_reparse = $false
        }
    }
    $item = $items[0]
    $isDirectory = [bool](Get-CatalogChatProperty -InputObject $item -Name 'PSIsContainer')
    return [pscustomobject][ordered]@{
        path = $Path
        observation_available = $true
        exists = $true
        is_directory = $isDirectory
        is_reparse = (Test-CatalogChatReparsePoint -Item $item)
    }
}

function ConvertTo-CatalogChatIdentityText {
    param([Parameter(Mandatory = $false)][AllowNull()][object]$Identity)
    if ($null -eq $Identity) {
        return ''
    }
    $value = Get-CatalogChatProperty -InputObject $Identity -Name 'Value'
    if ($null -ne $value) {
        return [string]$value
    }
    return [string]$Identity
}

function Test-CatalogChatWriteRight {
    param([Parameter(Mandatory = $true)][string]$Rights, [switch]$Ancestor)
    try { $mask = [long][Security.AccessControl.FileSystemRights]$Rights }
    catch { return $true } # Unknown rights cannot establish a safe preflight.
    $forbidden = 0x500D0040 # Generic write/all, delete, change owner/DACL, delete children.
    if (-not $Ancestor) { $forbidden = $forbidden -bor 0x116 }
    return ($mask -band $forbidden) -ne 0
}

function Test-CatalogChatAllowedWriter {
    param(
        [Parameter(Mandatory = $true)][string]$Identity,
        [Parameter(Mandatory = $false)][AllowEmptyCollection()][string[]]$AdditionalWriters = @(),
        [switch]$AncestorOwner
    )
    try {
        if ($Identity -match '^S-1-') {
            $sid = ([Security.Principal.SecurityIdentifier]::new($Identity)).Value
        } else {
            $sid = ([Security.Principal.NTAccount]::new($Identity)).Translate([Security.Principal.SecurityIdentifier]).Value
        }
        if ($sid -in @('S-1-5-18', 'S-1-5-32-544')) { return $true }
        if ($AncestorOwner -and $sid -eq 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464') {
            return $true # Windows TrustedInstaller as ancestor owner only.
        }
        foreach ($additional in @($AdditionalWriters)) {
            if ($additional -notin @('HP', 'AURORAAgent', 'AURORARequester')) { return $false }
            $accountSid = [string](Get-LocalUser -Name $additional -ErrorAction Stop).SID
            if ($sid -eq $accountSid) { return $true }
        }
    } catch { return $false }
    return $false
}

function Get-CatalogChatAclObservation {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $false)][AllowEmptyCollection()][string[]]$AdditionalWriters = @(),
        [switch]$Ancestor
    )
    try {
        $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    }
    catch {
        return [pscustomobject][ordered]@{
            observation_available = $false
            owner = $null
            sddl = $null
            access_rules = @()
            effective_writers = @()
        }
    }

    $owner = [string](Get-CatalogChatProperty -InputObject $acl -Name 'Owner')
    $sddl = [string](Get-CatalogChatProperty -InputObject $acl -Name 'Sddl')
    if ([string]::IsNullOrWhiteSpace($sddl)) {
        try {
            $sddl = [string]$acl.GetSecurityDescriptorSddlForm('All')
        }
        catch {
            $sddl = ''
        }
    }
    $accessProperty = $acl.PSObject.Properties['Access']
    $accessValue = if ($null -eq $accessProperty) { $null } else { @($accessProperty.Value) }
    if ([string]::IsNullOrWhiteSpace($owner) -or [string]::IsNullOrWhiteSpace($sddl) -or $null -eq $accessProperty) {
        return [pscustomobject][ordered]@{
            observation_available = $false
            owner = $owner
            sddl = $sddl
            access_rules = @()
            effective_writers = @()
        }
    }

    $rules = @()
    # Ownership itself can confer DACL control; do not inspect allow ACEs alone.
    $writers = @($owner)
    foreach ($rule in @($accessValue)) {
        $identity = ConvertTo-CatalogChatIdentityText -Identity (Get-CatalogChatProperty -InputObject $rule -Name 'IdentityReference')
        $rights = [string](Get-CatalogChatProperty -InputObject $rule -Name 'FileSystemRights')
        $accessType = [string](Get-CatalogChatProperty -InputObject $rule -Name 'AccessControlType')
        $inherited = Get-CatalogChatProperty -InputObject $rule -Name 'IsInherited'
        $inheritance = [string](Get-CatalogChatProperty -InputObject $rule -Name 'InheritanceFlags')
        $propagation = [string](Get-CatalogChatProperty -InputObject $rule -Name 'PropagationFlags')
        if ([string]::IsNullOrWhiteSpace($identity) -or
            [string]::IsNullOrWhiteSpace($rights) -or
            [string]::IsNullOrWhiteSpace($accessType) -or
            $null -eq $inherited) {
            return [pscustomobject][ordered]@{
                observation_available = $false
                owner = $owner
                sddl = $sddl
                access_rules = @()
                effective_writers = @()
            }
        }
        $record = [ordered]@{
            identity = $identity
            access_type = $accessType
            rights = $rights
            is_inherited = [bool]$inherited
            inheritance_flags = $inheritance
            propagation_flags = $propagation
        }
        $rules += [pscustomobject]$record
        if ($accessType -ieq 'Allow' -and $propagation -notmatch 'InheritOnly' -and
            (Test-CatalogChatWriteRight -Rights $rights -Ancestor:$Ancestor)) {
            $writers += $identity
        }
    }
    $unauthorized = @(
        $writers | Where-Object {
            -not (Test-CatalogChatAllowedWriter -Identity ([string]$_) -AdditionalWriters $AdditionalWriters -AncestorOwner:($Ancestor -and $_ -eq $owner))
        } | Sort-Object -Unique
    )
    return [pscustomobject][ordered]@{
        observation_available = $true
        owner = $owner
        sddl = $sddl
        access_rules = @($rules)
        effective_writers = @($writers | Sort-Object -Unique)
        unauthorized_effective_writers = $unauthorized
    }
}

function ConvertTo-CatalogChatRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $false)][AllowEmptyCollection()][string[]]$AdditionalWriters = @()
    )
    $pathObservation = Get-CatalogChatPathObservation -Path $Path
    $record = [ordered]@{
        path = $Path
        relative_path = $RelativePath
        kind = $Kind
        state = 'absent'
        is_reparse = $false
        is_directory = $false
        sha256 = $null
        acl = $null
        observation_available = [bool]$pathObservation.observation_available
    }
    if (-not $pathObservation.observation_available) {
        $record.state = 'unavailable'
        return [pscustomobject]$record
    }
    if (-not $pathObservation.exists) {
        return [pscustomobject]$record
    }
    $record.state = 'existing'
    $record.is_reparse = [bool]$pathObservation.is_reparse
    $record.is_directory = [bool]$pathObservation.is_directory
    if ($pathObservation.is_reparse) {
        return [pscustomobject]$record
    }

    $acl = Get-CatalogChatAclObservation -Path $Path -AdditionalWriters $AdditionalWriters
    $record.acl = $acl
    if (-not $acl.observation_available) {
        return [pscustomobject]$record
    }
    if ($pathObservation.is_directory) {
        return [pscustomobject]$record
    }
    try {
        $hash = Get-CatalogChatFileHash -Path $Path
        $record.sha256 = ([string]$hash).ToLowerInvariant()
    }
    catch {
        $record.sha256 = $null
    }
    return [pscustomobject]$record
}

function Get-CatalogChatAncestorPaths {
    $paths = @()
    $current = $script:CatalogChatMaintenanceRoot
    while ($true) {
        $parent = Split-Path -Path $current -Parent
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            break
        }
        $paths += $parent
        if ($parent -eq 'C:\') {
            break
        }
        $current = $parent
    }
    return @($paths)
}

function Get-CatalogChatMaintenancePreflight {
    $issues = [System.Collections.Generic.List[string]]::new()
    $notes = [System.Collections.Generic.List[string]]::new()
    $inventory = [ordered]@{}

    $rootPath = $script:CatalogChatMaintenanceRoot
    $rootObservation = Get-CatalogChatPathObservation -Path $rootPath
    $rootRecord = [ordered]@{
        path = $rootPath
        state = $(if ($rootObservation.exists) { 'existing' } else { 'absent' })
        is_reparse = [bool]$rootObservation.is_reparse
        observation_available = [bool]$rootObservation.observation_available
        acl = $null
    }
    if (-not $rootObservation.observation_available) {
        $null = $issues.Add('PREFLIGHT_ROOT_UNAVAILABLE')
    }
    elseif (-not $rootObservation.exists) {
        $null = $issues.Add('PREFLIGHT_ROOT_MISSING')
    }
    elseif ($rootObservation.is_reparse) {
        $null = $issues.Add('PREFLIGHT_ROOT_REPARSE')
    }
    elseif (-not $rootObservation.is_directory) {
        $null = $issues.Add('PREFLIGHT_ROOT_NOT_DIRECTORY')
    }
    if ($rootObservation.exists -and -not $rootObservation.is_reparse -and $rootObservation.is_directory) {
        $rootRecord.acl = Get-CatalogChatAclObservation -Path $rootPath -AdditionalWriters @()
        if (-not $rootRecord.acl.observation_available) {
            $null = $issues.Add('PREFLIGHT_ROOT_ACL_UNAVAILABLE')
        }
        elseif (@($rootRecord.acl.unauthorized_effective_writers).Count -gt 0) {
            $null = $issues.Add('PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER')
        }
    }
    $inventory.root = [pscustomobject]$rootRecord

    $ancestors = @()
    foreach ($ancestorPath in Get-CatalogChatAncestorPaths) {
        $ancestorObservation = Get-CatalogChatPathObservation -Path $ancestorPath
        $ancestorRecord = [ordered]@{
            path = $ancestorPath
            state = $(if ($ancestorObservation.exists) { 'existing' } else { 'absent' })
            is_reparse = [bool]$ancestorObservation.is_reparse
            observation_available = [bool]$ancestorObservation.observation_available
        }
        if (-not $ancestorObservation.observation_available) {
            $null = $issues.Add('PREFLIGHT_ANCESTOR_UNAVAILABLE')
        }
        elseif (-not $ancestorObservation.exists) {
            $null = $issues.Add('PREFLIGHT_ANCESTOR_MISSING')
        }
        elseif ($ancestorObservation.is_reparse) {
            $null = $issues.Add('PREFLIGHT_ANCESTOR_REPARSE')
        }
        elseif (-not $ancestorObservation.is_directory) {
            $null = $issues.Add('PREFLIGHT_ANCESTOR_NOT_DIRECTORY')
        }
        else {
            $ancestorAcl = Get-CatalogChatAclObservation -Path $ancestorPath -Ancestor
            $ancestorRecord['acl'] = $ancestorAcl
            if (-not $ancestorAcl.observation_available) {
                $null = $issues.Add('PREFLIGHT_ACL_UNAVAILABLE')
            } elseif (@($ancestorAcl.unauthorized_effective_writers).Count -gt 0) {
                $null = $issues.Add('PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER')
            }
        }
        $ancestors += [pscustomobject]$ancestorRecord
    }
    $inventory.ancestors = @($ancestors)

    $accounts = @()
    foreach ($accountName in @('AURORAAgent', 'AURORARequester', 'HP')) {
        $account = [ordered]@{ name = $accountName; state = 'unavailable'; sid = $null }
        try {
            $localUser = Get-LocalUser -Name $accountName -ErrorAction Stop
            $sid = [string](Get-CatalogChatProperty -InputObject $localUser -Name 'SID')
            if ([string]::IsNullOrWhiteSpace($sid)) {
                $null = $issues.Add('PREFLIGHT_ACCOUNT_UNAVAILABLE')
            }
            else {
                $account.state = 'existing'
                $account.sid = $sid
            }
        }
        catch {
            $null = $issues.Add('PREFLIGHT_ACCOUNT_UNAVAILABLE')
        }
        $accounts += [pscustomobject]$account
    }
    $inventory.accounts = @($accounts)

    $directories = @()
    foreach ($directory in $script:CatalogChatMaintenanceDirectories) {
        $relative = [string]$directory.relative_path
        $path = Join-Path -Path $rootPath -ChildPath ($relative.Replace('/', '\'))
        $additionalWriters = @()
        if ($relative -eq 'chat-inbox') {
            $additionalWriters = @('HP')
        }
        elseif ($relative -eq 'chat-intents' -or $relative -eq 'chat-replies') {
            $additionalWriters = @('AURORAAgent')
        }
        elseif ($relative -eq 'receipts') {
            $additionalWriters = @('AURORARequester')
        }
        $record = ConvertTo-CatalogChatRecord -Path $path -RelativePath $relative -Kind 'directory' -AdditionalWriters $additionalWriters
        $directories += $record
        if (-not $record.observation_available) {
            $null = $issues.Add('PREFLIGHT_DIRECTORY_OBSERVATION_UNAVAILABLE')
        }
        elseif ($record.state -eq 'existing' -and $record.is_reparse) {
            $null = $issues.Add('PREFLIGHT_DIRECTORY_REPARSE')
        }
        elseif ($record.state -eq 'existing' -and -not $record.is_directory) {
            $null = $issues.Add('PREFLIGHT_DIRECTORY_TYPE_INVALID')
        }
        elseif ($record.state -eq 'existing' -and $null -eq $record.acl) {
            $null = $issues.Add('PREFLIGHT_ACL_UNAVAILABLE')
        }
        elseif ($null -ne $record.acl -and -not $record.acl.observation_available) {
            $null = $issues.Add('PREFLIGHT_ACL_UNAVAILABLE')
        }
        elseif ($null -ne $record.acl -and @($record.acl.unauthorized_effective_writers).Count -gt 0) {
            $null = $issues.Add('PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER')
        }
    }
    $inventory.directories = @($directories)

    $definitionFiles = @()
    try { $definitionFiles = @(Get-CatalogChatDefinitionFiles) }
    catch {
        $reason = 'PREFLIGHT_REGISTRY_UNAVAILABLE'
        if ($_.Exception.Message -eq 'PREFLIGHT_REGISTRY_DEFINITION_INVALID') { $reason = $_.Exception.Message }
        $null = $issues.Add($reason)
    }
    $publicFiles = @()
    foreach ($publicFile in @($script:CatalogChatMaintenancePublicFiles) + $definitionFiles) {
        $relative = [string]$publicFile.relative_path
        $path = Join-Path -Path $rootPath -ChildPath ($relative.Replace('/', '\'))
        $record = ConvertTo-CatalogChatRecord -Path $path -RelativePath $relative -Kind ([string]$publicFile.kind)
        $publicFiles += $record
        if (-not $record.observation_available) {
            $null = $issues.Add('PREFLIGHT_PUBLIC_FILE_OBSERVATION_UNAVAILABLE')
        }
        elseif ($record.state -eq 'absent') {
            $null = $issues.Add('PREFLIGHT_PUBLIC_FILE_MISSING')
        }
        elseif ($record.is_reparse) {
            $null = $issues.Add('PREFLIGHT_PUBLIC_FILE_REPARSE')
        }
        elseif ($record.acl -eq $null -or -not $record.acl.observation_available) {
            $null = $issues.Add('PREFLIGHT_ACL_UNAVAILABLE')
        }
        elseif (@($record.acl.unauthorized_effective_writers).Count -gt 0) {
            $null = $issues.Add('PREFLIGHT_UNAUTHORIZED_EFFECTIVE_WRITER')
        }
        elseif ([string]::IsNullOrWhiteSpace([string]$record.sha256)) {
            $null = $issues.Add('PREFLIGHT_HASH_UNAVAILABLE')
        }
    }
    $inventory.public_files = @($publicFiles)

    $taskObservation = [ordered]@{
        task_name = $script:CatalogChatMaintenanceTaskName
        task_path = '\'
        state = 'unavailable'
        exists = $false
    }
    try {
        $tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
            Where-Object { $null -ne $_ -and [string]$_.TaskName -eq $script:CatalogChatMaintenanceTaskName })
        if ($tasks.Count -eq 0) {
            $taskObservation.state = 'absent'
            $null = $notes.Add('PREFLIGHT_TASK_ABSENT')
        }
        elseif ($tasks.Count -eq 1) {
            $taskObservation.state = 'existing'
            $taskObservation.exists = $true
            $null = $issues.Add('PREFLIGHT_TASK_EXISTS')
        }
        else {
            $taskObservation.state = 'ambiguous'
            $taskObservation.exists = $true
            $null = $issues.Add('PREFLIGHT_TASK_AMBIGUOUS')
        }
    }
    catch {
        $null = $issues.Add('PREFLIGHT_TASK_OBSERVATION_UNAVAILABLE')
    }
    $inventory.task = [pscustomobject]$taskObservation

    $uniqueIssues = @($issues | Select-Object -Unique)
    $status = 'PREFLIGHT'
    $reasonCode = 'PREFLIGHT_INVENTORY_COMPLETE'
    if ($uniqueIssues.Count -gt 0) {
        $status = 'BLOCKED'
        $reasonCode = [string]$uniqueIssues[0]
    }
    elseif ($notes.Count -gt 0) {
        $reasonCode = [string]$notes[0]
    }
    return [pscustomobject][ordered]@{
        schema_version = '1'
        status = $status
        reason_code = $reasonCode
        reason_codes = @($uniqueIssues)
        notes = @($notes | Select-Object -Unique)
        observed_at = [DateTime]::UtcNow.ToString('o')
        root = $rootPath
        mode = 'READ_ONLY'
        input_contract = 'ZERO_RUNTIME_PATHS_OR_COMMANDS'
        mutations_performed = $false
        secrets_read = $false
        candidate_approved = $false
        rollback_tested = $false
        production_ready = $false
        inventory = [pscustomobject]$inventory
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Get-CatalogChatMaintenancePreflight | ConvertTo-Json -Depth 30 -Compress
}
