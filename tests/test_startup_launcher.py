from pathlib import Path

from radmon.config import Settings
from radmon.paths import ApplicationPaths
from radmon.startup_launcher import RadMonLauncher


def make_paths(tmp_path: Path) -> ApplicationPaths:
    return ApplicationPaths(
        install_root=tmp_path,
        app_dir=tmp_path / "app",
        config_dir=tmp_path / "config",
        runtime_dir=tmp_path / "runtime",
        archive_dir=tmp_path / "archives",
        report_dir=tmp_path / "reports",
        log_dir=tmp_path / "logs",
        assets_dir=tmp_path / "assets",
        grafana_dir=tmp_path / "grafana",
    )


def make_launcher(tmp_path, *, db=True, central=False, grafana=False, task=False,
                  on_task=None, on_process=None, ensure=None, timeout=0):
    state = {"db": db, "central": central, "grafana": grafana}
    calls = {"task": 0, "process": 0, "ensure": 0}

    def tcp(host, port):
        return state["db"]

    def http(url):
        if "/health" in url and "api/health" not in url:
            return state["central"]
        return state["grafana"]

    def run_task():
        calls["task"] += 1
        if on_task:
            on_task(state)
        return task

    def start_process():
        calls["process"] += 1
        if on_process:
            on_process(state)

    def ensure_grafana():
        calls["ensure"] += 1
        if ensure:
            ensure(state)
        else:
            state["grafana"] = True

    launcher = RadMonLauncher(
        Settings(), make_paths(tmp_path), tcp_probe=tcp, http_probe=http,
        run_task=run_task, start_process=start_process,
        ensure_grafana=ensure_grafana, sleeper=lambda _delay: None,
        timeout=timeout, poll_interval=0.01,
    )
    return launcher, state, calls


def status(states, component):
    return next(item.status for item in states if item.name == component)


def test_all_down_falls_back_to_managed_server_then_grafana(tmp_path):
    launcher, state, calls = make_launcher(
        tmp_path, db=False,
        on_process=lambda current: current.update(central=True, grafana=True),
    )
    states = launcher.start()
    assert status(states, "MariaDB") == "tidak tersedia"
    assert status(states, "Central/API") == "dimulai"
    assert status(states, "Grafana") == "sudah berjalan"
    assert calls == {"task": 1, "process": 1, "ensure": 0}


def test_central_down_grafana_up_starts_only_central_via_task(tmp_path):
    launcher, state, calls = make_launcher(
        tmp_path, grafana=True, task=True,
        on_task=lambda current: current.update(central=True),
    )
    states = launcher.start()
    assert status(states, "Central/API") == "dimulai"
    assert status(states, "Grafana") == "sudah berjalan"
    assert calls == {"task": 1, "process": 0, "ensure": 0}


def test_grafana_down_with_central_up_starts_grafana_only(tmp_path):
    launcher, _state, calls = make_launcher(tmp_path, central=True)
    states = launcher.start()
    assert status(states, "Central/API") == "sudah berjalan"
    assert status(states, "Grafana") == "siap"
    assert calls == {"task": 0, "process": 0, "ensure": 1}


def test_all_healthy_reuses_components_without_starting_anything(tmp_path):
    launcher, _state, calls = make_launcher(tmp_path, central=True, grafana=True)
    states = launcher.start()
    assert status(states, "Central/API") == "sudah berjalan"
    assert status(states, "Grafana") == "sudah berjalan"
    assert calls == {"task": 0, "process": 0, "ensure": 0}


def test_missing_task_uses_managed_server_fallback(tmp_path):
    launcher, _state, calls = make_launcher(
        tmp_path, task=False,
        on_process=lambda current: current.update(central=True),
    )
    assert status(launcher.start(), "Central/API") == "dimulai"
    assert calls["task"] == 1 and calls["process"] == 1


def test_accepted_task_that_stays_unhealthy_falls_back_once_to_managed_server(tmp_path):
    launcher, _state, calls = make_launcher(
        tmp_path, task=True,
        on_process=lambda current: current.update(central=True, grafana=True),
    )
    states = launcher.start()
    assert status(states, "Central/API") == "dimulai"
    assert "fallback" in next(item.detail for item in states if item.name == "Central/API")
    assert calls == {"task": 1, "process": 1, "ensure": 0}


def test_late_task_health_is_reused_without_duplicate_managed_start(tmp_path):
    launcher, _state, calls = make_launcher(tmp_path, task=True, timeout=0)
    central_probes = 0

    def late_health(url):
        nonlocal central_probes
        if "/health" in url and "api/health" not in url:
            central_probes += 1
            return central_probes >= 3
        return False

    launcher.http_probe = late_health
    states = launcher.start()
    assert status(states, "Central/API") == "dimulai"
    assert "Scheduled Task" in next(item.detail for item in states if item.name == "Central/API")
    assert calls == {"task": 1, "process": 0, "ensure": 0}


def test_start_timeout_is_reported_without_repeated_launches(tmp_path):
    launcher, _state, calls = make_launcher(tmp_path, timeout=0)
    states = launcher.start()
    assert status(states, "Central/API") == "timeout"
    assert calls["task"] == 1 and calls["process"] == 1


def test_new_server_owns_grafana_start_and_launcher_does_not_race_it(tmp_path):
    launcher, _state, calls = make_launcher(
        tmp_path, timeout=0,
        on_process=lambda current: current.update(central=True),
    )
    states = launcher.start()
    assert status(states, "Central/API") == "dimulai"
    assert status(states, "Grafana") == "timeout"
    assert calls == {"task": 1, "process": 1, "ensure": 0}


def test_stale_lock_recovery_waits_for_health_and_never_starts_duplicate(tmp_path):
    def recover_by_task(state):
        # Scheduled server owns lock recovery; once healthy, launcher reuses it.
        state.update(central=True, grafana=True)

    launcher, _state, calls = make_launcher(
        tmp_path, task=True, on_task=recover_by_task,
    )
    states = launcher.start()
    assert status(states, "Central/API") == "dimulai"
    assert calls == {"task": 1, "process": 0, "ensure": 0}


def test_grafana_failure_is_partial_and_does_not_restart_central(tmp_path):
    def fail(_state):
        raise RuntimeError("Grafana executable tidak ditemukan")

    launcher, _state, calls = make_launcher(tmp_path, central=True, ensure=fail)
    states = launcher.start()
    assert status(states, "Central/API") == "sudah berjalan"
    assert status(states, "Grafana") == "gagal memulai"
    assert calls == {"task": 0, "process": 0, "ensure": 1}
