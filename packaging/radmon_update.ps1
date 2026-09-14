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

    Write-UpdaterLog "Automatic upgrade completed successfully: $remoteSha."

    Get-ChildItem -Path $updatesRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne $remoteSha } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
catch {
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
