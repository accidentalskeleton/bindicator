"""Calendar provider contract, canonical collection events, and built-in registry.

Providers only fetch and normalise collections. They do not control Hue,
choose indicator colours, write settings or decide when to refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo
import hashlib
import json

from icalendar import Calendar
import recurring_ical_events

UK = ZoneInfo("Europe/London")


@dataclass(frozen=True, order=True)
class CollectionEvent:
    """Provider-neutral collection occurrence; dates use UK local calendar days."""
    date: date
    title: str
    source_id: str
    original_title: str
    event_id: str = ""

    def __post_init__(self):
        if not isinstance(self.date, date) or isinstance(self.date, datetime):
            raise ValueError("Collection date must be a date.")
        if not self.title or not self.source_id or not self.original_title:
            raise ValueError("A collection must include a title and source.")
        if any(ord(c) < 32 for c in self.title):
            raise ValueError("Invalid collection title.")


class CalendarProvider(Protocol):
    id: str
    name: str
    config_fields: tuple[dict, ...]

    def configured(self, config: dict) -> bool: ...
    def identity(self, config: dict) -> str: ...
    def fetch(self, config: dict, state_dir) -> bytes: ...
    def events(self, config: dict, state_dir, start: date, end: date) -> list[CollectionEvent]: ...
    def discover_titles(self, config: dict, state_dir) -> list[str]: ...


def ical_events(data: bytes, source_id: str, start: date, end: date) -> list[CollectionEvent]:
    """Expand recurrence, cancellations and timezones once for every iCal source."""
    if end <= start:
        return []
    calendar = Calendar.from_ical(data)
    expanded = recurring_ical_events.of(calendar).between(start, end)
    result = []
    seen = set()
    for item in expanded:
        if str(item.get("STATUS", "")).upper() == "CANCELLED":
            continue
        title = str(item.get("SUMMARY", "")).strip()
        if not title:
            continue
        when = item.decoded("DTSTART")
        day = when.astimezone(UK).date() if isinstance(when, datetime) else when
        if start <= day < end:
            event = CollectionEvent(
                date=day, title=title, source_id=source_id,
                original_title=title, event_id=str(item.get("UID", "")),
            )
            if event not in seen:
                seen.add(event)
                result.append(event)
    return sorted(result, key=lambda item: item.date)


@dataclass(frozen=True)
class ICalendarProvider:
    id: str = "ical"
    name: str = "iCalendar (iCal)"
    config_fields: tuple[dict, ...] = (
        {"key": "url", "label": "Private HTTPS iCalendar URL", "type": "secret_url"},
    )

    def configured(self, config):
        import os
        return bool(os.environ.get("BINDICATOR_ICAL_URL"))

    def identity(self, config):
        import os
        url = os.environ.get("BINDICATOR_ICAL_URL", "")
        return hashlib.sha256(url.encode()).hexdigest()

    def fetch(self, config, state_dir):
        from .app import Bindicator
        return Bindicator(config, state_dir).zoho_calendar_data(allow_cache=False)

    def events(self, config, state_dir, start, end):
        # Use a live read for provider tests, not a cached active-source feed.
        return ical_events(self.fetch(config, state_dir), self.id, start, end)

    def discover_titles(self, config, state_dir):
        from .app import Bindicator
        data = Bindicator(config, state_dir).zoho_calendar_data()
        calendar = Calendar.from_ical(data)
        return sorted({
            str(item.get("SUMMARY", "")).strip()
            for item in calendar.walk("VEVENT")
            if 0 < len(str(item.get("SUMMARY", "")).strip()) <= 120
        })


@dataclass(frozen=True)
class NorthYorkshireProvider:
    id: str = "council"
    name: str = "North Yorkshire Council"
    config_fields: tuple[dict, ...] = (
        {"key": "uprn", "label": "Property UPRN", "type": "secret_text"},
    )

    def configured(self, config):
        return bool(config.get("north_yorkshire", {}).get("uprn"))

    def identity(self, config):
        payload = json.dumps(
            [config["north_yorkshire"]["uprn"], config["calendar"]["events"]],
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def fetch_records(self, config):
        from . import north_yorkshire
        return north_yorkshire.fetch_collections(config["north_yorkshire"]["uprn"])

    def fetch(self, config, state_dir):
        from . import north_yorkshire
        return north_yorkshire.to_ical(north_yorkshire.resolve_mappings(
            self.fetch_records(config), config["calendar"]["events"],
        ))

    def discover_titles(self, config, state_dir):
        return sorted({record["title"] for record in self.fetch_records(config)})

    def events(self, config, state_dir, start, end):
        records = self.fetch_records(config)
        result = set()
        for entry in records:
            day = date.fromisoformat(entry["date"])
            if start <= day < end:
                result.add(CollectionEvent(
                    date=day, title=entry["title"], source_id=self.id,
                    original_title=entry["type"],
                    event_id=f"{day.isoformat()}:{entry['title']}",
                ))
        return sorted(result)


# Built-in adapters are trusted. Additional providers must be explicitly
# installed by the machine administrator via a Python package entry point.
PROVIDERS: dict[str, CalendarProvider] = {
    "council": NorthYorkshireProvider(),
    "ical": ICalendarProvider(),
}
_PLUGINS_LOADED = False


def register_provider(provider: CalendarProvider) -> None:
    """Register one locally trusted adapter, never an arbitrary import string."""
    provider_id = getattr(provider, "id", None)
    if (not isinstance(provider_id, str) or not provider_id.isidentifier()
            or provider_id in PROVIDERS):
        raise ValueError("Provider IDs must be unique Python identifiers.")
    if not isinstance(getattr(provider, "name", None), str) or not provider.name:
        raise ValueError("Provider must supply a display name.")
    for method in ("configured", "identity", "fetch", "events", "discover_titles"):
        if not callable(getattr(provider, method, None)):
            raise ValueError(f"Provider is missing {method}().")
    if not isinstance(getattr(provider, "config_fields", None), (tuple, list)):
        raise ValueError("Provider must declare its configuration fields.")
    PROVIDERS[provider_id] = provider


def load_installed_providers() -> None:
    """Discover trusted Python packages installed in Bindicator's environment.

    Only entry points in the explicit namespace are loaded. Calendar responses,
    browser input and YAML cannot provide module paths or import code.
    Installing a provider grants it Python code execution: administrators
    should install only packages they trust.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    from importlib.metadata import entry_points
    import inspect
    import logging
    log = logging.getLogger("bindicator.providers")
    for entry in entry_points(group="bindicator.calendar_providers"):
        try:
            plugin = entry.load()
            provider = plugin() if inspect.isclass(plugin) else plugin
            register_provider(provider)
        except Exception as exc:
            log.warning("Could not register installed provider %s (%s).",
                        entry.name, type(exc).__name__)


def registered_providers() -> tuple[CalendarProvider, ...]:
    load_installed_providers()
    return tuple(PROVIDERS.values())


def get_provider(source_id: str) -> CalendarProvider:
    load_installed_providers()
    try:
        return PROVIDERS[source_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("Unknown calendar provider.") from exc


def active_source(config: dict) -> str:
    # Backward-compatible migration from north_yorkshire.enabled.
    return config.get("calendar_source") or (
        "council" if config.get("north_yorkshire", {}).get("enabled") else "ical"
    )


def group_events(events: list[CollectionEvent], *, limit: int = 12) -> list[dict]:
    grouped: dict[date, list[str]] = {}
    for event in sorted(events):
        titles = grouped.setdefault(event.date, [])
        if event.original_title not in titles:
            titles.append(event.original_title)
    return [{"date": day.isoformat(), "collections": grouped[day]}
            for day in sorted(grouped)[:limit]]
