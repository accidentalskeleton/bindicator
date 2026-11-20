"""First-run wizard works without any preconfigured Hue Bridge or IP address."""
from __future__ import annotations

import json
import stat

import pytest

from bindicator.app import BindicatorError, Hue, load_config
from bindicator.bridges import BridgePool
from bindicator.setup import guided_setup


BASE = """# Preserve the user's bin collection settings
calendar:
  events:
    "BinDay - Recycling": blue
hue:
  bridges: {}
  lights: []
  mode: spread
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
"""

BRIDGES = [
    {"host": "192.168.1.180", "id": "001788AAAABBBBCC", "name": "Philips Hue 1", "source": "mDNS"},
    {"host": "192.168.1.197", "id": "001788DDDDEEEEFF", "name": "Philips Hue 2", "source": "mDNS"},
]


def make_files(tmp_path, config_text=BASE):
    config = tmp_path / "config.yaml"
    config.write_text(config_text, encoding="utf-8")
    config.chmod(0o640)
    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        'BINDICATOR_ICAL_URL="https://example.invalid/private-calendar.ics"\n',
        encoding="utf-8",
    )
    secrets.chmod(0o640)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return config, secrets, state_dir


def test_empty_bridges_are_accepted_before_setup(tmp_path):
    config, _, _ = make_files(tmp_path)
    loaded = load_config(config)
    assert loaded["hue"]["bridges"] == {}
    assert loaded["hue"]["lights"] == []


def test_discovery_first_pairs_two_bridges_and_selects_lights(monkeypatch, tmp_path, capsys):
    config, secrets, state_dir = make_files(tmp_path)
    addresses = []

    def pair(self):
        addresses.append(self.base)
        return f"0123456789abcdef{len(addresses):016d}"

    def lights(self, name):
        return [{
            "id": "26584554-24d6-4d4c-bbad-0ac099f243f2" if name == "office" else
                  "881d8bc0-987a-4884-8d97-24efe4742a54",
            "metadata": {"name": "Desk Lamp" if name == "office" else "Hall"},
            "on": {"on": False},
            "color": {"xy": {"x": 0.3, "y": 0.3}},
        }]

    monkeypatch.setattr(Hue, "pair", pair)
    monkeypatch.setattr(BridgePool, "lights", lights)
    # Default selects both discovered Bridges, then we name/pair them.
    # Finally pick both lamps and approve saving selection.
    inputs = iter(["", "office", "y", "house", "y", "1,2", "y"])
    assert guided_setup(
        config, secrets, state_dir,
        prompt=lambda _: next(inputs), discover=lambda: list(BRIDGES),
    )
    expected = load_config(config)
    assert expected["hue"]["bridges"]["office"]["host"] == "192.168.1.180"
    assert expected["hue"]["bridges"]["house"]["host"] == "192.168.1.197"
    assert expected["hue"]["bridges"]["house"]["id"] == "001788DDDDEEEEFF"
    assert expected["hue"]["lights"] == [
        {"bridge": "office", "id": "26584554-24d6-4d4c-bbad-0ac099f243f2"},
        {"bridge": "house", "id": "881d8bc0-987a-4884-8d97-24efe4742a54"},
    ]
    assert addresses == ["https://192.168.1.180", "https://192.168.1.197"]
    text = secrets.read_text()
    assert 'BINDICATOR_HUE_KEY_OFFICE="' in text
    assert 'BINDICATOR_HUE_KEY_HOUSE="' in text
    assert "BINDICATOR_ICAL_URL=" in text
    assert "0123456789abcdef" not in capsys.readouterr().out
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o640
    assert "# Preserve the user's bin collection settings" in config.read_text()


def test_overwrite_existing_manual_bridge_ip_using_saved_hardware_id(monkeypatch, tmp_path):
    config, secrets, state_dir = make_files(
        tmp_path,
        BASE.replace(
            "bridges: {}",
            'bridges:\n    office: {host: "192.168.1.180", id: "001788AAAABBBBCC"}',
        ),
    )
    monkeypatch.setenv("BINDICATOR_HUE_KEY_OFFICE", "0123456789abcdef0123456789abcdef")
    updated = [dict(BRIDGES[0], host="192.168.1.190")]
    paired = []

    def no_pair(self):
        paired.append(self.base)
        return "0123456789abcdef"

    monkeypatch.setattr(Hue, "pair", no_pair)
    inputs = iter([""])
    assert guided_setup(
        config, secrets, state_dir, prompt=lambda _: next(inputs),
        discover=lambda: updated,
        choose_lights=lambda *args, **kwargs: False,
    )
    assert load_config(config)["hue"]["bridges"]["office"]["host"] == "192.168.1.190"
    assert paired == []  # Existing valid application key is reused.


def test_fresh_resets_old_manual_bridge_settings_without_losing_zoho(monkeypatch, tmp_path):
    config, secrets, state_dir = make_files(
        tmp_path,
        BASE.replace(
            "bridges: {}\n  lights: []",
            'bridges:\n    old: {host: "192.168.1.45"}\n'
            '  lights:\n    - {bridge: old, id: "abc"}',
        ),
    )
    old_key = "oldkey0123" + "456789"  # Synthetic fixture, not a live key
    secrets.write_text(
        secrets.read_text() + f'BINDICATOR_HUE_KEY_OLD="{old_key}"\n'
    )
    monkeypatch.setenv("BINDICATOR_HUE_KEY_OLD", "oldkey0123456789")
    monkeypatch.setattr(Hue, "pair", lambda _: "abcdef0123456789abcdef0123456789")
    inputs = iter(["RESET", "", "office", "y"])
    assert guided_setup(
        config, secrets, state_dir, fresh=True,
        prompt=lambda _: next(inputs), discover=lambda: [BRIDGES[0]],
        choose_lights=lambda *args, **kwargs: False,
    )
    actual = load_config(config)
    assert set(actual["hue"]["bridges"]) == {"office"}
    assert actual["hue"]["lights"] == []
    assert actual["calendar"]["events"]["BinDay - Recycling"] == "blue"
    assert "BINDICATOR_HUE_KEY_OLD=" not in secrets.read_text()
    assert "BINDICATOR_HUE_KEY_OFFICE=" in secrets.read_text()
    assert "BINDICATOR_ICAL_URL=" in secrets.read_text()


def test_discovery_unavailable_uses_manual_private_ip_fallback(monkeypatch, tmp_path):
    config, secrets, state_dir = make_files(tmp_path)
    monkeypatch.setattr(Hue, "pair", lambda _: "0123456789abcdef0123456789abcdef")
    inputs = iter(["192.168.1.200", "", "garage", "y"])
    assert guided_setup(
        config, secrets, state_dir,
        prompt=lambda _: next(inputs), discover=lambda: [],
        choose_lights=lambda *args, **kwargs: False,
    )
    assert load_config(config)["hue"]["bridges"]["garage"]["host"] == "192.168.1.200"


def test_cancel_from_empty_config_does_not_change_files(tmp_path):
    config, secrets, state_dir = make_files(tmp_path)
    before = config.read_bytes(), secrets.read_bytes()
    assert not guided_setup(
        config, secrets, state_dir, prompt=lambda _: "", discover=lambda: [],
    )
    assert before == (config.read_bytes(), secrets.read_bytes())


def test_fresh_cancel_leaves_manual_settings_intact(tmp_path):
    config, secrets, state_dir = make_files(tmp_path)
    before = config.read_bytes(), secrets.read_bytes()
    assert not guided_setup(
        config, secrets, state_dir, fresh=True,
        prompt=lambda _: "no", discover=lambda: list(BRIDGES),
    )
    assert before == (config.read_bytes(), secrets.read_bytes())


def test_active_light_state_blocks_routing_change(tmp_path):
    config, secrets, state_dir = make_files(tmp_path)
    (state_dir / "state.json").write_text(
        json.dumps({
            "date": "2026-11-11",
            "lights": {
                "office/uuid": {
                    "applied_xy": {"x": .1, "y": .2},
                    "original": {"color": {"xy": {"x": .3, "y": .4}}},
                }
            },
        })
    )
    with pytest.raises(BindicatorError, match="active bin reminder"):
        guided_setup(
            config, secrets, state_dir,
            prompt=lambda _: "RESET",
            discover=lambda: list(BRIDGES),
            fresh=True,
        )


def test_public_ip_rejected_for_manual_fallback(tmp_path):
    config, secrets, state_dir = make_files(tmp_path)
    with pytest.raises(BindicatorError, match="private LAN"):
        guided_setup(
            config, secrets, state_dir,
            prompt=lambda _: "8.8.8.8", discover=lambda: [],
        )


def test_checked_in_example_has_no_manual_bridge_addresses():
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / "config.example.yaml"
    config = load_config(sample)
    assert config["hue"]["bridges"] == {}
    assert config["hue"]["lights"] == []


def test_cli_setup_routes_to_discovery_wizard(monkeypatch, tmp_path):
    import sys
    import bindicator.cli as cli
    import bindicator.setup as setup

    config, secrets, state_dir = make_files(tmp_path)
    calls = []

    class TTY:
        def isatty(self):
            return True

    def fake_setup(config_path, secrets_path, state_path, **kwargs):
        calls.append((config_path, secrets_path, state_path, kwargs["fresh"]))
        return True

    monkeypatch.setattr(sys, "stdin", TTY())
    monkeypatch.setattr(setup, "guided_setup", fake_setup)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state_dir), "--setup", "--fresh",
    ])
    assert cli.main() == 0
    assert calls == [(config, secrets, state_dir, True)]


def test_reset_removes_exported_hue_keys_not_zoho(monkeypatch, tmp_path):
    from bindicator.setup import _reset_hue_settings

    config, secrets, state_dir = make_files(tmp_path)
    exported_key = "01234567" + "89abcdef"  # Synthetic fixture
    secrets.write_text(
        secrets.read_text()
        + f'export BINDICATOR_HUE_KEY_OLD="{exported_key}"\n'
    )
    _reset_hue_settings(config, secrets)
    result = secrets.read_text()
    assert "BINDICATOR_HUE_KEY_OLD" not in result
    assert "BINDICATOR_ICAL_URL=" in result
