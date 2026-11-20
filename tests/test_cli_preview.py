"""CLI contract checks for bin collection simulation without real Hue hardware."""
from __future__ import annotations

import json
import sys

import pytest
import yaml

from bindicator.app import BindicatorError


def make_files(tmp_path):
    config = {
        "calendar": {"events": {
            "BinDay - Recycling": "blue",
            "BinDay - Household waste": "orange",
            "BinDay - Garden Waste": "green",
        }},
        "hue": {
            "bridges": {"office": {"host": "192.168.1.180"}},
            "lights": [{"bridge": "office", "id": "lamp-uuid"}],
            "mode": "priority",
        },
        "colors": {
            "blue": {"x": 0.17, "y": 0.08},
            "orange": {"x": 0.57, "y": 0.39},
            "green": {"x": 0.21, "y": 0.65},
        },
        "priority": ["orange", "blue", "green"],
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(config))
    return config_file, tmp_path / "secrets.env", tmp_path / "state"


def test_list_bin_types_needs_no_bridge_or_calendar_credentials(monkeypatch, capsys, tmp_path):
    import bindicator.cli as cli

    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--list-bin-types",
    ])
    assert cli.main() == 0
    result = capsys.readouterr()
    assert "Recycling" in result.out
    assert "Household waste" in result.out
    assert "Garden Waste" in result.out


def test_test_bin_uses_actual_event_names_and_no_zoho_request(monkeypatch, tmp_path):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp

    config, secrets, state = make_files(tmp_path)
    args = []
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda pool, config, colours, seconds: args.append((colours, seconds)),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--test-bin", "recycling,household waste",
        "--seconds", "6",
    ])
    assert cli.main() == 0
    assert args == [(["orange", "blue"], 6)]
    assert not (state / "state.json").exists()


def test_test_bin_refuses_when_scheduled_reminder_is_active(monkeypatch, caplog, tmp_path):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    (state / "state.json").write_text(json.dumps({
        "date": "2026-11-11",
        "lights": {"office/lamp-uuid": {
            "original": {"color": {"xy": {"x": .2, "y": .2}}},
            "applied_xy": {"x": .1, "y": .1}
        }},
    }))
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda *args, **kwargs: pytest.fail("Must not test during scheduled reminder"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--test-bin", "recycling",
    ])
    assert cli.main() == 1
    assert "scheduled reminder is still active" in caplog.text


def test_invalid_collection_never_contacts_a_bridge(monkeypatch, tmp_path):
    import bindicator.cli as cli
    import bindicator.bridges as bridges

    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(
        bridges.BridgePool, "light",
        lambda *args: pytest.fail("No Bridge call expected"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--test-bin", "glass",
    ])
    assert cli.main() == 1


def test_next_collection_cli_prints_date_and_uses_mixed_bin_assignments(
    monkeypatch, capsys, tmp_path
):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from test_bin_preview import ICS_COLLECTIONS

    config, secrets, state = make_files(tmp_path)
    seen = []

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 15, 0, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli.Bindicator, "calendar_data", lambda self: ICS_COLLECTIONS)
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda pool, config, colours, seconds: seen.append((colours, seconds)),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--test-bin", "--next-collection",
        "--seconds", "9",
    ])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "17 Nov 2026" in output
    assert "orange, green" in output
    assert seen == [(["orange", "green"], 9)]
    assert not (state / "state.json").exists()


@pytest.mark.parametrize("extra, expected", [
    (["--test-bin"], "Use --next-collection alone"),
    (["--test-bin", "recycling", "--next-collection"], "--next-collection must be used alone"),
    (["--next-collection", "--status"], "--next-collection must be used alone"),
    (["--next-collection", "--pause"], "--next-collection must be used alone"),
])
def test_invalid_next_collection_argument_combinations(
    monkeypatch, caplog, tmp_path, extra, expected
):
    import bindicator.cli as cli

    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), *extra,
    ])
    assert cli.main() == 1
    assert expected in caplog.text
    assert not state.exists()


def test_standalone_next_collection_cli_activates_persistent_reminder(
    monkeypatch, capsys, tmp_path,
):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from test_bin_preview import ICS_COLLECTIONS

    config, secrets, state = make_files(tmp_path)
    observed = []

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 15, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli.Bindicator, "calendar_data", lambda self: ICS_COLLECTIONS)
    monkeypatch.setattr(
        cli.Bindicator, "apply_collections",
        lambda self, day, colours, *, manual: observed.append((str(day), colours, manual)),
    )
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda *args, **kwargs: pytest.fail("Standalone command must not time out"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--next-collection",
    ])
    assert cli.main() == 0
    assert observed == [("2026-11-17", ["orange", "green"], True)]
    output = capsys.readouterr().out
    assert "17 Nov 2026" in output
    assert "orange, green" in output
    assert "until 2026-11-17 at 09:00" in output


@pytest.mark.parametrize("seconds", [1, 10, 60])
def test_standalone_next_collection_with_seconds_returns_without_waiting(
    monkeypatch, tmp_path, capsys, seconds,
):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from test_bin_preview import ICS_COLLECTIONS

    config, secrets, state = make_files(tmp_path)
    observed = []

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 15, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli.Bindicator, "calendar_data", lambda self: ICS_COLLECTIONS)
    monkeypatch.setattr(
        cli.Bindicator, "apply_collections",
        lambda *args, **kwargs: pytest.fail("Preview must not persist an alert"),
    )
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda *args, **kwargs: pytest.fail("Preview must not block CLI process"),
    )
    def fake_spawn(**kwargs):
        observed.append(kwargs)
        return 5678

    monkeypatch.setattr(bp, "launch_detached_preview", fake_spawn)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--next-collection", "--seconds", str(seconds),
    ])
    assert cli.main() == 0
    assert len(observed) == 1
    assert observed[0]["colours"] == ["orange", "green"]
    assert observed[0]["seconds"] == seconds
    assert observed[0]["lock_fd"] >= 0
    output = capsys.readouterr().out
    assert "Next collection" in output
    assert "5678" in output
    assert "background" in output
    assert not (state / "state.json").exists()


@pytest.mark.parametrize("seconds", [0, -1, 61])
def test_standalone_next_collection_rejects_bad_duration_before_hue_writes(
    monkeypatch, tmp_path, seconds,
):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from test_bin_preview import ICS_COLLECTIONS

    config, secrets, state = make_files(tmp_path)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 15, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli.Bindicator, "calendar_data", lambda self: ICS_COLLECTIONS)
    # This uses the real preview duration check, but no Hue calls are allowed.
    monkeypatch.setattr(
        cli.BridgePool, "light",
        lambda *args, **kwargs: pytest.fail("Invalid duration must not access Hue"),
    )
    monkeypatch.setattr(
        bp, "preview_lights", bp.preview_lights,
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--next-collection", "--seconds", str(seconds),
    ])
    assert cli.main() == 1
    assert not (state / "state.json").exists()


def test_standalone_next_collection_refuses_during_pause(
    monkeypatch, tmp_path, caplog,
):
    import bindicator.cli as cli
    from bindicator.controls import set_paused

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    set_paused(state, True)
    monkeypatch.setattr(
        cli.Bindicator, "calendar_data",
        lambda self: pytest.fail("Paused command must not fetch Zoho"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--next-collection",
    ])
    assert cli.main() == 1
    assert "Bindicator is paused" in caplog.text


def test_next_collection_cli_refuses_when_reminder_is_active(monkeypatch, tmp_path, caplog):
    import bindicator.cli as cli
    from bindicator.app import Bindicator

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    (state / "state.json").write_text(json.dumps({
        "date": "2026-11-11",
        "lights": {
            "office/lamp-uuid": {
                "original": {"color": {"xy": {"x": 0.2, "y": 0.2}}},
                "applied_xy": {"x": 0.1, "y": 0.1},
            }
        },
    }))
    def no_calendar(self):
        pytest.fail("Active reminder must block next-collection calendar request")
    monkeypatch.setattr(Bindicator, "calendar_data", no_calendar)
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--test-bin", "--next-collection",
    ])
    assert cli.main() == 1
    assert "scheduled reminder is still active" in caplog.text


def test_next_collection_cli_no_matching_event_fails_before_hue_preview(
    monkeypatch, tmp_path, caplog
):
    import bindicator.cli as cli
    import bindicator.bin_preview as bp
    from test_bin_preview import ICS_COLLECTIONS
    from datetime import datetime
    from zoneinfo import ZoneInfo

    config, secrets, state = make_files(tmp_path)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 1, 1, 15, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli.Bindicator, "calendar_data", lambda self: ICS_COLLECTIONS)
    monkeypatch.setattr(
        bp, "preview_lights",
        lambda *args, **kwargs: pytest.fail("Hue preview must not start"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bindicator", "--config", str(config), "--secrets-file", str(secrets),
        "--state-dir", str(state), "--test-bin", "--next-collection"
    ])
    assert cli.main() == 1
    assert "No matching future bin collection" in caplog.text
