from types import SimpleNamespace

import pytest

from radmon.process_ownership import (
    PortOwner,
    find_listener_owner,
    is_legacy_radmon_central,
    stop_legacy_radmon_central,
)


def test_legacy_central_requires_radmon_script_and_exact_port():
    assert is_legacy_radmon_central(
        PortOwner(42, r'python.exe C:\old\Radmon\central_server.py --host 0.0.0.0 --port 8090'),
        8090,
    )
    assert not is_legacy_radmon_central(
        PortOwner(43, r'python.exe other_server.py --port 8090'),
        8090,
    )
    assert not is_legacy_radmon_central(
        PortOwner(44, r'python.exe C:\old\Radmon\central_server.py --port 9000'),
        8090,
    )


def test_stop_refuses_foreign_owner_without_invoking_runner():
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="bukan legacy RadMon"):
        stop_legacy_radmon_central(PortOwner(10, "python.exe other_server.py --port 8090"), runner=runner)
    assert calls == []


def test_find_listener_owner_parses_pid_and_command_line():
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="321\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="python.exe C:\\Radmon\\central_server.py --port 8090\n", stderr=""),
        ]
    )

    def runner(*args, **kwargs):
        return next(responses)

    owner = find_listener_owner(8090, runner=runner)
    assert owner == PortOwner(321, r"python.exe C:\Radmon\central_server.py --port 8090")
