"""Regression coverage for configurable reminder timing and scheduler phases."""
from datetime import datetime, date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from bindicator.app import TZ, active_collection_date, load_config, validate_schedule, BindicatorError
from bindicator.scheduler import phase_at, tick


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def test_default_and_custom_windows():
    schedule = validate_schedule({})
    assert schedule == {"start": "18:00", "restore": "09:00"}
    assert active_collection_date(at("2026-11-10T17:59"), schedule) is None
    assert active_collection_date(at("2026-11-10T18:00"), schedule) == date(2026, 11, 11)
    assert active_collection_date(at("2026-11-11T08:59"), schedule) == date(2026, 11, 11)
    assert active_collection_date(at("2026-11-11T09:00"), schedule) is None
    custom = validate_schedule({"start": "16:30", "restore": "07:15"})
    assert active_collection_date(at("2026-11-10T16:29"), custom) is None
    assert active_collection_date(at("2026-11-10T16:30"), custom) == date(2026, 11, 11)
    assert active_collection_date(at("2026-11-11T07:14"), custom) == date(2026, 11, 11)
    assert active_collection_date(at("2026-11-11T07:15"), custom) is None


@pytest.mark.parametrize("schedule", [
    {"start": "09:00", "restore": "09:00"},
    {"start": "18:00", "restore": "18:00"},
    {"start": "24:00", "restore": "09:00"},
    {"start": "18:00", "restore": "09:60"},
    {"start": "18:00", "restore": "09:00", "other": "x"},
])
def test_invalid_schedule(schedule):
    with pytest.raises(BindicatorError):
        validate_schedule(schedule)


def test_phase_unchanged_over_midnight_and_dst():
    schedule = validate_schedule({})
    assert phase_at(at("2026-11-10T18:00"), schedule) == phase_at(at("2026-11-11T08:59"), schedule)
    assert phase_at(at("2026-11-11T09:00"), schedule) != phase_at(at("2026-11-11T08:59"), schedule)
    assert phase_at(at("2026-03-28T18:00"), schedule) == phase_at(at("2026-03-29T08:00"), schedule)
    assert phase_at(at("2026-10-24T18:00"), schedule) == phase_at(at("2026-10-25T08:00"), schedule)


def test_tick_executes_once_per_successful_phase_and_retries_failures(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("""calendar:
  events: {}
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  green: {x: 0.21, y: 0.65}
priority: [green]
schedule: {start: '18:00', restore: '09:00'}
""")
    state = tmp_path / "state"
    calls = []
    ok = {"value": True}
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0 if ok["value"] else 1)
    monkeypatch.setattr("bindicator.scheduler.subprocess.run", fake_run)
    assert tick(config, state, at("2026-11-10T18:00"))
    assert not tick(config, state, at("2026-11-11T08:30"))
    assert tick(config, state, at("2026-11-11T09:00"))
    ok["value"] = False
    with pytest.raises(RuntimeError):
        tick(config, state, at("2026-11-11T18:00"))
    ok["value"] = True
    assert tick(config, state, at("2026-11-11T18:01"))
    assert len(calls) == 4
    assert not tick(config, state, at("2026-11-11T18:02"))
    config.write_text(config.read_text().replace("18:00", "17:30"))
    assert tick(config, state, at("2026-11-11T18:03"))
