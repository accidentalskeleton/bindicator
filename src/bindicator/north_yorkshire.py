"""North Yorkshire Council bin collection adapter (read-only, UPRN-based).

The council currently serves an address-selected Drupal bin calendar through
a POST followed by a same-site AJAX GET. Fail closed on unexpected content,
unrecognised collection types or redirects to other hosts.
"""
from __future__ import annotations

from datetime import datetime, date
from urllib.parse import urlsplit
import re

import requests
from bs4 import BeautifulSoup

LOOKUP_URL = "https://www.northyorks.gov.uk/bin-calendar/lookup"
EXPECTED_HOST = "www.northyorks.gov.uk"

# These titles intentionally match existing Bindicator calendar event mappings.
TITLES = {
    "household": "BinDay - Household waste",
    "recycling": "BinDay - Recycling",
    "garden": "BinDay - Garden Waste",
}


def validate_uprn(uprn: str) -> str:
    if not isinstance(uprn, str) or not re.fullmatch(r"[0-9]{8,12}", uprn):
        raise ValueError("Enter an 8–12 digit North Yorkshire property UPRN.")
    return uprn


def collection_title(raw: str) -> str:
    """Map identifiable council labels to existing Bindicator event names.

    Ambiguous/unrecognised labels are refused, never silently mapped.
    """
    label = " ".join(raw.casefold().split())
    if any(token in label for token in ("garden waste", "green waste", "garden bin")):
        return TITLES["garden"]
    if any(token in label for token in ("recycl", "paper", "cardboard", "glass", "plastic", "cans")):
        return TITLES["recycling"]
    if any(token in label for token in ("household", "refuse", "general waste", "rubbish", "residual", "black bin")):
        return TITLES["household"]
    raise ValueError("Unrecognised council collection type; review the council calendar before activating.")


def _safe_url(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https" and parts.hostname == EXPECTED_HOST
        and parts.port in (None, 443) and parts.username is None
        and parts.password is None and not parts.query and not parts.fragment
        and parts.path.startswith("/bin-calendar/")
    )


def fetch_collections(uprn: str, *, session=None) -> list[dict]:
    """Return sorted, deduplicated collections. Network calls use bounded timeouts."""
    validate_uprn(uprn)
    session = session or requests.Session()
    try:
        response = session.post(
            LOOKUP_URL,
            data={"selected_address": uprn, "submit": "Continue",
                  "form_id": "bin_calendar_lookup_form"},
            timeout=(5, 20), allow_redirects=False,
        )
        # requests won't follow this POST automatically: validate every redirect.
        if response.status_code in (301, 302, 303, 307, 308):
            from urllib.parse import urljoin
            target = urljoin(LOOKUP_URL, response.headers.get("Location", ""))
        elif response.status_code == 200:
            target = response.url
        else:
            response.raise_for_status()
            raise ValueError("Unexpected council lookup response.")
        if not _safe_url(target):
            raise ValueError("Unexpected council redirect; refusing off-site request.")
        ajax_url = target.rstrip("/") + "/ajax"
        if not _safe_url(ajax_url):
            raise ValueError("Invalid council AJAX endpoint.")
        result = session.get(ajax_url, timeout=(5, 20), allow_redirects=False)
        if result.is_redirect or not _safe_url(result.url):
            raise ValueError("Unexpected council AJAX redirect.")
        result.raise_for_status()
        if len(result.content) > 1_000_000:
            raise ValueError("Council response exceeds size limit.")
        payload = result.json()
    except requests.RequestException as exc:
        raise ValueError("North Yorkshire Council lookup unavailable.") from exc
    except (ValueError, TypeError) as exc:
        if str(exc).startswith(("Unexpected council redirect", "Unexpected council AJAX redirect",
                                "Invalid council AJAX endpoint")):
            raise
        raise ValueError("North Yorkshire Council did not return usable collection data.") from exc
    if not isinstance(payload, list):
        raise ValueError("Unexpected council AJAX format.")
    html = next(
        (item["data"] for item in payload
         if isinstance(item, dict) and isinstance(item.get("data"), str)
         and 'upcoming-collection' in item["data"]),
        None,
    )
    if not html:
        raise ValueError("No council collection calendar found for the configured property.")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("#upcoming-collection table tbody")
    if table is None:
        raise ValueError("Council collection table is missing.")
    records = {}
    for row in table.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            raise ValueError("Unexpected council collection row.")
        raw_date = cells[0].get_text(" ", strip=True)
        try:
            day = datetime.strptime(raw_date, "%d %B %Y").date()
        except ValueError as exc:
            raise ValueError("Unrecognised council collection date.") from exc
        for label in cells[2].stripped_strings:
            name = " ".join(label.split())
            title = collection_title(name)
            records[(day, title)] = {"date": day.isoformat(), "type": name, "title": title}
    if not records:
        raise ValueError("Council collection calendar contains no dates.")
    return [records[k] for k in sorted(records)]


def resolve_mappings(records: list[dict], configured: dict) -> list[dict]:
    """Resolve council types onto the user's existing calendar event titles.

    Matching is semantic by bin type, not punctuation (hyphen/en dash) or
    the exact event prefix. Multiple mappings for one type are ambiguous
    and will never be chosen silently.
    """
    by_type = {}
    for event in configured:
        try:
            canonical = collection_title(event)
        except ValueError:
            continue
        by_type.setdefault(canonical, []).append(event)
    result = []
    for record in records:
        matches = by_type.get(record["title"], [])
        if not matches or len({configured[title] for title in matches}) != 1:
            raise ValueError(
                "Council type has no unique calendar colour mapping: "
                + record["type"] + ". Map matching events consistently to one colour."
            )
        # Multiple synonyms are safe when they all map to the same colour.
        chosen = record["title"] if record["title"] in matches else matches[0]
        result.append({**record, "title": chosen})
    return result


def to_ical(records: list[dict]) -> bytes:
    """Generate a local iCalendar using the established event-title mappings."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bindicator//North Yorkshire//EN"]
    for i, item in enumerate(records):
        day = date.fromisoformat(item["date"])
        title = item["title"]
        if collection_title(title) not in TITLES.values() or any(ord(c) < 32 or c in ";," for c in title):
            raise ValueError("Unsupported council collection title.")
        lines.extend([
            "BEGIN:VEVENT", f"UID:nyc-{day:%Y%m%d}-{i}@bindicator.local",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"SUMMARY:{title}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
