"""Hue v2 state-snapshot and restoration regression tests, offline."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import date

import pytest

from bindicator.app import (
    Bindicator, BindicatorError, snapshot_light_state,
)
from bindicator.bin_preview import preview_lights
from test_bindicator import (
    BLUE, DOWN, GREEN, ORANGE, UP, FakePool, at, gradient_fixture, make_app,
)
from test_bin_preview import CONFIG as PREVIEW_CONFIG, FakePool as PreviewPool


def test_snapshot_is_persisted_before_any_hue_write(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["dimming"]["brightness"] = 24.5
    original_set = pool.set
    seen = []

    def check_saved_before_set(rid, payload):
        saved = json.loads(app.state_path.read_text())
        record = saved["lights"][rid]
        assert record["original_state"] == {
            "on": {"on": False},
            "dimming": {"brightness": 24.5 if rid == DOWN else 37.0},
            "color": {"xy": {"x": 0.33, "y": 0.33}},
        }
        assert record["original_on"] is False
        assert record["applied_xy"] == ORANGE
        seen.append(rid)
        original_set(rid, payload)

    pool.set = check_saved_before_set
    app.run(at("2026-11-10T18:00"))
    assert seen == [DOWN, UP]
    assert pool.data[DOWN]["dimming"]["brightness"] == 24.5
    app.run(at("2026-11-11T09:00"))
    assert not app.state["lights"]
    assert pool.data[DOWN]["dimming"]["brightness"] == 24.5


def test_full_state_restoration_preserves_on_and_off_brightness(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["on"]["on"] = True
    pool.data[DOWN]["dimming"]["brightness"] = 18.4
    pool.data[UP]["dimming"]["brightness"] = 74.2

    app.run(at("2026-11-10T18:00"))
    assert app.state["lights"][DOWN]["original_state"]["dimming"] == {
        "brightness": 18.4
    }
    assert app.state["lights"][UP]["original_state"]["on"] == {"on": False}

    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is True
    assert pool.data[UP]["on"]["on"] is False
    assert pool.data[DOWN]["dimming"]["brightness"] == 18.4
    assert pool.data[UP]["dimming"]["brightness"] == 74.2
    restores = pool.changes[-2:]
    assert (DOWN, {
        "on": {"on": True},
        "dimming": {"brightness": 18.4},
        "color": {"xy": {"x": 0.33, "y": 0.33}},
    }) in restores
    assert (UP, {
        "on": {"on": False},
        "dimming": {"brightness": 74.2},
        "color": {"xy": {"x": 0.33, "y": 0.33}},
    }) in restores


def test_lost_put_acknowledgement_still_allows_restoration(tmp_path):
    app, pool = make_app(tmp_path)
    original_set = pool.set

    def applied_but_connection_failed(rid, payload):
        original_set(rid, payload)
        if rid == DOWN:
            raise BindicatorError("Acknowledgement was lost")

    pool.set = applied_but_connection_failed
    with pytest.raises(BindicatorError, match="Acknowledgement"):
        app.run(at("2026-11-10T18:00"))
    record = json.loads(app.state_path.read_text())["lights"][DOWN]
    assert record["original_state"]["on"] == {"on": False}
    assert record["original_state"]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[DOWN]["color"]["xy"] == ORANGE

    # Another CLI process can load the snapshot after a crash.
    pool.set = original_set
    recovered = Bindicator(app.config, tmp_path, pool)
    recovered.restore()
    assert recovered.state["lights"] == {}
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[DOWN]["on"]["on"] is False


def test_manual_brightness_change_is_not_overwritten(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["on"]["on"] = True
    app.run(at("2026-11-10T18:00"))
    count = len(pool.changes)
    pool.data[DOWN]["dimming"]["brightness"] = 69.0
    app.run(at("2026-11-11T09:00"))

    assert all(rid != DOWN for rid, _ in pool.changes[count:])
    assert pool.data[DOWN]["dimming"]["brightness"] == 69.0
    assert pool.data[DOWN]["color"]["xy"] == ORANGE
    assert pool.data[UP]["on"]["on"] is False
    assert app.state["lights"] == {}


def test_dynamic_scene_and_entertainment_not_destroyed(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["dynamics"] = {
        "status": "dynamic_palette",
        "speed_valid": True, "speed": 0.5,
    }
    app.run(at("2026-11-10T18:00"))
    assert all(rid != DOWN for rid, _ in pool.changes)
    assert DOWN not in app.state["lights"]
    assert pool.data[DOWN]["dynamics"]["status"] == "dynamic_palette"
    assert pool.data[UP]["color"]["xy"] == ORANGE

    another, other_pool = make_app(tmp_path / "stream")
    other_pool.data[DOWN]["mode"] = "streaming"
    another.run(at("2026-11-10T18:00"))
    assert all(rid != DOWN for rid, _ in other_pool.changes)
    assert other_pool.data[UP]["color"]["xy"] == ORANGE


def test_live_builtin_effect_snapshot_and_restore(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["on"]["on"] = True
    pool.data[DOWN]["dimming"]["brightness"] = 61.5
    pool.data[DOWN]["effects_v2"] = {
        "status": {"effect": "candle", "parameters": {
            "speed": 0.45,
            "color": {"xy": {"x": 0.31, "y": 0.41}},
        }},
        "action": {"effect_values": ["no_effect", "candle"]},
    }
    original_set = pool.set

    def emulate_effects_response(rid, payload):
        original_set(rid, payload)
        if rid == DOWN and "effects_v2" in payload:
            effect = payload["effects_v2"]["action"]["effect"]
            pool.data[DOWN]["effects_v2"]["status"] = {
                "effect": effect,
                "parameters": deepcopy(
                    payload["effects_v2"]["action"].get("parameters", {})
                ),
            }

    pool.set = emulate_effects_response
    app.run(at("2026-11-10T18:00"))
    first = dict(pool.changes)[DOWN]
    assert first["effects_v2"] == {"action": {"effect": "no_effect"}}
    assert app.state["lights"][DOWN]["original_state"]["effects_v2"] == {
        "action": {
            "effect": "candle",
            "parameters": {
                "speed": 0.45,
                "color": {"xy": {"x": 0.31, "y": 0.41}},
            },
        }
    }
    assert pool.data[DOWN]["effects_v2"]["status"]["effect"] == "no_effect"

    app.run(at("2026-11-11T09:00"))
    restored = [payload for rid, payload in pool.changes if rid == DOWN][-1]
    assert restored["effects_v2"]["action"]["effect"] == "candle"
    assert restored["dimming"] == {"brightness": 61.5}
    assert restored["on"] == {"on": True}


def test_timed_effect_is_skipped_if_not_reconstructible(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["timed_effects"] = {"status": "sunrise", "duration": 120000}
    app.run(at("2026-11-10T18:00"))
    assert all(rid != DOWN for rid, _ in pool.changes)
    assert pool.data[DOWN]["timed_effects"]["status"] == "sunrise"


def test_gradient_restored_with_original_brightness(tmp_path):
    app, pool = make_app(tmp_path)
    original = gradient_fixture(app, pool)
    pool.data[DOWN]["dimming"]["brightness"] = 14.7
    app.apply_collections(date(2026, 11, 17), ["orange", "green"], manual=True)
    saved = app.state["lights"][DOWN]["original_state"]
    assert saved["gradient"] == original
    assert saved["dimming"] == {"brightness": 14.7}
    app.restore()
    assert pool.data[DOWN]["gradient"]["points"] == original["points"]
    assert pool.data[DOWN]["dimming"]["brightness"] == 14.7


def test_preview_saves_full_snapshot_in_memory_and_restores_brightness():
    pool = PreviewPool()
    pool.data["office/desk-uuid"]["dimming"]["brightness"] = 44.1
    seen = []

    def during(seconds):
        seen.append(seconds)
        assert pool.data["office/desk-uuid"]["on"]["on"] is True

    preview_lights(pool, PREVIEW_CONFIG, ["blue"], seconds=2, sleeper=during)
    assert seen == [2]
    restored = [
        payload for rid, payload in pool.writes if rid == "office/desk-uuid"
    ][-1]
    assert restored == {
        "on": {"on": False},
        "dimming": {"brightness": 44.1},
        "color": {"xy": {"x": 0.33, "y": 0.33}},
    }


def test_preview_respects_manual_brightness_override():
    pool = PreviewPool()
    def during(seconds):
        pool.data["office/desk-uuid"]["dimming"]["brightness"] = 71.0

    preview_lights(pool, PREVIEW_CONFIG, ["blue"], seconds=2, sleeper=during)
    assert pool.data["office/desk-uuid"]["color"]["xy"] == BLUE
    assert pool.data["office/desk-uuid"]["dimming"]["brightness"] == 71.0


def test_snapshot_omits_readonly_hue_fields():
    live = {
        "id": "some-uuid", "metadata": {"name": "Private lamp"},
        "on": {"on": True}, "dimming": {
            "brightness": 50.5, "min_dim_level": 0.2,
        }, "color": {
            "xy": {"x": 0.23, "y": 0.32},
            "gamut": {"red": {"x": 0.7, "y": 0.3}},
        },
        "owner": {"rid": "device-id", "rtype": "device"},
        "color_temperature": {"mirek": None, "mirek_valid": False},
    }
    assert snapshot_light_state(live) == {
        "on": {"on": True},
        "dimming": {"brightness": 50.5},
        "color": {"xy": {"x": 0.23, "y": 0.32}},
    }



def test_legacy_hue_effect_get_status_maps_to_writable_effect():
    lamp = {
        "on": {"on": True},
        "dimming": {"brightness": 64.0},
        "color": {"xy": {"x": 0.31, "y": 0.41}},
        "effects": {
            "status": "prism",
            "effect_values": ["no_effect", "prism"],
        },
    }
    assert snapshot_light_state(lamp) == {
        "on": {"on": True},
        "dimming": {"brightness": 64.0},
        "effects": {"effect": "prism"},
    }


def test_preview_skips_nonrestorable_dynamic_light_but_previews_others():
    pool = PreviewPool()
    pool.data["office/desk-uuid"]["dynamics"] = {
        "status": "dynamic_palette",
        "speed": 0.2,
        "speed_valid": True,
    }

    def during(seconds):
        assert pool.data["office/desk-uuid"]["on"]["on"] is False
        assert pool.data["house/hall-uuid"]["on"]["on"] is True

    preview_lights(pool, PREVIEW_CONFIG, ["orange"], seconds=3, sleeper=during)
    assert all(rid != "office/desk-uuid" for rid, _ in pool.writes)
    assert pool.data["office/desk-uuid"]["dynamics"]["status"] == "dynamic_palette"
    assert pool.data["house/hall-uuid"]["on"]["on"] is False


def test_manually_turned_off_lamp_not_switched_on_by_restore(tmp_path):
    app, pool = make_app(tmp_path)
    pool.data[DOWN]["on"]["on"] = True
    app.run(at("2026-11-10T18:00"))
    pool.data[DOWN]["on"]["on"] = False
    pool.data[DOWN]["dimming"]["brightness"] = 1.0  # Hue may report a low dim when off.
    app.run(at("2026-11-11T09:00"))
    assert pool.data[DOWN]["on"]["on"] is False
    assert pool.data[DOWN]["color"]["xy"] == {"x": 0.33, "y": 0.33}
    assert pool.data[DOWN]["dimming"]["brightness"] == 37.0
