"""North Yorkshire Council adapter offline regressions."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from bindicator.north_yorkshire import (
    LOOKUP_URL, validate_uprn, collection_title, fetch_collections, to_ical,
)
from bindicator.app import collection_events_in_range, Bindicator


@pytest.fixture
def council_html():
    return """<div id="upcoming-collection"><table><tbody>
    <tr><td>20 November 2026</td><td>Friday</td><td>
    <span>Household waste</span><span>Recycling</span></td></tr>
    <tr><td>27 November 2026</td><td>Friday</td><td>
    <span>Garden Waste</span></td></tr>
    </tbody></table></div>"""


def session_for(html, *, redirect="https://www.northyorks.gov.uk/bin-calendar/Harrogate/results/12345678901"):
    session = Mock()
    session.post.return_value = SimpleNamespace(
        status_code=302, headers={"Location": redirect},
        url=LOOKUP_URL,
    )
    session.get.return_value = SimpleNamespace(
        is_redirect=False,
        url=redirect + "/ajax",
        content=b"small",
        json=lambda: [{"command": "settings", "data": {}},
                      {"command": "insert", "data": html}],
        raise_for_status=lambda: None,
    )
    return session


def test_council_fetch_and_ical_roundtrip(council_html):
    session = session_for(council_html)
    data = fetch_collections("12345678901", session=session)
    assert [(x["date"], x["title"]) for x in data] == [
        ("2026-11-20", "BinDay - Household waste"),
        ("2026-11-20", "BinDay - Recycling"),
        ("2026-11-27", "BinDay - Garden Waste"),
    ]
    session.post.assert_called_once()
    assert session.post.call_args.kwargs["data"]["selected_address"] == "12345678901"
    assert session.get.call_args.args[0].endswith("/ajax")
    events = collection_events_in_range(
        to_ical(data), date(2026, 11, 19), date(2026, 12, 1),
        {"BinDay - Household waste": "orange", "BinDay - Recycling": "blue",
         "BinDay - Garden Waste": "green"},
    )
    assert {x["colour"] for x in events[date(2026, 11, 20)]} == {"orange", "blue"}


@pytest.mark.parametrize("uprn", ["", "abc", "123456", "1234567890123", "1234567x90", " 12345678901 "])
def test_invalid_uprn_is_rejected_without_network(uprn):
    with pytest.raises(ValueError):
        validate_uprn(uprn)


@pytest.mark.parametrize("label,expected", [
    ("Refuse", "BinDay - Household waste"),
    ("Household waste", "BinDay - Household waste"),
    ("Recycling", "BinDay - Recycling"),
    ("Glass and cans", "BinDay - Recycling"),
    ("Garden Waste", "BinDay - Garden Waste"),
])
def test_council_name_to_existing_event(label, expected):
    assert collection_title(label) == expected


def test_unknown_bin_type_fails_closed(council_html):
    with pytest.raises(ValueError, match="Unrecognised"):
        fetch_collections("12345678901", session=session_for(council_html.replace("Garden Waste", "Medical Waste")))


@pytest.mark.parametrize("target", [
    "http://www.northyorks.gov.uk/bin-calendar/results/123",
    "https://evil.example/bin-calendar/results/123",
    "https://www.northyorks.gov.uk.evil.example/bin-calendar/results/123",
    "https://www.northyorks.gov.uk/admin",
])
def test_offsite_or_unexpected_redirect_refused(council_html, target):
    s = session_for(council_html, redirect=target)
    with pytest.raises(ValueError, match="redirect"):
        fetch_collections("12345678901", session=s)
    s.get.assert_not_called()


def test_absent_table_fails_closed():
    with pytest.raises(ValueError, match="Council collection table is missing"):
        fetch_collections("12345678901", session=session_for("<div id='upcoming-collection'></div>"))


def test_council_data_source_is_opt_in_and_cached(monkeypatch, tmp_path):
    from bindicator import north_yorkshire
    config = {"north_yorkshire": {"enabled": True, "uprn": "12345678901"},
              "calendar": {"events": {"BinDay – Recycling": "blue"}}}
    app = Bindicator(config, tmp_path)
    calls = []
    def fake_fetch(uprn):
        calls.append(uprn)
        return [{"date": "2026-11-20", "title": "BinDay - Recycling", "type": "Recycling"}]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", fake_fetch)
    first = app.calendar_data()
    second = app.calendar_data()
    assert first == second
    assert len(calls) == 1
    assert (tmp_path / "north-yorkshire-v2.ics").read_bytes() == first


def test_resolve_council_events_to_existing_calendar_titles():
    from bindicator.north_yorkshire import resolve_mappings
    records = [{"date": "2026-11-24", "type": "Recycling", "title": "BinDay - Recycling"}]
    existing = {"BinDay – Recycling": "blue", "BinDay – Household waste": "orange"}
    matched = resolve_mappings(records, existing)
    assert matched[0]["title"] == "BinDay – Recycling"
    consistent = resolve_mappings(records, {"Recycling": "blue", "BinDay – Recycling": "blue"})
    assert consistent[0]["title"] == "Recycling"
    with pytest.raises(ValueError, match="no unique"):
        resolve_mappings(records, {"Recycling": "blue", "BinDay – Recycling": "orange"})


def test_interval_refresh_metadata_and_forced_refresh(monkeypatch, tmp_path):
    from bindicator import north_yorkshire
    from bindicator.council_refresh import refresh_council, cache_status
    from bindicator.app import Bindicator
    config = {"north_yorkshire": {"enabled": True, "uprn": "12345678901",
                                  "refresh_days": 7},
              "calendar": {"events": {"BinDay – Recycling": "blue"}}}
    calls = []
    def download(uprn):
        calls.append(uprn)
        return [{"date": "2026-11-24", "title": "BinDay - Recycling", "type": "Recycling"}]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", download)
    app = Bindicator(config, tmp_path)
    first = app.calendar_data()
    assert b"BEGIN:VCALENDAR" in first and len(calls) == 1
    assert refresh_council(config, tmp_path)["refreshed"] is False
    assert len(calls) == 1
    status = cache_status(config, tmp_path)
    assert status["last_success"] is not None
    assert status["next_due"] is not None
    assert status["refresh_days"] == 7 and status["stale"] is False
    assert refresh_council(config, tmp_path, force=True)["refreshed"] is True
    assert len(calls) == 2


def test_failed_manual_refresh_does_not_erase_council_cache(monkeypatch, tmp_path):
    from bindicator import north_yorkshire
    from bindicator.council_refresh import refresh_council
    from bindicator.app import BindicatorError
    config = {"north_yorkshire": {"enabled": True, "uprn": "12345678901",
                                  "refresh_days": 7},
              "calendar": {"events": {"BinDay – Recycling": "blue"}}}
    records = [{"date": "2026-11-24", "title": "BinDay - Recycling", "type": "Recycling"}]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda uprn: records)
    refresh_council(config, tmp_path)
    original = (tmp_path / "north-yorkshire-v2.ics").read_bytes()
    def fail(_):
        raise ValueError("Council offline")
    monkeypatch.setattr(north_yorkshire, "fetch_collections", fail)
    with pytest.raises(BindicatorError, match="preserved"):
        refresh_council(config, tmp_path, force=True)
    assert (tmp_path / "north-yorkshire-v2.ics").read_bytes() == original


def test_scheduled_council_due_check_respects_disabled_source(monkeypatch, tmp_path):
    from bindicator import council_refresh_job
    from bindicator import north_yorkshire
    config = tmp_path / "config.yaml"
    config.write_text("""calendar:
  events:
    BinDay - Recycling: blue
hue: {bridges: {}, lights: [], mode: spread}
colors: {blue: {x: 0.17, y: 0.08}}
priority: [blue]
north_yorkshire: {enabled: false, uprn: '', refresh_days: 7}
""")
    from bindicator import calendar_engine
    real_refresh = calendar_engine.refresh_source
    ical_calls = []
    def dispatch(source, cfg, directory):
        if source == "ical":
            ical_calls.append(True)
            return {"refreshed": False}
        return real_refresh(source, cfg, directory)
    monkeypatch.setattr(calendar_engine, "refresh_source", dispatch)
    assert council_refresh_job.run(config, tmp_path) is False
    assert ical_calls == [True]
    config.write_text(config.read_text().replace("enabled: false, uprn: ''", "enabled: true, uprn: '12345678901'"))
    calls = []
    def fake(uprn):
        calls.append(uprn)
        return [{"date": "2026-11-24", "title": "BinDay - Recycling", "type": "Recycling"}]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", fake)
    assert council_refresh_job.run(config, tmp_path) is True
    assert council_refresh_job.run(config, tmp_path) is False
    assert calls == ["12345678901"]


def test_combined_collection_names_align_with_display_colours():
    from bindicator.bin_preview import upcoming_collections
    from bindicator.app import TZ
    from datetime import datetime
    data = to_ical([
        {"date": "2026-12-01", "title": "BinDay - Garden Waste"},
        {"date": "2026-12-01", "title": "BinDay - Household waste"},
        {"date": "2026-12-08", "title": "BinDay - Recycling"},
    ])
    config = {"calendar": {"events": {
        "BinDay - Garden Waste": "green",
        "BinDay - Household waste": "orange",
        "BinDay - Recycling": "blue"}},
        "priority": ["orange", "blue", "green"]}
    rows = upcoming_collections(config, data, datetime(2026, 11, 25, 12, tzinfo=TZ))
    assert rows[0]["collections"] == ["Household waste", "Garden Waste"]
    assert rows[0]["display_colours"] == ["orange", "green"]
    assert rows[0]["colours"] == ["orange", "green"]
    assert rows[1]["collections"] == ["Recycling"]
    assert rows[1]["display_colours"] == ["blue"]
