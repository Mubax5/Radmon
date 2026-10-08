param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Repository = "Mubax5/Radmon"
$LatestRef = "refs/tags/latest"
$GitHubApiBase = "https://api.github.com/repos/$Repository"
$ReleaseBase = "https://github.com/$Repository/releases/download/latest"
$UserAgent = "RadMon-Updater"
$MutexName = "Global\RadMonAutoUpdater"

function Write-UpdaterLog {
    param([string]$Message)

    $logDir = Join-Path $InstallRoot "runtime\logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logPath = Join-Path $logDir "radmon-updater.log"
    $stamp = [DateTime]::UtcNow.ToString("o")
    Add-Content -Path $logPath -Value "$stamp $Message" -Encoding UTF8
}

function Test-AutoUpdateEnabled {
    param([string]$EnvPath)

    if (-not (Test-Path $EnvPath)) {
        return $true
    }

    $line = Get-Content -Path $EnvPath -ErrorAction Stop |
        Where-Object { $_ -match '^\s*RADMON_AUTO_UPDATE\s*=' } |
        Select-Object -Last 1
    if (-not $line) {
        return $true
    }

    $value = (($line -split '=', 2)[1]).Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    elseif ($value.StartsWith("'") -and $value.EndsWith("'") -and $value.Length -ge 2) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    $value = $value.Trim().ToLowerInvariant()

    return $value -notin @("0", "false", "no", "off", "disabled")
}

function Get-ReleaseShaFromMarker {
    param([string]$MarkerPath)

    if (-not (Test-Path $MarkerPath)) {
        throw "Installed release marker is missing: $MarkerPath"
    }
    $marker = Get-Content -Path $MarkerPath -Raw -ErrorAction Stop | ConvertFrom-Json
    $sha = [string]$marker.commit_sha
    if ($sha -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Installed release marker contains an invalid commit SHA"
    }
    return $sha.ToLowerInvariant()
}

function Get-ExpectedChecksum {
    param([string]$ChecksumText)

    $match = [regex]::Match(
        $ChecksumText,
        '(?im)^\s*([0-9a-f]{64})\s+\*?RadMon-Setup\.exe\s*$'
    )
    if (-not $match.Success) {
        throw "Release checksum file has an invalid format"
    }
    return $match.Groups[1].Value.ToLowerInvariant()
}

function Get-LatestReleaseSha {
    $uri = "$GitHubApiBase/git/ref/tags/latest"
    $response = Invoke-RestMethod -Uri $uri -Headers @{ "User-Agent" = $UserAgent } -Method Get
    $sha = [string]$response.object.sha
    if ($sha -notmatch '^[0-9a-fA-F]{40}$') {
        throw "GitHub latest tag returned an invalid commit SHA"
    }
    return $sha.ToLowerInvariant()
}

function Compare-ReleaseAncestry {
    param(
        [string]$LocalSha,
        [string]$RemoteSha
    )

    $uri = "$GitHubApiBase/compare/$LocalSha...$RemoteSha"
    $response = Invoke-RestMethod -Uri $uri -Headers @{ "User-Agent" = $UserAgent } -Method Get
    return ([string]$response.status).ToLowerInvariant()
}

function Download-ReleaseFile {
    param(
        [string]$Uri,
        [string]$Destination
    )

    $partial = "$Destination.part"
    Remove-Item -Path $partial -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $partial -Headers @{ "User-Agent" = $UserAgent }
    Move-Item -Path $partial -Destination $Destination -Force
}

function Test-InstallerChecksum {
    param(
        [string]$SetupPath,
        [string]$ChecksumPath
    )

    $expected = Get-ExpectedChecksum -ChecksumText (Get-Content -Path $ChecksumPath -Raw -ErrorAction Stop)
    $actual = (Get-FileHash -Path $SetupPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "RadMon installer checksum mismatch: expected $expected, got $actual"
    }
    return $actual
}

function Get-CentralReadiness {
    param(
        [int]$TimeoutSeconds = 2
    )

    try {
        $response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "http://127.0.0.1:8090/health" `
            -TimeoutSec ([Math]::Max(1, $TimeoutSeconds)) `
            -Headers @{ "User-Agent" = $UserAgent }
        $health = $response.Content | ConvertFrom-Json
        if ($response.StatusCode -eq 200 -and [string]$health.status -eq "ok") {
            return [pscustomobject]@{
                Ready = $true
                Detail = "HTTP $($response.StatusCode), health status '$($health.status)'"
            }
        }
        return [pscustomobject]@{
            Ready = $false
            Detail = "HTTP $($response.StatusCode), health status '$($health.status)'"
        }
    }
    catch {
        return [pscustomobject]@{
            Ready = $false
            Detail = $_.Exception.Message
        }
    }
}

function Get-CentralDiagnostics {
    param(
        [string]$Root
    )

    $taskInfo = $null
    try {
        $taskInfo = Get-ScheduledTaskInfo -TaskName "RadMon Server" -ErrorAction Stop
    }
    catch {
    }
    $taskSummary = if ($null -eq $taskInfo) {
        "task=unavailable"
    }
    else {
        "task=lastResult:$($taskInfo.LastTaskResult),lastRun:$($taskInfo.LastRunTime)"
    }

    $appDir = Join-Path $Root "app"
    $processIds = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -and
                ([System.IO.Path]::GetFullPath([string]$_.ExecutablePath) -like (([System.IO.Path]::GetFullPath($appDir)).TrimEnd('\') + '\*'))
            } |
            ForEach-Object { $_.ProcessId }
    ) -join ","
    $listeners = @(
        Get-NetTCPConnection -State Listen -LocalPort 8090 -ErrorAction SilentlyContinue |
            ForEach-Object { "pid=$($_.OwningProcess);local=$($_.LocalAddress):$($_.LocalPort)" }
    ) -join ","
    return "$taskSummary; appPids=$processIds; listeners=$listeners"
}

function Wait-CentralReadiness {
    param(
        [int]$TimeoutSeconds = 60,
        [int]$StableChecks = 3,
        [int]$IntervalSeconds = 2,
        [scriptblock]$Probe = $null
    )

    $timeout = [Math]::Max(1, $TimeoutSeconds)
    $requiredChecks = [Math]::Max(1, $StableChecks)
    $interval = [Math]::Max(0, $IntervalSeconds)
    $deadline = [DateTime]::UtcNow.AddSeconds($timeout)
    $consecutiveHealthy = 0
    $lastDetail = "no health response"

    while ([DateTime]::UtcNow -lt $deadline) {
        $probeResult = if ($null -eq $Probe) { Get-CentralReadiness } else { & $Probe }
        if ($probeResult.Ready) {
            $consecutiveHealthy++
            if ($consecutiveHealthy -ge $requiredChecks) {
                return $probeResult.Detail
            }
        }
        else {
            $consecutiveHealthy = 0
            $lastDetail = $probeResult.Detail
        }

        $remaining = $deadline - [DateTime]::UtcNow
        if ($remaining.TotalSeconds -gt 0 -and $interval -gt 0) {
            $sleepSeconds = [Math]::Min($interval, [int][Math]::Ceiling($remaining.TotalSeconds))
            if ($sleepSeconds -gt 0) {
                Start-Sleep -Seconds $sleepSeconds
            }
        }
    }

    $diagnostics = Get-CentralDiagnostics -Root $InstallRoot
    throw "RadMon control plane did not become ready and stable within $timeout seconds. Last health result: $lastDetail. $diagnostics"
}

function Stop-InstalledServer {
    param([string]$AppDir)

    $task = Get-ScheduledTask -TaskName "RadMon Server" -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Stop-ScheduledTask -TaskName "RadMon Server" -ErrorAction SilentlyContinue
    }
    $normalized = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\') + '\'
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $processes = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $path = [string]$_.ExecutablePath
                    $path -and $path.StartsWith($normalized, [System.StringComparison]::OrdinalIgnoreCase)
                }
        )
        foreach ($process in $processes) {
            Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
        }
        if ($processes.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "RadMon app processes did not stop before the verified upgrade window"
}

function Move-AppToUpgradeBackup {
    param(
        [string]$AppDir,
        [string]$BackupDir
    )

    $root = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
    $app = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\')
    if ($app -eq $root -or -not $app.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stage an app directory outside the owned install root"
    }
    if (-not (Test-Path -LiteralPath $AppDir -PathType Container)) {
        throw "Installed RadMon app directory is missing: $AppDir"
    }
    if (Test-Path -LiteralPath $BackupDir) {
        throw "Upgrade backup already exists: $BackupDir"
    }
    Move-Item -LiteralPath $AppDir -Destination $BackupDir -Force
}

function Restore-AppFromUpgradeBackup {
    param(
        [string]$AppDir,
        [string]$BackupDir,
        [switch]$StartServer
    )

    if (-not (Test-Path -LiteralPath $BackupDir -PathType Container)) {
        throw "Upgrade rollback backup is missing: $BackupDir"
    }
    Stop-InstalledServer -AppDir $AppDir
    if (Test-Path -LiteralPath $AppDir) {
        $failedDir = "$AppDir.failed-$([Guid]::NewGuid().ToString('N'))"
        # Move the failed tree aside rather than recursively deleting arbitrary
        # content. The tree remains available for post-failure diagnostics.
        Move-Item -LiteralPath $AppDir -Destination $failedDir -Force
    }
    Move-Item -LiteralPath $BackupDir -Destination $AppDir -Force
    if ($StartServer) {
        Start-ScheduledTask -TaskName "RadMon Server" -ErrorAction SilentlyContinue
    }
}

function Invoke-UpdaterSelfTest {
    $root = Join-Path ([System.IO.Path]::GetTempPath()) ("radmon-updater-selftest-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    try {
        $envPath = Join-Path $root ".env"
        if (-not (Test-AutoUpdateEnabled -EnvPath $envPath)) {
            throw "Missing config must default auto-update to enabled"
        }

        foreach ($value in @("0", "false", "no", "off", "disabled")) {
            "RADMON_AUTO_UPDATE=$value" | Set-Content -Path $envPath -Encoding ASCII
            if (Test-AutoUpdateEnabled -EnvPath $envPath) {
                throw "RADMON_AUTO_UPDATE=$value must disable updates"
            }
        }

        "RADMON_AUTO_UPDATE=1" | Set-Content -Path $envPath -Encoding ASCII
        if (-not (Test-AutoUpdateEnabled -EnvPath $envPath)) {
            throw "RADMON_AUTO_UPDATE=1 must enable updates"
        }

        $sampleHash = "a" * 64
        $parsed = Get-ExpectedChecksum -ChecksumText "$sampleHash  RadMon-Setup.exe"
        if ($parsed -ne $sampleHash) {
            throw "Checksum parser self-test failed"
        }

        $script:radmonUpdaterSelfTestProbeCalls = 0
        $syntheticProbe = {
            $script:radmonUpdaterSelfTestProbeCalls++
            [pscustomobject]@{ Ready = $true; Detail = "synthetic health" }
        }
        $syntheticDetail = Wait-CentralReadiness -TimeoutSeconds 2 -StableChecks 3 -IntervalSeconds 0 -Probe $syntheticProbe
        if ($syntheticDetail -ne "synthetic health" -or $script:radmonUpdaterSelfTestProbeCalls -ne 3) {
            throw "Bounded stable readiness self-test failed"
        }
        Remove-Variable -Name radmonUpdaterSelfTestProbeCalls -Scope Script -ErrorAction SilentlyContinue

        # Simulate an installer that leaves a new app tree before readiness
        # succeeds. The old owned tree must be restored and the failed tree must
        # remain available for diagnostics; no real scheduled task is started.
        $oldInstallRoot = $InstallRoot
        try {
            $InstallRoot = $root
            $appDir = Join-Path $root "app"
            $backupDir = Join-Path $root "runtime\updates\previous-app"
            New-Item -ItemType Directory -Force -Path $appDir, (Split-Path -Parent $backupDir) | Out-Null
            "old-release" | Set-Content -Path (Join-Path $appDir "release.txt") -Encoding ASCII
            Move-AppToUpgradeBackup -AppDir $appDir -BackupDir $backupDir
            New-Item -ItemType Directory -Force -Path $appDir | Out-Null
            "failed-release" | Set-Content -Path (Join-Path $appDir "release.txt") -Encoding ASCII
            Restore-AppFromUpgradeBackup -AppDir $appDir -BackupDir $backupDir
            $restored = Get-Content -Path (Join-Path $appDir "release.txt") -Raw
            if ($restored.Trim() -ne "old-release") {
                throw "App rollback self-test did not restore the previous release"
            }
            if (@(Get-ChildItem -Path "$appDir.failed-*" -ErrorAction SilentlyContinue).Count -ne 1) {
                throw "App rollback self-test did not preserve the failed tree"
            }
        }
        finally {
            $InstallRoot = $oldInstallRoot
        }
    }
    finally {
        Remove-Item -Path $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($SelfTest) {
    Invoke-UpdaterSelfTest
    Write-Output "RadMon updater self-test passed"
    exit 0
}

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$mutex = New-Object System.Threading.Mutex($false, $MutexName)
$hasMutex = $false
$backupDir = $null
$backupMoved = $false
try {
    try {
        $hasMutex = $mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $hasMutex = $true
    }

    if (-not $hasMutex) {
        Write-UpdaterLog "Another updater instance is already running; skipping."
        exit 0
    }

    $envPath = Join-Path $InstallRoot "config\.env"
    if (-not (Test-AutoUpdateEnabled -EnvPath $envPath)) {
        Write-UpdaterLog "Automatic updates are disabled by RADMON_AUTO_UPDATE."
        exit 0
    }

    $markerPath = Join-Path $InstallRoot "app\release.json"
    $localSha = Get-ReleaseShaFromMarker -MarkerPath $markerPath
    $remoteSha = Get-LatestReleaseSha

    if ($localSha -eq $remoteSha) {
        exit 0
    }

    $relationship = Compare-ReleaseAncestry -LocalSha $localSha -RemoteSha $remoteSha
    if ($relationship -ne "ahead") {
        Write-UpdaterLog "Ignoring latest=$remoteSha because compare status from installed=$localSha is '$relationship'."
        exit 0
    }

    Write-UpdaterLog "New verified release candidate detected: installed=$localSha latest=$remoteSha."

    $updatesRoot = Join-Path $InstallRoot "runtime\updates"
    $updateDir = Join-Path $updatesRoot $remoteSha
    New-Item -ItemType Directory -Force -Path $updateDir | Out-Null

    $setupPath = Join-Path $updateDir "RadMon-Setup.exe"
    $checksumPath = Join-Path $updateDir "RadMon-Setup.exe.sha256"
    Download-ReleaseFile -Uri "$ReleaseBase/RadMon-Setup.exe" -Destination $setupPath
    Download-ReleaseFile -Uri "$ReleaseBase/RadMon-Setup.exe.sha256" -Destination $checksumPath

    $verifiedHash = Test-InstallerChecksum -SetupPath $setupPath -ChecksumPath $checksumPath
    Write-UpdaterLog "Installer checksum verified: $verifiedHash. Starting silent upgrade to $remoteSha."

    $appDir = Join-Path $InstallRoot "app"
    $backupDir = Join-Path $updateDir "previous-app"
    Stop-InstalledServer -AppDir $appDir
    Move-AppToUpgradeBackup -AppDir $appDir -BackupDir $backupDir
    $backupMoved = $true
    Write-UpdaterLog "Previous release staged at $backupDir before installer execution."

    $arguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=`"$InstallRoot`""
    )
    $installer = Start-Process -FilePath $setupPath -ArgumentList $arguments -Wait -PassThru
    if ($installer.ExitCode -ne 0) {
        throw "RadMon installer exited with code $($installer.ExitCode)"
    }

    $installedSha = Get-ReleaseShaFromMarker -MarkerPath $markerPath
    if ($installedSha -ne $remoteSha) {
        throw "Upgrade completed but installed release marker is $installedSha instead of $remoteSha"
    }

    $readiness = Wait-CentralReadiness -TimeoutSeconds 60 -StableChecks 3 -IntervalSeconds 2
    Write-UpdaterLog "Control plane readiness verified after upgrade: $readiness."
    Write-UpdaterLog "Automatic upgrade completed successfully: $remoteSha."

    if ($backupMoved -and (Test-Path -LiteralPath $backupDir)) {
        Remove-Item -LiteralPath $backupDir -Recurse -Force
        $backupMoved = $false
    }

    Get-ChildItem -Path $updatesRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne $remoteSha } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
catch {
    if ($backupMoved -and $null -ne $backupDir) {
        try {
            Write-UpdaterLog "Upgrade failed; restoring the previous app release from $backupDir."
            Restore-AppFromUpgradeBackup -AppDir (Join-Path $InstallRoot "app") -BackupDir $backupDir -StartServer
            Write-UpdaterLog "Previous app release restored and server task restart requested."
            $backupMoved = $false
        }
        catch {
            try { Write-UpdaterLog ("Automatic rollback failed: " + $_.Exception.Message) } catch { }
        }
    }
    try {
        Write-UpdaterLog ("Updater failed: " + $_.Exception.Message)
    }
    catch {
    }
    exit 1
}
finally {
    if ($hasMutex) {
        try { $mutex.ReleaseMutex() } catch { }
    }
    if ($null -ne $mutex) {
        $mutex.Dispose()
    }
}
