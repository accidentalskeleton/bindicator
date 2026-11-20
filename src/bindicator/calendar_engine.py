"""Shared refresh, cache and failure policy for all collection providers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import fcntl
import json
import logging
import time

from icalendar import Calendar

from .app import BindicatorError, atomic_bytes_save
from .calendar_providers import get_provider

LOG = logging.getLogger("bindicator.calendar_engine")
GRACE_SECONDS = 72 * 3600

# Existing file names are deliberately retained to migrate in-place.
FILES = {
    "ical": ("ical-source.ics", "ical-refresh.json", "ical-refresh.lock"),
    "council": ("north-yorkshire-v2.ics", "north-yorkshire-refresh.json",
                "north-yorkshire-refresh.lock"),
}


def _names(source: str):
    return FILES.get(source, (
        f"calendar-{source}.ics", f"calendar-{source}.json",
        f"calendar-{source}.lock",
    ))


def _cached(source: str, config: dict, state_dir: Path):
    cache, meta, _ = _names(source)
    try:
        details = json.loads((state_dir / meta).read_text(encoding="utf-8"))
        if details.get("identity") != get_provider(source).identity(config):
            return None
        updated = details["updated_at"]
        if type(updated) not in (float, int) or updated < 0:
            return None
        return {"data": (state_dir / cache).read_bytes(), "updated_at": updated}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def cache_status(source: str, config: dict, state_dir: Path) -> dict:
    interval_days = config.get("calendar_refresh", {}).get(
        "days", config.get("north_yorkshire", {}).get("refresh_days", 7)
    )
    cached = _cached(source, config, state_dir)
    stamp = cached["updated_at"] if cached else None
    now = time.time()
    age = max(0, now - stamp) if stamp is not None else None
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts is not None else None
    return {
        "last_success": iso(stamp),
        "next_due": iso(stamp + interval_days * 86400) if stamp is not None else None,
        "refresh_days": interval_days,
        "stale": age is None or age >= interval_days * 86400,
        "within_grace": age is not None and age <= interval_days * 86400 + GRACE_SECONDS,
    }


def refresh_source(source: str, config: dict, state_dir: Path, *, force: bool = False) -> dict:
    provider = get_provider(source)
    if not provider.configured(config):
        raise BindicatorError(f"{provider.name} is not configured.")
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_path, meta_path, lock_name = _names(source)
    with (state_dir / lock_name).open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        cached = _cached(source, config, state_dir)
        now = time.time()
        interval = cache_status(source, config, state_dir)["refresh_days"] * 86400
        if not force and cached and now - cached["updated_at"] < interval:
            return {**cache_status(source, config, state_dir), "refreshed": False}
        try:
            data = provider.fetch(config, state_dir)
            if not isinstance(data, bytes) or len(data) > 2_000_000:
                raise ValueError("Invalid calendar response.")
            parsed = Calendar.from_ical(data)
            if not any(component.name == "VEVENT" for component in parsed.walk()):
                raise ValueError("The calendar contains no collection events.")
            atomic_bytes_save(state_dir / cache_path, data)
            stamp = time.time()
            atomic_bytes_save(state_dir / meta_path, (json.dumps({
                "identity": provider.identity(config),
                "updated_at": stamp,
            }) + "\n").encode("utf-8"))
            return {**cache_status(source, config, state_dir), "refreshed": True}
        except (OSError, ValueError, BindicatorError) as exc:
            LOG.warning("Calendar provider %s failed (%s).", source, type(exc).__name__)
            if not force and cached and 0 <= now - cached["updated_at"] <= interval + GRACE_SECONDS:
                return {**cache_status(source, config, state_dir), "refreshed": False,
                        "error": f"{provider.name} refresh failed; cached dates remain in use."}
            raise BindicatorError(
                f"{provider.name} refresh failed; existing cached dates were preserved."
            ) from exc


def calendar_data(source: str, config: dict, state_dir: Path) -> bytes:
    refresh_source(source, config, state_dir)
    cached = _cached(source, config, state_dir)
    if cached is None:
        raise BindicatorError("No verified calendar data available.")
    return cached["data"]
