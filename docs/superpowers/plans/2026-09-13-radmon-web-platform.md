# RadMon Web Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a low-memory Windows web-first RadMon platform with Kumo UI, authenticated RBAC app, anonymous full Grafana landing page, persistent editable Grafana, and boot-time background operation.

**Architecture:** Keep the current Python/FastAPI/LAN core. Add a static React/Kumo SPA served by FastAPI, seed-only Grafana provisioning, server-only executable mode, and Windows Task Scheduler startup registration in the installer.

**Tech Stack:** Python/FastAPI/Uvicorn/SQLite, React + TypeScript + Vite, @cloudflare/kumo, @phosphor-icons/react, native Grafana, PyInstaller, Inno Setup, Windows Task Scheduler.

**Spec:** `docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md`

## Global Constraints
- Production hardware and Windows stay unchanged.
- Only branches `main` and `feature` may exist.
- Work on `feature`; merge to `main` only after CI and Windows package verification.
- No Docker runtime requirement and no source MariaDB DDL changes.
- Grafana edits are persistent and never auto-overwritten.
- Anonymous access is Grafana monitoring only; Viewer is authenticated.
- Production runtime has no Node.js server.

### Task 1: Web-platform contracts
**Files:** `tests/test_web_platform_contract.py`, `tests/test_grafana_persistence.py`
- [ ] Write failing tests for anonymous monitoring landing, authenticated app/API, role boundaries, seed-only Grafana, and absence of production Docker dependency.
- [ ] Run focused tests and confirm RED.
- [ ] Implement minimal backend contracts.
- [ ] Run focused and full Python tests.
- [ ] Commit.

### Task 2: Grafana seed-only persistence
**Files:** `radmon/grafana_bootstrap.py`, `radmon/config.py`, `.env.example`
- [ ] Test existing dashboard and playlist are never overwritten.
- [ ] Test missing resources are created exactly once.
- [ ] Keep native data under persistent `runtime/grafana` with anonymous Viewer.
- [ ] Remove Docker from normal production fallback path.
- [ ] Run full tests and commit.

### Task 3: Web API read models and RBAC
**Files:** `radmon/secure_api.py`, `radmon/central_service.py`, `tests/test_web_api.py`
- [ ] Add authenticated overview, stations, latest/history, archives, source health, diagnostics reads.
- [ ] Preserve backend permission enforcement for all write actions.
- [ ] Run full tests and commit.

### Task 4: Static SPA hosting
**Files:** `radmon/web_host.py`, `radmon/central_service.py`, `tests/test_web_host.py`
- [ ] Test `/` redirects to Grafana kiosk, `/app` serves SPA, SPA fallback works, missing web build returns clear 503.
- [ ] Implement static hosting independent of Node at runtime.
- [ ] Run full tests and commit.

### Task 5: React/Kumo frontend
**Files:** `web/package.json`, `web/index.html`, `web/src/*`, `web/vite.config.ts`, `web/tsconfig.json`
- [ ] Create Vite React TypeScript app using Kumo standalone styles and Kumo components.
- [ ] Implement login and authenticated Cloudflare-style shell.
- [ ] Implement Viewer, Operator, Administrator navigation and route guards.
- [ ] Implement Overview, Stations, History, Archives, Alarms, Users, System pages against FastAPI.
- [ ] Build production `web/dist`.

### Task 6: Server-only 24/7 mode
**Files:** `radmon/production_app.py`, `radmon/__main__.py`, `tests/test_server_mode.py`
- [ ] Add lifecycle tests for `--server` without PySide UI.
- [ ] Implement long-running central and Grafana startup with clean signal/keyboard shutdown.
- [ ] Keep desktop emergency mode compatible.
- [ ] Run full tests and commit.

### Task 7: Windows startup registration
**Files:** `packaging/RadMon.iss`, `tests/test_installer_release.py`
- [ ] Test installer registers startup task with `RadMon.exe --server` and removes it on uninstall.
- [ ] Preserve config/runtime/archive/report paths.
- [ ] Run packaging tests and commit.

### Task 8: Frontend-aware packaging and CI
**Files:** `.github/workflows/ci.yml`, `.github/workflows/windows-build.yml`, `RadMon.spec`, `tests/test_bundle.py`
- [ ] Add Node setup and frontend build before PyInstaller.
- [ ] Bundle `web/dist` into onedir.
- [ ] Add packaged smoke tests and installer checks.
- [ ] Publish/update fixed `latest` release with `RadMon-Setup.exe`.

### Task 9: Documentation and final cleanup
**Files:** `README.md`, `docs/INSTALLATION.md`, `docs/USER-MANUAL.md`, `grafana/README.md`
- [ ] Document anonymous Grafana landing, `/app` login/RBAC, localhost:3300 admin editing, persistence, startup task, and recovery.
- [ ] Remove stale Docker-as-default instructions.
- [ ] Delete the temporary spec/plan before final merge to preserve the clean-repo policy.
- [ ] Run full Python tests, frontend build, compile validation, Grafana validation, Windows build.
- [ ] Merge `feature` to `main`; keep exactly `main` and `feature`.
