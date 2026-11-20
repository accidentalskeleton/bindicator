"""mDNS Bridge discovery, pairing and safe configuration persistence."""
from __future__ import annotations

import stat

import pytest
from ruamel.yaml import YAML

from bindicator.app import BindicatorError, load_config
from bindicator.bridge_discovery import (
    _HueListener, available_bridges, bridge_name, discover_bridges,
)
from bindicator.bridge_setup import save_bridge_config, save_bridge_key, setup_bridge
from bindicator.bridges import BridgePool


CONFIG_TEXT = """# keep this comment
calendar:
  events:
    "BinDay - Recycling": blue
hue:
  bridges:
    office:
      host: "192.168.1.180"  # original Office Bridge
      verify_tls: false
    house:
      host: "192.168.1.197"
      verify_tls: false
  lights:
    - {bridge: office, id: "26584554-24d6-4d4c-bbad-0ac099f243f2"}
  mode: spread
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
"""


def files(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG_TEXT, encoding="utf-8")
    config.chmod(0o640)
    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        'BINDICATOR_ICAL_URL="https://example.invalid/private.ics"\n'
        'BINDICATOR_HUE_KEY_OFFICE="old-office-key"\n',
        encoding="utf-8",
    )
    secrets.chmod(0o640)
    return config, secrets


def test_mdns_listener_extracts_bridge_id_and_ipv4():
    class Info:
        properties = {b"bridgeid": b"001788FFEEDDCCBB", b"modelid": b"BSB002"}

        def parsed_addresses(self):
            return ["fe80::1", "192.168.1.180"]

    class ZC:
        def get_service_info(self, service_type, name, timeout=1500):
            return Info()

    listener = _HueListener()
    listener.add_service(ZC(), "_hue._tcp.local.", "Philips hue._hue._tcp.local.")
    listener.update_service(ZC(), "_hue._tcp.local.", "Philips hue._hue._tcp.local.")
    assert listener.found == [{
        "host": "192.168.1.180",
        "id": "001788FFEEDDCCBB",
        "name": "Philips hue",
        "source": "mDNS",
    }]


def test_mdns_zero_returns_empty_not_failure(monkeypatch):
    import bindicator.bridge_discovery as mdns

    class ZC:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class Browser:
        def __init__(self, zc, type_, listener):
            assert type_ == "_hue._tcp.local."

        def cancel(self):
            pass

    monkeypatch.setattr(mdns, "Zeroconf", ZC)
    monkeypatch.setattr(mdns, "ServiceBrowser", Browser)
    monkeypatch.setattr(mdns.time, "sleep", lambda _: None)
    assert discover_bridges() == []


def test_discovery_matches_stable_id_after_dhcp_change():
    configured = {
        "office": {"host": "192.168.1.180", "id": "001788ABCDEF1234"},
        "house": {"host": "192.168.1.197", "id": "001788EEEEFF0000"},
    }
    candidate = {
        "host": "192.168.1.190",
        "id": "001788ABCDEF1234",
        "name": "Hue Bridge",
        "source": "mDNS",
    }
    assert bridge_name(candidate, configured) == "office"
    results = available_bridges(configured, [candidate])
    assert results[0]["configured_as"] == "office"
    assert any(item["configured_as"] == "house" for item in results[1:])


def test_save_single_bridge_preserves_calendar_lamps_and_comments(tmp_path):
    path, _ = files(tmp_path)
    original = path.stat()
    save_bridge_config(path, "house", "192.168.1.198", "0017881234567890")
    content = path.read_text()
    assert "# keep this comment" in content
    assert "# original Office Bridge" in content
    assert "26584554-24d6-4d4c-bbad-0ac099f243f2" in content
    config = load_config(path)
    assert config["hue"]["bridges"]["house"]["host"] == "192.168.1.198"
    assert config["hue"]["bridges"]["house"]["id"] == "0017881234567890"
    assert config["hue"]["lights"] == [
        {"bridge": "office", "id": "26584554-24d6-4d4c-bbad-0ac099f243f2"}
    ]
    new_stat = path.stat()
    assert stat.S_IMODE(new_stat.st_mode) == stat.S_IMODE(original.st_mode)
    assert (new_stat.st_uid, new_stat.st_gid) == (original.st_uid, original.st_gid)


def test_save_key_preserves_other_secrets_and_private_permissions(tmp_path):
    _, secret = files(tmp_path)
    save_bridge_key(secret, "house", "abcdef0123456789")
    save_bridge_key(secret, "house", "fedcba9876543210")
    content = secret.read_text()
    expected_house_key = "fedcba98" + "76543210"  # Synthetic fixture, not a Hue key
    assert f'BINDICATOR_HUE_KEY_HOUSE="{expected_house_key}"' in content
    assert content.count("BINDICATOR_HUE_KEY_HOUSE=") == 1
    assert 'BINDICATOR_HUE_KEY_OFFICE="old-office-key"' in content
    assert 'https://example.invalid/private.ics' in content
    assert stat.S_IMODE(secret.stat().st_mode) == 0o640


def test_pair_configured_unpaired_house_and_store_key(monkeypatch, capsys, tmp_path):
    from bindicator.app import Hue

    config, secrets = files(tmp_path)
    monkeypatch.delenv("BINDICATOR_HUE_KEY_HOUSE", raising=False)
    monkeypatch.setenv("BINDICATOR_HUE_KEY_OFFICE", "old-office-key")
    addresses = []

    def pair(self):
        addresses.append(self.base)
        return "0123456789abcdef0123456789abcdef"

    monkeypatch.setattr(Hue, "pair", pair)
    pool = BridgePool(load_config(config)["hue"])
    prompts = iter(["2", "yes"])  # house is configured but unpaired
    assert setup_bridge(
        pool, config, secrets,
        prompt=lambda _: next(prompts), discover=lambda: [],
    )
    assert addresses == ["https://192.168.1.197"]
    paired_key = ("01234567" + "89abcdef") * 2  # Synthetic fixture
    assert f'BINDICATOR_HUE_KEY_HOUSE="{paired_key}"' in secrets.read_text()
    assert load_config(config)["hue"]["bridges"]["house"]["host"] == "192.168.1.197"
    assert "0123456789abcdef" not in capsys.readouterr().out


def test_pair_newly_discovered_bridge_adds_named_mapping(monkeypatch, tmp_path):
    from bindicator.app import Hue

    config, secrets = files(tmp_path)
    monkeypatch.setattr(Hue, "pair", lambda _: "0123456789abcdef0123456789abcdef")
    pool = BridgePool(load_config(config)["hue"])
    discovery = [{
        "host": "192.168.1.222",
        "id": "001788AAAABBBBCC",
        "name": "Hue Bridge 3",
        "source": "mDNS",
    }]
    prompts = iter(["1", "shed", "y"])
    assert setup_bridge(
        pool, config, secrets,
        prompt=lambda _: next(prompts), discover=lambda: discovery,
    )
    updated = load_config(config)
    assert updated["hue"]["bridges"]["shed"] == {
        "host": "192.168.1.222",
        "verify_tls": False,
        "id": "001788AAAABBBBCC",
    }
    assert 'BINDICATOR_HUE_KEY_SHED=' in secrets.read_text()
    assert updated["hue"]["lights"][0]["bridge"] == "office"


def test_pairing_failure_does_not_update_config_or_secrets(monkeypatch, tmp_path):
    from bindicator.app import Hue

    config, secrets = files(tmp_path)
    old_config, old_secrets = config.read_bytes(), secrets.read_bytes()

    def fail(_):
        raise BindicatorError("button not pressed")

    monkeypatch.setattr(Hue, "pair", fail)
    pool = BridgePool(load_config(config)["hue"])
    prompts = iter(["1", "y"])
    with pytest.raises(BindicatorError, match="button not pressed"):
        setup_bridge(
            pool, config, secrets,
            prompt=lambda _: next(prompts), discover=lambda: [],
        )
    assert config.read_bytes() == old_config
    assert secrets.read_bytes() == old_secrets


def test_cancel_setup_does_not_write(tmp_path):
    config, secrets = files(tmp_path)
    old_config, old_secrets = config.read_bytes(), secrets.read_bytes()
    pool = BridgePool(load_config(config)["hue"])
    assert not setup_bridge(
        pool, config, secrets, prompt=lambda _: "", discover=lambda: []
    )
    assert config.read_bytes() == old_config
    assert secrets.read_bytes() == old_secrets


def test_refuse_unrelated_known_bridge_id_with_recycled_ip(tmp_path):
    config, secrets = files(tmp_path)
    save_bridge_config(config, "office", "192.168.1.180", "001788AAAAAAAAAA")
    pool = BridgePool(load_config(config)["hue"])
    discovery = [{
        "host": "192.168.1.180",
        "id": "001788BBBBBBBBBB",
        "name": "Other Bridge",
        "source": "mDNS",
    }]
    prompts = iter(["1", "office"])
    with pytest.raises(BindicatorError, match="different hardware ID"):
        setup_bridge(
            pool, config, secrets,
            prompt=lambda _: next(prompts), discover=lambda: discovery,
        )


def test_sample_secret_placeholder_is_not_treated_as_paired(monkeypatch, tmp_path):
    config, secrets = files(tmp_path)
    monkeypatch.delenv("BINDICATOR_HUE_KEY_HOUSE", raising=False)
    monkeypatch.setenv("BINDICATOR_HUE_KEY_HOUSE", "PASTE_HOUSE_APPLICATION_KEY_HERE")
    pool = BridgePool(load_config(config)["hue"])
    assert pool.has_key("house") is False
    monkeypatch.setenv("BINDICATOR_HUE_KEY_HOUSE", "0123456789abcdef")
    assert pool.has_key("house") is True
