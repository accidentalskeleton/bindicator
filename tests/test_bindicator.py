"""Offline multi-Bridge regression tests: no real Hue devices or Zoho needed."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import yaml

from bindicator.app import (
    Bindicator, BindicatorError, active_collection_date, assignments,
    load_config, ordered_colors, parse_collections, same_xy,
)
from bindicator.bridges import BridgePool, light_key, normalize_hue_config

TZ = ZoneInfo("Europe/London")
BLUE = {"x": 0.17, "y": 0.08}
ORANGE = {"x": 0.57, "y": 0.39}
GREEN = {"x": 0.21, "y": 0.65}
EVENTS = {
    "BinDay - Recycling": "blue",
    "BinDay - Household waste": "orange",
    "BinDay - Garden Waste": "green",
}
CONFIG = {
    "calendar": {"events": EVENTS},
    "hue": {
        "bridges": {
            "downstairs": {"host": "192.168.1.20", "verify_tls": False},
            "upstairs": {"host": "192.168.1.21", "verify_tls": False},
        },
        "lights": [
            {"bridge": "downstairs", "id": "light-a"},
            {"bridge": "upstairs", "id": "light-b"},
        ],
        "mode": "spread",
    },
    "colors": {"blue": BLUE, "orange": ORANGE, "green": GREEN},
    "priority": ["orange", "blue", "green"],
}
DOWN = "downstairs/light-a"
UP = "upstairs/light-b"


class FakePool:
    """Models two Hue Bridges, sharing no state except our test fixture."""

    def __init__(self):
        self.data = {
            key: {
                "id": key.split("/", 1)[1],
                "metadata": {"name": key},
                "on": {"on": False},
                "dimming": {"brightness": 37.0},
                "color": {"xy": {"x": 0.33, "y": 0.33}},
                "color_temperature": {"mirek": None, "mirek_valid": False},
            }
            for key in (DOWN, UP)
        }
        self.changes = []
        self.unavailable = set()

    def light(self, key):
        if key in self.unavailable:
            raise BindicatorError("Fake Bridge unreachable")
        return deepcopy(self.data[key])

    def set(self, key, payload):
        if key in self.unavailable:
            raise BindicatorError("Fake Bridge unreachable")
        self.changes.append((key, deepcopy(payload)))
        if "gradient" in payload:
            self.data[key].setdefault("gradient", {}).update(deepcopy(payload["gradient"]))
        self.data[key].update({
            field: deepcopy(value) for field, value in payload.items()
            if field != "gradient"
        })


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def make_app(tmp_path, mode="spread"):
    config = deepcopy(CONFIG)
    config["hue"]["mode"] = mode
    pool = FakePool()
    app = Bindicator(config, tmp_path, pool)
    app.collections = lambda day: ["orange", "blue"]
    return app, pool


def test_reminder_window():
    assert active_collection_date(at("2026-11-10T17:59")) is None
    assert str(active_collection_date(at("2026-11-10T18:00"))) == "2026-11-11"
    assert str(active_collection_date(at("2026-11-11T08:59"))) == "2026-11-11"
    assert active_collection_date(at("2026-11-11T09:00")) is None


def test_priority_and_spread_across_bridges():
    assert ordered_colors(["blue", "orange", "blue"], ["orange", "blue"]) == [
        "orange", "blue"
    ]
    # With just one selected lamp per Bridge, each shows the priority colour.
    assert assignments([DOWN, UP], ["orange", "blue"], "spread") == {
        DOWN: "orange", UP: "orange"
    }
    assert assignments([DOWN, UP], ["orange", "blue"], "priority") == {
        DOWN: "orange", UP: "orange"
    }


def test_spread_restarts_at_highest_priority_on_each_bridge():
    # Interleaved selection order must not make a different Bridge inherit
    # the preceding Bridge's colour index.
    office_second = "downstairs/light-c"
    house_second = "upstairs/light-d"
    lights = [DOWN, UP, office_second, house_second]
    assert assignments(lights, ["orange", "green"], "spread") == {
        DOWN: "orange",
        UP: "orange",
        office_second: "green",
        house_second: "green",
    }
    assert assignments(lights, ["orange", "green"], "priority") == {
        light: "orange" for light in lights
    }


def test_spread_one_bridge_with_two_lamps_and_another_with_one():
    office_second = "downstairs/light-c"
    lights = [DOWN, UP, office_second]
    assert assignments(lights, ["orange", "green", "blue"], "spread") == {
        DOWN: "orange",
        UP: "orange",
        office_second: "green",
    }
    assert assignments(lights, [], "spread") == {}


def test_case_insensitive_calendar_matching_and_recurrence():
    ics = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Bindicator tests//EN
BEGIN:VEVENT
UID:recycling-1
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261111
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:binday - recycling
END:VEVENT
BEGIN:VEVENT
UID:general-1
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261118
SUMMARY:BinDay - Household waste
END:VEVENT
END:VCALENDAR
"""
    assert parse_collections(ics, date(2026, 11, 11), EVENTS) == ["blue"]
    assert set(parse_collections(ics, date(2026, 11, 18), EVENTS)) == {
        "blue", "orange"
    }
    assert parse_collections(ics, date(2026, 11, 19), EVENTS) == []


def test_apply_restore_two_bridges(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    assert len(pool.changes) == 2
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    assert pool.data[UP]["color"]["xy"] == ORANGE
    assert pool.data[DOWN]["on"]["on"] is True
    assert pool.data[UP]["on"]["on"] is True
    assert pool.data[DOWN]["dimming"]["brightness"] == 37.0
    assert app.state["date"] == "2026-11-11"
    assert list(app.state["lights"]) == [DOWN, UP]
    app.run(at("2026-11-11T09:00"))
    assert len(pool.changes) == 4
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[UP]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[UP]["on"]["on"] is False
    assert app.state["lights"] == {}


def test_scheduled_reminder_spreads_only_within_each_bridge(tmp_path):
    app, pool = make_app(tmp_path)
    office_second = "downstairs/light-c"
    pool.data[office_second] = deepcopy(pool.data[DOWN])
    app.config["hue"]["lights"].append({
        "bridge": "downstairs", "id": "light-c",
    })
    app.run(at("2026-11-10T18:00"))
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    assert pool.data[UP]["color"]["xy"] == ORANGE
    assert pool.data[office_second]["color"]["xy"] == BLUE
    assert list(app.state["lights"]) == [DOWN, UP, office_second]
    app.run(at("2026-11-11T09:00"))
    for light in (DOWN, UP, office_second):
        assert pool.data[light]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert app.state["lights"] == {}


def test_power_on_only_when_needed_and_restore_original_state(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[UP]["on"]["on"] = True
    app.run(at("2026-11-10T18:00"))
    # Off lamp is explicitly switched on, while an already-on lamp only
    # needs its colour changed. Brightness is never modified.
    first = dict(pool.changes)
    assert first[DOWN]["on"] == {"on": True}
    assert "on" not in first[UP]
    assert app.state["lights"][DOWN]["original_on"] is False
    assert app.state["lights"][UP]["original_on"] is True
    assert pool.data[DOWN]["dimming"]["brightness"] == 37.0
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[UP]["on"]["on"] is True
    assert pool.data[UP]["color"]["xy"] == {"x": 0.33, "y": 0.33}


def test_off_lamp_with_target_colour_must_still_be_turned_on(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["color"]["xy"] = dict(ORANGE)
    app.run(at("2026-11-10T18:00"))
    assert pool.data[DOWN]["on"]["on"] is True
    assert app.state["lights"][DOWN]["original_on"] is False
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[DOWN]["color"]["xy"] == ORANGE


def test_manually_switched_off_during_reminder_stays_off(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["on"]["on"] = True
    app.run(at("2026-11-10T18:00"))
    pool.data[DOWN]["on"]["on"] = False  # manual action after reminder
    app.run(at("2026-11-10T19:00"))
    assert pool.data[DOWN]["on"]["on"] is False
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}


def test_manual_colour_override_keeps_power_when_restoring(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    pool.data[DOWN]["color"]["xy"] = dict(GREEN)
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["color"]["xy"] == GREEN
    assert pool.data[DOWN]["on"]["on"] is True  # leave manual action intact


def gradient_fixture(app, pool):
    original = {
        "points": [
            {"color": {"xy": dict(GREEN)}},
            {"color": {"xy": dict(BLUE)}},
        ],
        "mode": "interpolated_palette",
    }
    pool.data[DOWN]["gradient"] = {
        **deepcopy(original),
        "points_capable": 5,
        "mode_values": ["interpolated_palette", "segmented_palette"],
        "pixel_count": 10,
    }
    return original


def test_gradient_reminder_uses_multiple_colours_and_restores_original(tmp_path):
    app, pool = make_app(tmp_path)
    original = gradient_fixture(app, pool)
    app.run(at("2026-11-10T18:00"))
    assert pool.data[DOWN]["on"]["on"] is True
    assert pool.data[UP]["on"]["on"] is True
    assert pool.data[DOWN]["gradient"]["mode"] == "segmented_palette"
    assert pool.data[DOWN]["gradient"]["points"] == [
        {"color": {"xy": ORANGE}}, {"color": {"xy": BLUE}}
    ]
    assert pool.data[UP]["color"]["xy"] == ORANGE
    assert pool.data[DOWN]["dimming"]["brightness"] == 37.0
    assert "applied_gradient" in app.state["lights"][DOWN]
    assert "applied_xy" not in app.state["lights"][DOWN]
    assert "applied_xy" in app.state["lights"][UP]
    before = len(pool.changes)
    app.run(at("2026-11-10T19:00"))
    assert len(pool.changes) == before
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[UP]["on"]["on"] is False
    assert pool.data[DOWN]["gradient"]["mode"] == original["mode"]
    assert pool.data[DOWN]["gradient"]["points"] == original["points"]
    assert app.state["lights"] == {}


def test_manual_gradient_override_is_not_restored(tmp_path):
    app, pool = make_app(tmp_path)
    gradient_fixture(app, pool)
    app.run(at("2026-11-10T18:00"))
    pool.data[DOWN]["gradient"]["points"][1]["color"]["xy"] = dict(GREEN)
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is True
    assert pool.data[DOWN]["gradient"]["points"][1]["color"]["xy"] == GREEN


def test_gradient_honours_priority_mode(tmp_path):
    app, pool = make_app(tmp_path, mode="priority")
    gradient_fixture(app, pool)
    app.run(at("2026-11-10T18:00"))
    applied = dict(pool.changes)[DOWN]
    assert applied == {"color": {"xy": ORANGE}, "on": {"on": True}}
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is False


def test_signe_always_gradient_even_when_global_mode_is_priority(tmp_path):
    app, pool = make_app(tmp_path, mode="priority")
    original = gradient_fixture(app, pool)
    app.config["hue"]["lights"][0]["always_gradient"] = True
    app.run(at("2026-11-10T18:00"))
    applied = dict(pool.changes)[DOWN]
    assert applied["gradient"]["mode"] == "segmented_palette"
    assert applied["gradient"]["points"] == [
        {"color": {"xy": ORANGE}}, {"color": {"xy": BLUE}}
    ]
    # Other (non-gradient or non-overridden) indicator remains priority colour.
    assert dict(pool.changes)[UP]["color"]["xy"] == ORANGE
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["gradient"]["points"] == original["points"]
    assert pool.data[DOWN]["gradient"]["mode"] == original["mode"]


def test_gradient_without_advertised_capacity_falls_back_to_solid(tmp_path):
    app, pool = make_app(tmp_path)
    gradient_fixture(app, pool)
    pool.data[DOWN]["gradient"].pop("points_capable")
    app.run(at("2026-11-10T18:00"))
    assert "color" in dict(pool.changes)[DOWN]
    assert "gradient" not in dict(pool.changes)[DOWN]


def test_idempotent_and_manual_override_on_one_bridge(tmp_path):
    app, pool = make_app(tmp_path, mode="priority")
    app.run(at("2026-11-10T18:00"))
    app.run(at("2026-11-10T19:00"))
    assert len(pool.changes) == 2
    pool.data[DOWN]["color"]["xy"] = GREEN
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["color"]["xy"] == GREEN
    assert pool.data[UP]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert len(pool.changes) == 3


def test_dry_run_does_not_modify_any_bridge(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"), dry_run=True)
    assert pool.changes == []
    assert not app.state_path.exists()


def test_color_temperature_restoration(tmp_path):
    app, pool = make_app(tmp_path, mode="priority")
    pool.data[DOWN]["color_temperature"] = {"mirek": 280, "mirek_valid": True}
    app.run(at("2026-11-10T18:00"))
    app.run(at("2026-11-11T09:00"))
    assert (
        DOWN, {
            "on": {"on": False},
            "dimming": {"brightness": 37.0},
            "color_temperature": {"mirek": 280},
        }
    ) in pool.changes


def test_xy_comparison_tolerance():
    assert same_xy(BLUE, {"x": 0.171, "y": 0.079})
    assert not same_xy(BLUE, GREEN)
    assert not same_xy(BLUE, None)


def test_config_validation_and_same_id_on_different_bridges(tmp_path):
    config = deepcopy(CONFIG)
    config["hue"]["lights"][1]["id"] = "light-a"
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(config), encoding="utf-8")
    loaded = load_config(file)
    assert loaded["hue"]["lights"][0]["id"] == loaded["hue"]["lights"][1]["id"]
    assert loaded["hue"]["bridges"]["upstairs"]["host"] == "192.168.1.21"
    config["hue"]["lights"][1]["bridge"] = "downstairs"
    file.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(BindicatorError, match="Duplicate"):
        load_config(file)


def test_unknown_bridge_rejected(tmp_path):
    bad = deepcopy(CONFIG)
    bad["hue"]["lights"][0]["bridge"] = "unknown"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(BindicatorError, match="unknown Hue Bridge"):
        load_config(path)


def test_legacy_single_bridge_config_and_key(monkeypatch, tmp_path):
    legacy = deepcopy(CONFIG)
    legacy["hue"] = {
        "bridge": "192.168.1.10",
        "lights": ["light-a"],
        "mode": "priority",
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(legacy), encoding="utf-8")
    loaded = load_config(path)
    assert loaded["hue"]["lights"] == [{"bridge": "default", "id": "light-a"}]
    monkeypatch.setenv("BINDICATOR_HUE_KEY", "old-secret")
    pool = BridgePool(loaded["hue"])
    assert pool.client("default").key == "old-secret"


def test_separate_keys_and_clients_for_each_bridge(monkeypatch):
    config = deepcopy(CONFIG["hue"])
    normalize_hue_config(config)
    monkeypatch.setenv("BINDICATOR_HUE_KEY_DOWNSTAIRS", "key-a")
    monkeypatch.setenv("BINDICATOR_HUE_KEY_UPSTAIRS", "key-b")
    pool = BridgePool(config)
    assert pool.client("downstairs").base == "https://192.168.1.20"
    assert pool.client("downstairs").key == "key-a"
    assert pool.client("upstairs").base == "https://192.168.1.21"
    assert pool.client("upstairs").key == "key-b"
    assert light_key("downstairs", "light-a") == DOWN


def test_old_state_migrates_if_original_bridge_known(tmp_path):
    config = deepcopy(CONFIG)
    config["hue"]["legacy_bridge"] = "downstairs"
    old = {"date": "2026-11-11", "lights": {
        "light-a": {"original": {"color": {"xy": BLUE}}, "applied_xy": ORANGE}
    }}
    (tmp_path / "state.json").write_text(json.dumps(old), encoding="utf-8")
    app = Bindicator(config, tmp_path, FakePool())
    assert DOWN in app.state["lights"]
    assert "light-a" not in app.state["lights"]
    assert DOWN in json.loads((tmp_path / "state.json").read_text())["lights"]


def test_ambiguous_old_state_refuses_to_guess_bridge(tmp_path):
    old = {"date": "2026-11-11", "lights": {
        "light-a": {"original": {"color": {"xy": BLUE}}, "applied_xy": ORANGE}
    }}
    (tmp_path / "state.json").write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(BindicatorError, match="legacy_bridge"):
        Bindicator(deepcopy(CONFIG), tmp_path, FakePool())


def test_bridge_failure_keeps_partial_state_and_recovers(tmp_path):
    app, pool = make_app(tmp_path)
    pool.unavailable.add(UP)
    with pytest.raises(BindicatorError, match="unreachable"):
        app.run(at("2026-11-10T18:00"))
    assert list(app.state["lights"]) == [DOWN]
    assert len(pool.changes) == 1
    pool.unavailable.clear()
    app.run(at("2026-11-10T19:00"))
    assert list(app.state["lights"]) == [DOWN, UP]
    assert len(pool.changes) == 2
    app.run(at("2026-11-11T09:00"))
    assert app.state["lights"] == {}
    assert len(pool.changes) == 4


def test_restore_failure_retries_other_bridge_later(tmp_path):
    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    pool.unavailable.add(UP)
    with pytest.raises(BindicatorError, match="will retry"):
        app.run(at("2026-11-11T09:00"))
    assert list(app.state["lights"]) == [UP]
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    pool.unavailable.clear()
    app.run(at("2026-11-11T10:00"))
    assert app.state["lights"] == {}


def test_list_lights_all_bridges(monkeypatch, capsys, tmp_path):
    import sys
    import bindicator.cli as cli

    monkeypatch.setenv("BINDICATOR_HUE_KEY_DOWNSTAIRS", "key-a")
    monkeypatch.setenv("BINDICATOR_HUE_KEY_UPSTAIRS", "key-b")
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    secrets = tmp_path / "secrets.env"
    monkeypatch.setattr(
        cli.BridgePool, "lights",
        lambda self, name: [{
            "id": f"{name}-uuid",
            "metadata": {"name": f"{name} lamp"},
            "on": {"on": False},
            "color": {"xy": BLUE},
        }],
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(conf), "--secrets-file",
        str(secrets), "--list-lights"
    ])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "[downstairs]" in out
    assert "[upstairs]" in out
    assert "downstairs-uuid" in out
    assert "upstairs-uuid" in out


def test_list_lights_filters_single_bridge(monkeypatch, capsys, tmp_path):
    import sys
    import bindicator.cli as cli

    monkeypatch.setenv("BINDICATOR_HUE_KEY_UPSTAIRS", "key-b")
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    monkeypatch.setattr(cli.BridgePool, "lights", lambda self, name: [])
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(conf), "--secrets-file",
        str(tmp_path / "missing"), "--list-lights", "--bridge", "upstairs"
    ])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "[upstairs]" in out
    assert "[downstairs]" not in out


def test_pair_retries_link_button_error_until_success(monkeypatch):
    from bindicator.app import Hue

    hue = Hue("192.168.1.20", None)
    responses = iter([
        [{"error": {"type": 101, "description": "link button not pressed"}}],
        [{"success": {"username": "new-private-key"}}],
    ])
    calls = []

    def fake_request(method, path, payload):
        calls.append((method, path, payload))
        return next(responses)

    monkeypatch.setattr(hue, "request", fake_request)
    monkeypatch.setattr("bindicator.app.clock.sleep", lambda _: None)
    assert hue.pair(timeout_seconds=10) == "new-private-key"
    assert len(calls) == 2
    assert all(method == "POST" and path == "/api" for method, path, _ in calls)
    assert all(payload == {"devicetype": "bindicator#mrlazy"} for _, _, payload in calls)


def test_pair_fails_immediately_for_unrelated_bridge_errors(monkeypatch):
    from bindicator.app import Hue

    hue = Hue("192.168.1.21", None)
    calls = []

    def fake_request(method, path, payload):
        calls.append((method, path, payload))
        return [{"error": {"type": 7, "description": "invalid value"}}]

    monkeypatch.setattr(hue, "request", fake_request)
    with pytest.raises(BindicatorError, match="invalid value"):
        hue.pair(timeout_seconds=10)
    assert len(calls) == 1


def test_pair_times_out_waiting_for_bridge_button(monkeypatch):
    from bindicator.app import Hue

    hue = Hue("192.168.1.20", None)
    monkeypatch.setattr(
        hue, "request", lambda *args: [
            {"error": {"type": 101, "description": "link button not pressed"}}
        ],
    )
    elapsed = iter([100.0, 100.6])
    monkeypatch.setattr("bindicator.app.clock.monotonic", lambda: next(elapsed))
    monkeypatch.setattr("bindicator.app.clock.sleep", lambda _: None)
    with pytest.raises(BindicatorError, match="timed out"):
        hue.pair(timeout_seconds=0.5)


def test_list_lights_skips_unpaired_bridge_without_error(monkeypatch, capsys, tmp_path):
    import sys
    import bindicator.cli as cli

    monkeypatch.setenv("BINDICATOR_HUE_KEY_DOWNSTAIRS", "key-a")
    monkeypatch.delenv("BINDICATOR_HUE_KEY_UPSTAIRS", raising=False)
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    calls = []

    def fake_lights(self, name):
        calls.append(name)
        if name != "downstairs":
            raise AssertionError("Must not contact unpaired Bridge")
        return [{"id": "light-a", "metadata": {"name": "Desk Lamp"},
                 "on": {"on": True}, "color": {"xy": BLUE}}]

    monkeypatch.setattr(cli.BridgePool, "lights", fake_lights)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(conf),
        "--secrets-file", str(tmp_path / "missing"), "--list-lights"
    ])
    assert cli.main() == 0
    result = capsys.readouterr()
    assert "Desk Lamp" in result.out
    assert "[upstairs]" in result.out
    assert "Not paired" in result.out
    assert "ERROR" not in result.err
    assert calls == ["downstairs"]


def test_list_lights_all_unpaired_returns_success(monkeypatch, capsys, tmp_path):
    import sys
    import bindicator.cli as cli

    monkeypatch.delenv("BINDICATOR_HUE_KEY_DOWNSTAIRS", raising=False)
    monkeypatch.delenv("BINDICATOR_HUE_KEY_UPSTAIRS", raising=False)
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    monkeypatch.setattr(
        cli.BridgePool, "lights",
        lambda self, name: (_ for _ in ()).throw(
            AssertionError("Unpaired Bridge must not be contacted")
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(conf),
        "--secrets-file", str(tmp_path / "missing"), "--list-lights"
    ])
    assert cli.main() == 0
    result = capsys.readouterr()
    assert result.out.count("Not paired") == 2
    assert not result.err


def test_list_lights_auth_error_still_fails(monkeypatch, capsys, caplog, tmp_path):
    import sys
    import bindicator.cli as cli

    monkeypatch.setenv("BINDICATOR_HUE_KEY_DOWNSTAIRS", "key-a")
    monkeypatch.delenv("BINDICATOR_HUE_KEY_UPSTAIRS", raising=False)
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    def bad_bridge(self, name):
        raise BindicatorError("Fake authentication failure")

    monkeypatch.setattr(cli.BridgePool, "lights", bad_bridge)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(conf),
        "--secrets-file", str(tmp_path / "missing"), "--list-lights"
    ])
    assert cli.main() == 1
    result = capsys.readouterr()
    assert "Not paired" in result.out
    assert "Fake authentication failure" in caplog.text



def test_manual_next_collection_reminder_persists_until_collection_morning(tmp_path):
    from datetime import date

    app, pool = make_app(tmp_path)
    target_date = date(2026, 11, 17)
    app.apply_collections(target_date, ["orange", "green"], manual=True)
    assert app.state["manual_until"] == "2026-11-17"
    assert app.state["date"] == "2026-11-17"
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    assert pool.data[UP]["color"]["xy"] == ORANGE
    assert pool.data[DOWN]["on"]["on"] is True
    count = len(pool.changes)

    # Emulates an ordinary 18:00 check, a next-morning 09:00 check,
    # a reboot, and the real 18:00 check on the eve of the collection.
    app.run(at("2026-11-10T18:00"))
    app.run(at("2026-11-11T09:00"))
    reloaded = Bindicator(app.config, tmp_path, pool)
    reloaded.collections = lambda day: ["orange", "green"]
    reloaded.run(at("2026-11-16T18:00"))
    reloaded.run(at("2026-11-17T08:59"))
    assert len(pool.changes) == count
    assert reloaded.state["manual_until"] == "2026-11-17"

    reloaded.run(at("2026-11-17T09:00"))
    assert reloaded.state["lights"] == {}
    assert "manual_until" not in reloaded.state
    assert reloaded.state["date"] is None
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[UP]["on"]["on"] is False


def test_manual_reminder_respects_scene_changes_at_restore(tmp_path):
    from datetime import date

    app, pool = make_app(tmp_path)
    app.apply_collections(date(2026, 11, 17), ["orange", "green"], manual=True)
    pool.data[DOWN]["color"]["xy"] = dict(GREEN)  # Dinner scene, manual override.
    app.run(at("2026-11-17T09:00"))
    assert pool.data[DOWN]["color"]["xy"] == GREEN
    assert pool.data[DOWN]["on"]["on"] is True
    assert pool.data[UP]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert app.state["lights"] == {}
    assert "manual_until" not in app.state


def test_manual_reminder_must_not_replace_an_existing_reminder(tmp_path):
    from datetime import date

    app, pool = make_app(tmp_path)
    app.run(at("2026-11-10T18:00"))
    before = deepcopy(app.state)
    writes = len(pool.changes)
    with pytest.raises(BindicatorError, match="already active"):
        app.apply_collections(date(2026, 11, 17), ["orange"], manual=True)
    assert app.state == before
    assert len(pool.changes) == writes


def test_manual_reminder_pause_resume_does_not_restore_until_due(tmp_path):
    from datetime import date
    from bindicator.controls import set_paused

    app, pool = make_app(tmp_path)
    app.apply_collections(date(2026, 11, 17), ["orange", "green"], manual=True)
    before = len(pool.changes)
    set_paused(tmp_path, True)
    app.run(at("2026-11-17T09:00"))
    assert len(pool.changes) == before
    assert app.state["manual_until"] == "2026-11-17"
    set_paused(tmp_path, False)
    app.run(at("2026-11-17T12:00"))
    assert len(pool.changes) == before + 2
    assert "manual_until" not in app.state


def test_manual_gradient_reminder_restores_gradient_at_due_time(tmp_path):
    from datetime import date

    app, pool = make_app(tmp_path)
    original = gradient_fixture(app, pool)
    app.apply_collections(date(2026, 11, 17), ["orange", "blue"], manual=True)
    assert pool.data[DOWN]["gradient"]["mode"] == "segmented_palette"
    app.run(at("2026-11-16T18:00"))
    assert pool.data[DOWN]["gradient"]["mode"] == "segmented_palette"
    app.run(at("2026-11-17T09:00"))
    assert pool.data[DOWN]["gradient"]["mode"] == original["mode"]
    assert pool.data[DOWN]["gradient"]["points"] == original["points"]
    assert pool.data[DOWN]["on"]["on"] is False


def test_cycle_rotates_once_per_minute_and_restores_original_lights(tmp_path):
    app, pool = make_app(tmp_path, mode="cycle")
    app.run(at("2026-11-10T18:00"))
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    assert pool.data[UP]["color"]["xy"] == ORANGE
    assert app.state["active_colours"] == ["orange", "blue"]
    app.run(at("2026-11-10T18:00:30"))
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    app.run(at("2026-11-10T18:01"))
    assert pool.data[DOWN]["color"]["xy"] == BLUE
    assert pool.data[UP]["color"]["xy"] == BLUE
    app.run(at("2026-11-10T18:02"))
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[UP]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert not app.state.get("cycle_started")
    assert not app.state.get("active_colours")


def test_cycle_respects_manual_override(tmp_path):
    app, pool = make_app(tmp_path, mode="cycle")
    app.run(at("2026-11-10T18:00"))
    pool.data[DOWN]["color"]["xy"] = {"x": 0.4, "y": 0.4}
    app.run(at("2026-11-10T18:01"))
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.4, "y": 0.4}
    assert pool.data[UP]["color"]["xy"] == BLUE
