"""Offline Echo Show APL regression tests. No AWS, Hue or Cloudflare access."""
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alexa.apl import DOCUMENT_TOKEN, category, document, presentation, valid_bins_out_event


@pytest.mark.parametrize("title,kind", [
    ("Recycling", "recycling"),
    ("Garden Waste", "garden"),
    ("Household waste", "household"),
    ("Unmapped type", "other"),
])
def test_bin_categories_match_dashboard(title, kind):
    assert category(title) == kind


def test_apl_document_uses_dashboard_theme_and_icon_shapes():
    raw = document()
    assert raw["type"] == "APL"
    assert raw["background"] == "#0b1914"
    for name in ("BinGarden", "BinRecycling", "BinHousehold", "BinOther"):
        assert raw["graphics"][name]["type"] == "AVG"
        assert raw["graphics"][name]["width"] == 42
    assert "binsOutButton" in json.dumps(raw)
    panel = next(item for item in raw["mainTemplate"]["items"][0]["items"]
                 if item.get("type") == "Frame" and item.get("backgroundColor") == "#132820")
    assert "grow" not in panel
    assert "payload.binbuddy.bins.length" in panel["height"]
    wheelie = panel["items"][0]["items"][0]["items"][0]["items"][0]
    assert wheelie["type"] == "VectorGraphic"
    assert wheelie["width"] >= 70
    assert raw["mainTemplate"]["parameters"] == ["payload"]


def test_echo_show_header_matches_web_dashboard_without_external_image():
    raw = document()
    header = raw["mainTemplate"]["items"][0]["items"][0]
    assert header["type"] == "Container"
    assert "viewport.height < 500" in header["height"]
    heading = header["items"][0]["items"]
    assert heading[0]["type"] == "VectorGraphic"
    assert heading[0]["source"] == "BindicatorMark"
    assert heading[1]["type"] == "Container"
    assert heading[1]["width"] == "${viewport.width < 650 ? 30 : 44}"
    assert heading[1]["height"] == 1
    assert heading[1]["items"] == []
    assert "marginLeft" not in heading[2]
    assert heading[2]["marginRight"] == 12
    assert heading[3]["marginLeft"] == 8
    brand_text = heading[2]["items"]
    assert brand_text[0]["text"] == "BINDICATOR"
    assert brand_text[1]["text"] == "Home lighting & bin collection reminders"
    assert brand_text[1]["marginTop"] == 5
    assert "viewport.height < 500" in brand_text[0]["fontSize"]
    assert heading[3]["text"] == "${payload.binbuddy.status}"
    assert header["items"][1]["backgroundColor"] == "#55c48b"
    assert "http" not in json.dumps(header).lower()


def test_presentation_renders_real_collections_and_countdown():
    data = presentation(
        {"date": "2026-11-24", "collections": ["Recycling", "Garden Waste"]},
        {"paused": False, "indicator_count": 2},
        today=date(2026, 11, 20),
    )["binbuddy"]
    assert data["dateLabel"] == "Tuesday 24 November"
    assert data["countdown"] == "In 4 days"
    assert data["bins"] == [
        {"title": "Recycling", "graphic": "BinRecycling"},
        {"title": "Garden Waste", "graphic": "BinGarden"},
    ]
    assert data["canAcknowledge"] is True


def test_acknowledged_and_paused_disable_touch_control():
    next_data = {"date": "2026-11-24", "collections": ["Household waste"]}
    ack = presentation(next_data, {
        "paused": False, "indicator_count": 1, "acknowledged_date": "2026-11-24"
    }, today=date(2026, 11, 23))["binbuddy"]
    assert ack["canAcknowledge"] is False
    assert ack["buttonLabel"] == "Already acknowledged"
    paused = presentation(next_data, {
        "paused": True, "indicator_count": 1
    }, today=date(2026, 11, 23))["binbuddy"]
    assert paused["status"] == "PAUSED"
    assert paused["canAcknowledge"] is False


def test_unknown_fields_and_titles_are_bounded():
    model = presentation({"date": "not a date", "collections": ["x" * 200] * 15},
                         {"paused": False, "indicator_count": 0}, today=date(2026, 11, 20))["binbuddy"]
    assert model["dateLabel"] == "Not available"
    assert len(model["bins"]) == 8
    assert all(len(item["title"]) <= 90 for item in model["bins"])
    assert model["canAcknowledge"] is False


def test_only_our_touch_event_may_acknowledge():
    request = SimpleNamespace(token=DOCUMENT_TOKEN, arguments=["bins-out"],
                              source={"id": "binsOutButton"})
    assert valid_bins_out_event(request)
    assert not valid_bins_out_event(SimpleNamespace(
        token="different", arguments=["bins-out"], source={"id": "binsOutButton"}))
    assert not valid_bins_out_event(SimpleNamespace(
        token=DOCUMENT_TOKEN, arguments=["pause"], source={"id": "binsOutButton"}))
    assert not valid_bins_out_event(SimpleNamespace(
        token=DOCUMENT_TOKEN, arguments=["bins-out"], source={"id": "anotherButton"}))


def test_apl_directive_only_on_supported_device(monkeypatch):
    pytest.importorskip("ask_sdk_core")
    pytest.importorskip("ask_sdk_model")
    monkeypatch.setenv("ALEXA_SKILL_ID", "amzn1.ask.skill.11111111-1111-1111-1111-111111111111")
    import importlib
    handler = importlib.import_module("alexa.lambda_function")

    input_ = Mock()
    calls = []
    def fake_api(method, path):
        calls.append((method, path))
        if path.endswith("/next"):
            return {"date": "2026-11-24", "collections": ["Recycling"]}
        return {"paused": False, "indicator_count": 0}
    monkeypatch.setattr(handler, "call_api", fake_api)

    monkeypatch.setattr(handler, "get_supported_interfaces",
                        lambda _: SimpleNamespace(alexa_presentation_apl=None))
    handler.attach_echo_show(input_)
    assert calls == []
    input_.response_builder.add_directive.assert_not_called()

    monkeypatch.setattr(handler, "get_supported_interfaces",
                        lambda _: SimpleNamespace(alexa_presentation_apl=object()))
    handler.attach_echo_show(input_)
    assert calls == [
        ("GET", "/api/v1/collections/next"), ("GET", "/api/v1/status")]
    directive = input_.response_builder.add_directive.call_args.args[0]
    assert directive.token == DOCUMENT_TOKEN
    assert directive.datasources["binbuddy"]["bins"][0]["title"] == "Recycling"


def test_unknown_touch_event_cannot_call_bins_out(monkeypatch):
    pytest.importorskip("ask_sdk_core")
    pytest.importorskip("ask_sdk_model")
    monkeypatch.setenv("ALEXA_SKILL_ID", "amzn1.ask.skill.11111111-1111-1111-1111-111111111111")
    import importlib
    handler = importlib.import_module("alexa.lambda_function")
    inp = Mock()
    inp.request_envelope.request = SimpleNamespace(
        token=DOCUMENT_TOKEN, arguments=["pause"], source={"id": "binsOutButton"})
    inp.response_builder.speak.return_value = inp.response_builder
    inp.response_builder.set_should_end_session.return_value = inp.response_builder
    inp.response_builder.response = "handled"
    invoked = []
    monkeypatch.setattr(handler, "handle_intent", lambda *args: invoked.append(args))
    assert handler.BinsOutTouchHandler().handle(inp) == "handled"
    assert invoked == []


def test_brand_mark_is_local_vector_and_recycling_stays_blue():
    raw = document()
    emblem = raw["graphics"]["BindicatorMark"]
    assert emblem["type"] == "AVG"
    assert emblem["width"] == 110
    assert len(emblem["items"]) >= 10
    # The main visual is green; waste-type identification retains blue recycling.
    assert raw["background"] == "#0b1914"
    assert raw["graphics"]["BinRecycling"]["items"][0]["fill"] == "#4088af"
    assert "https://" not in json.dumps(raw)
    assert "http://" not in json.dumps(raw)
    assert raw["mainTemplate"]["items"][0]["items"][-1]["disabled"] == "${!payload.binbuddy.canAcknowledge}"
