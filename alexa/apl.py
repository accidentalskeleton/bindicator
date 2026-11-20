"""Echo Show view model, derived only from authenticated Bindicator API data.

Matches the existing web dashboard's bin classification and vector palette.
No credentials, raw calendar URLs, bridge IDs, or custom remote artwork.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DOCUMENT_TOKEN = "bindicator-next-collection-v1"
LOCAL_ZONE = ZoneInfo("Europe/London")
CATEGORY_PATTERNS = (
    ("garden", r"garden|green waste"),
    ("recycling", r"recycl|paper|cardboard|glass|plastic|cans"),
    ("household", r"household|refuse|general waste|rubbish|residual|black bin"),
)


def document() -> dict:
    """Read the bundled APL document without relying on a working directory."""
    return json.loads(Path(__file__).with_name("echo_show.json").read_text(encoding="utf-8"))


def category(title: str) -> str:
    name = title.casefold()
    for kind, pattern in CATEGORY_PATTERNS:
        if re.search(pattern, name):
            return kind
    return "other"


def presentation(next_collection: dict, status: dict, *, today: date | None = None) -> dict:
    """Produce bounded, display-safe fields from real API responses."""
    if today is None:
        today = datetime.now(LOCAL_ZONE).date()
    raw_date = next_collection.get("date")
    try:
        collection_date = date.fromisoformat(raw_date)
    except (TypeError, ValueError):
        collection_date = None

    if collection_date is None:
        date_label, countdown = "Not available", "Check your collection calendar"
    else:
        date_label = collection_date.strftime("%A %-d %B")
        days = (collection_date - today).days
        if days == 0:
            countdown = "Collection day today"
        elif days == 1:
            countdown = "Tomorrow"
        elif days > 1:
            countdown = f"In {days} days"
        else:
            countdown = "Collection date has passed"

    titles = next_collection.get("collections")
    if not isinstance(titles, list):
        titles = []
    bins = []
    for title in titles[:8]:
        if isinstance(title, str) and title.strip():
            safe_title = title.strip()[:90]
            kind = category(safe_title)
            bins.append({"title": safe_title, "graphic": "Bin" + kind.title()})
    if not bins:
        bins = [{"title": "No collection types available", "graphic": "BinOther"}]

    paused = status.get("paused") is True
    active = bool(status.get("indicator_count")) or bool(status.get("manual_until"))
    acknowledged = bool(collection_date and status.get("acknowledged_date") == collection_date.isoformat())
    can_acknowledge = active and not acknowledged and not paused
    if acknowledged:
        detail = "This collection has been acknowledged."
    elif active:
        detail = "Hue indicators currently active."
    elif paused:
        detail = "Reminders are paused."
    else:
        detail = "Reminders enabled. No active bin alert."
    return {
        "binbuddy": {
            "status": "PAUSED" if paused else "REMINDERS ON",
            "dateLabel": date_label,
            "countdown": countdown,
            "bins": bins,
            "detail": detail,
            "canAcknowledge": can_acknowledge,
            "buttonLabel": "I've put the bins out" if can_acknowledge else (
                "Already acknowledged" if acknowledged else "No active reminder"
            ),
        }
    }


def valid_bins_out_event(request) -> bool:
    """Only the fixed, known action from our own rendered document is accepted."""
    source = getattr(request, "source", None)
    return (
        getattr(request, "token", None) == DOCUMENT_TOKEN
        and getattr(request, "arguments", None) == ["bins-out"]
        and isinstance(source, dict)
        and source.get("id") == "binsOutButton"
    )
