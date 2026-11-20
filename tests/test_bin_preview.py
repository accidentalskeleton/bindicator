"""Offline checks for short-lived bin collection previews."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bindicator.app import BindicatorError
from bindicator.bin_preview import (
    available_bin_types, next_collection, upcoming_collections, preview_lights, resolve_bin_types, identify_light,
)

BLUE = {"x": 0.17, "y": 0.08}
ORANGE = {"x": 0.57, "y": 0.39}
GREEN = {"x": 0.21, "y": 0.65}
DEFAULT = {"x": 0.33, "y": 0.33}
CONFIG = {
    "calendar": {"events": {
        "BinDay - Recycling": "blue",
        "BinDay - Household waste": "orange",
        "BinDay - Garden Waste": "green",
    }},
    "colors": {"blue": BLUE, "orange": ORANGE, "green": GREEN},
    "priority": ["orange", "blue", "green"],
    "hue": {"mode": "spread", "lights": [
        {"bridge": "office", "id": "desk-uuid"},
        {"bridge": "house", "id": "hall-uuid"},
    ]},
}


class FakePool:
    def __init__(self):
        self.data = {
            rid: {
                "color": {"xy": dict(DEFAULT)},
                "on": {"on": False},
                "dimming": {"brightness": 37.0},
                "color_temperature": {"mirek": None, "mirek_valid": False},
            }
            for rid in ("office/desk-uuid", "house/hall-uuid")
        }
        self.writes = []
        self.fail = set()

    def light(self, rid):
        if rid in self.fail:
            raise BindicatorError("Bridge offline")
        return deepcopy(self.data[rid])

    def set(self, rid, payload):
        if rid in self.fail:
            raise BindicatorError("Bridge offline")
        self.writes.append((rid, deepcopy(payload)))
        if "gradient" in payload:
            self.data[rid].setdefault("gradient", {}).update(deepcopy(payload["gradient"]))
        self.data[rid].update({
            field: deepcopy(value) for field, value in payload.items()
            if field != "gradient"
        })


def test_bin_type_listing_and_aliases():
    assert available_bin_types(CONFIG) == list(CONFIG["calendar"]["events"].items())
    assert resolve_bin_types(CONFIG, "recycling") == ["blue"]
    assert resolve_bin_types(CONFIG, "BinDay - Household waste") == ["orange"]
    assert resolve_bin_types(CONFIG, "garden waste") == ["green"]
    assert resolve_bin_types(CONFIG, "recycling,household waste") == ["orange", "blue"]
    assert resolve_bin_types(CONFIG, "recycling,recycling") == ["blue"]


def test_unrecognised_collection_is_rejected():
    with pytest.raises(BindicatorError, match="Unknown collection"):
        resolve_bin_types(CONFIG, "food waste")
    with pytest.raises(BindicatorError, match="Specify"):
        resolve_bin_types(CONFIG, "")


def test_spread_bin_preview_matches_production_assignment_and_restores():
    pool = FakePool()
    seen = []

    def while_lit(seconds):
        seen.append(seconds)
        assert pool.data["office/desk-uuid"]["color"]["xy"] == ORANGE
        assert pool.data["house/hall-uuid"]["color"]["xy"] == ORANGE
        assert pool.data["office/desk-uuid"]["on"]["on"] is True
        assert pool.data["house/hall-uuid"]["on"]["on"] is True
        assert pool.data["house/hall-uuid"]["dimming"]["brightness"] == 37.0

    result = preview_lights(
        pool, CONFIG, resolve_bin_types(CONFIG, "recycling,household waste"),
        seconds=7, sleeper=while_lit,
    )
    assert result == {
        "office/desk-uuid": "orange", "house/hall-uuid": "orange"
    }
    assert seen == [7]
    assert len(pool.writes) == 4
    assert pool.data["office/desk-uuid"]["color"]["xy"] == DEFAULT
    assert pool.data["house/hall-uuid"]["color"]["xy"] == DEFAULT
    assert pool.data["office/desk-uuid"]["on"]["on"] is False
    assert pool.data["house/hall-uuid"]["on"]["on"] is False


def test_spread_preview_uses_separate_counters_on_each_bridge():
    pool = FakePool()
    config = deepcopy(CONFIG)
    second_office = "office/desk-second"
    pool.data[second_office] = deepcopy(pool.data["office/desk-uuid"])
    # Alternate Bridges in the selection order to exercise grouping.
    config["hue"]["lights"].append({"bridge": "office", "id": "desk-second"})
    during = []

    def while_lit(seconds):
        during.append(seconds)
        assert pool.data["office/desk-uuid"]["color"]["xy"] == ORANGE
        assert pool.data["house/hall-uuid"]["color"]["xy"] == ORANGE
        assert pool.data[second_office]["color"]["xy"] == GREEN

    result = preview_lights(
        pool, config, ["orange", "green"], seconds=3, sleeper=while_lit
    )
    assert during == [3]
    assert result == {
        "office/desk-uuid": "orange",
        "house/hall-uuid": "orange",
        second_office: "green",
    }
    assert len(pool.writes) == 6
    for rid in result:
        assert pool.data[rid]["color"]["xy"] == DEFAULT


def test_gradient_preview_displays_two_colours_and_restores_gradient_and_power():
    pool = FakePool()
    original_points = [
        {"color": {"xy": dict(GREEN)}},
        {"color": {"xy": dict(BLUE)}},
    ]
    pool.data["office/desk-uuid"]["gradient"] = {
        "points_capable": 5,
        "mode_values": ["interpolated_palette", "segmented_palette"],
        "pixel_count": 10,
        "mode": "interpolated_palette",
        "points": deepcopy(original_points),
    }
    def during(seconds):
        lamp = pool.data["office/desk-uuid"]
        assert lamp["on"]["on"] is True
        assert lamp["gradient"]["mode"] == "segmented_palette"
        assert lamp["gradient"]["points"] == [
            {"color": {"xy": ORANGE}},
            {"color": {"xy": GREEN}},
        ]
        assert lamp["dimming"]["brightness"] == 37.0
        # Other Bridge still uses priority colour (first colour).
        assert pool.data["house/hall-uuid"]["color"]["xy"] == ORANGE

    desired = preview_lights(
        pool, CONFIG, ["orange", "green"], seconds=4, sleeper=during
    )
    assert desired["office/desk-uuid"] == "orange"
    lamp = pool.data["office/desk-uuid"]
    assert lamp["gradient"]["points"] == original_points
    assert lamp["gradient"]["mode"] == "interpolated_palette"
    assert lamp["on"]["on"] is False
    assert pool.data["house/hall-uuid"]["on"]["on"] is False


def test_gradient_preview_overrides_priority_for_opted_in_signe():
    pool = FakePool()
    rid = "office/desk-uuid"
    pool.data[rid]["gradient"] = {
        "points_capable": 4,
        "mode_values": ["segmented_palette", "interpolated_palette"],
        "mode": "interpolated_palette",
        "points": [{"color": {"xy": dict(DEFAULT)}}] * 2,
    }
    config = deepcopy(CONFIG)
    config["hue"]["mode"] = "priority"
    config["hue"]["lights"][0]["always_gradient"] = True
    original = deepcopy(pool.data[rid])
    def during(seconds):
        assert pool.data[rid]["gradient"]["points"] == [
            {"color": {"xy": ORANGE}}, {"color": {"xy": GREEN}}
        ]
        assert pool.data["house/hall-uuid"]["color"]["xy"] == ORANGE
    preview_lights(pool, config, ["orange", "green"], seconds=1, sleeper=during)
    assert pool.data[rid]["gradient"] == original["gradient"]
    assert pool.data[rid]["on"] == original["on"]


def test_gradient_preview_preserves_manual_point_change():
    pool = FakePool()
    pool.data["office/desk-uuid"]["gradient"] = {
        "points_capable": 5,
        "mode_values": ["segmented_palette", "interpolated_palette"],
        "mode": "interpolated_palette",
        "points": [
            {"color": {"xy": dict(DEFAULT)}},
            {"color": {"xy": dict(DEFAULT)}},
        ],
    }
    def during(seconds):
        pool.data["office/desk-uuid"]["gradient"]["points"][1]["color"]["xy"] = dict(BLUE)

    preview_lights(pool, CONFIG, ["orange", "green"], seconds=4, sleeper=during)
    assert pool.data["office/desk-uuid"]["gradient"]["points"][1]["color"]["xy"] == BLUE
    assert pool.data["office/desk-uuid"]["on"]["on"] is True


def test_gradient_preview_respects_point_capacity():
    pool = FakePool()
    pool.data["office/desk-uuid"]["gradient"] = {
        "points_capable": 2,
        "mode_values": ["interpolated_palette"],
        "mode": "interpolated_palette",
        "points": [
            {"color": {"xy": dict(DEFAULT)}},
            {"color": {"xy": dict(DEFAULT)}},
        ],
    }
    def during(seconds):
        points = pool.data["office/desk-uuid"]["gradient"]["points"]
        assert len(points) == 2
        assert points[0]["color"]["xy"] == ORANGE
        assert points[1]["color"]["xy"] == GREEN

    preview_lights(pool, CONFIG, ["orange", "green", "blue"], seconds=5, sleeper=during)
    assert pool.data["office/desk-uuid"]["on"]["on"] is False


def test_priority_preview_assigns_all_lamps_same_highest_priority_colour():
    pool = FakePool()
    config = deepcopy(CONFIG)
    config["hue"]["mode"] = "priority"

    def during(seconds):
        assert pool.data["office/desk-uuid"]["color"]["xy"] == ORANGE
        assert pool.data["house/hall-uuid"]["color"]["xy"] == ORANGE

    preview_lights(
        pool, config, resolve_bin_types(config, "household waste,recycling"),
        seconds=5, sleeper=during,
    )
    assert pool.data["office/desk-uuid"]["color"]["xy"] == DEFAULT
    assert pool.data["house/hall-uuid"]["color"]["xy"] == DEFAULT


def test_preview_respects_manual_colour_change_during_test():
    pool = FakePool()

    def during(seconds):
        pool.data["office/desk-uuid"]["color"]["xy"] = GREEN

    preview_lights(pool, CONFIG, ["blue"], seconds=5, sleeper=during)
    assert pool.data["office/desk-uuid"]["color"]["xy"] == GREEN
    assert pool.data["house/hall-uuid"]["color"]["xy"] == DEFAULT


def test_preview_preserves_originally_on_lamp_and_off_lamp(tmp_path):
    pool = FakePool()
    pool.data["house/hall-uuid"]["on"]["on"] = True
    def during(seconds):
        assert pool.data["office/desk-uuid"]["on"]["on"] is True
        assert pool.data["house/hall-uuid"]["on"]["on"] is True
        assert pool.data["office/desk-uuid"]["dimming"]["brightness"] == 37.0
    preview_lights(pool, CONFIG, ["orange"], seconds=5, sleeper=during)
    assert pool.data["office/desk-uuid"]["on"]["on"] is False
    assert pool.data["house/hall-uuid"]["on"]["on"] is True
    # Alert writes never adjust brightness; restoration replays the snapshot.
    assert all(
        "dimming" not in payload
        for _, payload in pool.writes[:2]
    )
    assert all(
        payload.get("dimming") == {"brightness": 37.0}
        for _, payload in pool.writes[2:]
    )


def test_preview_off_lamp_already_target_colour_still_switches_on():
    pool = FakePool()
    pool.data["office/desk-uuid"]["color"]["xy"] = dict(ORANGE)
    def during(seconds):
        assert pool.data["office/desk-uuid"]["on"]["on"] is True
    preview_lights(pool, CONFIG, ["orange"], seconds=4, sleeper=during)
    assert pool.data["office/desk-uuid"]["on"]["on"] is False
    assert pool.data["office/desk-uuid"]["color"]["xy"] == ORANGE


def test_preview_respects_manual_power_off_for_initially_on_light():
    pool = FakePool()
    pool.data["office/desk-uuid"]["on"]["on"] = True
    def during(seconds):
        pool.data["office/desk-uuid"]["on"]["on"] = False
    preview_lights(pool, CONFIG, ["blue"], seconds=5, sleeper=during)
    assert pool.data["office/desk-uuid"]["on"]["on"] is False


def test_preview_preflight_reads_all_lights_before_any_write():
    pool = FakePool()
    pool.fail.add("house/hall-uuid")
    with pytest.raises(BindicatorError, match="offline"):
        preview_lights(pool, CONFIG, ["blue"], seconds=5, sleeper=lambda _: None)
    assert pool.writes == []


def test_preview_restore_after_partial_put_failure():
    pool = FakePool()

    def bad_set(rid, payload):
        if rid == "house/hall-uuid" and payload.get("color", {}).get("xy") == ORANGE:
            raise BindicatorError("Hue refused preview")
        FakePool.set(pool, rid, payload)

    pool.set = bad_set
    with pytest.raises(BindicatorError, match="Hue refused"):
        preview_lights(
            pool, CONFIG, resolve_bin_types(CONFIG, "recycling,household waste"),
            seconds=5, sleeper=lambda _: None,
        )
    assert pool.data["office/desk-uuid"]["color"]["xy"] == DEFAULT
    assert pool.data["house/hall-uuid"]["color"]["xy"] == DEFAULT


def test_preview_seconds_bounds_and_missing_lights():
    pool = FakePool()
    for seconds in (0, 61):
        with pytest.raises(BindicatorError, match="seconds"):
            preview_lights(pool, CONFIG, ["blue"], seconds=seconds)
    config = deepcopy(CONFIG)
    config["hue"]["lights"] = []
    with pytest.raises(BindicatorError, match="No indicator lamps"):
        preview_lights(pool, config, ["blue"], seconds=5)


def test_no_scheduled_state_is_created_by_preview(tmp_path):
    pool = FakePool()
    preview_lights(pool, CONFIG, ["green"], seconds=1, sleeper=lambda _: None)
    assert not (tmp_path / "state.json").exists()


# Alternate-weekly recycling, mixed orange/green the following week.
ICS_COLLECTIONS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Bindicator next collection regression test//EN
BEGIN:VEVENT
UID:recurring-recycling
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261110
RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3
SUMMARY:binday - recycling
END:VEVENT
BEGIN:VEVENT
UID:household
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261117
SUMMARY:BinDay - Household waste
END:VEVENT
BEGIN:VEVENT
UID:garden
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261117
SUMMARY:BinDay - Garden Waste
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261112
STATUS:CANCELLED
SUMMARY:BinDay - Household waste
END:VEVENT
BEGIN:VEVENT
UID:unrelated
DTSTAMP:20261101T120000Z
DTSTART;VALUE=DATE:20261111
SUMMARY:Not a bin collection
END:VEVENT
END:VCALENDAR
"""


def test_next_collection_skips_today_and_finds_both_bins():
    uk = ZoneInfo("Europe/London")
    day, colours = next_collection(
        CONFIG, ICS_COLLECTIONS, datetime(2026, 11, 10, 15, 0, tzinfo=uk)
    )
    assert str(day) == "2026-11-17"
    assert colours == ["orange", "green"]


def test_next_collection_handles_recurrence_and_ignores_cancelled():
    uk = ZoneInfo("Europe/London")
    day, colours = next_collection(
        CONFIG, ICS_COLLECTIONS, datetime(2026, 11, 18, 10, 0, tzinfo=uk)
    )
    assert str(day) == "2026-11-24"
    assert colours == ["blue"]


def test_next_collection_timezone_uses_europe_london_local_date():
    from datetime import timezone

    # 23:30 UTC on 31 July is already 1 August in London (BST).
    # Therefore "next" must skip the 1 August collection and find 2 August.
    summer_ics = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Bindicator BST test//EN
BEGIN:VEVENT
UID:summer-recycling
DTSTAMP:20260701T120000Z
DTSTART;VALUE=DATE:20260801
SUMMARY:BinDay - Recycling
END:VEVENT
BEGIN:VEVENT
UID:summer-garden
DTSTAMP:20260701T120000Z
DTSTART;VALUE=DATE:20260802
SUMMARY:BinDay - Garden Waste
END:VEVENT
END:VCALENDAR
"""
    day, colours = next_collection(
        CONFIG, summer_ics,
        datetime(2026, 7, 31, 23, 30, tzinfo=timezone.utc),
    )
    assert str(day) == "2026-08-02"
    assert colours == ["green"]


def test_next_collection_no_matching_future_date_gives_clear_error():
    uk = ZoneInfo("Europe/London")
    with pytest.raises(BindicatorError, match="No matching future bin collection"):
        next_collection(
            CONFIG, ICS_COLLECTIONS, datetime(2026, 12, 10, 10, tzinfo=uk)
        )


def test_next_collection_does_not_change_preview_state():
    uk = ZoneInfo("Europe/London")
    before = deepcopy(CONFIG)
    next_collection(CONFIG, ICS_COLLECTIONS, datetime(2026, 11, 10, 15, tzinfo=uk))
    assert CONFIG == before


def test_next_collection_one_day_window_excludes_other_dates():
    uk = ZoneInfo("Europe/London")
    with pytest.raises(BindicatorError, match="No matching future"):
        next_collection(
            CONFIG, ICS_COLLECTIONS, datetime(2026, 11, 10, 15, tzinfo=uk),
            days_ahead=2
        )


def test_identify_one_off_light_then_restores_without_touching_other_lights():
    pool = FakePool()
    original = deepcopy(pool.data)
    seen = []
    def during(seconds):
        seen.append(seconds)
        assert pool.data["office/desk-uuid"]["on"]["on"] is True
        assert pool.data["house/hall-uuid"] == original["house/hall-uuid"]
    assert identify_light(pool, "office/desk-uuid", sleeper=during)
    assert seen == [0.8]
    assert [ref for ref, _ in pool.writes] == ["office/desk-uuid"] * 2
    assert pool.data == original


def test_identify_on_light_restores_its_original_state():
    pool = FakePool()
    pool.data["office/desk-uuid"]["on"]["on"] = True
    original = deepcopy(pool.data["office/desk-uuid"])
    assert identify_light(pool, "office/desk-uuid", sleeper=lambda secs: None)
    assert pool.data["office/desk-uuid"] == original


def test_identify_does_not_override_manual_power_change():
    pool = FakePool()
    def manual_change(seconds):
        # User switches lamp off while Bindicator temporarily turned it on.
        pool.data["office/desk-uuid"]["on"]["on"] = False
    assert not identify_light(pool, "office/desk-uuid", sleeper=manual_change)
    assert len(pool.writes) == 1


def test_identify_refuses_unrestorable_dynamic_scene():
    pool = FakePool()
    pool.data["office/desk-uuid"]["dynamics"] = {"status": "dynamic_palette"}
    with pytest.raises(BindicatorError, match="dynamic"):
        identify_light(pool, "office/desk-uuid", sleeper=lambda _: None)
    assert not pool.writes


def test_upcoming_five_distinct_days_grouped_and_prioritized():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    feed = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-1
DTSTART;VALUE=DATE:20261112
DTEND;VALUE=DATE:20261113
SUMMARY:BinDay - Recycling
END:VEVENT
BEGIN:VEVENT
UID:event-2
DTSTART;VALUE=DATE:20261112
DTEND;VALUE=DATE:20261113
SUMMARY:BinDay - Household waste
END:VEVENT
BEGIN:VEVENT
UID:event-3
DTSTART;VALUE=DATE:20261117
DTEND;VALUE=DATE:20261118
SUMMARY:BinDay - Garden Waste
RRULE:FREQ=WEEKLY;COUNT=6
END:VEVENT
END:VCALENDAR
"""
    rows = upcoming_collections(CONFIG, feed, datetime(2026, 11, 11, 15, 0, tzinfo=ZoneInfo("Europe/London")))
    assert len(rows) == 5
    assert [row["date"] for row in rows] == [
        "2026-11-12", "2026-11-17", "2026-11-24",
        "2026-12-01", "2026-12-08",
    ]
    assert rows[0]["collections"] == ["Household waste", "Recycling"]
    assert rows[0]["display_colours"] == ["orange", "blue"]
    assert rows[0]["colours"] == ["orange", "blue"]
    assert rows[1]["colours"] == ["green"]
    assert upcoming_collections(CONFIG, feed, datetime(2026, 11, 11, 15, 0, tzinfo=ZoneInfo("Europe/London")), limit=2) == rows[:2]
