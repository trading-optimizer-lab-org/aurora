[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CatalogChatServiceStatus {
    # Read-only lifecycle evidence. This is never a production READY receipt.
    $result = [ordered]@{
        schema_version = '1'
        status = 'BLOCKED'
        reason_code = 'CHAT_SERVICE_INSPECTION_FAILED'
        production_verified = $false
        observed_at = [DateTime]::UtcNow.ToString('o')
        process_id = $null
    }
    $root = 'C:\ProgramData\AURORA\CatalogRequester'
    $python = "$root\client-venv\Scripts\python.exe"
    $application = "$root\bin\catalog-requester-client.pyz"
    $arguments = '-I -s -E "' + $application + '" --serve-chat'
    try {
        $tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $null -ne $_ -and $_.TaskName -eq 'AURORA Catalog Chat Entry' })
        if ($tasks.Count -eq 0) {
            $result.reason_code = 'CHAT_SERVICE_TASK_MISSING'
            return [pscustomobject]$result
        }
        if ($tasks.Count -ne 1) { return [pscustomobject]$result }
        $task = $tasks[0]
        $sid = [string](Get-LocalUser -Name 'AURORAAgent' -ErrorAction Stop).SID
        $allowedPrincipals = @($sid, "$env:COMPUTERNAME\AURORAAgent", '.\AURORAAgent', 'AURORAAgent')
        if ($task.Principal.UserId -notin $allowedPrincipals -or [string]$task.Principal.RunLevel -ne 'Limited') {
            $result.reason_code = 'CHAT_SERVICE_PRINCIPAL_INVALID'
            return [pscustomobject]$result
        }
        $actions = @($task.Actions)
        if ($actions.Count -ne 1 -or $actions[0].Execute -ine $python -or
            $actions[0].Arguments -cne $arguments -or $actions[0].WorkingDirectory -ine $root) {
            $result.reason_code = 'CHAT_SERVICE_ACTION_INVALID'
            return [pscustomobject]$result
        }
        if ([string]$task.State -ne 'Running') {
            $result.reason_code = 'CHAT_SERVICE_NOT_RUNNING'
            return [pscustomobject]$result
        }
        $pattern = '^"?' + [regex]::Escape($python) + '"?\s+' + [regex]::Escape($arguments) + '$'
        $processes = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop |
            Where-Object { $_.ExecutablePath -ieq $python -and $_.CommandLine -imatch $pattern })
        if ($processes.Count -ne 1) {
            $result.reason_code = 'CHAT_SERVICE_PROCESS_INVALID'
            return [pscustomobject]$result
        }
        $owner = Invoke-CimMethod -InputObject $processes[0] -MethodName GetOwner -ErrorAction Stop
        if ($owner.ReturnValue -ne 0 -or $owner.User -ine 'AURORAAgent' -or $owner.Domain -ine $env:COMPUTERNAME) {
            $result.reason_code = 'CHAT_SERVICE_PROCESS_INVALID'
            return [pscustomobject]$result
        }
        $result.status = 'RUNNING'
        $result.reason_code = 'CHAT_SERVICE_RUNNING'
        $result.process_id = [int]$processes[0].ProcessId
    }
    catch {
        # Do not leak environment, credentials or uncontrolled exception text.
        $result.reason_code = 'CHAT_SERVICE_INSPECTION_FAILED'
    }
    return [pscustomobject]$result
}

if ($MyInvocation.InvocationName -ne '.') {
    Get-CatalogChatServiceStatus | ConvertTo-Json -Compress
}
