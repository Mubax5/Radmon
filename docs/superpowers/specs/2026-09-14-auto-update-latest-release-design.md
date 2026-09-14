# RadMon Automatic Release Updater Design

## Goal

Every installed RadMon can automatically upgrade itself shortly after the GitHub `latest` release moves forward. The updater is installed with RadMon, runs without an interactive user, preserves existing configuration/data, and can be disabled with configuration.

## Source of truth

The updater follows `Mubax5/Radmon` tag `latest`, not the tip of `main`. This ensures a PC only installs an installer that has completed the Windows build/release workflow.

The packaged application contains `app/release.json` with the exact build commit SHA. The updater fetches `refs/tags/latest`. If the SHA matches, it exits. If it differs, the updater calls GitHub's compare API and proceeds only when the release SHA is a descendant of the installed SHA. A release that is older than the installed build is ignored, preventing CI-time downgrades while a newer `main` build is still being produced.

## Runtime architecture

The installer places `updater/radmon_update.ps1` outside the replaceable `app` directory and registers a `RadMon Updater` Scheduled Task running as `SYSTEM` with highest privileges. It runs every 2 minutes with `MultipleInstances IgnoreNew` and also uses a named mutex so manual/task overlap cannot install twice.

The updater reads `<install-root>/config/.env`. `RADMON_AUTO_UPDATE=1` enables updates; `0`, `false`, `no`, `off`, or `disabled` disables them. Missing `RADMON_AUTO_UPDATE` defaults to enabled so existing installations receive the feature after upgrading once.

## Update flow

1. Read the local `app/release.json` commit SHA.
2. Fetch GitHub tag `latest` with a RadMon User-Agent.
3. Exit when local and remote SHAs match.
4. Use the GitHub compare API to verify remote `latest` is ahead of local. Ignore an older/diverged remote instead of downgrading.
5. Download `RadMon-Setup.exe` and `RadMon-Setup.exe.sha256` into `runtime/updates/<sha>/` using temporary `.part` files.
6. Validate the checksum file format and compare SHA-256 before touching the running service.
7. Run the installer with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=<install-root>` and wait for its exit code.
8. Verify the installed `app/release.json` now contains the expected SHA. The installer already performs pre-upgrade RadMon shutdown and re-registers/restarts the server.
9. Log updater activity to `runtime/logs/radmon-updater.log` and remove stale downloaded update directories after successful installation.

Network/API/download failures happen before RadMon is stopped, so the currently installed server keeps running. Checksum failures abort installation. Installer failures are logged and retried on a later scheduled run.

## Installer/build integration

The Windows workflow writes `portable/RadMon/app/release.json` using `GITHUB_SHA` before building the installer. `packaging/RadMon.iss` installs the updater script to `{app}/updater`, registers the updater task, and removes that task on uninstall. Upgrading overwrites the updater script but preserves `config`, `runtime`, `archives`, and `reports` exactly as today.

The existing `RadMon Server` task stays independent. The updater task must never run the application from a Git checkout or copy source files directly to the machine.

## Validation

Tests must cover the packaging contract, presence of the build SHA marker, Scheduled Task registration, default-enabled/explicit-disable config parsing, checksum verification contract, no-downgrade compare behavior, and persistence of the updater task across installer upgrade. The Windows workflow must smoke-test updater script self-validation and confirm `RadMon Updater` exists after initial install and upgrade.
