"""Offline Alexa adapter tests: no Echo, AWS, Cloudflare or Hue needed."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
from email.message import Message
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from alexa import logic
from bindicator import api
from bindicator.app import collection_events_in_range
from test_bin_preview import ICS_COLLECTIONS
from test_cli_preview import make_files

MODEL = Path(__file__).resolve().parents[1] / "alexa" / "interaction-model-en-GB.json"


def test_interaction_model_is_valid_en_gb_and_all_intents_have_utterances():
    data = json.loads(MODEL.read_text())
    language = data["interactionModel"]["languageModel"]
    assert language["invocationName"] == "bin buddy"
    intents = {i["name"]: i for i in language["intents"]}
    for name in (
        "PauseIntent", "ResumeIntent", "ToggleIntent", "StatusIntent",
        "NextCollectionIntent", "ShowNextIntent", "ShowPersistentIntent",
        "BinsOutIntent",
    ):
        assert len(intents[name]["samples"]) >= 3
    assert intents["ShowNextIntent"]["slots"] == [
        {"name": "duration", "type": "AMAZON.NUMBER"}
    ]
    all_phrases = [
        phrase.casefold()
        for intent in language["intents"] for phrase in intent["samples"]
    ]
    assert len(all_phrases) == len(set(all_phrases))


def test_next_collection_speaks_real_event_names_and_british_date():
    calls = []
    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        return {
            "date": "2026-11-17",
            "collections": ["Household waste", "Garden Waste"],
        }
    result = logic.interpret("NextCollectionIntent", api_client=fake)
    assert result == (
        "Your next collection is Household waste and Garden Waste, "
        "on Tuesday the 17th of November."
    )
    assert calls == [("GET", "/api/v1/collections/next", None)]


@pytest.mark.parametrize("intent, action, reply", [
    ("PauseIntent", "pause", "Bin reminders paused."),
    ("ResumeIntent", "resume", "Bin reminders enabled."),
])
def test_action_intents_delegate_to_fixed_endpoints(intent, action, reply):
    calls = []
    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}
    assert logic.interpret(intent, api_client=fake).startswith(reply)
    assert calls == [("POST", "/api/v1/" + action, {})]


def test_toggle_checks_actual_state_after_request():
    calls = []
    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True} if method == "POST" else {"paused": True}
    assert logic.interpret("ToggleIntent", api_client=fake) == "Bin reminders paused."
    assert calls == [
        ("POST", "/api/v1/toggle", {}),
        ("GET", "/api/v1/status", None),
    ]


@pytest.mark.parametrize("paused, expected", [
    (True, "Bin reminders are paused."),
    (False, "Bin reminders are enabled."),
])
def test_status(paused, expected):
    assert logic.interpret(
        "StatusIntent",
        api_client=lambda *args: {"paused": paused},
    ) == expected


@pytest.mark.parametrize("raw, expected", [
    ("1", 1), ("10", 10), ("60", 60),
])
def test_duration_slot(raw, expected):
    assert logic.duration_seconds({"duration": {"value": raw}}) == expected


@pytest.mark.parametrize("value", [
    "0", "61", "-5", "1.5", "nan", "10 seconds", 10, "12345",
])
def test_bad_duration_never_becomes_persistent(value):
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        return {"ok": True}
    response = logic.handle_intent(
        "ShowNextIntent", slots={"duration": {"value": value}}, api_client=fake,
    )
    assert "between one and sixty seconds" in response
    assert calls == []


def test_missing_duration_never_runs_persistent_alert():
    calls = []
    result = logic.interpret(
        "ShowNextIntent",
        slots={},
        api_client=lambda *args: calls.append(args),
    )
    assert "show the bins until collection day" in result
    assert calls == []


def test_short_preview_and_separate_persistent_intent():
    calls = []
    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}
    result = logic.interpret(
        "ShowNextIntent", slots={"duration": {"value": "10"}},
        api_client=fake,
    )
    assert "10 seconds" in result
    assert calls == [("POST", "/api/v1/alerts/next", {"seconds": 10})]
    assert "until collection morning" in logic.interpret(
        "ShowPersistentIntent", api_client=fake,
    )
    assert calls[-1] == ("POST", "/api/v1/alerts/next", {})


def test_alexa_connection_error_does_not_claim_action_succeeded():
    def fail(*args):
        raise logic.BindicatorUnavailable()
    msg = logic.handle_intent("PauseIntent", api_client=fail)
    assert "couldn't reach Bin Indicator" in msg
    assert "paused" not in msg


def test_calendar_names_escaped_from_ssml():
    assert logic.speech_xml('Waste & <lights> "quoted"') == (
        'Waste &amp; &lt;lights&gt; &quot;quoted&quot;'
    )


def test_cloudflare_authentication_and_api_bearer_headers(monkeypatch):
    environ = {
        "BINDICATOR_API_URL": "https://bins.example.org",
        "BINDICATOR_API_TOKEN": "secret" * 12,
        "CF_ACCESS_CLIENT_ID": "client-id",
        "CF_ACCESS_CLIENT_SECRET": "client-secret",
    }
    requests = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b'{"paused":true}'
    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()
    monkeypatch.setattr(logic.urllib.request, "urlopen", fake_urlopen)
    result = logic.call_api("GET", "/api/v1/status", environ=environ)
    assert result == {"paused": True}
    req, timeout = requests[0]
    assert req.full_url == "https://bins.example.org/api/v1/status"
    assert req.get_header("Authorization") == "Bearer " + environ["BINDICATOR_API_TOKEN"]
    assert req.get_header("Cf-access-client-id") == "client-id"
    assert req.get_header("Cf-access-client-secret") == "client-secret"
    assert timeout == 4


def test_reject_http_url_unknown_operations_and_missing_credentials():
    env = {
        "BINDICATOR_API_URL": "http://127.0.0.1:18050",
        "BINDICATOR_API_TOKEN": "a" * 40,
        "CF_ACCESS_CLIENT_ID": "x",
        "CF_ACCESS_CLIENT_SECRET": "y",
    }
    with pytest.raises(logic.AlexaConfigError):
        logic.transport_config(env)
    with pytest.raises(ValueError):
        logic.call_api("POST", "/api/v1/run/shell")


def test_exact_calendar_titles_even_with_shared_colour(tmp_path, monkeypatch):
    config, secrets, state = make_files(tmp_path)
    import yaml
    contents = yaml.safe_load(config.read_text())
    contents["calendar"]["events"]["BinDay - Mixed Paper"] = "orange"
    config.write_text(yaml.safe_dump(contents))
    ics = ICS_COLLECTIONS.replace(
        b"END:VCALENDAR",
        b"BEGIN:VEVENT\nUID:mixed-paper\nDTSTAMP:20261101T120000Z\n"
        b"DTSTART;VALUE=DATE:20261117\n"
        b"SUMMARY:BinDay - Mixed Paper\nEND:VEVENT\nEND:VCALENDAR",
    )
    matched = collection_events_in_range(
        ics, date(2026, 11, 17), date(2026, 11, 18),
        contents["calendar"]["events"],
    )
    assert {item["title"] for item in matched[date(2026,11,17)]} == {
        "BinDay - Household waste", "BinDay - Garden Waste",
        "BinDay - Mixed Paper",
    }
    # API must show all three actual types, even with only two unique colours.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, tzinfo=ZoneInfo("Europe/London"))
    monkeypatch.setattr(api, "datetime", FixedDatetime)
    monkeypatch.setattr(api.Bindicator, "calendar_data", lambda self: ics)
    response = api.BindicatorAPI(config, secrets, state).next_collection()
    assert response["colours"] == ["orange", "green"]
    assert set(response["collections"]) == {
        "Household waste", "Garden Waste", "Mixed Paper",
    }


@pytest.fixture
def alexa_test_environment():
    return {
        "BINDICATOR_API_URL": "https://bins.example.org",
        "BINDICATOR_API_TOKEN": "API_TOKEN_NEVER_LOG_" + "x" * 40,
        "CF_ACCESS_CLIENT_ID": "CLIENT_ID_NEVER_LOG.access",
        "CF_ACCESS_CLIENT_SECRET": "CLIENT_SECRET_NEVER_LOG",
    }


@pytest.mark.parametrize("status,media_type,category", [
    (401, "text/html", "html"),
    (403, "text/html", "html"),
    (401, "application/json", "json"),
    (400, "application/json", "json"),
    (502, "text/plain", "other"),
])
def test_alexa_http_failures_log_only_safe_status_and_response_type(
    monkeypatch, caplog, alexa_test_environment, status, media_type, category,
):
    headers = Message()
    headers["Content-Type"] = media_type
    def reject(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url + "?API_TOKEN_NEVER_LOG", status,
            "CLIENT_SECRET_NEVER_LOG", headers, None,
        )
    monkeypatch.setattr(logic.urllib.request, "urlopen", reject)
    with caplog.at_level(logging.WARNING, logger="bindicator.alexa.transport"):
        assert "couldn't reach" in logic.handle_intent(
            "NextCollectionIntent",
            api_client=lambda method, path: logic.call_api(
                method, path, environ=alexa_test_environment,
            ),
        )
    assert f"status={status} response_type={category}" in caplog.text
    for secret in (
        alexa_test_environment["BINDICATOR_API_TOKEN"],
        alexa_test_environment["CF_ACCESS_CLIENT_ID"],
        alexa_test_environment["CF_ACCESS_CLIENT_SECRET"],
        "API_TOKEN_NEVER_LOG",
        "CLIENT_SECRET_NEVER_LOG",
        "bins.example.org",
    ):
        assert secret not in caplog.text


@pytest.mark.parametrize("exception,expected", [
    (TimeoutError("SECRET_NEVER_LOG"), "kind=timeout"),
    (urllib.error.URLError(TimeoutError("SECRET_NEVER_LOG")), "kind=timeout"),
    (urllib.error.URLError("SECRET_NEVER_LOG"), "kind=connection"),
])
def test_alexa_network_diagnostics_never_log_exception_details(
    monkeypatch, caplog, alexa_test_environment, exception, expected,
):
    def reject(request, timeout):
        raise exception
    monkeypatch.setattr(logic.urllib.request, "urlopen", reject)
    with caplog.at_level(logging.WARNING, logger="bindicator.alexa.transport"):
        with pytest.raises(logic.BindicatorUnavailable):
            logic.call_api("GET", "/api/v1/status", environ=alexa_test_environment)
    assert expected in caplog.text
    assert "SECRET_NEVER_LOG" not in caplog.text


def test_alexa_invalid_configuration_logs_category_without_values(caplog):
    env = {
        "BINDICATOR_API_URL": "http://PRIVATE_HOST_NEVER_LOG",
        "BINDICATOR_API_TOKEN": "SECRET_NEVER_LOG",
        "CF_ACCESS_CLIENT_ID": "SECRET_NEVER_LOG",
        "CF_ACCESS_CLIENT_SECRET": "SECRET_NEVER_LOG",
    }
    with caplog.at_level(logging.ERROR, logger="bindicator.alexa.transport"):
        assert "couldn't reach" in logic.handle_intent(
            "StatusIntent",
            api_client=lambda method, path: logic.call_api(
                method, path, environ=env,
            ),
        )
    assert "configuration invalid" in caplog.text
    assert "SECRET_NEVER_LOG" not in caplog.text
    assert "PRIVATE_HOST_NEVER_LOG" not in caplog.text


def test_alexa_invalid_json_logs_no_response_body(
    monkeypatch, caplog, alexa_test_environment,
):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b'SECRET_NEVER_LOG{'
    monkeypatch.setattr(logic.urllib.request, "urlopen", lambda *args, **kw: Response())
    with caplog.at_level(logging.WARNING, logger="bindicator.alexa.transport"):
        with pytest.raises(logic.BindicatorUnavailable):
            logic.call_api("GET", "/api/v1/status", environ=alexa_test_environment)
    assert "invalid JSON" in caplog.text
    assert "SECRET_NEVER_LOG" not in caplog.text


@pytest.mark.parametrize("acknowledged,expected", [
    (True, "marked the bins as put out"),
    (False, "no active bin reminder"),
])
def test_bins_out_voice_confirmation(acknowledged, expected):
    calls = []
    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True, "acknowledged": acknowledged, "restored": True}
    response = logic.interpret("BinsOutIntent", api_client=fake)
    assert expected in response
    assert "Future reminders are still enabled" in response
    assert calls == [("POST", "/api/v1/bins-out", {})]


def test_bins_out_never_claims_restoration_when_api_failed():
    assert "couldn't reach" in logic.handle_intent(
        "BinsOutIntent",
        api_client=lambda *args: {"ok": False, "acknowledged": False},
    )


@pytest.mark.parametrize("intent,title", [
    ("NextCollectionIntent", "Next bin collection"),
    ("StatusIntent", "Reminder status"),
    ("PauseIntent", "Reminders paused"),
    ("ResumeIntent", "Reminders enabled"),
    ("BinsOutIntent", "Bins put out"),
    ("ShowNextIntent", "Bin light preview"),
])
def test_alexa_card_matches_spoken_result_without_extra_api_call(intent, title):
    speech = "Recycling and Garden Waste, Tuesday 24 November."
    assert logic.card_content(intent, speech) == (title, speech)


def test_alexa_card_is_plain_text_and_bounded():
    spoken = "Bins & <lights> " + "x" * 2000
    title, content = logic.card_content("NextCollectionIntent", spoken)
    assert title == "Next bin collection"
    assert content.startswith("Bins & <lights> ")
    assert len(content) == 1000


def test_skill_lambda_attaches_simple_card_to_spoken_response(monkeypatch):
    pytest.importorskip("ask_sdk_model")
    pytest.importorskip("ask_sdk_core")
    from ask_sdk_model.ui import SimpleCard
    import importlib
    from unittest.mock import Mock

    monkeypatch.setenv("ALEXA_SKILL_ID", "amzn1.ask.skill.11111111-1111-1111-1111-111111111111")
    lambda_function = importlib.import_module("alexa.lambda_function")

    handler_input = Mock()
    handler_input.request_envelope.request.intent.name = "NextCollectionIntent"
    handler_input.request_envelope.request.intent.slots = {}
    handler_input.response_builder.speak.return_value = handler_input.response_builder
    handler_input.response_builder.set_card.return_value = handler_input.response_builder
    handler_input.response_builder.set_should_end_session.return_value = handler_input.response_builder
    handler_input.response_builder.response = "response"
    original = lambda_function.handle_intent
    lambda_function.handle_intent = lambda intent, slots: "Your next collection is Recycling."
    try:
        assert lambda_function.KnownIntentHandler().handle(handler_input) == "response"
    finally:
        lambda_function.handle_intent = original
    card = handler_input.response_builder.set_card.call_args.args[0]
    assert isinstance(card, SimpleCard)
    assert card.title == "Next bin collection"
    assert card.content == "Your next collection is Recycling."
