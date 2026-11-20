"""Interactive config editing tests; no Hue devices needed."""
from __future__ import annotations

import os
import stat
from copy import deepcopy

import pytest
from ruamel.yaml import YAML

from bindicator.app import BindicatorError, load_config
from bindicator.light_selection import (
    configure_lights, light_capability_label, parse_choice, write_selected_config,
)

SAMPLE = """# preserve this first comment
calendar:
  events:
    "BinDay - Recycling": blue
hue:
  bridges:
    office:
      host: "192.168.1.180" # keep this address
    house:
      host: "192.168.1.197"
  lights: [] # indicator lamps
  mode: spread
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
"""


class FakeBridgePool:
    bridges = {
        "office": {"host": "192.168.1.180"},
        "house": {"host": "192.168.1.197"},
    }
    names = ["office", "house"]

    def __init__(self, office_paired=True, house_paired=False, failure=None):
        self.paired = {"office": office_paired, "house": house_paired}
        self.failure = failure
        self.calls = []

    def has_key(self, name):
        return self.paired[name]

    def lights(self, name):
        self.calls.append(name)
        if name == self.failure:
            raise BindicatorError("Unable to reach paired bridge")
        if name == "office":
            return [
                {"id": "aaa", "metadata": {"name": "Desk Lamp"}, "color": {}},
                {"id": "bbb", "metadata": {"name": "Floor Lamp"}, "color": {}},
                {"id": "ccc", "metadata": {"name": "White bulb"}},
            ]
        return [{"id": "ddd", "metadata": {"name": "House Hall"}, "color": {}}]


def make_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    path.chmod(0o640)
    return path


def test_parse_choice():
    assert parse_choice("1, 2,1", 3) == [0, 1]
    assert parse_choice("none", 3) == []
    assert parse_choice("", 3) is None
    with pytest.raises(BindicatorError, match="not in the list"):
        parse_choice("5", 3)
    with pytest.raises(BindicatorError):
        parse_choice("1;2", 3)
    with pytest.raises(KeyboardInterrupt):
        parse_choice("q", 3)


def test_roundtrip_edit_preserves_comments_other_settings_and_permissions(tmp_path):
    path = make_config(tmp_path)
    before = path.stat()
    chosen = [{"bridge": "office", "id": "aaa"}, {"bridge": "house", "id": "ddd"}]
    write_selected_config(path, chosen)
    content = path.read_text(encoding="utf-8")
    assert "# preserve this first comment" in content
    assert "# keep this address" in content
    assert '192.168.1.180' in content
    assert 'BinDay - Recycling' in content
    parsed = load_config(path)
    assert parsed["hue"]["lights"] == chosen
    after = path.stat()
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)


def test_interactive_selects_two_office_lights_with_unpaired_house(tmp_path):
    path = make_config(tmp_path)
    prompts = iter(["2,1", "yes"])
    pool = FakeBridgePool()
    assert configure_lights(
        pool, load_config(path), path, prompt=lambda _message: next(prompts)
    )
    assert load_config(path)["hue"]["lights"] == [
        {"bridge": "office", "id": "bbb"},
        {"bridge": "office", "id": "aaa"},
    ]
    assert pool.calls == ["office"]


def test_interactive_retains_selected_house_lamp_when_unpaired(tmp_path):
    path = make_config(tmp_path)
    write_selected_config(path, [{"bridge": "house", "id": "ddd"}])
    prompts = iter(["1", "y"])
    assert configure_lights(
        FakeBridgePool(), load_config(path), path, prompt=lambda _: next(prompts)
    )
    assert load_config(path)["hue"]["lights"] == [
        {"bridge": "office", "id": "aaa"},
        {"bridge": "house", "id": "ddd"},
    ]


def test_empty_input_keeps_original_file_untouched(tmp_path):
    path = make_config(tmp_path)
    original = path.read_bytes()
    assert not configure_lights(
        FakeBridgePool(), load_config(path), path, prompt=lambda _: ""
    )
    assert path.read_bytes() == original


def test_cancel_does_not_write(tmp_path):
    path = make_config(tmp_path)
    original = path.read_bytes()
    assert not configure_lights(
        FakeBridgePool(), load_config(path), path, prompt=lambda _: "q"
    )
    assert path.read_bytes() == original


def test_failing_paired_bridge_aborts_without_writing(tmp_path):
    path = make_config(tmp_path)
    original = path.read_bytes()
    with pytest.raises(BindicatorError, match="Configuration was not changed"):
        configure_lights(
            FakeBridgePool(house_paired=True, failure="house"),
            load_config(path), path,
        )
    assert path.read_bytes() == original


def test_noninteractive_bridge_is_not_touched_when_not_paired(tmp_path):
    path = make_config(tmp_path)
    pool = FakeBridgePool(office_paired=False, house_paired=True)
    prompts = iter(["1", "y"])
    assert configure_lights(
        pool, load_config(path), path, prompt=lambda _: next(prompts)
    )
    assert pool.calls == ["house"]
    assert load_config(path)["hue"]["lights"] == [{"bridge": "house", "id": "ddd"}]


def test_gradient_capabilities_displayed_from_live_bridge_api():
    gradient = {
        "id": "signe",
        "metadata": {"name": "Signe Gradient Floor"},
        "color": {},
        "gradient": {
            "points_capable": 5,
            "mode_values": ["interpolated_palette", "segmented_palette"],
            "pixel_count": 10,
        },
    }
    label = light_capability_label(gradient)
    assert label == "gradient, up to 5 colours, segmented, 10 pixels"
    assert light_capability_label({"color": {}}) == "colour"
    assert light_capability_label({"on": {"on": True}}) == "no colour control"
    assert "limit not reported" in light_capability_label({"gradient": {}})


def test_setup_marks_gradient_lamp_and_keeps_standard_config_shape(
    monkeypatch, tmp_path, capsys,
):
    path = make_config(tmp_path)
    pool = FakeBridgePool()

    original_lights = pool.lights
    def gradient_lights(name):
        if name != "office":
            return original_lights(name)
        return original_lights(name) + [{
            "id": "signe", "metadata": {"name": "Signe Gradient Floor"},
            "color": {},
            "gradient": {
                "points_capable": 5,
                "mode_values": ["interpolated_palette", "segmented_palette"],
                "pixel_count": 10,
            },
        }]

    monkeypatch.setattr(pool, "lights", gradient_lights)
    prompts = iter(["3", "yes"])
    assert configure_lights(
        pool, load_config(path), path, prompt=lambda _: next(prompts)
    )
    assert load_config(path)["hue"]["lights"] == [
        {"bridge": "office", "id": "signe"}
    ]
    output = capsys.readouterr().out
    assert "Signe Gradient Floor" in output
    assert "gradient, up to 5 colours, segmented, 10 pixels" in output


def test_gradient_only_lamp_can_be_selected(tmp_path):
    path = make_config(tmp_path)
    pool = FakeBridgePool()
    pool.lights = lambda name: ([{
        "id": "gradient-only",
        "metadata": {"name": "Gradient Only"},
        "gradient": {"points_capable": 3},
    }] if name == "office" else [])
    prompts = iter(["1", "y"])
    assert configure_lights(pool, load_config(path), path, prompt=lambda _: next(prompts))
    assert load_config(path)["hue"]["lights"][0]["id"] == "gradient-only"
