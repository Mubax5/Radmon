param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = "Stop"
$taskName = "RadMon Server"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
}

$normalizedAppDir = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\') + '\'
$deadline = [DateTime]::UtcNow.AddSeconds(10)

function Get-RadMonInstallProcesses {
    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $path = [string]$_.ExecutablePath
                $path -and $path.StartsWith($normalizedAppDir, [System.StringComparison]::OrdinalIgnoreCase)
            }
    )
}

while ($true) {
    $processes = @(Get-RadMonInstallProcesses)
    if ($processes.Count -eq 0) {
        break
    }

    foreach ($process in $processes) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
    }

    if ([DateTime]::UtcNow -ge $deadline) {
        break
    }
    Start-Sleep -Milliseconds 250
}

$remaining = @(Get-RadMonInstallProcesses)
if ($remaining.Count -gt 0) {
    $pids = ($remaining | ForEach-Object { $_.ProcessId }) -join ", "
    throw "RadMon upgrade cannot continue because app processes are still running: $pids"
}
