"""Provider registry, canonical event model and shared calendar engine contracts."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from bindicator.calendar_providers import (
    CollectionEvent, ICalendarProvider, NorthYorkshireProvider,
    PROVIDERS, active_source, get_provider, group_events, ical_events,
    register_provider,
)
from bindicator.calendar_engine import cache_status, calendar_data, refresh_source
from bindicator.app import BindicatorError


def test_builtin_providers_are_registered_and_declared():
    assert set(("ical", "council")) <= set(PROVIDERS)
    for provider in (get_provider("ical"), get_provider("council")):
        assert provider.config_fields
        assert provider.id and provider.name
        assert callable(provider.fetch)
        assert callable(provider.events)
        assert callable(provider.discover_titles)
    assert active_source({"north_yorkshire": {"enabled": True}}) == "council"
    assert active_source({"north_yorkshire": {"enabled": False}}) == "ical"
    assert active_source({"calendar_source": "other",
                          "north_yorkshire": {"enabled": True}}) == "other"
    with pytest.raises(ValueError, match="Unknown"):
        get_provider("not-registered")


def test_ical_and_council_return_same_canonical_shape(monkeypatch, tmp_path):
    from bindicator import north_yorkshire
    from bindicator.app import Bindicator
    ics = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
           b"UID:bin1\r\nDTSTART;VALUE=DATE:20300101\r\n"
           b"SUMMARY:BinDay - Recycling\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    monkeypatch.setattr(Bindicator, "zoho_calendar_data",
                        lambda self, *, allow_cache=True: ics)
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda uprn: [{
        "date": "2030-01-01", "title": "BinDay - Recycling", "type": "Recycling"
    }])
    cfg = {"north_yorkshire": {"uprn": "12345678901"},
           "calendar": {"events": {"BinDay - Recycling": "blue"}}}
    start, end = date(2029, 12, 31), date(2030, 1, 3)
    cal = get_provider("ical").events(cfg, tmp_path, start, end)
    council = get_provider("council").events(cfg, tmp_path, start, end)
    assert len(cal) == len(council) == 1
    assert cal[0].date == council[0].date == date(2030, 1, 1)
    assert cal[0].title == council[0].title == "BinDay - Recycling"
    assert cal[0].source_id == "ical"
    assert council[0].source_id == "council"
    assert council[0].original_title == "Recycling"
    assert group_events(council) == [
        {"date": "2030-01-01", "collections": ["Recycling"]}
    ]


def test_custom_registered_provider_uses_engine_without_core_changes(monkeypatch, tmp_path):
    class CustomCouncil:
        id = "example_council"
        name = "Example Council"
        config_fields = ({"key": "postcode", "label": "Postcode", "type": "text"},)

        def configured(self, config):
            return bool(config.get("example_council", {}).get("postcode"))

        def identity(self, config):
            return config["example_council"]["postcode"]

        def fetch(self, config, state_dir):
            calls.append(config["example_council"]["postcode"])
            return (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
                    b"UID:test\r\nDTSTART;VALUE=DATE:20300101\r\n"
                    b"SUMMARY:BinDay - Recycling\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

        def events(self, config, state_dir, start, end):
            return ical_events(self.fetch(config, state_dir), self.id, start, end)

        def discover_titles(self, config, state_dir):
            return ["BinDay - Recycling"]

    calls = []
    monkeypatch.setitem(PROVIDERS, "example_council", CustomCouncil())
    cfg = {"calendar_source": "example_council",
           "example_council": {"postcode": "EX1 1AA"},
           "calendar_refresh": {"days": 7},
           "calendar": {"events": {"BinDay - Recycling": "blue"}}}
    assert active_source(cfg) == "example_council"
    assert calendar_data(active_source(cfg), cfg, tmp_path).startswith(b"BEGIN:VCALENDAR")
    assert len(calls) == 1
    assert refresh_source("example_council", cfg, tmp_path)["refreshed"] is False
    assert len(calls) == 1
    assert refresh_source("example_council", cfg, tmp_path, force=True)["refreshed"] is True
    assert len(calls) == 2
    assert cache_status("example_council", cfg, tmp_path)["last_success"]
    cfg["example_council"]["postcode"] = "EX2 2BB"
    assert cache_status("example_council", cfg, tmp_path)["last_success"] is None
    assert refresh_source("example_council", cfg, tmp_path)["refreshed"] is True
    assert calls[-1] == "EX2 2BB"


def test_custom_provider_failure_preserves_cache_and_does_not_fake_manual_success(
    monkeypatch, tmp_path
):
    class UnavailableCouncil:
        id = "unavailable_council"
        name = "Unavailable Council"
        config_fields = ()
        fail = False

        def configured(self, config):
            return True

        def identity(self, config):
            return "constant"

        def fetch(self, config, state_dir):
            if self.fail:
                raise ValueError("Network failure")
            return (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
                    b"UID:test\r\nDTSTART;VALUE=DATE:20300101\r\n"
                    b"SUMMARY:BinDay - Recycling\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

        def events(self, config, state_dir, start, end):
            return []

        def discover_titles(self, config, state_dir):
            return []

    provider = UnavailableCouncil()
    monkeypatch.setitem(PROVIDERS, provider.id, provider)
    cfg = {"calendar_refresh": {"days": 7}}
    first = calendar_data(provider.id, cfg, tmp_path)
    provider.fail = True
    with pytest.raises(BindicatorError, match="preserved"):
        refresh_source(provider.id, cfg, tmp_path, force=True)
    assert calendar_data(provider.id, cfg, tmp_path) == first


def test_registration_rejects_duplicates_and_invalid_ids():
    class Invalid:
        id = "ical"
    with pytest.raises(ValueError, match="unique"):
        register_provider(Invalid())
    with pytest.raises(ValueError, match="Unknown"):
        get_provider("__missing_provider__")


def test_trusted_entry_point_installs_provider_without_core_edits(monkeypatch):
    import importlib.metadata
    import bindicator.calendar_providers as providers

    class DemoCouncil:
        id = "demo_installed_council"
        name = "Installed Council"
        config_fields = ({"key": "postcode", "label": "Postcode", "type": "text"},)
        def configured(self, config):
            return True
        def identity(self, config):
            return "demo"
        def fetch(self, config, state_dir):
            return b""
        def events(self, config, state_dir, start, end):
            return []
        def discover_titles(self, config, state_dir):
            return []

    class EntryPoint:
        name = "demo"
        def load(self):
            return DemoCouncil

    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda *, group: [EntryPoint()] if group == "bindicator.calendar_providers" else [])
    monkeypatch.setattr(providers, "_PLUGINS_LOADED", False)
    try:
        assert providers.get_provider("demo_installed_council").name == "Installed Council"
        assert any(p.id == "demo_installed_council" for p in providers.registered_providers())
    finally:
        providers.PROVIDERS.pop("demo_installed_council", None)


def test_registration_requires_provider_contract():
    class Broken:
        id = "missing_methods"
        name = "Broken"
        config_fields = ()
    with pytest.raises(ValueError, match="missing"):
        register_provider(Broken())
    assert "missing_methods" not in PROVIDERS
