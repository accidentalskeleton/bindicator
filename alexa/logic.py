"""Testable Bindicator Alexa intent logic and authenticated API transport.

This module has no Alexa SDK dependency, so its network and speech handling
can be tested offline. Only predeclared operations can cross the API.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from html import escape
from urllib.parse import urlsplit


LOG = logging.getLogger("bindicator.alexa.transport")


class AlexaConfigError(Exception):
    pass


class BindicatorUnavailable(Exception):
    pass


def transport_config(environ=None):
    env = os.environ if environ is None else environ
    url = env.get("BINDICATOR_API_URL", "").rstrip("/")
    token = env.get("BINDICATOR_API_TOKEN", "")
    if not url or not url.startswith("https://"):
        raise AlexaConfigError("HTTPS Bindicator API URL is required.")
    parsed = urlsplit(url)
    if (
        parsed.username or parsed.password or not parsed.hostname
        or parsed.query or parsed.fragment or parsed.path
    ):
        raise AlexaConfigError("Invalid API hostname.")
    if len(token) < 32 or any(x.isspace() for x in token):
        raise AlexaConfigError("Invalid Bindicator API token.")
    cf_id = env.get("CF_ACCESS_CLIENT_ID", "")
    cf_secret = env.get("CF_ACCESS_CLIENT_SECRET", "")
    if not cf_id or not cf_secret:
        raise AlexaConfigError("Cloudflare Access service credentials required.")
    return url, token, cf_id, cf_secret


def call_api(method: str, path: str, payload: dict | None = None, *, environ=None) -> dict:
    """Call only the permitted Bindicator endpoints, never a caller-defined URL."""
    permitted = {
        ("GET", "/api/v1/status"),
        ("GET", "/api/v1/collections/next"),
        ("POST", "/api/v1/pause"),
        ("POST", "/api/v1/resume"),
        ("POST", "/api/v1/toggle"),
        ("POST", "/api/v1/alerts/next"),
        ("POST", "/api/v1/bins-out"),
    }
    if (method, path) not in permitted:
        raise ValueError("Unknown Bindicator API action.")
    try:
        url, token, cf_id, cf_secret = transport_config(environ)
    except AlexaConfigError:
        # Do not interpolate invalid configuration values or exception text.
        LOG.error("Bindicator Alexa API configuration invalid")
        raise
    headers = {
        "Authorization": "Bearer " + token,
        "CF-Access-Client-Id": cf_id,
        "CF-Access-Client-Secret": cf_secret,
        "Accept": "application/json",
    }
    body = None
    if method == "POST":
        body = json.dumps(payload if payload is not None else {}).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url + path, data=body, method=method, headers=headers,
    )
    try:
        # The Lambda needs a rapid response to fit Alexa's response budget.
        with urllib.request.urlopen(request, timeout=4) as response:
            if response.status != 200:
                LOG.warning("Bindicator Alexa API unexpected HTTP status=%d", response.status)
                raise BindicatorUnavailable("API did not return success.")
            raw = response.read(16385)
            if len(raw) > 16384:
                LOG.warning("Bindicator Alexa API response exceeded size limit")
                raise BindicatorUnavailable("Unexpected API response size.")
        data = json.loads(raw)
        if not isinstance(data, dict):
            LOG.warning("Bindicator Alexa API response was not a JSON object")
            raise BindicatorUnavailable("Unexpected API response format.")
        return data
    except urllib.error.HTTPError as exc:
        # Never log HTTPError itself: exception strings can contain request URLs.
        # Cloudflare Access typically returns HTML, the application API JSON.
        content_type = exc.headers.get_content_type() if exc.headers else ""
        source = "html" if content_type == "text/html" else (
            "json" if content_type == "application/json" else "other"
        )
        LOG.warning("Bindicator Alexa API HTTP failure status=%d response_type=%s",
                    exc.code, source)
        raise BindicatorUnavailable("Bindicator API unavailable.") from None
    except (TimeoutError, OSError, urllib.error.URLError) as exc:
        # Do not include exception details: some include the target URL.
        reason = getattr(exc, "reason", None)
        timeout = isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError)
        LOG.warning("Bindicator Alexa API network failure kind=%s",
                    "timeout" if timeout else "connection")
        raise BindicatorUnavailable("Bindicator API unavailable.") from None
    except ValueError:
        LOG.warning("Bindicator Alexa API returned invalid JSON")
        raise BindicatorUnavailable("Bindicator API unavailable.") from None


def _speech_names(items: list[str]) -> str:
    names = [str(x).strip() for x in items if isinstance(x, str) and str(x).strip()]
    if not names:
        return "the bins"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _friendly_date(iso: str) -> str:
    try:
        day = date.fromisoformat(iso)
    except (ValueError, TypeError):
        return "the next collection day"
    # "Tuesday the 17th of November", natural in en-GB.
    n = day.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1:"st", 2:"nd", 3:"rd"}.get(n % 10, "th")
    return f"{day:%A} the {n}{suffix} of {day:%B}"


def duration_seconds(slots: dict | None) -> int | None:
    """Strictly parse an optional positive-number Alexa slot.

    The interaction model uses a single AMAZON.NUMBER slot measured in
    seconds. A missing slot returns None so the caller asks for a duration
    or an explicitly persistent command. Malformed/out-of-range slots are
    rejected, never silently interpreted as a persistent alert.
    """
    item = (slots or {}).get("duration")
    if item is None:
        return None
    raw = item.get("value") if isinstance(item, dict) else item
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,2}", raw):
        raise ValueError("Please choose between one and sixty seconds.")
    seconds = int(raw)
    if not 1 <= seconds <= 60:
        raise ValueError("Please choose between one and sixty seconds.")
    return seconds


def interpret(intent: str, *, slots: dict | None = None, api_client=call_api) -> str:
    """Map Alexa intent to a fixed API action and concise spoken confirmation."""
    if intent == "NextCollectionIntent":
        result = api_client("GET", "/api/v1/collections/next")
        types = _speech_names(result.get("collections", []))
        when = _friendly_date(result.get("date", ""))
        return f"Your next collection is {types}, on {when}."

    if intent == "StatusIntent":
        result = api_client("GET", "/api/v1/status")
        if result.get("paused") is True:
            return "Bin reminders are paused."
        if result.get("paused") is False:
            return "Bin reminders are enabled."
        raise BindicatorUnavailable("Invalid status.")

    if intent in ("PauseIntent", "ResumeIntent", "ToggleIntent"):
        action = {
            "PauseIntent": "pause",
            "ResumeIntent": "resume",
            "ToggleIntent": "toggle",
        }[intent]
        result = api_client("POST", "/api/v1/" + action, {})
        if result.get("ok") is not True:
            raise BindicatorUnavailable("Control action failed.")
        if action == "pause":
            return "Bin reminders paused. Previous lighting restored where unchanged."
        if action == "resume":
            return "Bin reminders enabled."
        # Toggle needs actual result, not a guess about the prior state.
        status = api_client("GET", "/api/v1/status")
        if status.get("paused") is True:
            return "Bin reminders paused."
        if status.get("paused") is False:
            return "Bin reminders enabled."
        raise BindicatorUnavailable("Could not confirm toggle state.")

    if intent == "BinsOutIntent":
        result = api_client("POST", "/api/v1/bins-out", {})
        if result.get("ok") is not True or type(result.get("acknowledged")) is not bool:
            raise BindicatorUnavailable("Bin acknowledgement failed.")
        if result["acknowledged"]:
            return (
                "Thanks, I've marked the bins as put out and restored the "
                "indicator lights where unchanged. Future reminders are still enabled."
            )
        return "There's no active bin reminder to clear. Future reminders are still enabled."

    if intent == "ShowNextIntent":
        seconds = duration_seconds(slots)
        # Persistent activation is intentionally a separate intent to avoid
        # an accidentally-missing duration triggering a week-long alert.
        if seconds is None:
            return (
                "To keep the bin colours on until collection day, say "
                "show the bins until collection day. "
                "Or ask to show them for ten seconds."
            )
        result = api_client("POST", "/api/v1/alerts/next", {"seconds": seconds})
        if result.get("ok") is not True:
            raise BindicatorUnavailable("Preview could not be started.")
        return (
            f"Showing the next bins for {seconds} seconds. "
            "The lights will return to their previous settings afterwards."
        )

    if intent == "ShowPersistentIntent":
        result = api_client("POST", "/api/v1/alerts/next", {})
        if result.get("ok") is not True:
            raise BindicatorUnavailable("Reminder could not be started.")
        return (
            "Showing the next collection colours until collection morning. "
            "You can ask me to pause reminders to restore the lights."
        )

    raise ValueError("Unknown Alexa intent.")



def card_content(intent: str, spoken_text: str) -> tuple[str, str]:
    """Plain-text Alexa companion card matching the actual spoken result.

    Use only the already computed speech; never make another API request or
    expose internal identifiers, credentials, calendar URLs or Hue state.
    """
    titles = {
        "NextCollectionIntent": "Next bin collection",
        "StatusIntent": "Reminder status",
        "PauseIntent": "Reminders paused",
        "ResumeIntent": "Reminders enabled",
        "ToggleIntent": "Reminder status",
        "BinsOutIntent": "Bins put out",
        "ShowNextIntent": "Bin light preview",
        "ShowPersistentIntent": "Bin lights",
    }
    if not isinstance(spoken_text, str):
        raise ValueError("Card text must be plain text.")
    title = titles.get(intent, "Bin Dicator")
    # The existing transport limits source responses to 16 KiB. Keep the
    # Alexa card concise, even when an external calendar title is unusually long.
    content = spoken_text[:1000]
    return title, content


def speech_xml(text: str) -> str:
    """Guard spoken responses against markup injection from calendar titles."""
    return escape(text, quote=True)


def handle_intent(intent: str, *, slots: dict | None = None, api_client=call_api) -> str:
    try:
        return interpret(intent, slots=slots, api_client=api_client)
    except ValueError as exc:
        return str(exc)
    except (AlexaConfigError, BindicatorUnavailable):
        return "I couldn't reach Bin Indicator. Please try again in a moment."
