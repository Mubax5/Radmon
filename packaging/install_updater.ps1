param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = "Stop"
$taskName = "RadMon Updater"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`" -InstallRoot `"$InstallRoot`""
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Do not stop/unregister an existing updater here. During a self-update this helper
# runs inside the child installer while the current updater process is waiting for
# the installer to finish. Register -Force updates the future task definition
# without intentionally terminating that parent updater process.
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "RadMon automatic updater for the verified GitHub latest release" `
    -Force | Out-Null
