param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = "Stop"
$taskName = "RadMon Server"
$taskCommand = '"' + $ExePath + '" --server'

& "$env:SystemRoot\System32\schtasks.exe" /Create /F /SC ONSTART /TN $taskName /TR $taskCommand /RU SYSTEM /RL HIGHEST | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to register RadMon startup task (exit $LASTEXITCODE)"
}

$netsh = "$env:SystemRoot\System32\netsh.exe"
foreach ($rule in @("RadMon Web", "RadMon Grafana Monitoring")) {
    & $netsh advfirewall firewall delete rule name=$rule | Out-Null
}

& $netsh advfirewall firewall add rule name="RadMon Web" dir=in action=allow protocol=TCP localport=8090 remoteip=LocalSubnet profile=any | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to open RadMon web port 8090" }

& $netsh advfirewall firewall add rule name="RadMon Grafana Monitoring" dir=in action=allow protocol=TCP localport=3300 remoteip=LocalSubnet profile=any | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to open Grafana monitoring port 3300" }

& "$env:SystemRoot\System32\schtasks.exe" /Run /TN $taskName | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "RadMon startup task was registered but could not be started"
}
