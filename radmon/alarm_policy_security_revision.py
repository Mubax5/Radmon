"""Alarm-policy permission additions kept separate from legacy role definitions."""
from __future__ import annotations


def apply() -> None:
    from . import security as module

    for role in (module.Role.ADMINISTRATOR, module.Role.OPERATOR):
        module.ROLE_PERMISSIONS[role] = frozenset(
            set(module.ROLE_PERMISSIONS[role]) | {"suppress_alarm"}
        )
    # Viewer is deliberately not granted suppression control.
