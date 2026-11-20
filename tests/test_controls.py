"""Offline regression tests for Bindicator's persistent pause/resume switch."""
from __future__ import annotations

import json
import stat
import sys
from copy import deepcopy

import pytest

from bindicator.app import BindicatorError
from bindicator.controls import is_paused, set_paused

from test_bindicator import DOWN, UP, make_app, at
from test_cli_preview import make_files


def test_pause_defaults_active_persists_and_is_group_accessible(tmp_path):
    assert is_paused(tmp_path) is False
    set_paused(tmp_path, True)
    assert is_paused(tmp_path)
    file = tmp_path / "control.json"
    assert json.loads(file.read_text()) == {"paused": True}
    assert stat.S_IMODE(file.stat().st_mode) == 0o660
    set_paused(tmp_path, False)
    assert is_paused(tmp_path) is False


@pytest.mark.parametrize("contents", [
    "not json", '{"paused": "yes"}', '{"paused": 1}', '[]',
    '{"unexpected": false}',
])
def test_corrupt_pause_state_fails_closed(tmp_path, contents):
    (tmp_path / "control.json").write_text(contents)
    with pytest.raises(BindicatorError, match="pause state"):
        is_paused(tmp_path)


def test_scheduled_reminder_never_contacts_calendar_or_hue_while_paused(
    tmp_path,
):
    app, pool = make_app(tmp_path)
    set_paused(tmp_path, True)
    app.collections = lambda day: pytest.fail("No calendar fetch while paused")
    pool.light = lambda rid: pytest.fail("No Hue read while paused")
    pool.set = lambda rid, payload: pytest.fail("No Hue write while paused")
    app.run(at("2026-11-10T18:00"))
    app.run(at("2026-11-11T09:00"))
    assert not app.state_path.exists()


def test_pause_during_active_reminder_keeps_snapshot_and_does_not_restore(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    colour_during = deepcopy(pool.data[DOWN]["color"])
    original_state = deepcopy(app.state)
    before = len(pool.changes)

    set_paused(tmp_path, True)
    # The morning timer leaves both Hue and the restoration snapshot alone.
    app.run(at("2026-11-11T09:00"))
    assert len(pool.changes) == before
    assert pool.data[DOWN]["color"] == colour_during
    assert app.state == original_state

    set_paused(tmp_path, False)
    app.run(at("2026-11-11T09:00"))
    assert app.state["lights"] == {}
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[UP]["on"]["on"] is False


def test_paused_state_survives_reconstruction(tmp_path):
    app, pool = make_app(tmp_path)
    set_paused(tmp_path, True)
    reloaded = type(app)(app.config, tmp_path, pool)
    reloaded.collections = lambda day: pytest.fail("No calendar fetch")
    reloaded.run(at("2026-11-10T18:00"))
    assert pool.changes == []


def call_cli(monkeypatch, config, secrets, state, *args):
    import bindicator.cli as cli

    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), *args,
    ])
    return cli.main()


def test_cli_pause_resume_toggle_status_no_hue_calls(monkeypatch, capsys, tmp_path):
    from bindicator.bridges import BridgePool

    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(
        BridgePool, "light",
        lambda *args: pytest.fail("Pause controls must not call Hue"),
    )
    monkeypatch.setattr(
        BridgePool, "set",
        lambda *args: pytest.fail("Pause controls must not write Hue"),
    )

    assert call_cli(monkeypatch, config, secrets, state, "--status") == 0
    assert "Bindicator: ACTIVE" in capsys.readouterr().out
    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 0
    assert "PAUSED" in capsys.readouterr().out
    assert is_paused(state)
    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 0
    assert is_paused(state)
    assert call_cli(monkeypatch, config, secrets, state, "--status") == 0
    assert "Bindicator: PAUSED" in capsys.readouterr().out
    assert call_cli(monkeypatch, config, secrets, state, "--toggle") == 0
    assert "ACTIVE" in capsys.readouterr().out
    assert not is_paused(state)
    assert call_cli(monkeypatch, config, secrets, state, "--toggle") == 0
    assert is_paused(state)
    assert call_cli(monkeypatch, config, secrets, state, "--resume") == 0
    assert not is_paused(state)
    assert call_cli(monkeypatch, config, secrets, state, "--resume") == 0
    assert not is_paused(state)


def test_cli_preview_refused_while_paused(monkeypatch, tmp_path, caplog):
    import bindicator.bin_preview as bp

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    set_paused(state, True)
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda *args, **kwargs: pytest.fail("A paused preview must not run"),
    )
    assert call_cli(
        monkeypatch, config, secrets, state, "--test-bin", "recycling"
    ) == 1
    assert "Bindicator is paused" in caplog.text


def test_cli_scheduled_check_refuses_to_control_lights_when_paused(
    monkeypatch, tmp_path,
):
    import bindicator.app as app
    import bindicator.bridges as bridges

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    set_paused(state, True)
    monkeypatch.setattr(
        app.Bindicator, "calendar_data",
        lambda *args: pytest.fail("Paused checks must not download Zoho"),
    )
    monkeypatch.setattr(
        bridges.BridgePool, "light",
        lambda *args: pytest.fail("Paused checks must not contact Hue"),
    )
    assert call_cli(monkeypatch, config, secrets, state, "--run") == 0


def _make_active_reminder(tmp_path):
    """Create a saved one-lamp reminder for exercising the real CLI restore."""
    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    snapshot = {
        "date": "2026-11-17",
        "manual_until": "2026-11-17",
        "lights": {"office/lamp-uuid": {
            "original": {"color": {"xy": {"x": 0.3, "y": 0.3}}},
            "applied_xy": {"x": 0.57, "y": 0.39},
            "original_on": False,
            "color_name": "orange",
        }},
    }
    (state / "state.json").write_text(json.dumps(snapshot))
    return config, secrets, state, snapshot


def test_cli_pause_restores_original_colour_and_power_immediately(
    monkeypatch, capsys, tmp_path,
):
    from bindicator.bridges import BridgePool

    config, secrets, state, _ = _make_active_reminder(tmp_path)
    live = {
        "color": {"xy": {"x": 0.57, "y": 0.39}},
        "on": {"on": True},
        "dimming": {"brightness": 31},
    }
    writes = []

    def get_light(self, rid):
        assert rid == "office/lamp-uuid"
        return deepcopy(live)

    def set_light(self, rid, payload):
        assert rid == "office/lamp-uuid"
        writes.append(deepcopy(payload))
        live.update(deepcopy(payload))

    monkeypatch.setattr(BridgePool, "light", get_light)
    monkeypatch.setattr(BridgePool, "set", set_light)

    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 0
    assert is_paused(state)
    assert writes == [{"color": {"xy": {"x": 0.3, "y": 0.3}}, "on": {"on": False}}]
    assert live["dimming"]["brightness"] == 31
    saved = json.loads((state / "state.json").read_text())
    assert saved == {"date": None, "lights": {}}
    assert "original lamp appearance restored" in capsys.readouterr().out

    assert call_cli(monkeypatch, config, secrets, state, "--status") == 0
    out = capsys.readouterr().out
    assert "Bindicator: PAUSED" in out
    assert "Active collection date: (none)" in out
    assert call_cli(monkeypatch, config, secrets, state, "--resume") == 0
    assert not is_paused(state)
    assert len(writes) == 1  # Resume itself never changes the lights.


def test_cli_toggle_to_paused_restores_original_gradient(
    monkeypatch, tmp_path,
):
    from bindicator.bridges import BridgePool

    config, secrets, state, snapshot = _make_active_reminder(tmp_path)
    original = {"points": [
        {"color": {"xy": {"x": 0.11, "y": 0.29}}},
        {"color": {"xy": {"x": 0.2, "y": 0.48}}},
    ], "mode": "interpolated_palette"}
    applied = {"points": [
        {"color": {"xy": {"x": 0.57, "y": 0.39}}},
        {"color": {"xy": {"x": 0.21, "y": 0.65}}},
    ], "mode": "segmented_palette"}
    record = snapshot["lights"]["office/lamp-uuid"]
    record["original"] = {"gradient": deepcopy(original)}
    record.pop("applied_xy")
    record["applied_gradient"] = deepcopy(applied)
    (state / "state.json").write_text(json.dumps(snapshot))

    lamp = {
        "on": {"on": True},
        "gradient": deepcopy(applied),
        "dimming": {"brightness": 72},
    }
    writes = []

    monkeypatch.setattr(
        BridgePool, "light", lambda self, rid: deepcopy(lamp),
    )
    def set_gradient(self, rid, payload):
        writes.append(deepcopy(payload))
        lamp.update(deepcopy(payload))
    monkeypatch.setattr(BridgePool, "set", set_gradient)

    assert call_cli(monkeypatch, config, secrets, state, "--toggle") == 0
    assert is_paused(state)
    assert writes == [{"gradient": original, "on": {"on": False}}]
    assert lamp["dimming"]["brightness"] == 72
    assert json.loads((state / "state.json").read_text()) == {
        "date": None, "lights": {}
    }


def test_cli_pause_respects_manual_override_without_writing(
    monkeypatch, tmp_path,
):
    from bindicator.bridges import BridgePool

    config, secrets, state, _ = _make_active_reminder(tmp_path)
    monkeypatch.setattr(
        BridgePool, "light",
        lambda self, rid: {
            "color": {"xy": {"x": 0.2, "y": 0.6}},
            "on": {"on": True},
        },
    )
    monkeypatch.setattr(
        BridgePool, "set",
        lambda *args: pytest.fail("Must not overwrite a manual scene"),
    )
    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 0
    assert is_paused(state)
    assert json.loads((state / "state.json").read_text()) == {
        "date": None, "lights": {}
    }


def test_cli_pause_failure_stays_paused_and_retains_snapshot_for_retry(
    monkeypatch, tmp_path, caplog,
):
    from bindicator.bridges import BridgePool

    config, secrets, state, snapshot = _make_active_reminder(tmp_path)
    def failing_light(self, rid):
        raise BindicatorError("Bridge offline")
    monkeypatch.setattr(BridgePool, "light", failing_light)
    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 1
    assert is_paused(state)
    assert json.loads((state / "state.json").read_text()) == snapshot
    assert "Saved light state was retained for retry" in caplog.text

    lamp = {
        "color": {"xy": {"x": 0.57, "y": 0.39}},
        "on": {"on": True},
    }
    written = []
    monkeypatch.setattr(BridgePool, "light", lambda self, rid: deepcopy(lamp))
    def write(self, rid, payload):
        written.append(deepcopy(payload))
        lamp.update(deepcopy(payload))
    monkeypatch.setattr(BridgePool, "set", write)
    # A second --pause retries even though the pause flag is already true.
    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 0
    assert is_paused(state)
    assert written == [{"color": {"xy": {"x": 0.3, "y": 0.3}}, "on": {"on": False}}]
    assert json.loads((state / "state.json").read_text()) == {
        "date": None, "lights": {}
    }


def test_cli_pause_when_no_reminder_does_not_contact_hue(
    monkeypatch, tmp_path,
):
    from bindicator.bridges import BridgePool
    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(
        BridgePool, "light",
        lambda *args: pytest.fail("No active reminder; no reads"),
    )
    monkeypatch.setattr(
        BridgePool, "set",
        lambda *args: pytest.fail("No active reminder; no writes"),
    )
    assert call_cli(monkeypatch, config, secrets, state, "--pause") == 0
    assert is_paused(state)


def test_bins_out_restores_original_scene_and_keeps_future_reminders(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    assert app.state["lights"]
    assert app.state["date"] == "2026-11-11"
    assert app.acknowledge_bins_out() == {"acknowledged": True, "restored": True}
    assert app.state["lights"] == {}
    assert app.state["acknowledged_date"] == "2026-11-11"
    assert not is_paused(tmp_path)
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[UP]["on"]["on"] is False
    count = len(pool.changes)
    reloaded = type(app)(app.config, tmp_path, pool)
    reloaded.run(at("2026-11-10T18:30"))
    reloaded.run(at("2026-11-11T08:59"))
    assert len(pool.changes) == count
    # The acknowledgement must not suppress a later collection.
    reloaded.collections = lambda day: ["orange"]
    reloaded.run(at("2026-11-11T18:00"))
    assert reloaded.state["date"] == "2026-11-12"
    assert reloaded.state["lights"]


def test_bins_out_is_idempotent_when_no_active_reminder(tmp_path):
    app, pool = make_app(tmp_path)
    assert app.acknowledge_bins_out() == {"acknowledged": False, "restored": True}
    assert app.state.get("acknowledged_date") is None
    assert pool.changes == []


def test_bins_out_retains_failed_restoration_for_retry(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    before = deepcopy(app.state)
    pool.light = lambda ref: (_ for _ in ()).throw(BindicatorError("Bridge offline"))
    with pytest.raises(BindicatorError, match="Could not restore"):
        app.acknowledge_bins_out()
    assert app.state["acknowledged_date"] == before["date"]
    assert app.state["lights"]
    # A scheduled check must not overwrite the saved recovery snapshot.
    with pytest.raises(BindicatorError, match="Could not restore"):
        app.run(at("2026-11-10T18:30"))
    assert app.state["lights"]


def test_bins_out_dismisses_persistent_manual_reminder(tmp_path):
    from datetime import date
    app, pool = make_app(tmp_path)
    app.apply_collections(date(2026, 11, 17), ["orange"], manual=True)
    assert app.state["manual_until"] == "2026-11-17"
    assert app.acknowledge_bins_out()["acknowledged"] is True
    assert app.state["acknowledged_date"] == "2026-11-17"
    assert app.state.get("manual_until") is None
    count = len(pool.changes)
    app.run(at("2026-11-16T19:00"))
    assert len(pool.changes) == count
    assert not is_paused(tmp_path)


def test_bins_out_preserves_manual_hue_changes(tmp_path):
    from test_bindicator import GREEN
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    pool.data[DOWN]["color"]["xy"] = deepcopy(GREEN)
    assert app.acknowledge_bins_out()["restored"] is True
    assert pool.data[DOWN]["color"]["xy"] == GREEN
    assert app.state["lights"] == {}
