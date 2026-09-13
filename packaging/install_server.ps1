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

# 8090 is the single BRIN-facing gateway. Using Any here allows routed BRIN-NET
# VLANs/subnets to reach the Dell; upstream BRIN routing/ACL remains the network boundary.
& $netsh advfirewall firewall add rule name="RadMon Web" dir=in action=allow protocol=TCP localport=8090 remoteip=any profile=any | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to open RadMon web port 8090" }

# Grafana 3300 intentionally has no inbound firewall rule and binds loopback-only.
# Remote monitoring is reverse-proxied through RadMon on port 8090.

Start-ScheduledTask -TaskName $taskName
