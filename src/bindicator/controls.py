"""Persistent local enable/disable switch for scheduled Hue reminders.

Stored separately from active reminder state so pausing never discards
restoration snapshots. All changes are atomic and group-accessible.
"""
from __future__ import annotations

import json
from pathlib import Path

from .app import BindicatorError, json_save


def is_paused(state_dir: Path) -> bool:
    """Read the saved switch; fail closed if the file is corrupt or unreadable."""
    path = state_dir / "control.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:
        raise BindicatorError(
            "Cannot read Bindicator pause state; refusing to control lights."
        ) from exc
    if not isinstance(value, dict) or type(value.get("paused")) is not bool:
        raise BindicatorError(
            "Invalid Bindicator pause state; refusing to control lights."
        )
    return value["paused"]


def set_paused(state_dir: Path, paused: bool) -> None:
    """Persist the manual pause state across reboots and service restarts."""
    if type(paused) is not bool:
        raise ValueError("paused must be a boolean")
    json_save(state_dir / "control.json", {"paused": paused})
