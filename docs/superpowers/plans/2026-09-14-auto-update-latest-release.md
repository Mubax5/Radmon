# RadMon Automatic Release Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a safe Windows auto-updater that follows the GitHub `latest` release and upgrades RadMon within about two minutes of publication.

**Architecture:** A `SYSTEM` Scheduled Task runs a persistent PowerShell updater script outside the replaceable `app` tree. The script compares `app/release.json` with tag `latest`, refuses downgrade/divergence, downloads and verifies the published installer checksum, and only then launches the existing silent upgrade path.

**Tech Stack:** PowerShell 5.1+, Windows Task Scheduler, Inno Setup 6, GitHub REST/releases, pytest packaging contract tests, GitHub Actions Windows runner.

**Spec:** `docs/superpowers/specs/2026-09-14-auto-update-latest-release-design.md`

## Global Constraints

- Release source of truth is tag `latest`, never raw `main` source.
- Poll interval is 2 minutes.
- Missing `RADMON_AUTO_UPDATE` means enabled; `0`, `false`, `no`, `off`, and `disabled` mean disabled.
- Never stop RadMon before installer and checksum are fully downloaded and SHA-256 verified.
- Never install a `latest` SHA that is behind or diverged from the locally installed SHA.
- Preserve `config`, `runtime`, `archives`, and `reports` across upgrades.
- Updater runs as `SYSTEM` with highest privileges and ignores overlapping task instances.

---

### Task 1: Lock the updater packaging contract with failing tests

**Files:**
- Create: `tests/test_windows_auto_update.py`
- Modify: `tests/test_windows_packaging.py`

**Interfaces:**
- Consumes: existing packaging files under `packaging/` and `.github/workflows/windows-build.yml`.
- Produces: regression assertions for updater script, release marker, task registration, checksum validation, and installer upgrade persistence.

- [ ] **Step 1: Write failing contract tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auto_updater_is_packaged_and_registered():
    installer = (ROOT / "packaging/RadMon.iss").read_text(encoding="utf-8")
    assert 'Source: "packaging\\radmon_update.ps1"' in installer
    assert 'Source: "packaging\\install_updater.ps1"' in installer
    assert "RadMon Updater" in installer


def test_updater_fails_closed_before_installing_unverified_payload():
    script = (ROOT / "packaging/radmon_update.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in script
    assert "Compare-ReleaseAncestry" in script
    assert "Start-Process" in script
    assert script.index("Get-FileHash") < script.index("Start-Process")


def test_windows_build_embeds_release_sha_and_smokes_updater():
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert "release.json" in workflow
    assert "$env:GITHUB_SHA" in workflow
    assert "Smoke test updater helper" in workflow
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_windows_auto_update.py tests/test_windows_packaging.py`
Expected: failures for missing updater scripts/marker/workflow integration.

- [ ] **Step 3: Commit the tests**

```bash
git add tests/test_windows_auto_update.py tests/test_windows_packaging.py
git commit -m "test: define Windows auto-update contract"
```

---

### Task 2: Implement the safe PowerShell updater

**Files:**
- Create: `packaging/radmon_update.ps1`
- Modify: `.env.example`
- Test: `tests/test_windows_auto_update.py`

**Interfaces:**
- Consumes: `<install-root>/app/release.json`, `<install-root>/config/.env`, GitHub tag `latest`, release assets.
- Produces: verified silent installer execution and `runtime/logs/radmon-updater.log`.

- [ ] **Step 1: Implement config/marker helpers and self-test**

```powershell
param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [switch]$SelfTest
)

function Test-AutoUpdateEnabled([string]$EnvPath) {
    if (-not (Test-Path $EnvPath)) { return $true }
    $line = Get-Content $EnvPath | Where-Object { $_ -match '^\s*RADMON_AUTO_UPDATE\s*=' } | Select-Object -Last 1
    if (-not $line) { return $true }
    $value = (($line -split '=', 2)[1]).Trim().Trim('"').Trim("'").ToLowerInvariant()
    return $value -notin @('0', 'false', 'no', 'off', 'disabled')
}
```

Add `.env.example`:

```dotenv
# Automatic production upgrades follow the verified GitHub `latest` release.
RADMON_AUTO_UPDATE=1
```

`-SelfTest` must exercise enabled/disabled parsing and checksum parser without network access, then exit 0.

- [ ] **Step 2: Implement release ancestry check**

```powershell
function Compare-ReleaseAncestry([string]$LocalSha, [string]$RemoteSha) {
    $uri = "https://api.github.com/repos/Mubax5/Radmon/compare/$LocalSha...$RemoteSha"
    $result = Invoke-RestMethod -Uri $uri -Headers @{ 'User-Agent' = 'RadMon-Updater' }
    return [string]$result.status
}
```

Proceed only for `ahead`; exit for `identical`, `behind`, or `diverged`.

- [ ] **Step 3: Implement download/checksum/install ordering**

Download both assets from:

```text
https://github.com/Mubax5/Radmon/releases/download/latest/RadMon-Setup.exe
https://github.com/Mubax5/Radmon/releases/download/latest/RadMon-Setup.exe.sha256
```

Write `.part` files, rename only after completed downloads, parse exactly one 64-hex SHA-256 token, verify with `Get-FileHash`, then call:

```powershell
$process = Start-Process -FilePath $setupPath -ArgumentList @(
  '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$InstallRoot"
) -Wait -PassThru
```

After exit code 0, re-read `app/release.json` and require the expected remote SHA.

- [ ] **Step 4: Add named mutex and append-only logging**

Use `System.Threading.Mutex` named `Global\RadMonAutoUpdater`, write timestamped lines to `runtime/logs/radmon-updater.log`, and always release/dispose in `finally`.

- [ ] **Step 5: Run focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_windows_auto_update.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packaging/radmon_update.ps1 .env.example tests/test_windows_auto_update.py
git commit -m "feat: add verified RadMon release updater"
```

---

### Task 3: Register and remove the updater Scheduled Task

**Files:**
- Create: `packaging/install_updater.ps1`
- Modify: `packaging/RadMon.iss`
- Test: `tests/test_windows_auto_update.py`, `tests/test_windows_packaging.py`

**Interfaces:**
- Consumes: installed updater path and install root from Inno Setup.
- Produces: `RadMon Updater` task as `SYSTEM`, highest privileges, two-minute repetition, `IgnoreNew` concurrency policy.

- [ ] **Step 1: Implement task registration**

`install_updater.ps1` accepts `-ScriptPath` and `-InstallRoot`, creates:

```powershell
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`" -InstallRoot `"$InstallRoot`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
  -RepetitionInterval (New-TimeSpan -Minutes 2) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
```

Register with a `SYSTEM`/Highest principal and `MultipleInstances IgnoreNew`.

- [ ] **Step 2: Package/register/uninstall in Inno Setup**

Copy `radmon_update.ps1` to `{app}\updater`, extract/run `install_updater.ps1` after server registration, and add uninstall commands to end/delete `RadMon Updater` before deleting the server task.

- [ ] **Step 3: Run focused packaging tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_windows_auto_update.py tests/test_windows_packaging.py`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add packaging/install_updater.ps1 packaging/RadMon.iss tests/test_windows_auto_update.py tests/test_windows_packaging.py
git commit -m "feat: register RadMon automatic updater task"
```

---

### Task 4: Embed exact build SHA and smoke-test updater on Windows CI

**Files:**
- Modify: `.github/workflows/windows-build.yml`
- Test: `tests/test_windows_auto_update.py`, `tests/test_windows_packaging.py`

**Interfaces:**
- Consumes: `GITHUB_SHA` from the build job.
- Produces: `portable/RadMon/app/release.json`; Windows smoke evidence for updater script/task across initial install and upgrade.

- [ ] **Step 1: Write release marker before installer assembly completes**

In the portable-layout PowerShell step:

```powershell
@{
  commit_sha = $env:GITHUB_SHA
  repository = $env:GITHUB_REPOSITORY
  release_tag = 'latest'
  built_at_utc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content "$portable\app\release.json" -Encoding utf8
```

- [ ] **Step 2: Add updater helper smoke test**

Run:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "packaging\radmon_update.ps1" -InstallRoot "$PWD" -SelfTest
if ($LASTEXITCODE -ne 0) { throw "RadMon updater self-test failed" }
```

- [ ] **Step 3: Assert task registration survives install and upgrade**

After initial installer smoke test and again after upgrade:

```powershell
Get-ScheduledTask -TaskName "RadMon Updater" -ErrorAction Stop | Out-Null
```

- [ ] **Step 4: Run focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_windows_auto_update.py tests/test_windows_packaging.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/windows-build.yml tests/test_windows_auto_update.py tests/test_windows_packaging.py
git commit -m "ci: verify RadMon automatic updater"
```

---

### Task 5: Full verification and release integration

**Files:**
- No new production files.

**Interfaces:**
- Consumes: completed feature branch.
- Produces: verified branch ready for fast-forward to `main`, followed by a matching `latest` release.

- [ ] **Step 1: Run full CI-equivalent test suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
Expected: all tests pass.

Run: `cd web && npm ci && npm run check && npm run build`
Expected: type-check and Vite production build pass.

- [ ] **Step 2: Verify branch CI**

Require the GitHub Actions `CI` workflow on the exact feature head SHA to conclude `success`.

- [ ] **Step 3: Fast-forward main**

Only if the branch is ahead of `main` and behind by 0, move `main` to the verified feature head without force.

- [ ] **Step 4: Verify main workflows and release**

Require both `CI` and `Windows RadMon EXE` for the exact new `main` SHA to conclude `success`. Then verify `refs/tags/latest` points to that same SHA and the release contains newly uploaded `RadMon-Setup.exe` plus `.sha256` assets.
