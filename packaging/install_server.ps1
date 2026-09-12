param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = "Stop"
$taskName = "RadMon Server"

$action = New-ScheduledTaskAction -Execute $ExePath -Argument "--server"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "RadMon 24/7 central collector, authenticated web platform, and Grafana bootstrap" `
    -Force | Out-Null

$netsh = "$env:SystemRoot\System32\netsh.exe"
foreach ($rule in @("RadMon Web", "RadMon Grafana Monitoring")) {
    & $netsh advfirewall firewall delete rule name=$rule | Out-Null
}

& $netsh advfirewall firewall add rule name="RadMon Web" dir=in action=allow protocol=TCP localport=8090 remoteip=LocalSubnet profile=any | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to open RadMon web port 8090" }

& $netsh advfirewall firewall add rule name="RadMon Grafana Monitoring" dir=in action=allow protocol=TCP localport=3300 remoteip=LocalSubnet profile=any | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to open Grafana monitoring port 3300" }

Start-ScheduledTask -TaskName $taskName
