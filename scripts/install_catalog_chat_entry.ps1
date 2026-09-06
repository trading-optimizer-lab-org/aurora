[CmdletBinding()]
param(
    [string]$CandidateRoot,
    [string]$ExpectedCandidateSha256,
    [string]$ExpectedApprovedCommitSha,
    [switch]$Apply,
    [string]$Confirm = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:CatalogChatEntryRequesterRoot = 'C:\ProgramData\AURORA\CatalogRequester'
$script:CatalogChatEntrySenderRoot = 'C:\ProgramData\AURORA\CatalogChatSender'
$script:CatalogChatEntryAuroraRoot = 'C:\ProgramData\AURORA'
$script:CatalogChatEntryBackupRoot = 'C:\ProgramData\AURORA-CatalogChatMaintenance'
$script:CatalogChatEntryCredentialPath = 'C:\ProgramData\AURORA\CatalogAgent\credentials\catalog-agent-credential.dpapi'
$script:CatalogChatEntryTaskName = 'AURORA Catalog Chat Entry'
$script:CatalogChatEntryBrokerTaskName = 'AURORA Catalog Requester Broker'
$script:CatalogChatEntryAgentIdentity = 'AURORAAgent'
$script:CatalogChatEntryRequesterIdentity = 'AURORARequester'
$script:CatalogChatEntryExpectedConfirmation = 'AURORA_CATALOG_CHAT_ENTRY_V1'
$script:CatalogChatEntryHistoricalReady = 'receipts/controller-bootstrap-v1.receipt.json'
$script:CatalogChatEntryProductionSeal = 'config/production-enabled-v1.seal.json'
$script:CatalogChatEntryMaintenanceReceipt = 'receipts/requester-maintenance-v1.receipt.json'
$script:CatalogChatEntryPublicKey = 'config/catalog_requester_public_key_v1.pem'
$script:CatalogChatEntryMaxJsonBytes = 1048576
$script:CatalogChatEntryMaxFileBytes = 67108864

$script:CatalogChatEntryPublicInputs = @(
    'docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md',
    'config/catalog_run_prompt_policy_v1.json',
    'config/catalog_campaign_registry_v1.json',
    'config/catalog_requester_v1.json',
    'config/catalog_controller_actors_v1.json',
    'config/catalog_github_controls_v1.json',
    'config/catalog_requester_public_key_v1.pem',
    'schemas/catalog_requester_app_manifest_v1.schema.json',
    'schemas/catalog_campaign_definition_manifest_v1.schema.json',
    'schemas/catalog_run_prompt_policy_v1.schema.json'
)

$script:CatalogChatEntryRuntimeLogicalPaths = [ordered]@{
    client_python = 'C:\ProgramData\AURORA\CatalogRequester\client-venv\Scripts\python.exe'
    broker_python = 'C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts\python.exe'
    broker_pythonw = 'C:\ProgramData\AURORA\CatalogRequester\broker-venv\Scripts\pythonw.exe'
}

. (Join-Path $PSScriptRoot 'preflight_catalog_chat_maintenance.ps1')
Import-Module (Join-Path $PSScriptRoot 'catalog_chat_content_transaction.psm1') -ErrorAction Stop

if ($null -eq (Get-Command -Name Test-CatalogChatEntryAdministrator -CommandType Function -ErrorAction SilentlyContinue)) {
    function Test-CatalogChatEntryAdministrator {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }
}

if ($null -eq (Get-Command -Name Resolve-CatalogChatEntryPhysicalPath -CommandType Function -ErrorAction SilentlyContinue)) {
    function Resolve-CatalogChatEntryPhysicalPath {
        param([Parameter(Mandatory = $true)][string]$LogicalPath)
        return [IO.Path]::GetFullPath($LogicalPath)
    }
}

if ($null -eq (Get-Command -Name Get-CatalogChatEntryPathObservation -CommandType Function -ErrorAction SilentlyContinue)) {
    function Get-CatalogChatEntryPathObservation {
        param([Parameter(Mandatory = $true)][string]$Path)
        try {
            $item = Get-Item -LiteralPath (Resolve-CatalogChatEntryPhysicalPath -LogicalPath $Path) -Force -ErrorAction Stop
        }
        catch {
            $missing = $_.CategoryInfo.Category -eq [Management.Automation.ErrorCategory]::ObjectNotFound -or
                $_.Exception -is [IO.FileNotFoundException] -or
                $_.Exception -is [DirectoryNotFoundException]
            if ($missing) {
                return [pscustomobject][ordered]@{
                    path = $Path; observation_available = $true; exists = $false
                    is_directory = $false; is_reparse = $false
                }
            }
            return [pscustomobject][ordered]@{
                path = $Path; observation_available = $false; exists = $false
                is_directory = $false; is_reparse = $false
            }
        }
        $isDirectory = [bool](Get-CatalogChatProperty -InputObject $item -Name 'PSIsContainer')
        return [pscustomobject][ordered]@{
            path = $Path; observation_available = $true; exists = $true
            is_directory = $isDirectory; is_reparse = (Test-CatalogChatReparsePoint -Item $item)
        }
    }
}

if ($null -eq (Get-Command -Name Get-CatalogChatEntryAclObservation -CommandType Function -ErrorAction SilentlyContinue)) {
    function Get-CatalogChatEntryAclObservation {
        param([Parameter(Mandatory = $true)][string]$Path)
        return Get-CatalogChatAclObservation -Path (Resolve-CatalogChatEntryPhysicalPath -LogicalPath $Path) -AdditionalWriters @()
    }
}

if ($null -eq (Get-Command -Name Set-CatalogChatEntryAcl -CommandType Function -ErrorAction SilentlyContinue)) {
    function Set-CatalogChatEntryAcl {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)]$AclObject
        )
        Set-Acl -LiteralPath (Resolve-CatalogChatEntryPhysicalPath -LogicalPath $Path) -AclObject $AclObject -ErrorAction Stop
    }
}

if ($null -eq (Get-Command -Name Get-CatalogChatEntryAffectedWork -CommandType Function -ErrorAction SilentlyContinue)) {
    function Get-CatalogChatEntryAffectedWork {
        param([switch]$AllowAuthenticatedBroker)
        $affectedNames = @($script:CatalogChatEntryTaskName, $script:CatalogChatEntryBrokerTaskName)
        $tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
            Where-Object { $null -ne $_ -and [string]$_.TaskName -in $affectedNames })
        $authenticatedBrokerRunning = $false
        if ($AllowAuthenticatedBroker) {
            $brokerTasks = @($tasks | Where-Object { [string]$_.TaskName -ceq $script:CatalogChatEntryBrokerTaskName })
            if ($brokerTasks.Count -eq 1 -and [string]$brokerTasks[0].State -ieq 'Running' -and
                (Test-CatalogChatEntryTaskAction $brokerTasks[0] (Get-CatalogChatEntryExpectedBrokerAction) $script:CatalogChatEntryRequesterIdentity)) {
                $authenticatedBrokerRunning = $true
            }
        }
        $runningTasks = @($tasks | Where-Object {
                [string]$_.State -ieq 'Running' -and
                -not ($AllowAuthenticatedBroker -and [string]$_.TaskName -ceq $script:CatalogChatEntryBrokerTaskName -and $authenticatedBrokerRunning)
            } | ForEach-Object { [pscustomobject]@{ kind = 'task'; name = [string]$_.TaskName } })

        $clientPython = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $script:CatalogChatEntryRuntimeLogicalPaths.client_python
        $brokerPythonw = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $script:CatalogChatEntryRuntimeLogicalPaths.broker_pythonw
        $processes = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction Stop | ForEach-Object {
            $path = [string]$_.ExecutablePath
            $isBroker = $path -ieq $brokerPythonw
            if ($AllowAuthenticatedBroker -and $isBroker -and $authenticatedBrokerRunning) { return }
            if ([string]::IsNullOrWhiteSpace($path) -or ($path -ine $clientPython -and -not $isBroker)) {
                [pscustomobject]@{ kind = 'unknown_process'; process_id = [int]$_.ProcessId; executable_path = $path }
                return
            }
            [pscustomobject]@{
                kind = 'process'; process_id = [int]$_.ProcessId
                executable_path = $path
            }
        })
        return @($runningTasks + $processes)
    }
}

if ($null -eq (Get-Command -Name Get-CatalogChatEntryCredential -CommandType Function -ErrorAction SilentlyContinue)) {
    function Get-CatalogChatEntryCredential {
        $logicalPath = $script:CatalogChatEntryCredentialPath
        $observation = Get-CatalogChatEntryPathObservation -Path $logicalPath
        if (-not $observation.observation_available -or -not $observation.exists -or
            $observation.is_directory -or $observation.is_reparse) {
            throw 'CREDENTIAL_FILE_UNAVAILABLE'
        }
        $acl = Get-CatalogChatEntryAclObservation -Path $logicalPath
        if (-not $acl.observation_available -or @($acl.unauthorized_effective_writers).Count -ne 0) {
            throw 'CREDENTIAL_FILE_ACL_INVALID'
        }
        $physicalPath = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $logicalPath
        $protected = [IO.File]::ReadAllText($physicalPath, [Text.UTF8Encoding]::new($false, $true))
        if ([string]::IsNullOrWhiteSpace($protected)) { throw 'CREDENTIAL_FILE_EMPTY' }
        $secure = ConvertTo-SecureString -String $protected -ErrorAction Stop
        if ($null -eq $secure -or $secure.Length -eq 0) {
            if ($null -ne $secure) { $secure.Dispose() }
            throw 'CREDENTIAL_DECRYPTION_FAILED'
        }
        return [PSCredential]::new($script:CatalogChatEntryAgentIdentity, $secure)
    }
}

if ($null -eq (Get-Command -Name Invoke-CatalogChatEntryVerifierProcess -CommandType Function -ErrorAction SilentlyContinue)) {
    $script:CatalogChatEntryVerifierSourceBase64 = 'ZnJvbSBpbXBvcnRsaWIgaW1wb3J0IGltcG9ydF9tb2R1bGUKaW1wb3J0IGpzb24KZnJvbSBwYXRobGliIGltcG9ydCBQYXRoCmltcG9ydCBzeXMKCmtpbmQgPSBzeXMuYXJndlsxXQpyb290ID0gUGF0aChzeXMuYXJndlsyXSkucmVzb2x2ZShzdHJpY3Q9VHJ1ZSkKaWYga2luZCBub3QgaW4geydjbGllbnQnLCAnYnJva2VyJ306CiAgICByYWlzZSBWYWx1ZUVycm9yKCd2ZXJpZmllciBraW5kIGlzIG5vdCBjbG9zZWQnKQphcHBsaWNhdGlvbiA9IHJvb3QgLyAnYmluJyAvIGYnY2F0YWxvZy1yZXF1ZXN0ZXIte2tpbmR9LnB5eicKc3lzLnBhdGguaW5zZXJ0KDAsIHN0cihhcHBsaWNhdGlvbikpCm1vZHVsZSA9IGltcG9ydF9tb2R1bGUoZidhdXJvcmFfY2F0YWxvZ19yZXF1ZXN0ZXJfe2tpbmR9LmNhdGFsb2dfcmVxdWVzdGVyJykKdmVyaWZpZWQgPSBtb2R1bGUudmVyaWZ5X2luc3RhbGxlZF9yZXF1ZXN0ZXJfYXBwbGljYXRpb24oCiAgICBicm9rZXJfcm9vdD1yb290LAogICAgYXBwbGljYXRpb25fa2luZD1raW5kLAogICAgYXBwbGljYXRpb25fcGF0aD1hcHBsaWNhdGlvbiwKKQppZiBub3QgaXNpbnN0YW5jZSh2ZXJpZmllZCwgZGljdCk6CiAgICByYWlzZSBWYWx1ZUVycm9yKCdvZmZpY2lhbCB2ZXJpZmllciByZXR1cm5lZCBubyBtYXBwaW5nJykKY29yZSA9IHZlcmlmaWVkLmdldCgnbWFuaWZlc3RfY29yZScpCmlmIG5vdCBpc2luc3RhbmNlKGNvcmUsIGRpY3QpOgogICAgcmFpc2UgVmFsdWVFcnJvcignb2ZmaWNpYWwgdmVyaWZpZXIgcmV0dXJuZWQgbm8gbWFuaWZlc3QgY29yZScpCnJlcG9ydGVkX2tpbmQgPSBjb3JlLmdldCgnYXBwbGljYXRpb25fa2luZCcpCnJlcG9ydGVkX2NvbW1pdCA9IGNvcmUuZ2V0KCdwcm90ZWN0ZWRfY29tbWl0X3NoYScpCnByaW50KGpzb24uZHVtcHMoewogICAgJ2FwcGxpY2F0aW9uX2tpbmQnOiByZXBvcnRlZF9raW5kLAogICAgJ3Byb3RlY3RlZF9jb21taXRfc2hhJzogcmVwb3J0ZWRfY29tbWl0LAp9LCBzb3J0X2tleXM9VHJ1ZSwgc2VwYXJhdG9ycz0oJywnLCAnOicpKSkK'
    $script:CatalogChatEntryVerifierBootstrap = "import base64,sys;exec(compile(base64.b64decode(sys.argv[3]),'<aurora-catalog-entry-verifier>','exec'))"

    function Invoke-CatalogChatEntryVerifierProcess {
        param(
            [Parameter(Mandatory = $true)][string]$RuntimePython,
            [Parameter(Mandatory = $true)][ValidateSet('client', 'broker')][string]$ApplicationKind,
            [Parameter(Mandatory = $true)][string]$VerificationRoot,
            [Parameter(Mandatory = $true)][string]$ExpectedCommitSha
        )
        $output = @(& $RuntimePython -I -s -E -c $script:CatalogChatEntryVerifierBootstrap $ApplicationKind $VerificationRoot $script:CatalogChatEntryVerifierSourceBase64 2>&1)
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -or $output.Count -ne 1) {
            throw ('OFFICIAL_VERIFIER_FAILED:' + $ApplicationKind)
        }
        try { $record = [string]$output[0] | ConvertFrom-Json -ErrorAction Stop }
        catch { throw ('OFFICIAL_VERIFIER_OUTPUT_INVALID:' + $ApplicationKind) }
        if ([string]$record.application_kind -cne $ApplicationKind -or
            [string]$record.protected_commit_sha -cne $ExpectedCommitSha) {
            throw ('OFFICIAL_VERIFIER_BINDING_INVALID:' + $ApplicationKind)
        }
        return $record
    }
}

function Get-CatalogChatEntryProperty {
    param(
        [Parameter(Mandatory = $false)][AllowNull()][object]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $InputObject) { return $null }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-CatalogChatEntryBytesHash {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-CatalogChatEntryFileBytes {
    param(
        [Parameter(Mandatory = $true)][string]$LogicalPath,
        [int]$MaximumBytes = $script:CatalogChatEntryMaxFileBytes
    )
    $observation = Get-CatalogChatEntryPathObservation -Path $LogicalPath
    if (-not $observation.observation_available -or -not $observation.exists -or
        $observation.is_directory -or $observation.is_reparse) {
        throw 'FILE_UNAVAILABLE'
    }
    $physicalPath = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $LogicalPath
    $stream = [IO.File]::Open($physicalPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        if ($stream.Length -gt $MaximumBytes) { throw 'FILE_TOO_LARGE' }
        $buffer = New-Object IO.MemoryStream
        try { $stream.CopyTo($buffer); return ,([byte[]]$buffer.ToArray()) }
        finally { $buffer.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Get-CatalogChatEntryFileHash {
    param([Parameter(Mandatory = $true)][string]$LogicalPath)
    return Get-CatalogChatEntryBytesHash -Bytes (Get-CatalogChatEntryFileBytes -LogicalPath $LogicalPath)
}

function Assert-CatalogChatEntryDirectory {
    param([Parameter(Mandatory = $true)][string]$LogicalPath, [switch]$AllowAbsent)
    $observation = Get-CatalogChatEntryPathObservation -Path $LogicalPath
    if (-not $observation.observation_available) { throw 'DIRECTORY_OBSERVATION_UNAVAILABLE' }
    if (-not $observation.exists) {
        if ($AllowAbsent) { return $false }
        throw 'DIRECTORY_MISSING'
    }
    if (-not $observation.is_directory) { throw 'DIRECTORY_REQUIRED' }
    if ($observation.is_reparse) { throw 'REPARSE_REJECTED' }
    return $true
}

function Assert-CatalogChatEntryFile {
    param([Parameter(Mandatory = $true)][string]$LogicalPath)
    $observation = Get-CatalogChatEntryPathObservation -Path $LogicalPath
    if (-not $observation.observation_available) { throw 'FILE_OBSERVATION_UNAVAILABLE' }
    if (-not $observation.exists) { throw 'FILE_MISSING' }
    if ($observation.is_directory) { throw 'FILE_REQUIRED' }
    if ($observation.is_reparse) { throw 'REPARSE_REJECTED' }
}

function Assert-CatalogChatEntryProtectedAcl {
    param([Parameter(Mandatory = $true)][string]$LogicalPath)
    $acl = Get-CatalogChatEntryAclObservation -Path $LogicalPath
    if ($null -eq $acl -or -not $acl.observation_available -or
        [string]::IsNullOrWhiteSpace([string]$acl.owner) -or
        [string]::IsNullOrWhiteSpace([string]$acl.sddl) -or
        @($acl.unauthorized_effective_writers).Count -ne 0) {
        throw 'PROTECTED_ACL_INVALID'
    }
    $owner = [string]$acl.owner
    if ($owner -notin @('S-1-5-32-544', 'BUILTIN\Administrators', 'Administrators') -and
        $owner -notmatch '(?i)(^|\\)Administrators$') {
        throw 'PROTECTED_ACL_OWNER_INVALID'
    }
    return $acl
}

function ConvertTo-CatalogChatEntrySid {
    param([Parameter(Mandatory = $true)][string]$Identity)
    try {
        if ($Identity -match '^S-1-') {
            return ([Security.Principal.SecurityIdentifier]::new($Identity)).Value
        }
        return ([Security.Principal.NTAccount]::new($Identity)).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        return ''
    }
}

function Get-CatalogChatEntryAclContractObservation {
    param([Parameter(Mandatory = $true)][string]$Path)
    $acl = Get-CatalogChatEntryAclObservation -Path $Path
    if ($null -eq $acl -or -not $acl.observation_available) {
        throw 'RESOURCE_ACL_OBSERVATION_UNAVAILABLE'
    }
    $rulesProperty = $acl.PSObject.Properties['access_rules']
    if ($null -eq $rulesProperty) {
        throw 'RESOURCE_ACL_RULES_UNAVAILABLE'
    }
    return $acl
}

function Get-CatalogChatEntryResourceAclEntries {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('config', 'inbox', 'intents', 'replies', 'sender')][string]$Kind
    )
    switch ($Kind) {
        'sender' {
            return @(
                [pscustomobject]@{ identity = 'S-1-5-18'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'S-1-5-32-544'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'HP'; rights = [Security.AccessControl.FileSystemRights]::ReadAndExecute }
            )
        }
        'config' {
            return @(
                [pscustomobject]@{ identity = 'S-1-5-18'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'S-1-5-32-544'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'AURORAAgent'; rights = [Security.AccessControl.FileSystemRights]::ReadAndExecute }
            )
        }
        'inbox' {
            return @(
                [pscustomobject]@{ identity = 'S-1-5-18'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'S-1-5-32-544'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'HP'; rights = ([Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Write) },
                [pscustomobject]@{ identity = 'AURORAAgent'; rights = [Security.AccessControl.FileSystemRights]::ReadAndExecute }
            )
        }
        'intents' {
            return @(
                [pscustomobject]@{ identity = 'S-1-5-18'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'S-1-5-32-544'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'AURORAAgent'; rights = [Security.AccessControl.FileSystemRights]::Modify }
            )
        }
        'replies' {
            return @(
                [pscustomobject]@{ identity = 'S-1-5-18'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'S-1-5-32-544'; rights = [Security.AccessControl.FileSystemRights]::FullControl },
                [pscustomobject]@{ identity = 'AURORAAgent'; rights = [Security.AccessControl.FileSystemRights]::Modify },
                [pscustomobject]@{ identity = 'HP'; rights = [Security.AccessControl.FileSystemRights]::ReadAndExecute }
            )
        }
    }
}

function Assert-CatalogChatEntryResourceAcl {
    param(
        [Parameter(Mandatory = $true)][string]$LogicalPath,
        [Parameter(Mandatory = $true)][ValidateSet('config', 'inbox', 'intents', 'replies', 'sender')][string]$Kind
    )
    $acl = Get-CatalogChatEntryAclContractObservation -Path $LogicalPath
    $ownerSid = ConvertTo-CatalogChatEntrySid -Identity ([string]$acl.owner)
    if ($ownerSid -ne 'S-1-5-32-544') { throw 'RESOURCE_ACL_OWNER_INVALID' }
    if ([string]$acl.sddl -match '(?i)G:') {
        # The owner/DACL observation is still required below; this only avoids accepting a partial mock.
        if ([string]::IsNullOrWhiteSpace([string]$acl.sddl)) { throw 'RESOURCE_ACL_INVALID' }
    }

    $hp = Get-LocalUser -Name 'HP' -ErrorAction Stop
    $agent = Get-LocalUser -Name $script:CatalogChatEntryAgentIdentity -ErrorAction Stop
    $hpSid = [string](Get-CatalogChatEntryProperty $hp 'SID')
    $agentSid = [string](Get-CatalogChatEntryProperty $agent 'SID')
    if ($hpSid -notmatch '^S-1-' -or $agentSid -notmatch '^S-1-') { throw 'RESOURCE_ACL_IDENTITY_UNAVAILABLE' }

    $sync = [long][Security.AccessControl.FileSystemRights]::Synchronize
    $read = [long][Security.AccessControl.FileSystemRights]::ReadAndExecute
    $writeRead = [long]([Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Write)
    $modify = [long][Security.AccessControl.FileSystemRights]::Modify
    $full = [long][Security.AccessControl.FileSystemRights]::FullControl
    $expected = @(
        [pscustomobject]@{ sid = 'S-1-5-18'; mask = $full },
        [pscustomobject]@{ sid = 'S-1-5-32-544'; mask = $full }
    )
    switch ($Kind) {
        'config' { $expected += [pscustomobject]@{ sid = $agentSid; mask = $read } }
        'sender' { $expected += [pscustomobject]@{ sid = $hpSid; mask = $read } }
        'inbox' {
            $expected += [pscustomobject]@{ sid = $hpSid; mask = $writeRead }
            $expected += [pscustomobject]@{ sid = $agentSid; mask = $read }
        }
        'intents' { $expected += [pscustomobject]@{ sid = $agentSid; mask = $modify } }
        'replies' {
            $expected += [pscustomobject]@{ sid = $agentSid; mask = $modify }
            $expected += [pscustomobject]@{ sid = $hpSid; mask = $read }
        }
    }

    $expectedBySid = @{}
    foreach ($item in @($expected)) { $expectedBySid[[string]$item.sid] = [long]$item.mask }
    $observedBySid = @{}
    $rules = @($acl.access_rules)
    if ($rules.Count -eq 0) { throw 'RESOURCE_ACL_RULES_INVALID' }
    foreach ($rule in $rules) {
        if ([string](Get-CatalogChatEntryProperty $rule 'access_type') -cne 'Allow' -or
            [bool](Get-CatalogChatEntryProperty $rule 'is_inherited') -or
            [string](Get-CatalogChatEntryProperty $rule 'propagation_flags') -match 'InheritOnly') {
            throw 'RESOURCE_ACL_RULES_INVALID'
        }
        $sid = ConvertTo-CatalogChatEntrySid -Identity ([string](Get-CatalogChatEntryProperty $rule 'identity'))
        if (-not $expectedBySid.ContainsKey($sid)) { throw 'RESOURCE_ACL_PRINCIPAL_INVALID' }
        try { $mask = [long][Security.AccessControl.FileSystemRights]([string](Get-CatalogChatEntryProperty $rule 'rights')) }
        catch { throw 'RESOURCE_ACL_RIGHTS_INVALID' }
        if ($observedBySid.ContainsKey($sid)) { $observedBySid[$sid] = $observedBySid[$sid] -bor $mask }
        else { $observedBySid[$sid] = $mask }
    }
    foreach ($item in @($expected)) {
        $sid = [string]$item.sid
        if (-not $observedBySid.ContainsKey($sid)) { throw 'RESOURCE_ACL_RULE_MISSING' }
        $observed = [long]$observedBySid[$sid]
        $required = [long]$item.mask
        $allowed = $required -bor $sync
        if (($observed -band $required) -ne $required -or ($observed -bor $allowed) -ne $allowed) {
            throw 'RESOURCE_ACL_MASK_INVALID'
        }
    }
    return $acl
}

function Set-CatalogChatEntryResourceAcl {
    param(
        [Parameter(Mandatory = $true)][string]$LogicalPath,
        [Parameter(Mandatory = $true)][ValidateSet('file', 'directory')][string]$ObjectKind,
        [Parameter(Mandatory = $true)][ValidateSet('config', 'inbox', 'intents', 'replies', 'sender')][string]$Profile
    )
    $security = if ($ObjectKind -eq 'directory') {
        New-Object System.Security.AccessControl.DirectorySecurity
    } else {
        New-Object System.Security.AccessControl.FileSecurity
    }
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    $inheritance = if ($ObjectKind -eq 'directory') {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else { [Security.AccessControl.InheritanceFlags]::None }
    $propagation = [Security.AccessControl.PropagationFlags]::None
    foreach ($entry in @(Get-CatalogChatEntryResourceAclEntries -Kind $Profile)) {
        $identity = if ([string]$entry.identity -match '^S-1-') {
            [Security.Principal.SecurityIdentifier]::new([string]$entry.identity)
        } else {
            [Security.Principal.SecurityIdentifier]::new([string](Get-CatalogChatEntryProperty (Get-LocalUser -Name ([string]$entry.identity) -ErrorAction Stop) 'SID'))
        }
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [Security.AccessControl.FileSystemRights]$entry.rights,
            $inheritance,
            $propagation,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $security.AddAccessRule($rule)
    }
    Set-CatalogChatEntryAcl -Path $LogicalPath -AclObject $security
}

function Get-CatalogChatEntryFileIdentity {
    param([Parameter(Mandatory = $true)][string]$LogicalPath)
    if ($null -eq ('CatalogChatContentNative' -as [type])) { throw 'FILE_IDENTITY_UNAVAILABLE' }
    $physical = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $LogicalPath
    $handle = [CatalogChatContentNative]::OpenForDelete($physical)
    try {
        $identity = [CatalogChatContentNative]::GetIdentity($handle)
        return ('{0}:{1}:{2}' -f $identity.VolumeSerialNumber, $identity.FileIndex, $identity.NumberOfLinks)
    }
    finally { $handle.Dispose() }
}

function Get-CatalogChatEntryResourcePlan {
    param([Parameter(Mandatory = $true)]$ServiceConfig)
    $items = New-Object 'System.Collections.Generic.List[object]'
    $senderExists = Assert-CatalogChatEntryDirectory $script:CatalogChatEntrySenderRoot -AllowAbsent
    if ($senderExists) { [void](Assert-CatalogChatEntryResourceAcl -LogicalPath $script:CatalogChatEntrySenderRoot -Kind sender) }
    if (-not $senderExists) {
        [void]$items.Add([pscustomobject]@{ path = $script:CatalogChatEntrySenderRoot; kind = 'directory'; profile = 'sender'; exists = $false })
    }
    if (-not [bool]$ServiceConfig.exists) {
        [void]$items.Add([pscustomobject]@{ path = [string]$ServiceConfig.path; kind = 'file'; profile = 'config'; exists = $false })
    }
    foreach ($item in @(
        [pscustomobject]@{ path = (Join-Path $script:CatalogChatEntryRequesterRoot 'chat-inbox'); profile = 'inbox' },
        [pscustomobject]@{ path = (Join-Path $script:CatalogChatEntryRequesterRoot 'chat-intents'); profile = 'intents' },
        [pscustomobject]@{ path = (Join-Path $script:CatalogChatEntryRequesterRoot 'chat-replies'); profile = 'replies' }
    )) {
        $observation = Get-CatalogChatEntryPathObservation -Path $item.path
        if (-not $observation.observation_available) { throw 'CHAT_DIRECTORY_OBSERVATION_UNAVAILABLE' }
        if ($observation.exists) {
            if (-not $observation.is_directory -or $observation.is_reparse) { throw 'CHAT_DIRECTORY_INVALID' }
            [void](Assert-CatalogChatEntryResourceAcl -LogicalPath $item.path -Kind $item.profile)
        }
        [void]$items.Add([pscustomobject]@{ path = $item.path; kind = 'directory'; profile = $item.profile; exists = [bool]$observation.exists })
    }
    return $items.ToArray()
}

function New-CatalogChatEntryOwnedConfigBytes {
    param([Parameter(Mandatory = $true)][string]$SenderSid)
    return [Text.UTF8Encoding]::new($false).GetBytes('{"schema_version":"1","sender_sid":"' + $SenderSid + '"}' + "`n")
}

function Add-CatalogChatEntryOwnedResource {
    param(
        [Parameter(Mandatory = $true)]$PlanItem,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$OwnedResources,
        [Parameter(Mandatory = $true)][string]$SenderSid
    )
    if ([bool]$PlanItem.exists) { return }
    if ($PlanItem.kind -eq 'file') {
        $physical = Resolve-CatalogChatEntryPhysicalPath -LogicalPath ([string]$PlanItem.path)
        $bytes = New-CatalogChatEntryOwnedConfigBytes -SenderSid $SenderSid
        $stream = [IO.FileStream]::new($physical, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $createdIdentity = [CatalogChatContentNative]::GetIdentity($stream.SafeFileHandle)
            [void]$OwnedResources.Add([pscustomobject]@{
                kind = 'file'; path = [string]$PlanItem.path
                sha256 = Get-CatalogChatEntryBytesHash $bytes
                identity = ('{0}:{1}:{2}' -f $createdIdentity.VolumeSerialNumber, $createdIdentity.FileIndex, $createdIdentity.NumberOfLinks)
            })
            $stream.Write($bytes, 0, $bytes.Length)
        }
        finally { $stream.Dispose() }
        Set-CatalogChatEntryResourceAcl -LogicalPath ([string]$PlanItem.path) -ObjectKind 'file' -Profile ([string]$PlanItem.profile)
        [void](Assert-CatalogChatEntryResourceAcl -LogicalPath ([string]$PlanItem.path) -Kind ([string]$PlanItem.profile))
        return
    }
    $physicalDirectory = Resolve-CatalogChatEntryPhysicalPath -LogicalPath ([string]$PlanItem.path)
    New-Item -ItemType Directory -Path $physicalDirectory -ErrorAction Stop | Out-Null
    [void]$OwnedResources.Add([pscustomobject]@{ kind = 'directory'; path = [string]$PlanItem.path })
    Set-CatalogChatEntryResourceAcl -LogicalPath ([string]$PlanItem.path) -ObjectKind 'directory' -Profile ([string]$PlanItem.profile)
    [void](Assert-CatalogChatEntryResourceAcl -LogicalPath ([string]$PlanItem.path) -Kind ([string]$PlanItem.profile))
}

function Invoke-CatalogChatEntryResourceProvisioning {
    param(
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$OwnedResources,
        [Parameter(Mandatory = $true)][string]$SenderSid
    )
    foreach ($item in @($Plan)) {
        Add-CatalogChatEntryOwnedResource -PlanItem $item -OwnedResources $OwnedResources -SenderSid $SenderSid
    }
    return $true
}

function Remove-CatalogChatEntryOwnedResources {
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$OwnedResources)
    $outcomes = New-Object 'System.Collections.Generic.List[object]'
    for ($index = $OwnedResources.Count - 1; $index -ge 0; $index--) {
        $resource = $OwnedResources[$index]
        try {
            $observation = Get-CatalogChatEntryPathObservation -Path ([string]$resource.path)
            if (-not $observation.observation_available -or -not $observation.exists -or $observation.is_reparse) {
                throw 'OWNED_RESOURCE_OBSERVATION_INVALID'
            }
            $physical = Resolve-CatalogChatEntryPhysicalPath -LogicalPath ([string]$resource.path)
            if ($resource.kind -eq 'file') {
                if ($observation.is_directory -or (Get-CatalogChatEntryFileHash -LogicalPath ([string]$resource.path)) -cne [string]$resource.sha256) {
                    throw 'OWNED_FILE_CHANGED'
                }
                $handle = [CatalogChatContentNative]::OpenForDelete($physical)
                try {
                    $current = [CatalogChatContentNative]::GetIdentity($handle)
                    $currentText = '{0}:{1}:{2}' -f $current.VolumeSerialNumber, $current.FileIndex, $current.NumberOfLinks
                    if ($currentText -cne [string]$resource.identity -or $current.NumberOfLinks -ne 1) { throw 'OWNED_FILE_IDENTITY_CHANGED' }
                    [CatalogChatContentNative]::DeleteByHandle($handle)
                }
                finally { $handle.Dispose() }
            }
            else {
                if (-not $observation.is_directory -or @([IO.Directory]::EnumerateFileSystemEntries($physical)).Count -ne 0) {
                    throw 'OWNED_DIRECTORY_NOT_EMPTY'
                }
                [IO.Directory]::Delete($physical, $false)
            }
            [void]$outcomes.Add([pscustomobject]@{ path = $resource.path; status = 'REMOVED' })
        }
        catch {
            [void]$outcomes.Add([pscustomobject]@{ path = $resource.path; status = 'NOT_REMOVED'; cause = [string]$_.Exception.Message })
        }
    }
    return $outcomes.ToArray()
}

function Assert-CatalogChatEntrySafeCandidateTree {
    param([Parameter(Mandatory = $true)][string]$Root)
    $rootFull = [IO.Path]::GetFullPath($Root)
    if (-not [IO.Directory]::Exists($rootFull)) { throw 'CANDIDATE_ROOT_MISSING' }
    $rootAttributes = [IO.File]::GetAttributes($rootFull)
    if (($rootAttributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'CANDIDATE_ROOT_REPARSE' }
    foreach ($path in [IO.Directory]::EnumerateDirectories($rootFull, '*', [IO.SearchOption]::AllDirectories)) {
        if (([IO.File]::GetAttributes($path) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'CANDIDATE_TREE_REPARSE'
        }
    }
    foreach ($path in [IO.Directory]::EnumerateFiles($rootFull, '*', [IO.SearchOption]::AllDirectories)) {
        if (([IO.File]::GetAttributes($path) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'CANDIDATE_TREE_REPARSE'
        }
        if (([IO.FileInfo]::new($path)).Length -gt $script:CatalogChatEntryMaxFileBytes) {
            throw 'CANDIDATE_FILE_TOO_LARGE'
        }
    }
    return $rootFull
}

function Assert-CatalogChatEntryRelativePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or $RelativePath -match '\\' -or
        $RelativePath.StartsWith('/') -or $RelativePath.EndsWith('/') -or
        $RelativePath -match '(^|/)\.(?:\.?)(/|$)' -or
        $RelativePath -match '(^|/)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
        throw 'CANDIDATE_PATH_INVALID'
    }
    foreach ($part in ($RelativePath -split '/')) {
        if ($part.Length -eq 0 -or $part.Length -gt 128) { throw 'CANDIDATE_PATH_INVALID' }
    }
}

function Get-CatalogChatEntryPayloadRelativePath {
    param([Parameter(Mandatory = $true)][string]$PayloadRoot, [Parameter(Mandatory = $true)][string]$FilePath)
    $payloadFull = [IO.Path]::GetFullPath($PayloadRoot).TrimEnd('\')
    $fileFull = [IO.Path]::GetFullPath($FilePath)
    if (-not $fileFull.StartsWith($payloadFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'CANDIDATE_PAYLOAD_PATH_INVALID'
    }
    return $fileFull.Substring($payloadFull.Length + 1).Replace('\', '/')
}

function Get-CatalogChatEntryActiveDefinitionPaths {
    param([Parameter(Mandatory = $true)][string]$RegistryText)
    try { $registry = $RegistryText | ConvertFrom-Json -ErrorAction Stop }
    catch { throw 'CANDIDATE_REGISTRY_INVALID' }
    if ([string](Get-CatalogChatEntryProperty $registry 'schema_version') -cne '1') {
        throw 'CANDIDATE_REGISTRY_INVALID'
    }
    $campaignsProperty = $registry.PSObject.Properties['campaigns']
    if ($null -eq $campaignsProperty -or $campaignsProperty.Value -isnot [array]) { throw 'CANDIDATE_REGISTRY_INVALID' }
    $campaigns = @($campaignsProperty.Value)
    if ($campaigns.Count -gt 256) { throw 'CANDIDATE_REGISTRY_INVALID' }
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $paths = New-Object 'System.Collections.Generic.List[string]'
    foreach ($campaign in $campaigns) {
        $active = Get-CatalogChatEntryProperty $campaign 'active'
        if ($active -isnot [bool]) { throw 'CANDIDATE_REGISTRY_INVALID' }
        if (-not $active) { continue }
        $key = Get-CatalogChatEntryProperty $campaign 'campaign_key'
        $path = Get-CatalogChatEntryProperty $campaign 'definition_manifest_path'
        if ($key -isnot [string] -or $key.Length -gt 128 -or
            $key -cnotmatch '^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+$' -or
            $path -isnot [string] -or
            $path -cne ('config/catalog_campaign_definitions/' + $key + '.manifest.json') -or
            -not $seen.Add($path)) {
            throw 'CANDIDATE_REGISTRY_INVALID'
        }
        $paths.Add('CatalogRequester/' + $path)
    }
    return @($paths)
}

function Get-CatalogChatEntryCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedCandidateSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedApprovedCommitSha
    )
    if ($ExpectedCandidateSha256 -notmatch '^[0-9a-f]{64}$' -or
        $ExpectedApprovedCommitSha -notmatch '^[0-9a-f]{40}$') {
        throw 'PIN_FORMAT_INVALID'
    }
    $rootFull = Assert-CatalogChatEntrySafeCandidateTree -Root $Root
    $candidatePath = Join-Path $rootFull 'candidate.json'
    if (-not [IO.File]::Exists($candidatePath)) { throw 'CANDIDATE_JSON_MISSING' }
    $candidateBytes = [IO.File]::ReadAllBytes($candidatePath)
    if ($candidateBytes.Length -gt $script:CatalogChatEntryMaxJsonBytes) { throw 'CANDIDATE_JSON_TOO_LARGE' }
    $candidateHash = Get-CatalogChatEntryBytesHash $candidateBytes
    if ($candidateHash -cne $ExpectedCandidateSha256) { throw 'CANDIDATE_HASH_MISMATCH' }
    try {
        $encoding = [Text.UTF8Encoding]::new($false, $true)
        $candidate = $encoding.GetString($candidateBytes) | ConvertFrom-Json -ErrorAction Stop
    }
    catch { throw 'CANDIDATE_JSON_INVALID' }
    if ([string](Get-CatalogChatEntryProperty $candidate 'schema_version') -cne '1' -or
        [string](Get-CatalogChatEntryProperty $candidate 'status') -cne 'CANDIDATE' -or
        [string](Get-CatalogChatEntryProperty $candidate 'protected_commit_sha') -cne $ExpectedApprovedCommitSha -or
        (Get-CatalogChatEntryProperty $candidate 'two_builds_identical') -ne $true -or
        (Get-CatalogChatEntryProperty $candidate 'applications_verified_unsealed') -ne $true -or
        (Get-CatalogChatEntryProperty $candidate 'production_verified') -ne $false -or
        (Get-CatalogChatEntryProperty $candidate 'installation_authorized_by_this_file') -ne $false -or
        (Get-CatalogChatEntryProperty $candidate 'applications_verified_sealed_against_baseline') -ne $true) {
        throw 'CANDIDATE_PROVENANCE_INVALID'
    }
    $payloadRoot = Join-Path $rootFull 'payload'
    if (-not [IO.Directory]::Exists($payloadRoot)) { throw 'CANDIDATE_PAYLOAD_MISSING' }
    $recordsProperty = $candidate.PSObject.Properties['files']
    if ($null -eq $recordsProperty) { throw 'CANDIDATE_FILE_INVENTORY_INVALID' }
    $records = @($recordsProperty.Value)
    if ($records.Count -eq 0) { throw 'CANDIDATE_FILE_INVENTORY_INVALID' }
    $recordByPath = @{}
    foreach ($record in $records) {
        $relative = Get-CatalogChatEntryProperty $record 'path'
        $hash = Get-CatalogChatEntryProperty $record 'sha256'
        $size = Get-CatalogChatEntryProperty $record 'size_bytes'
        if ($relative -isnot [string] -or $hash -isnot [string] -or
            $hash -notmatch '^[0-9a-f]{64}$' -or
            (($size -isnot [int]) -and ($size -isnot [long])) -or $size -lt 0 -or
            $size -gt $script:CatalogChatEntryMaxFileBytes) {
            throw 'CANDIDATE_FILE_INVENTORY_INVALID'
        }
        Assert-CatalogChatEntryRelativePath $relative
        if ($recordByPath.ContainsKey($relative)) { throw 'CANDIDATE_FILE_INVENTORY_DUPLICATE' }
        $recordByPath[$relative] = [pscustomobject]@{
            path = $relative; sha256 = $hash; size_bytes = [int]$size
        }
    }
    $actualPayloadPaths = New-Object 'System.Collections.Generic.List[string]'
    foreach ($filePath in [IO.Directory]::EnumerateFiles($payloadRoot, '*', [IO.SearchOption]::AllDirectories)) {
        $actualRelative = Get-CatalogChatEntryPayloadRelativePath $payloadRoot $filePath
        [void]$actualPayloadPaths.Add($actualRelative)
        if (-not $recordByPath.ContainsKey($actualRelative)) { throw 'CANDIDATE_FILE_INVENTORY_EXTRA' }
        $data = [IO.File]::ReadAllBytes($filePath)
        $record = $recordByPath[$actualRelative]
        if ($data.Length -ne $record.size_bytes -or (Get-CatalogChatEntryBytesHash $data) -cne $record.sha256) {
            throw 'CANDIDATE_FILE_HASH_MISMATCH'
        }
    }
    if ($actualPayloadPaths.Count -ne $recordByPath.Count) { throw 'CANDIDATE_FILE_INVENTORY_MISSING' }

    $registryRecord = $recordByPath['CatalogRequester/config/catalog_campaign_registry_v1.json']
    if ($null -eq $registryRecord) { throw 'CANDIDATE_REGISTRY_MISSING' }
    $registryPath = Join-Path $payloadRoot 'CatalogRequester/config/catalog_campaign_registry_v1.json'
    $registryEncoding = [Text.UTF8Encoding]::new($false, $true)
    $registryText = $registryEncoding.GetString([IO.File]::ReadAllBytes($registryPath))
    $activeDefinitions = @(Get-CatalogChatEntryActiveDefinitionPaths $registryText)
    $expected = New-Object 'System.Collections.Generic.List[string]'
    foreach ($relative in $script:CatalogChatEntryPublicInputs) { [void]$expected.Add('CatalogRequester/' + $relative) }
    foreach ($relative in @(
        'CatalogRequester/bin/catalog-requester-client.pyz',
        'CatalogRequester/bin/catalog-requester-client.manifest.json',
        'CatalogRequester/bin/catalog-requester-broker.pyz',
        'CatalogRequester/bin/catalog-requester-broker.manifest.json',
        ('CatalogRequester/' + $script:CatalogChatEntryProductionSeal),
        ('CatalogRequester/' + $script:CatalogChatEntryMaintenanceReceipt)
    )) { [void]$expected.Add($relative) }
    foreach ($relative in $activeDefinitions) { [void]$expected.Add($relative) }
    [void]$expected.Add('CatalogChatSender/submit_catalog_chat_intent.py')
    [void]$expected.Add('CatalogChatSender/catalog_campaign_registry_v1.json')
    if ($recordByPath.ContainsKey('CatalogRequester/' + $script:CatalogChatEntryHistoricalReady)) {
        throw 'HISTORICAL_READY_INVENTORY_FORBIDDEN'
    }
    $expectedSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($relative in $expected) { [void]$expectedSet.Add($relative) }
    if ($expectedSet.Count -ne $recordByPath.Count) { throw 'CANDIDATE_FILE_INVENTORY_CLOSED_SET_MISMATCH' }
    foreach ($relative in $expectedSet) {
        if (-not $recordByPath.ContainsKey($relative)) { throw 'CANDIDATE_FILE_INVENTORY_CLOSED_SET_MISMATCH' }
    }
    $senderRegistryPath = Join-Path $payloadRoot 'CatalogChatSender/catalog_campaign_registry_v1.json'
    $senderExists = [IO.File]::Exists($senderRegistryPath)
    if (-not $senderExists -or
        -not [System.Collections.StructuralComparisons]::StructuralEqualityComparer.Equals(
            [IO.File]::ReadAllBytes($registryPath), [IO.File]::ReadAllBytes($senderRegistryPath))) {
        throw 'SENDER_REGISTRY_MISMATCH'
    }

    $baselineProperty = $candidate.PSObject.Properties['baseline_file_sha256']
    if ($null -eq $baselineProperty -or $null -eq $baselineProperty.Value) { throw 'BASELINE_PINS_MISSING' }
    $baseline = $baselineProperty.Value
    $baselinePins = @{}
    foreach ($property in @($baseline.PSObject.Properties)) {
        if ($property.Name -notin @(
                $script:CatalogChatEntryHistoricalReady,
                $script:CatalogChatEntryProductionSeal,
                $script:CatalogChatEntryMaintenanceReceipt
            ) -or [string]$property.Value -notmatch '^[0-9a-f]{64}$') {
            throw 'BASELINE_PINS_INVALID'
        }
        $baselinePins[$property.Name] = [string]$property.Value
    }
    return [pscustomobject][ordered]@{
        root = $rootFull; payload_root = $payloadRoot; candidate = $candidate
        candidate_sha256 = $candidateHash; commit_sha = $ExpectedApprovedCommitSha
        records = $recordByPath; registry_text = $registryText
        active_definitions = $activeDefinitions; baseline_pins = $baselinePins
        candidate_json_path = $candidatePath
    }
}

function Get-CatalogChatEntryTaskRecords {
    return @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $null -ne $_ -and [string]$_.TaskName -eq $script:CatalogChatEntryTaskName })
}

function Get-CatalogChatEntryIdentityCandidates {
    param([Parameter(Mandatory = $true)][string]$IdentityName)
    $user = Get-LocalUser -Name $IdentityName -ErrorAction Stop
    $sid = [string](Get-CatalogChatEntryProperty $user 'SID')
    if ([string]::IsNullOrWhiteSpace($sid)) { throw 'TASK_IDENTITY_UNAVAILABLE' }
    return @($sid, $IdentityName, '.\' + $IdentityName, "$env:COMPUTERNAME\$IdentityName")
}

function Get-CatalogChatEntryExpectedChatAction {
    $root = $script:CatalogChatEntryRequesterRoot
    return [pscustomobject][ordered]@{
        execute = Join-Path $root 'client-venv\Scripts\python.exe'
        arguments = '-I -s -E "' + (Join-Path $root 'bin\catalog-requester-client.pyz') + '" --serve-chat'
        working_directory = $root
    }
}

function Get-CatalogChatEntryExpectedBrokerAction {
    $root = $script:CatalogChatEntryRequesterRoot
    return [pscustomobject][ordered]@{
        execute = Join-Path $root 'broker-venv\Scripts\pythonw.exe'
        arguments = '-I -s -E "' + (Join-Path $root 'bin\catalog-requester-broker.pyz') + '"'
        working_directory = $root
    }
}

function Test-CatalogChatEntryTaskAction {
    param(
        [Parameter(Mandatory = $true)]$Task,
        [Parameter(Mandatory = $true)]$ExpectedAction,
        [Parameter(Mandatory = $true)][string]$IdentityName
    )
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) { return $false }
    $action = $actions[0]
    $principals = Get-CatalogChatEntryIdentityCandidates $IdentityName
    $principal = Get-CatalogChatEntryProperty $Task 'Principal'
    return (
        [string](Get-CatalogChatEntryProperty $action 'Execute') -ceq [string]$ExpectedAction.execute -and
        [string](Get-CatalogChatEntryProperty $action 'Arguments') -ceq [string]$ExpectedAction.arguments -and
        [string](Get-CatalogChatEntryProperty $action 'WorkingDirectory') -ceq [string]$ExpectedAction.working_directory -and
        [string](Get-CatalogChatEntryProperty $principal 'UserId') -in $principals -and
        [string](Get-CatalogChatEntryProperty $principal 'RunLevel') -ceq 'Limited' -and
        [string](Get-CatalogChatEntryProperty $principal 'LogonType') -ceq 'Password'
    )
}

function Get-CatalogChatEntryTaskSettingsSnapshot {
    param([Parameter(Mandatory = $true)]$Task)
    $settings = Get-CatalogChatEntryProperty $Task 'Settings'
    if ($null -eq $settings) { throw 'BROKER_TASK_SETTINGS_UNAVAILABLE' }
    $requiredNames = @('Enabled', 'Hidden', 'MultipleInstances', 'RestartCount', 'RestartInterval', 'StartWhenAvailable')
    $values = [ordered]@{}
    foreach ($name in $requiredNames) {
        $value = Get-CatalogChatEntryProperty $settings $name
        if ($null -eq $value) { throw 'BROKER_TASK_SETTINGS_UNAVAILABLE' }
        $values[$name] = [string]$value
    }
    return [pscustomobject]$values
}

function Get-CatalogChatEntryTaskSnapshot {
    param([Parameter(Mandatory = $true)][ValidateSet('chat', 'broker')][string]$Kind, [switch]$AllowRunning)
    if ($Kind -eq 'chat') {
        $tasks = @(Get-CatalogChatEntryTaskRecords)
        if ($tasks.Count -gt 1) { throw 'TASK_AMBIGUOUS' }
        if ($tasks.Count -eq 0) {
            return [pscustomobject][ordered]@{ exists = $false; task = $null; created = $false }
        }
        $task = $tasks[0]
        if (-not (Test-CatalogChatEntryTaskAction $task (Get-CatalogChatEntryExpectedChatAction) $script:CatalogChatEntryAgentIdentity)) {
            throw 'TASK_ACTION_MISMATCH'
        }
        if ([string]$task.State -ieq 'Running' -and -not $AllowRunning) { throw 'AFFECTED_CHAT_TASK_RUNNING' }
        return [pscustomobject][ordered]@{ exists = $true; task = $task; created = $false }
    }
    $tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $null -ne $_ -and [string]$_.TaskName -eq $script:CatalogChatEntryBrokerTaskName })
    if ($tasks.Count -gt 1) { throw 'BROKER_TASK_AMBIGUOUS' }
    if ($tasks.Count -eq 0) {
        return [pscustomobject][ordered]@{ exists = $false; task = $null; created = $false }
    }
    $task = $tasks[0]
    if (-not (Test-CatalogChatEntryTaskAction $task (Get-CatalogChatEntryExpectedBrokerAction) $script:CatalogChatEntryRequesterIdentity)) {
        throw 'BROKER_TASK_ACTION_MISMATCH'
    }
    $settings = Get-CatalogChatEntryTaskSettingsSnapshot -Task $task
    if ([string]$task.State -ieq 'Running' -and -not $AllowRunning) { throw 'AFFECTED_BROKER_TASK_RUNNING' }
    return [pscustomobject][ordered]@{ exists = $true; task = $task; created = $false; settings = $settings }
}

function Assert-CatalogChatEntryRuntime {
    $runtime = [ordered]@{}
    foreach ($name in $script:CatalogChatEntryRuntimeLogicalPaths.Keys) {
        $logicalPath = [string]$script:CatalogChatEntryRuntimeLogicalPaths[$name]
        Assert-CatalogChatEntryFile $logicalPath
        $runtime[$name] = Resolve-CatalogChatEntryPhysicalPath $logicalPath
        $parent = Split-Path -Path $logicalPath -Parent
        [void](Assert-CatalogChatEntryDirectory $parent)
        [void](Assert-CatalogChatEntryProtectedAcl $parent)
        [void](Assert-CatalogChatEntryProtectedAcl $logicalPath)
    }
    return [pscustomobject]$runtime
}

function Assert-CatalogChatEntryBaseline {
    param([Parameter(Mandatory = $true)]$Candidate)
    $requester = $script:CatalogChatEntryRequesterRoot
    $readyLogical = Join-Path $requester $script:CatalogChatEntryHistoricalReady
    $sealLogical = Join-Path $requester $script:CatalogChatEntryProductionSeal
    $readyHash = Get-CatalogChatEntryFileHash $readyLogical
    $sealHash = Get-CatalogChatEntryFileHash $sealLogical
    if (-not $Candidate.baseline_pins.ContainsKey($script:CatalogChatEntryHistoricalReady) -or
        $Candidate.baseline_pins[$script:CatalogChatEntryHistoricalReady] -cne $readyHash) {
        throw 'BASELINE_READY_HASH_MISMATCH'
    }
    if (-not $Candidate.baseline_pins.ContainsKey($script:CatalogChatEntryProductionSeal) -or
        $Candidate.baseline_pins[$script:CatalogChatEntryProductionSeal] -cne $sealHash) {
        throw 'BASELINE_SEAL_HASH_MISMATCH'
    }
    $previousLogical = Join-Path $requester $script:CatalogChatEntryMaintenanceReceipt
    $previousObservation = Get-CatalogChatEntryPathObservation $previousLogical
    $hasPrevious = $previousObservation.observation_available -and $previousObservation.exists
    if ($hasPrevious) {
        if (-not $Candidate.baseline_pins.ContainsKey($script:CatalogChatEntryMaintenanceReceipt)) {
            throw 'BASELINE_PREVIOUS_MAINTENANCE_PIN_MISSING'
        }
        if ($Candidate.baseline_pins[$script:CatalogChatEntryMaintenanceReceipt] -cne (Get-CatalogChatEntryFileHash $previousLogical)) {
            throw 'BASELINE_PREVIOUS_MAINTENANCE_HASH_MISMATCH'
        }
    }
    elseif ($Candidate.baseline_pins.ContainsKey($script:CatalogChatEntryMaintenanceReceipt)) {
        throw 'BASELINE_PREVIOUS_MAINTENANCE_UNEXPECTED'
    }
    $keyLogical = Join-Path $requester $script:CatalogChatEntryPublicKey
    Assert-CatalogChatEntryFile $keyLogical
    $candidateKeyPath = Join-Path $Candidate.payload_root ('CatalogRequester/' + $script:CatalogChatEntryPublicKey).Replace('/', '\')
    $candidateKey = [IO.File]::ReadAllBytes($candidateKeyPath)
    $installedKey = Get-CatalogChatEntryFileBytes $keyLogical
    if (-not [System.Collections.StructuralComparisons]::StructuralEqualityComparer.Equals($candidateKey, $installedKey)) {
        throw 'INSTALLED_KEY_MISMATCH'
    }
    return [pscustomobject][ordered]@{
        ready_sha256 = $readyHash
        seal_sha256 = $sealHash
        previous_maintenance_sha256 = if ($hasPrevious) { Get-CatalogChatEntryFileHash $previousLogical } else { $null }
        public_key_sha256 = Get-CatalogChatEntryBytesHash $installedKey
        ready_acl = Get-CatalogChatEntryAclObservation $readyLogical
        seal_acl = Get-CatalogChatEntryAclObservation $sealLogical
    }
}

function Assert-CatalogChatEntryServiceConfig {
    $logicalPath = Join-Path $script:CatalogChatEntryRequesterRoot 'config\chat-entry-v1.json'
    $observation = Get-CatalogChatEntryPathObservation -Path $logicalPath
    if (-not $observation.observation_available) { throw 'CHAT_ENTRY_CONFIG_OBSERVATION_UNAVAILABLE' }
    if (-not $observation.exists) {
        $hp = Get-LocalUser -Name 'HP' -ErrorAction Stop
        $hpSid = [string](Get-CatalogChatEntryProperty $hp 'SID')
        if ($hpSid -notmatch '^S-1-5-21-(?:[0-9]+-){3}[0-9]+$') { throw 'CHAT_ENTRY_SENDER_IDENTITY_UNAVAILABLE' }
        return [pscustomobject][ordered]@{
            path = $logicalPath; exists = $false; needs_creation = $true
            sha256 = $null; sender_sid = $hpSid; acl = $null
        }
    }
    if ($observation.is_directory -or $observation.is_reparse) { throw 'CHAT_ENTRY_CONFIG_INVALID' }
    $bytes = Get-CatalogChatEntryFileBytes -LogicalPath $logicalPath -MaximumBytes 4096
    try {
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
        $config = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'CHAT_ENTRY_CONFIG_INVALID'
    }
    if ($null -eq $config -or $config -is [array]) { throw 'CHAT_ENTRY_CONFIG_INVALID' }
    $properties = @($config.PSObject.Properties.Name)
    $expectedNames = @('schema_version', 'sender_sid')
    if ($properties.Count -ne $expectedNames.Count) { throw 'CHAT_ENTRY_CONFIG_INVALID' }
    foreach ($name in $expectedNames) {
        if ($properties -cnotcontains $name) { throw 'CHAT_ENTRY_CONFIG_INVALID' }
    }
    foreach ($name in $properties) {
        if ($expectedNames -cnotcontains $name) { throw 'CHAT_ENTRY_CONFIG_INVALID' }
    }
    $sender = Get-CatalogChatEntryProperty $config 'sender_sid'
    $hp = Get-LocalUser -Name 'HP' -ErrorAction Stop
    $hpSid = [string](Get-CatalogChatEntryProperty $hp 'SID')
    if ([string]::IsNullOrWhiteSpace($hpSid)) { throw 'CHAT_ENTRY_SENDER_IDENTITY_UNAVAILABLE' }
    if ([string](Get-CatalogChatEntryProperty $config 'schema_version') -cne '1' -or
        $sender -isnot [string] -or $sender -cne $hpSid -or
        $sender -notmatch '^S-1-5-21-(?:[0-9]+-){3}[0-9]+$') {
        throw 'CHAT_ENTRY_CONFIG_INVALID'
    }
    return [pscustomobject][ordered]@{
        path = $logicalPath; exists = $true; needs_creation = $false
        sha256 = Get-CatalogChatEntryBytesHash $bytes
        sender_sid = $sender
        acl = Assert-CatalogChatEntryResourceAcl -LogicalPath $logicalPath -Kind 'config'
    }
}

function New-CatalogChatEntryVerificationTree {
    param(
        [Parameter(Mandatory = $true)]$Candidate,
        [Parameter(Mandatory = $true)][byte[]]$HistoricalReadyBytes
    )
    $root = Join-Path ([IO.Path]::GetTempPath()) ('aurora-catalog-chat-verify-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($root) | Out-Null
    try {
        foreach ($record in @($Candidate.records.Values | Where-Object { $_.path.StartsWith('CatalogRequester/', [StringComparison]::Ordinal) })) {
            $source = Join-Path $Candidate.payload_root $record.path.Replace('/', '\')
            $destination = Join-Path $root $record.path.Replace('/', '\')
            [IO.Directory]::CreateDirectory((Split-Path -Path $destination -Parent)) | Out-Null
            [IO.File]::WriteAllBytes($destination, [IO.File]::ReadAllBytes($source))
        }
        $readyPath = Join-Path $root ('CatalogRequester/' + $script:CatalogChatEntryHistoricalReady).Replace('/', '\')
        [IO.Directory]::CreateDirectory((Split-Path -Path $readyPath -Parent)) | Out-Null
        [IO.File]::WriteAllBytes($readyPath, $HistoricalReadyBytes)
        return $root
    }
    catch {
        try { if ([IO.Directory]::Exists($root)) { [IO.Directory]::Delete($root, $true) } } catch { }
        throw
    }
}

function Invoke-CatalogChatEntryOfficialVerification {
    param(
        [Parameter(Mandatory = $true)]$Candidate,
        [Parameter(Mandatory = $true)][string]$VerificationRoot,
        [Parameter(Mandatory = $true)]$Runtime
    )
    $results = New-Object 'System.Collections.Generic.List[object]'
    foreach ($kind in @('client', 'broker')) {
        $runtimePython = if ($kind -eq 'client') { [string]$Runtime.client_python } else { [string]$Runtime.broker_python }
        $result = Invoke-CatalogChatEntryVerifierProcess -RuntimePython $runtimePython -ApplicationKind $kind -VerificationRoot $VerificationRoot -ExpectedCommitSha $Candidate.commit_sha
        [void]$results.Add($result)
    }
    return $results.ToArray()
}

function Get-CatalogChatEntryTransactionFiles {
    param([Parameter(Mandatory = $true)]$Candidate)
    $files = New-Object 'System.Collections.Generic.List[object]'
    foreach ($record in @($Candidate.records.Values | Sort-Object path)) {
        $logicalTarget = Join-Path $script:CatalogChatEntryAuroraRoot $record.path.Replace('/', '\')
        $observation = Get-CatalogChatEntryPathObservation $logicalTarget
        if (-not $observation.observation_available) { throw 'TARGET_OBSERVATION_UNAVAILABLE' }
        if ($observation.exists -and ($observation.is_directory -or $observation.is_reparse)) {
            throw 'TARGET_FILE_INVALID'
        }
        $oldHash = if ($observation.exists) { Get-CatalogChatEntryFileHash $logicalTarget } else { $null }
        [void]$files.Add([pscustomobject]@{
            path = $record.path; sha256 = $record.sha256; expected_old_sha256 = $oldHash
        })
    }
    return $files.ToArray()
}

function Assert-CatalogChatEntryPostContent {
    param([Parameter(Mandatory = $true)]$Candidate)
    foreach ($record in @($Candidate.records.Values)) {
        $logicalTarget = Join-Path $script:CatalogChatEntryAuroraRoot $record.path.Replace('/', '\')
        Assert-CatalogChatEntryFile $logicalTarget
        if ((Get-CatalogChatEntryFileHash $logicalTarget) -cne $record.sha256) {
            throw 'POSTINSTALL_CONTENT_HASH_MISMATCH'
        }
        [void](Assert-CatalogChatEntryProtectedAcl $logicalTarget)
    }
    $requesterRegistry = Get-CatalogChatEntryFileBytes (Join-Path $script:CatalogChatEntryRequesterRoot 'config\catalog_campaign_registry_v1.json')
    $senderRegistry = Get-CatalogChatEntryFileBytes (Join-Path $script:CatalogChatEntrySenderRoot 'catalog_campaign_registry_v1.json')
    if (-not [System.Collections.StructuralComparisons]::StructuralEqualityComparer.Equals($requesterRegistry, $senderRegistry)) {
        throw 'POSTINSTALL_SENDER_REGISTRY_MISMATCH'
    }
    $readyLogical = Join-Path $script:CatalogChatEntryRequesterRoot $script:CatalogChatEntryHistoricalReady
    if ((Get-CatalogChatEntryFileHash $readyLogical) -cne $Candidate.baseline_pins[$script:CatalogChatEntryHistoricalReady]) {
        throw 'POSTINSTALL_READY_CHANGED'
    }
    return $true
}

function New-CatalogChatEntryTask {
    param([Parameter(Mandatory = $true)]$Credential)
    $expected = Get-CatalogChatEntryExpectedChatAction
    $action = New-ScheduledTaskAction -Execute $expected.execute -Argument $expected.arguments -WorkingDirectory $expected.working_directory
    $principal = New-ScheduledTaskPrincipal -UserId $script:CatalogChatEntryAgentIdentity -LogonType Password -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Days 3650)
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $task = New-ScheduledTask -Action $action -Principal $principal -Settings $settings -Trigger $trigger
    $password = $null
    try {
        $password = $Credential.GetNetworkCredential().Password
        Register-ScheduledTask -TaskName $script:CatalogChatEntryTaskName -TaskPath '\' -InputObject $task -User $Credential.UserName -Password $password | Out-Null
    }
    finally {
        $password = $null
    }
    $snapshot = Get-CatalogChatEntryTaskSnapshot 'chat'
    if (-not $snapshot.exists) { throw 'TASK_CREATE_READBACK_MISSING' }
    return $snapshot.task
}

function Stop-CatalogChatEntryBrokerForMaintenance {
    param([Parameter(Mandatory = $true)]$Snapshot)
    $state = [ordered]@{
        observed = [bool]$Snapshot.exists
        originally_running = $false
        originally_enabled = $false
        disabled = $false
        stopped = $false
        restored = $false
    }
    if (-not $Snapshot.exists) { return [pscustomobject]$state }
    $state.originally_running = [string]$Snapshot.task.State -ieq 'Running'
    $state.originally_enabled = [string]$Snapshot.settings.Enabled -ieq 'True'
    if (-not $state.originally_running) {
        $left = @(Get-CatalogChatEntryAffectedWork)
        if (@($left | Where-Object { [string]$_.kind -in @('process', 'unknown_process') }).Count -gt 0) {
            throw 'AFFECTED_BROKER_PROCESS_PRESENT'
        }
        return [pscustomobject]$state
    }
    try {
        if ($state.originally_enabled) {
            Disable-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop | Out-Null
            $state.disabled = $true
        }
        Stop-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop
        Start-Sleep -Milliseconds 250
        $after = Get-CatalogChatEntryTaskSnapshot 'broker' -AllowRunning
        if ([string]$after.task.State -ieq 'Running') { throw 'BROKER_STOP_UNCONFIRMED' }
        $left = @(Get-CatalogChatEntryAffectedWork)
        if (@($left | Where-Object { [string]$_.kind -in @('process', 'unknown_process') }).Count -gt 0) {
            throw 'BROKER_PROCESS_STOP_UNCONFIRMED'
        }
        $state.stopped = $true
        return [pscustomobject]$state
    }
    catch {
        $cause = [string]$_.Exception.Message
        if ($state.disabled) {
            try {
                Enable-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop | Out-Null
                $state.disabled = $false
                $state.restored = $true
            }
            catch { $cause = $cause + '|BROKER_ENABLE_RESTORE_FAILED:' + [string]$_.Exception.Message }
        }
        throw ('BROKER_STOP_FAILED:' + $cause)
    }
}

function Restore-CatalogChatEntryBrokerAfterMaintenance {
    param(
        [Parameter(Mandatory = $true)]$Lifecycle,
        [switch]$StartIfOriginallyRunning
    )
    if (-not [bool]$Lifecycle.observed) {
        return [pscustomobject][ordered]@{ status = 'NOT_PRESENT' }
    }
    if (-not [bool]$Lifecycle.originally_running) {
        return [pscustomobject][ordered]@{ status = 'PRESERVED_NOT_RUNNING'; enabled = [bool]$Lifecycle.originally_enabled }
    }
    if (-not [bool]$StartIfOriginallyRunning) {
        return [pscustomobject][ordered]@{ status = 'HELD_STOPPED'; cause = 'ROLLBACK_INCOMPLETE' }
    }
    try {
        if ([bool]$Lifecycle.originally_enabled -and [bool]$Lifecycle.disabled) {
            Enable-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop | Out-Null
            $Lifecycle.disabled = $false
        }
        elseif (-not [bool]$Lifecycle.originally_enabled) {
            Enable-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop | Out-Null
            $Lifecycle.disabled = $false
        }
        Start-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop
        Start-Sleep -Milliseconds 250
        $after = Get-CatalogChatEntryTaskSnapshot 'broker' -AllowRunning
        if ([string]$after.task.State -ine 'Running') { throw 'BROKER_START_UNCONFIRMED' }
        if (-not [bool]$Lifecycle.originally_enabled) {
            Disable-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop | Out-Null
            $Lifecycle.disabled = $true
        }
        $Lifecycle.restored = $true
        return [pscustomobject][ordered]@{
            status = 'RESTORED'; originally_running = $true; originally_enabled = [bool]$Lifecycle.originally_enabled
        }
    }
    catch {
        $restoreCause = [string]$_.Exception.Message
        if (-not [bool]$Lifecycle.originally_enabled) {
            try {
                Disable-ScheduledTask -TaskName $script:CatalogChatEntryBrokerTaskName -TaskPath '\' -ErrorAction Stop | Out-Null
                $disabledSnapshot = Get-CatalogChatEntryTaskSnapshot 'broker' -AllowRunning
                if (-not $disabledSnapshot.exists -or [string]$disabledSnapshot.settings.Enabled -ine 'False') {
                    throw 'BROKER_DISABLED_RESTORE_UNCONFIRMED'
                }
                $Lifecycle.disabled = $true
            }
            catch { $restoreCause += '|BROKER_DISABLED_RESTORE_FAILED:' + [string]$_.Exception.Message }
        }
        throw ('BROKER_RESTORE_FAILED:' + $restoreCause)
    }
}

function Get-CatalogChatEntryTaskOutput {
    param([Parameter(Mandatory = $true)]$Task)
    $action = @($Task.Actions)[0]
    return [pscustomobject][ordered]@{
        name = [string]$Task.TaskName
        path = [string]$Task.TaskPath
        state = [string]$Task.State
        principal = [ordered]@{
            user_id = [string]$Task.Principal.UserId
            run_level = [string]$Task.Principal.RunLevel
            logon_type = [string]$Task.Principal.LogonType
        }
        action = [ordered]@{
            execute = [string]$action.Execute
            arguments = [string]$action.Arguments
            working_directory = [string]$action.WorkingDirectory
        }
    }
}

function Remove-CatalogChatEntryOwnedTask {
    param([switch]$Unregister)
    $tasks = @(Get-CatalogChatEntryTaskRecords)
    if ($tasks.Count -gt 1) { throw 'CHAT_TASK_AMBIGUOUS_DURING_ROLLBACK' }
    if ($tasks.Count -eq 0) {
        $remaining = @(Get-CatalogChatEntryAffectedWork -AllowAuthenticatedBroker)
        if (@($remaining | Where-Object { [string]$_.kind -in @('process', 'unknown_process') }).Count -gt 0) { throw 'CHAT_CONSUMER_STOP_UNCONFIRMED' }
        return [pscustomobject][ordered]@{ status = 'ABSENT' }
    }
    $task = $tasks[0]
    if ([string]$task.State -in @('Running', 'Queued')) {
        try { Stop-ScheduledTask -TaskName $script:CatalogChatEntryTaskName -TaskPath '\' -ErrorAction Stop }
        catch { throw ('CHAT_TASK_STOP_FAILED:' + [string]$_.Exception.Message) }
        Start-Sleep -Milliseconds 250
        $after = @(Get-CatalogChatEntryTaskRecords)
        if ($after.Count -ne 1 -or [string]$after[0].State -notin @('Ready', 'Disabled')) {
            throw 'CHAT_TASK_STOP_UNCONFIRMED'
        }
    }
    elseif ([string]$task.State -notin @('Ready', 'Disabled')) { throw 'CHAT_TASK_STOP_UNCONFIRMED' }
    $remaining = @(Get-CatalogChatEntryAffectedWork -AllowAuthenticatedBroker)
    if (@($remaining | Where-Object { [string]$_.kind -in @('process', 'unknown_process') }).Count -gt 0) { throw 'CHAT_CONSUMER_STOP_UNCONFIRMED' }
    if ($Unregister) {
        try { Unregister-ScheduledTask -TaskName $script:CatalogChatEntryTaskName -TaskPath '\' -Confirm:$false -ErrorAction Stop }
        catch { throw ('CHAT_TASK_UNREGISTER_FAILED:' + [string]$_.Exception.Message) }
        if (@(Get-CatalogChatEntryTaskRecords).Count -ne 0) { throw 'CHAT_TASK_UNREGISTER_UNCONFIRMED' }
    }
    return [pscustomobject][ordered]@{ status = 'STOPPED'; unregistered = [bool]$Unregister }
}

function Invoke-CatalogChatEntryInstallation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$CandidateRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedCandidateSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedApprovedCommitSha,
        [switch]$Apply,
        [string]$Confirm = ''
    )

    $phase = 'CANDIDATE'
    $candidate = $null
    $credential = $null
    $verificationRoot = $null
    $transaction = $null
    $transactionApplied = $false
    $transactionAttempted = $false
    $createdTask = $false
    $startedTask = $false
    $startAttempted = $false
    $ownedResources = New-Object 'System.Collections.Generic.List[object]'
    $resourcePlan = $null
    $brokerLifecycle = $null
    $brokerResume = $null
    $resourceCleanup = @()
    $originalCause = $null
    $rollback = [ordered]@{ status = 'NOT_NEEDED' }

    try {
        if ($Apply) {
            if ($Confirm -cne $script:CatalogChatEntryExpectedConfirmation) {
                throw 'CONFIRMATION_REQUIRED'
            }
            if (-not (Test-CatalogChatEntryAdministrator)) {
                throw 'ADMINISTRATOR_REQUIRED'
            }
        }
        $candidate = Get-CatalogChatEntryCandidate -Root $CandidateRoot -ExpectedCandidateSha256 $ExpectedCandidateSha256 -ExpectedApprovedCommitSha $ExpectedApprovedCommitSha

        $phase = 'PREFLIGHT'
        $preflight = Get-CatalogChatMaintenancePreflight
        $preflightIssues = @($preflight.reason_codes | Where-Object { [string]$_ -ne 'PREFLIGHT_TASK_EXISTS' })
        if ($preflightIssues.Count -gt 0) {
            throw [string]$preflightIssues[0]
        }
        [void](Assert-CatalogChatEntryDirectory $script:CatalogChatEntryAuroraRoot)
        [void](Assert-CatalogChatEntryProtectedAcl $script:CatalogChatEntryAuroraRoot)
        [void](Assert-CatalogChatEntryDirectory $script:CatalogChatEntryRequesterRoot)
        [void](Assert-CatalogChatEntryProtectedAcl $script:CatalogChatEntryRequesterRoot)
        $serviceConfig = Assert-CatalogChatEntryServiceConfig
        $senderExists = Assert-CatalogChatEntryDirectory $script:CatalogChatEntrySenderRoot -AllowAbsent
        if ($senderExists) { [void](Assert-CatalogChatEntryProtectedAcl $script:CatalogChatEntrySenderRoot) }
        $resourcePlan = @(Get-CatalogChatEntryResourcePlan -ServiceConfig $serviceConfig)

        $phase = 'RUNTIME'
        $runtime = Assert-CatalogChatEntryRuntime
        $chatBefore = Get-CatalogChatEntryTaskSnapshot 'chat'
        $brokerBefore = Get-CatalogChatEntryTaskSnapshot 'broker' -AllowRunning
        $affected = @(Get-CatalogChatEntryAffectedWork -AllowAuthenticatedBroker)
        if ($affected.Count -gt 0) {
            throw 'AFFECTED_WORK_PRESENT'
        }
        $credential = Get-CatalogChatEntryCredential
        if ($null -eq $credential -or $credential.UserName -cne $script:CatalogChatEntryAgentIdentity) {
            throw 'TASK_CREDENTIAL_INVALID'
        }

        $phase = 'BASELINE'
        $baseline = Assert-CatalogChatEntryBaseline -Candidate $candidate
        $historicalReadyBytes = Get-CatalogChatEntryFileBytes (Join-Path $script:CatalogChatEntryRequesterRoot $script:CatalogChatEntryHistoricalReady)
        $verificationRoot = New-CatalogChatEntryVerificationTree -Candidate $candidate -HistoricalReadyBytes $historicalReadyBytes

        $phase = 'CANDIDATE_VERIFY'
        $candidateVerification = Invoke-CatalogChatEntryOfficialVerification -Candidate $candidate -VerificationRoot $verificationRoot -Runtime $runtime
        $transactionFiles = @(Get-CatalogChatEntryTransactionFiles -Candidate $candidate)

        if (-not $Apply) {
            return [pscustomobject][ordered]@{
                status = 'VALIDATED_NOT_APPLIED'
                reason_code = 'PREFLIGHT_VALIDATED'
                production_verified = $false
                candidate_sha256 = $candidate.candidate_sha256
                protected_commit_sha = $candidate.commit_sha
                task = if ($chatBefore.exists) { Get-CatalogChatEntryTaskOutput $chatBefore.task } else { $null }
                broker_task_observed = [bool]$brokerBefore.exists
                broker_task = if ($brokerBefore.exists) { Get-CatalogChatEntryTaskOutput $brokerBefore.task } else { $null }
                service_config = $serviceConfig
                resources_to_create = @($resourcePlan | Where-Object { -not $_.exists } | ForEach-Object { $_.path })
                verifier = @($candidateVerification)
            }
        }

        $targetRootPhysical = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $script:CatalogChatEntryAuroraRoot
        $backupRootPhysical = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $script:CatalogChatEntryBackupRoot

        $phase = 'BROKER_PAUSE'
        $brokerLifecycle = Stop-CatalogChatEntryBrokerForMaintenance -Snapshot $brokerBefore

        $phase = 'RESOURCE_PROVISION'
        $senderSid = [string]$serviceConfig.sender_sid
        [void](Invoke-CatalogChatEntryResourceProvisioning -Plan $resourcePlan -OwnedResources $ownedResources -SenderSid $senderSid)
        $serviceConfig = Assert-CatalogChatEntryServiceConfig

        $phase = 'CONTENT_TRANSACTION'
        $transactionAttempted = $true
        $transaction = Invoke-CatalogChatContentTransaction -PayloadRoot $candidate.payload_root -TargetRoot $targetRootPhysical -BackupRoot $backupRootPhysical -Files $transactionFiles
        if ($null -eq $transaction -or [string]$transaction.status -cne 'APPLIED') {
            throw ('CONTENT_TRANSACTION_NOT_APPLIED:' + [string](Get-CatalogChatEntryProperty $transaction 'status') + ':' + [string](Get-CatalogChatEntryProperty $transaction 'cause'))
        }
        $transactionApplied = $true

        $phase = 'TASK_CREATE'
        if ($chatBefore.exists) {
            $task = $chatBefore.task
        }
        else {
            $createdTask = $true
            $task = New-CatalogChatEntryTask -Credential $credential
        }

        $phase = 'POSTINSTALL_VERIFY'
        [void](Assert-CatalogChatEntryPostContent -Candidate $candidate)
        $installedRequesterRoot = Resolve-CatalogChatEntryPhysicalPath -LogicalPath $script:CatalogChatEntryRequesterRoot
        $installedVerification = Invoke-CatalogChatEntryOfficialVerification -Candidate $candidate -VerificationRoot $installedRequesterRoot -Runtime $runtime

        $phase = 'TASK_START'
        $startAttempted = $true
        Start-ScheduledTask -TaskName $script:CatalogChatEntryTaskName -TaskPath '\' -ErrorAction Stop
        $startedTask = $true
        Start-Sleep -Milliseconds 250
        $startedSnapshot = Get-CatalogChatEntryTaskSnapshot 'chat' -AllowRunning
        if (-not $startedSnapshot.exists -or [string]$startedSnapshot.task.State -ine 'Running') {
            throw 'TASK_START_FAILED'
        }

        $phase = 'BROKER_RESUME'
        $brokerResume = Restore-CatalogChatEntryBrokerAfterMaintenance -Lifecycle $brokerLifecycle -StartIfOriginallyRunning

        $phase = 'COMPLETE'
        return [pscustomobject][ordered]@{
            status = 'INSTALLED_NOT_QUALIFIED'
            reason_code = 'INSTALLATION_ONLY'
            production_verified = $false
            candidate_sha256 = $candidate.candidate_sha256
            protected_commit_sha = $candidate.commit_sha
            task = Get-CatalogChatEntryTaskOutput $startedSnapshot.task
            task_created = $createdTask
            broker_task_preserved = $brokerBefore.exists
            broker_lifecycle = $brokerLifecycle
            broker_resume = $brokerResume
            service_config = $serviceConfig
            resources = $ownedResources.ToArray()
            transaction = $transaction
            baseline = $baseline
            verifier = @($installedVerification)
            qualification = 'PENDING_CONTROL_PLANE_ACCEPTANCE'
        }
    }
    catch {
        $originalCause = [string]$_.Exception.Message
        $reason = switch ($phase) {
            'POSTINSTALL_VERIFY' { 'POSTINSTALL_VERIFY_FAILED'; break }
            'TASK_CREATE' { 'TASK_CREATE_FAILED'; break }
            'TASK_START' { 'TASK_START_FAILED'; break }
            'CONTENT_TRANSACTION' { 'CONTENT_TRANSACTION_FAILED'; break }
            'BROKER_PAUSE' { 'BROKER_STOP_FAILED'; break }
            'BROKER_RESUME' { 'BROKER_RESTORE_FAILED'; break }
            default { $originalCause }
        }
        $chatCleanupFailed = $false
        if ($transactionApplied -and ($startAttempted -or $startedTask -or $createdTask)) {
            try { $chatCleanup = Remove-CatalogChatEntryOwnedTask -Unregister:$createdTask }
            catch {
                $chatCleanupFailed = $true
                $chatCleanup = [pscustomobject][ordered]@{
                    status = 'FAILED'; cause = [string]$_.Exception.Message
                }
            }
        }

        $brokerCleanupFailed = $false
        $brokerCleanupCause = $null
        if ($transactionApplied -and $null -ne $brokerLifecycle -and [bool]$brokerLifecycle.observed) {
            try {
                $rollbackBrokerSnapshot = Get-CatalogChatEntryTaskSnapshot 'broker' -AllowRunning
                if (-not $rollbackBrokerSnapshot.exists) { throw 'BROKER_MISSING_BEFORE_UNDO' }
                $rollbackBrokerPause = Stop-CatalogChatEntryBrokerForMaintenance -Snapshot $rollbackBrokerSnapshot
                if ([bool]$rollbackBrokerPause.disabled) { $brokerLifecycle.disabled = $true }
            }
            catch {
                $brokerCleanupFailed = $true
                $brokerCleanupCause = [string]$_.Exception.Message
            }
        }
        $internalRollback = if ($null -ne $transaction) { Get-CatalogChatEntryProperty $transaction 'rollback' } else { $null }
        $internalRollbackStatus = if ($null -ne $internalRollback) { [string](Get-CatalogChatEntryProperty $internalRollback 'status') } else { '' }
        if ($transactionAttempted -and -not $transactionApplied -and $internalRollbackStatus -cnotin @('NOT_REQUIRED', 'ROLLED_BACK')) {
            $rollback = [ordered]@{
                status = if ($internalRollbackStatus) { $internalRollbackStatus } else { 'TRANSACTION_OUTCOME_UNKNOWN' }
                error = if ($null -ne $internalRollback) { Get-CatalogChatEntryProperty $internalRollback 'error' } else { $null }
                original_cause = $originalCause
                transaction = $transaction
                retained_resources = $ownedResources.ToArray()
                broker_resume = 'HELD_STOPPED'
            }
        }
        elseif ($brokerCleanupFailed) {
            $rollback = [ordered]@{
                status = 'BLOCKED_BROKER_STOP'
                cause = $brokerCleanupCause
                original_cause = $originalCause
                content_undo = 'NOT_ATTEMPTED'
            }
        }
        elseif ($chatCleanupFailed) {
            # Never undo bytes while the owned chat consumer may still be running.
            $rollback = [ordered]@{
                status = 'BLOCKED_CONSUMER_STOP'
                cause = [string]$chatCleanup.cause
                original_cause = $originalCause
                content_undo = 'NOT_ATTEMPTED'
                broker_resume = 'HELD_STOPPED'
            }
        }
        elseif ($transactionApplied) {
            try {
                $undo = Undo-CatalogChatContentTransaction -TargetRoot (Resolve-CatalogChatEntryPhysicalPath -LogicalPath $script:CatalogChatEntryAuroraRoot) -Transaction $transaction -Cause $originalCause
                $undoStatus = [string](Get-CatalogChatEntryProperty $undo 'status')
                if ([string]::IsNullOrWhiteSpace($undoStatus)) {
                    $rollback = [ordered]@{
                        status = 'UNDO_RESULT_INVALID'
                        cause = 'UNDO_RESULT_INVALID'
                        result = $undo
                    }
                }
                elseif ($undoStatus -cne 'ROLLED_BACK') {
                    # Preserve the transaction module's exact non-success state/cause.
                    $rollback = [ordered]@{
                        status = $undoStatus
                        cause = [string](Get-CatalogChatEntryProperty $undo 'cause')
                        error = [string](Get-CatalogChatEntryProperty $undo 'error')
                        result = $undo
                        broker_resume = 'HELD_STOPPED'
                    }
                }
                else {
                    $resourceCleanup = @(Remove-CatalogChatEntryOwnedResources -OwnedResources $ownedResources)
                    $cleanupFailures = @($resourceCleanup | Where-Object { [string]$_.status -ne 'REMOVED' })
                    if ($cleanupFailures.Count -gt 0) {
                        $rollback = [ordered]@{
                            status = 'ROLLBACK_INCOMPLETE'
                            cause = 'OWNED_RESOURCE_CLEANUP_FAILED'
                            content_undo = $undo
                            resource_cleanup = $resourceCleanup
                            broker_resume = 'HELD_STOPPED'
                        }
                    }
                    else {
                        try {
                            $brokerResume = Restore-CatalogChatEntryBrokerAfterMaintenance -Lifecycle $brokerLifecycle -StartIfOriginallyRunning
                            $rollback = [ordered]@{
                                status = 'ROLLED_BACK'
                                cause = [string](Get-CatalogChatEntryProperty $undo 'cause')
                                content_undo = $undo
                                resource_cleanup = $resourceCleanup
                                broker_resume = $brokerResume
                            }
                        }
                        catch {
                            $rollback = [ordered]@{
                                status = 'ROLLBACK_INCOMPLETE'
                                cause = [string]$_.Exception.Message
                                content_undo = $undo
                                resource_cleanup = $resourceCleanup
                                broker_resume = 'RESTORE_FAILED'
                            }
                        }
                    }
                }
            }
            catch {
                $rollback = [ordered]@{ status = 'UNDO_FAILED'; cause = [string]$_.Exception.Message; broker_resume = 'HELD_STOPPED' }
            }
        }
        else {
            if ($ownedResources.Count -gt 0) {
                $resourceCleanup = @(Remove-CatalogChatEntryOwnedResources -OwnedResources $ownedResources)
            }
            $cleanupFailures = @($resourceCleanup | Where-Object { [string]$_.status -ne 'REMOVED' })
            if ($cleanupFailures.Count -gt 0) {
                $rollback = [ordered]@{
                    status = 'RESOURCE_CLEANUP_INCOMPLETE'
                    cause = 'OWNED_RESOURCE_CLEANUP_FAILED'
                    resource_cleanup = $resourceCleanup
                    broker_resume = 'HELD_STOPPED'
                }
            }
            elseif ($null -ne $brokerLifecycle) {
                try {
                    $brokerResume = Restore-CatalogChatEntryBrokerAfterMaintenance -Lifecycle $brokerLifecycle -StartIfOriginallyRunning
                    $rollback = [ordered]@{ status = 'NO_CONTENT_CHANGE'; broker_resume = $brokerResume; resource_cleanup = $resourceCleanup }
                }
                catch {
                    $rollback = [ordered]@{ status = 'ROLLBACK_INCOMPLETE'; cause = [string]$_.Exception.Message; broker_resume = 'RESTORE_FAILED'; resource_cleanup = $resourceCleanup }
                }
            }
        }
        return [pscustomobject][ordered]@{
            status = 'BLOCKED'
            reason_code = $reason
            cause = $originalCause
            phase = $phase
            production_verified = $false
            candidate_sha256 = $ExpectedCandidateSha256
            protected_commit_sha = $ExpectedApprovedCommitSha
            rollback = $rollback
            broker_lifecycle = $brokerLifecycle
            broker_resume = $brokerResume
            resource_cleanup = $resourceCleanup
        }
    }
    finally {
        if ($null -ne $verificationRoot) {
            try { if ([IO.Directory]::Exists($verificationRoot)) { [IO.Directory]::Delete($verificationRoot, $true) } } catch { }
        }
        if ($null -ne $credential) {
            try { $credential.Password.Dispose() } catch { }
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-CatalogChatEntryInstallation -CandidateRoot $CandidateRoot -ExpectedCandidateSha256 $ExpectedCandidateSha256 -ExpectedApprovedCommitSha $ExpectedApprovedCommitSha -Apply:$Apply -Confirm $Confirm | ConvertTo-Json -Depth 50 -Compress
    }
    catch {
        [pscustomobject][ordered]@{
            status = 'BLOCKED'
            reason_code = [string]$_.Exception.Message
            production_verified = $false
        } | ConvertTo-Json -Depth 20 -Compress
    }
}
