"""Shared iCalendar source refresh and URL safety regressions."""
from datetime import date
from ipaddress import ip_address
from pathlib import Path
import pytest

from bindicator.ical_source import validate_public_ical_url


@pytest.mark.parametrize("url", [
    "https://calendar.zoho.com/private/calendar.ics",
    "https://calendar.google.com/calendar/ical/secret/basic.ics",
    "https://outlook.office365.com/calendar/private",
])
def test_known_public_ical_provider_urls(url):
    assert validate_public_ical_url(url) == url


@pytest.mark.parametrize("url", [
    "http://calendar.google.com/ics",
    "https://127.0.0.1/feed.ics",
    "https://192.168.1.69/calendar.ics",
    "https://myserver.local/ical",
    "https://localhost/feed",
    "https://calendar.google.com@127.0.0.1/feed",
    "https://calendar.google.com:8080/feed",
    "https://calendar.google.com/secret#fragment",
])
def test_non_public_calendar_targets_rejected(url):
    with pytest.raises(ValueError):
        validate_public_ical_url(url)


def _config():
    return {"north_yorkshire": {"enabled": False, "uprn": "", "refresh_days": 7},
            "calendar_refresh": {"days": 7},
            "calendar": {"events": {"BinDay - Recycling": "blue"}}}


def _feed():
    return (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            b"UID:recycling\r\nDTSTART;VALUE=DATE:20300101\r\n"
            b"SUMMARY:BinDay - Recycling\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def test_ical_cache_interval_and_forced_refresh(monkeypatch, tmp_path):
    from bindicator.ical_refresh import refresh_ical, status, ical_calendar_data
    from bindicator.app import Bindicator
    monkeypatch.setenv("BINDICATOR_ICAL_URL", "https://calendar.zoho.com/ical/example")
    calls = []
    def fetch(self, *, allow_cache=True):
        calls.append(allow_cache)
        return _feed()
    monkeypatch.setattr(Bindicator, "zoho_calendar_data", fetch)
    cfg = _config()
    assert ical_calendar_data(cfg, tmp_path) == _feed()
    assert ical_calendar_data(cfg, tmp_path) == _feed()
    assert calls == [False]
    assert status(cfg, tmp_path)["last_success"] is not None
    assert status(cfg, tmp_path)["refresh_days"] == 7
    assert refresh_ical(cfg, tmp_path, force=True)["refreshed"] is True
    assert calls == [False, False]


def test_ical_refresh_failure_preserves_prior_data(monkeypatch, tmp_path):
    from bindicator.ical_refresh import refresh_ical, ical_calendar_data
    from bindicator.app import Bindicator, BindicatorError
    monkeypatch.setenv("BINDICATOR_ICAL_URL", "https://calendar.google.com/ical/example")
    monkeypatch.setattr(Bindicator, "zoho_calendar_data",
                        lambda self, *, allow_cache=True: _feed())
    cfg = _config()
    refresh_ical(cfg, tmp_path)
    old = ical_calendar_data(cfg, tmp_path)
    def fail(self, *, allow_cache=True):
        raise BindicatorError("Source offline")
    monkeypatch.setattr(Bindicator, "zoho_calendar_data", fail)
    with pytest.raises(BindicatorError, match="preserved"):
        refresh_ical(cfg, tmp_path, force=True)
    assert ical_calendar_data(cfg, tmp_path) == old


def test_ical_url_change_invalidates_cached_calendar(monkeypatch, tmp_path):
    from bindicator.ical_refresh import ical_calendar_data
    from bindicator.app import Bindicator
    calls = []
    monkeypatch.setattr(Bindicator, "zoho_calendar_data",
                        lambda self, *, allow_cache=True: calls.append(True) or _feed())
    cfg = _config()
    monkeypatch.setenv("BINDICATOR_ICAL_URL", "https://calendar.zoho.com/feed-a")
    ical_calendar_data(cfg, tmp_path)
    monkeypatch.setenv("BINDICATOR_ICAL_URL", "https://calendar.zoho.com/feed-b")
    ical_calendar_data(cfg, tmp_path)
    assert len(calls) == 2
