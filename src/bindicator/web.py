"""LAN-only Bindicator management UI. Never expose this service through Tunnel.

Explicit private IPv4 binding, TLS, Host validation and
Origin/CSRF checks isolate configuration changes from the loopback Alexa API.
"""
from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import logging
import os
import re
import ssl
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from io import StringIO

from ruamel.yaml import YAML

from .app import DEFAULT_CONFIG, DEFAULT_SECRETS, DEFAULT_STATE_DIR, BindicatorError, load_config, load_secrets
from .api import BindicatorAPI
from .bridge_discovery import available_bridges, discover_bridges
from .bridge_setup import BRIDGE_NAME, _atomic_text, save_bridge_config, save_bridge_key, remove_bridge_config_and_key
from .bridges import BridgePool
from .light_selection import light_capability_label, write_selected_config
from .setup import _check_no_active_reminder

LOG = logging.getLogger("bindicator.web")
DEFAULT_PORT = 18051
MAX_BODY = 16384


def private_host(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise BindicatorError("Specify the machine's private LAN IPv4 address.") from exc
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        raise BindicatorError("The web interface requires a non-loopback private LAN IPv4 address.")
    return str(address)


def update_mode(path: Path, mode: str) -> None:
    if mode not in ("spread", "priority", "cycle"):
        raise ValueError("Mode must be spread, priority or cycle.")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    with path.open(encoding="utf-8") as src:
        doc = yaml.load(src)
    if not isinstance(doc, dict) or not isinstance(doc.get("hue"), dict):
        raise BindicatorError("Missing Hue configuration.")
    doc["hue"]["mode"] = mode
    out = StringIO()
    yaml.dump(doc, out)
    _atomic_text(path, out.getvalue())


def update_configuration(path: Path, *, section: str, value) -> None:
    """Update only a validated section; preserve YAML comments and other keys."""
    import re
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    with path.open(encoding="utf-8") as source:
        doc = yaml.load(source)
    if not isinstance(doc, dict):
        raise BindicatorError("Invalid configuration.")
    if section == "colours":
        # Accept the original palette-only API as well as a coordinated
        # palette/rename/priority update. All related fields are committed
        # together in one atomic YAML replacement.
        bundle = value if isinstance(value, dict) and set(value) in ({"colours", "renames", "priority"}, {"colours", "renames", "priority", "events"}) else None
        palette = bundle["colours"] if bundle is not None else value
        renames = bundle["renames"] if bundle is not None else {}
        requested_order = bundle["priority"] if bundle is not None else None
        if not isinstance(palette, dict) or not 1 <= len(palette) <= 5:
            raise ValueError("One to five colours are required.")
        for name, xy in palette.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
                raise ValueError("Colour names must be lowercase identifiers.")
            if not isinstance(xy, dict) or set(xy) != {"x", "y"}:
                raise ValueError("Provide x and y for each colour.")
            x, y = xy["x"], xy["y"]
            if (type(x) not in (float, int) or type(y) not in (float, int)
                or not 0 < x < 1 or not 0 < y < 1 or x + y >= 1):
                raise ValueError("CIE xy values must be inside the colour triangle.")
        original = doc.get("colors", {})
        if not isinstance(original, dict) or not original:
            raise BindicatorError("Existing colour configuration is invalid.")
        if (not isinstance(renames, dict)
            or any(not isinstance(old, str) or not isinstance(new, str)
                   or old not in original or old == new or new not in palette
                   for old, new in renames.items())
            or len(set(renames.values())) != len(renames)):
            raise ValueError("Invalid or duplicate colour rename.")
        # A rename must not silently collide with an existing, unrenamed
        # colour. A client must explicitly remove/rename both if appropriate.
        if any(new in original and new not in renames for new in renames.values()):
            raise ValueError("Renamed colour conflicts with an existing colour.")
        for name in original:
            if name in palette and name in renames:
                raise ValueError("A renamed colour cannot also retain its old name.")
        events = bundle.get("events", doc.get("calendar", {}).get("events", {})) if bundle is not None else doc.get("calendar", {}).get("events", {})
        if not isinstance(events, dict):
            raise BindicatorError("Invalid calendar events.")
        if len(events) > 100 or any(not isinstance(title, str) or not 1 <= len(title.strip()) <= 180 for title in events):
            raise ValueError("Invalid calendar event mappings.")
        updated_events = {}
        for title, colour in events.items():
            resolved = colour if bundle is not None and "events" in bundle else renames.get(colour, colour)
            if resolved not in palette:
                raise ValueError(
                    f"Cannot delete colour {colour!r} while used by calendar event {title!r}. "
                    "Reassign or remove the event first."
                )
            updated_events[title] = resolved
        old_priority = doc.get("priority", list(original))
        if not isinstance(old_priority, list):
            raise BindicatorError("Invalid existing colour priority.")
        derived = []
        for old in old_priority:
            name = renames.get(old, old)
            if name in palette and name not in derived:
                derived.append(name)
        derived.extend(name for name in palette if name not in derived)
        if requested_order is not None:
            if (not isinstance(requested_order, list)
                or len(requested_order) != len(palette)
                or any(not isinstance(name, str) for name in requested_order)
                or set(requested_order) != set(palette)):
                raise ValueError("Priority must include each colour exactly once.")
            derived = requested_order
        doc["colors"] = palette
        doc["priority"] = derived
        doc["calendar"]["events"] = updated_events
    elif section == "events":
        if not isinstance(value, dict) or len(value) > 100:
            raise ValueError("Expected at most 100 calendar mappings.")
        for title, colour in value.items():
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 180:
                raise ValueError("Invalid calendar event title.")
            if not isinstance(colour, str) or colour not in doc["colors"]:
                raise ValueError("Event references an undefined colour.")
        doc["calendar"]["events"] = value
    elif section == "priority":
        if not isinstance(value, list) or set(value) != set(doc["colors"]) or len(value) != len(set(value)):
            raise ValueError("Priority must include each colour exactly once.")
        doc["priority"] = value
    else:
        raise ValueError("Unsupported configuration section.")
    output = StringIO()
    yaml.dump(doc, output)
    _atomic_text(path, output.getvalue())
    # Validate after persistence; the above guards mirror load_config.
    load_config(path)


def calendar_url_present(path: Path) -> bool:
    import re
    text = path.read_text(encoding="utf-8")
    return bool(re.search(r"^\s*(?:export\s+)?BINDICATOR_ICAL_URL\s*=\s*['\\\"]?https://", text, re.M))


def save_calendar_url(path: Path, url: str) -> None:
    """Save a private HTTPS iCalendar feed without exposing it or its token."""
    import re
    from .ical_source import validate_public_ical_url
    validate_public_ical_url(url)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    pattern = re.compile(r"^\s*(?:export\s+)?BINDICATOR_ICAL_URL\s*=")
    # No shell evaluation; quotes in URL values are not accepted.
    if any(c in url for c in ("'", '"', "\\", "#")):
        raise ValueError("Invalid characters in calendar URL.")
    new = 'BINDICATOR_ICAL_URL="' + url + '"\n'
    updated = []
    replaced = False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                updated.append(new)
                replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and not updated[-1].endswith("\n"):
            updated[-1] += "\n"
        updated.append(new)
    _atomic_text(path, "".join(updated), private=True)
    # Drop stale environment value: load_secrets() uses setdefault.
    os.environ.pop("BINDICATOR_ICAL_URL", None)


class Management:
    def __init__(self, config: Path, secrets: Path, state: Path):
        self.config, self.secrets, self.state = config, secrets, state
        self.api = BindicatorAPI(config, secrets, state)

    def _config(self) -> dict:
        config = load_config(self.config)
        load_secrets(self.secrets)
        return config

    def overview(self) -> dict:
        from importlib.metadata import PackageNotFoundError, version
        from .calendar_engine import cache_status
        from .calendar_providers import active_source, registered_providers
        config = self._config()
        pool = BridgePool(config["hue"])
        try:
            application_version = version("bindicator")
        except PackageNotFoundError:
            application_version = "development"
        try:
            from ._build_info import BUILD_COMMIT
        except ImportError:
            BUILD_COMMIT = "unknown"
        return {
            "application_version": application_version,
            "application_commit": BUILD_COMMIT,
            "mode": config["hue"]["mode"],
            "schedule": config["schedule"],
            "bridges": [{"name": n, "host": pool.bridges[n]["host"],
                         "paired": pool.has_key(n)} for n in pool.names],
            "selected": config["hue"]["lights"],
            "colours": list(config["colors"]),
            "colour_xy": config["colors"],
            "priority": config["priority"],
            "calendar_configured": calendar_url_present(self.secrets),
            "active_calendar_source": active_source(config),
            "calendar_providers": [
                {"id": provider.id, "name": provider.name,
                 "configured": provider.configured(config),
                 "fields": [dict(field) for field in provider.config_fields]}
                for provider in registered_providers()
            ],
            "ical": {"configured": calendar_url_present(self.secrets),
                     **cache_status("ical", config, self.state)},
            "calendar_refresh_days": config["calendar_refresh"]["days"],
            "north_yorkshire": {
                "configured": bool(config["north_yorkshire"]["uprn"]),
                "enabled": config["north_yorkshire"]["enabled"],
                **cache_status("council", config, self.state),
            },
            "events": [{"name": name, "colour": color}
                       for name, color in config["calendar"]["events"].items()],
            "status": self.api.status(),
        }

    def calendar_event_options(self) -> dict:
        """Discover event titles through registered adapters, without secrets."""
        from .calendar_providers import registered_providers
        config = self._config()
        options: dict[str, set[str]] = {}
        warnings: list[str] = []
        for title in config["calendar"]["events"]:
            options.setdefault(title, set()).add("Saved mapping")
        for provider in registered_providers():
            if (provider.id == "ical" and
                    (not self.secrets.is_file() or not calendar_url_present(self.secrets))):
                continue
            if not provider.configured(config):
                continue
            try:
                for title in provider.discover_titles(config, self.state):
                    if isinstance(title, str) and 0 < len(title) <= 120:
                        options.setdefault(title, set()).add(
                            "North Yorkshire Council" if provider.id == "council"
                            else "iCalendar" if provider.id == "ical" else provider.name
                        )
            except (OSError, ValueError, BindicatorError) as exc:
                LOG.warning("Cannot discover events from %s (%s).", provider.id,
                            type(exc).__name__)
                warnings.append(f"{provider.name} unavailable")
        return {
            "events": [{"title": title, "sources": sorted(sources)}
                       for title, sources in sorted(options.items(), key=lambda row: row[0].casefold())],
            "warnings": warnings,
        }

    def discovery(self) -> list[dict]:
        config = self._config()
        return available_bridges(config["hue"]["bridges"], discover_bridges())

    def lights(self) -> list[dict]:
        config = self._config()
        pool = BridgePool(config["hue"])
        chosen = {(x["bridge"], x["id"]): x for x in config["hue"]["lights"]}
        result = []
        for name in pool.names:
            if not pool.has_key(name):
                continue
            for light in pool.lights(name):
                if "color" not in light and "gradient" not in light:
                    continue
                rid = light.get("id")
                if not isinstance(rid, str):
                    continue
                result.append({"bridge": name, "id": rid,
                               "name": light.get("metadata", {}).get("name", "Unnamed lamp"),
                               "capability": light_capability_label(light),
                               "gradient_capable": isinstance(light.get("gradient"), dict) and type((light.get("gradient") or {}).get("points_capable")) is int and light["gradient"]["points_capable"] >= 2,
                               "always_gradient": chosen.get((name, rid), {}).get("always_gradient", False),
                               "selected": (name, rid) in chosen})
        return result

    def check_calendar_source(self, body: dict) -> dict:
        """Provider-neutral read-only connectivity test or date preview."""
        from datetime import datetime, timedelta
        from .app import TZ
        from .calendar_providers import get_provider, group_events

        if (set(body) != {"source", "preview"}
                or not isinstance(body["source"], str)
                or type(body["preview"]) is not bool):
            raise ValueError("Choose a calendar provider and a preview flag.")
        provider = get_provider(body["source"])
        config = self._config()
        if not provider.configured(config):
            raise ValueError(f"Configure {provider.name} before testing.")
        today = datetime.now(TZ).date()
        horizon = 3650 if provider.id == "council" else 366
        events = provider.events(config, self.state, today, today + timedelta(days=horizon))
        dates = group_events(events, limit=12)
        count = len({event.date for event in events if event.date >= today})
        return {"ok": True, "source": provider.id, "count": count,
                "dates": dates if body["preview"] else []}

    def refresh_active_calendar(self, body: dict) -> dict:
        if body:
            raise ValueError("Refresh requires an empty JSON object.")
        from .calendar_providers import active_source
        from .calendar_engine import refresh_source
        config = self._config()
        source = active_source(config)
        result = refresh_source(source, config, self.state, force=True)
        return {"ok": True, "source": source, **result}

    def refresh_north_yorkshire(self, body: dict) -> dict:
        """Force a real council download on demand, bypassing the cache."""
        if body:
            raise ValueError("Refresh requires an empty JSON object.")
        from .council_refresh import refresh_council
        result = refresh_council(self._config(), self.state, force=True)
        return {"ok": True, **result}

    def check_north_yorkshire(self, body: dict) -> dict:
        """Read-only council connectivity test: never affects active reminders."""
        if set(body) != {"uprn"} or not isinstance(body["uprn"], str):
            raise ValueError("Expected UPRN input.")
        from .north_yorkshire import fetch_collections, validate_uprn, resolve_mappings
        uprn = body["uprn"].strip() or self._config()["north_yorkshire"]["uprn"]
        validate_uprn(uprn)
        results = fetch_collections(uprn)
        configured = self._config()["calendar"]["events"]
        entries = []
        for item in results[:20]:
            try:
                resolved = resolve_mappings([item], configured)[0]
                entries.append({**resolved, "mapped": True})
            except ValueError:
                entries.append({**item, "mapped": False})
        return {"ok": True, "count": len(results), "entries": entries}

    def upcoming(self) -> list[dict]:
        """List upcoming collection days with a single calendar fetch."""
        from datetime import datetime
        from .app import TZ
        from .bin_preview import upcoming_collections
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BindicatorError("Bindicator is busy; retry shortly.") from exc
            app = self.api._app()
            return upcoming_collections(
                app.config, app.calendar_data(), datetime.now(TZ)
            )

    def test_collection(self, body: dict) -> dict:
        """Preview only a verified upcoming date, without persistent state."""
        from datetime import date, datetime
        from .app import TZ
        from .bin_preview import preview_lights, upcoming_collections
        if set(body) != {"date", "seconds"}:
            raise ValueError("Expected collection date and preview seconds.")
        requested, seconds = body["date"], body["seconds"]
        if not isinstance(requested, str) or len(requested) != 10:
            raise ValueError("Expected collection date in YYYY-MM-DD format.")
        try:
            target = date.fromisoformat(requested)
        except ValueError as exc:
            raise ValueError("Invalid collection date.") from exc
        if target.isoformat() != requested:
            raise ValueError("Expected collection date in YYYY-MM-DD format.")
        if type(seconds) is not int or not 1 <= seconds <= 30:
            raise ValueError("Preview must last 1–30 seconds.")

        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BindicatorError("Bindicator is busy; retry shortly.") from exc
            from .controls import is_paused
            if is_paused(self.state):
                raise BindicatorError("Bindicator is paused; cannot test collections.")
            app = self.api._app()
            if app.state["lights"] or app.state.get("manual_until"):
                raise BindicatorError("A reminder is active; preview is unavailable.")
            # Re-read the calendar under the same lock. Never accept arbitrary
            # colours or trust a date/colour pairing provided by the browser.
            candidates = upcoming_collections(
                app.config, app.calendar_data(), datetime.now(TZ)
            )
            matching = next((row for row in candidates if row["date"] == requested), None)
            if matching is None:
                raise ValueError("Date is no longer among the next five collections; refresh the list.")
            preview_lights(app.hue, app.config, matching["colours"], seconds=seconds)
            return {"ok": True, "message":
                    f"Previewed {matching['weekday']} {requested} for {seconds} seconds; "
                    "previous light appearance restored where unchanged."}

    def preview(self, body: dict) -> dict:
        """Run the CLI's bounded, restoring preview; CLI owns run.lock."""
        if set(body) != {"colour", "seconds"}:
            raise ValueError("Expected colour and seconds.")
        colour, seconds = body["colour"], body["seconds"]
        if type(colour) is not str or colour not in self._config()["colors"]:
            raise ValueError("Choose a configured colour.")
        if type(seconds) is not int or not 1 <= seconds <= 30:
            raise ValueError("Preview duration must be 1–30 seconds.")
        cmd = [sys.executable, "-m", "bindicator.cli",
               "--config", str(self.config),
               "--secrets-file", str(self.secrets),
               "--state-dir", str(self.state),
               "--test", colour, "--seconds", str(seconds)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=seconds + 30)
        except subprocess.TimeoutExpired as exc:
            LOG.error("Lamp preview timed out; check preview restoration and lamps.")
            raise BindicatorError("Lamp preview timed out; check the service log and lights.") from exc
        if result.returncode:
            LOG.warning("Lamp preview refused (exit %s): %s",
                        result.returncode, result.stderr[-400:])
            raise BindicatorError("Lamp preview refused; check reminders or service logs.")
        return {"ok": True, "message": "Preview finished; original lamp state restored where unchanged."}

    def api_action(self, action: str, body: dict) -> dict:
        """Delegate existing voice/API actions to their shared CLI safeguards."""
        if action not in ("pause", "resume", "toggle", "alerts/next"):
            raise ValueError("Unknown API action.")
        if action != "alerts/next" and body:
            raise ValueError("This operation requires an empty JSON object.")
        return self.api.command(action, body)

    def identify(self, body: dict) -> dict:
        """Identify exactly one paired Hue lamp, without saving selection."""
        if set(body) != {"bridge", "id"}:
            raise ValueError("Expected bridge and id.")
        bridge, light_id = body["bridge"], body["id"]
        if not isinstance(bridge, str) or not isinstance(light_id, str):
            raise ValueError("Bridge and light ID must be strings.")
        config = self._config()
        if bridge not in config["hue"]["bridges"]:
            raise ValueError("Unknown Hue Bridge.")
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BindicatorError("Bindicator is busy; try again shortly.") from exc

            status = self.api.status()
            if status["paused"] or status["indicator_count"] or status["manual_until"]:
                raise BindicatorError("Cannot identify a light while paused or a reminder is active.")

            pool = BridgePool(config["hue"])
            if not pool.has_key(bridge):
                raise BindicatorError("Hue Bridge is not paired.")
            # Only known, colour-capable lights from this configured Bridge.
            available = {
                light["id"] for light in pool.lights(bridge)
                if isinstance(light.get("id"), str)
                and ("color" in light or "gradient" in light)
            }
            if light_id not in available:
                raise ValueError("Light is not available from the chosen Hue Bridge.")

            from .bin_preview import identify_light
            restored = identify_light(pool, f"{bridge}/{light_id}")
            return {"ok": True, "message": (
                "Light briefly flashed and its previous appearance restored."
                if restored else
                "Light was changed during identification; left its latest appearance untouched."
            )}

    def change(self, action: str, body: dict) -> dict:
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BindicatorError("Bindicator is busy. Try again shortly.") from exc

            config = self._config()
            if action == "delete_bridge":
                if set(body) != {"name"} or not isinstance(body["name"], str):
                    raise ValueError("Expected configured Bridge name.")
                name = body["name"]
                if not BRIDGE_NAME.fullmatch(name) or name not in config["hue"]["bridges"]:
                    raise ValueError("Unknown configured Hue Bridge.")
                # Never discard the routing or credentials needed to restore
                # lamps that currently have a reminder applied.
                _check_no_active_reminder(self.state)
                state = self.api.status()
                if state["indicator_count"] or state["manual_until"]:
                    raise BindicatorError("An active reminder must be restored before deleting a Bridge.")
                removed = remove_bridge_config_and_key(self.config, self.secrets, name)
                return {"ok": True, "message":
                        f"Removed Hue Bridge {name} and {removed} selected indicator light(s)."}
            elif action == "schedule":
                if set(body) != {"start", "restore"}:
                    raise ValueError("Expected start and restore times.")
                from .app import validate_schedule
                schedule = validate_schedule(body)
                yaml = YAML(typ="rt")
                yaml.preserve_quotes = True
                with self.config.open(encoding="utf-8") as stream:
                    doc = yaml.load(stream)
                from ruamel.yaml.scalarstring import DoubleQuotedScalarString
                doc["schedule"] = {key: DoubleQuotedScalarString(value) for key, value in schedule.items()}
                out = StringIO()
                yaml.dump(doc, out)
                _atomic_text(self.config, out.getvalue())
            elif action in ("colours", "events", "priority"):
                if set(body) != {"value"}:
                    raise ValueError("Expected value.")
                update_configuration(self.config, section=action, value=body["value"])
            elif action == "calendar_source":
                from .calendar_providers import get_provider
                if set(body) != {"source"} or not isinstance(body["source"], str):
                    raise ValueError("Select a registered calendar provider.")
                source = body["source"]
                provider = get_provider(source)
                if not provider.configured(config):
                    raise ValueError(f"Configure {provider.name} before selecting it.")
                # Checking connectivity is a separate action: selecting an
                # existing configured iCal feed must still work during an outage.
                # Council activation additionally validates its required mappings.
                if source == "council":
                    self.check_calendar_source({"source": source, "preview": False})
                    from .north_yorkshire import resolve_mappings
                    from .calendar_providers import NorthYorkshireProvider
                    resolve_mappings(
                        NorthYorkshireProvider().fetch_records(config),
                        config["calendar"]["events"],
                    )
                yaml = YAML(typ="rt")
                yaml.preserve_quotes = True
                with self.config.open(encoding="utf-8") as stream:
                    doc = yaml.load(stream)
                doc["calendar_source"] = source
                if "north_yorkshire" not in doc:
                    doc["north_yorkshire"] = {}
                doc["north_yorkshire"]["enabled"] = source == "council"
                out = StringIO()
                yaml.dump(doc, out)
                _atomic_text(self.config, out.getvalue())
            elif action == "calendar_refresh":
                if set(body) != {"days"} or type(body["days"]) is not int or not 1 <= body["days"] <= 90:
                    raise ValueError("Refresh interval must be 1–90 whole days.")
                yaml = YAML(typ="rt")
                yaml.preserve_quotes = True
                with self.config.open(encoding="utf-8") as stream:
                    doc = yaml.load(stream)
                doc["calendar_refresh"] = {"days": body["days"]}
                out = StringIO()
                yaml.dump(doc, out)
                _atomic_text(self.config, out.getvalue())
            elif action == "north_yorkshire":
                if (set(body) != {"uprn", "enabled", "refresh_days"}
                    or not isinstance(body["uprn"], str)
                    or type(body["enabled"]) is not bool
                    or type(body["refresh_days"]) is not int
                    or not 1 <= body["refresh_days"] <= 90):
                    raise ValueError("Expected council UPRN, enabled flag and 1–90 day refresh interval.")
                from .north_yorkshire import validate_uprn, fetch_collections, resolve_mappings
                uprn = body["uprn"].strip() or config["north_yorkshire"]["uprn"]
                if uprn:
                    validate_uprn(uprn)
                if body["enabled"]:
                    if not uprn:
                        raise ValueError("Enter a UPRN before enabling council collections.")
                    records = fetch_collections(uprn)
                    try:
                        resolve_mappings(records, config["calendar"]["events"])
                    except ValueError as exc:
                        raise ValueError("Add matching calendar-event colour mappings before enabling council source: "
                                         + str(exc)) from exc
                    from datetime import date
                    if not any(date.fromisoformat(item["date"]) >= date.today() for item in records):
                        raise ValueError("Council returned no current or future collection dates.")
                yaml = YAML(typ="rt")
                yaml.preserve_quotes = True
                with self.config.open(encoding="utf-8") as stream:
                    doc = yaml.load(stream)
                from ruamel.yaml.scalarstring import DoubleQuotedScalarString
                doc["north_yorkshire"] = {
                    "enabled": body["enabled"],
                    "uprn": DoubleQuotedScalarString(uprn),
                    "refresh_days": body["refresh_days"],
                }
                out = StringIO()
                yaml.dump(doc, out)
                _atomic_text(self.config, out.getvalue())
            elif action == "calendar":
                if set(body) != {"url"}:
                    raise ValueError("Expected url.")
                save_calendar_url(self.secrets, body["url"])
            elif action == "mode":
                if set(body) != {"mode"} or body["mode"] not in ("spread", "priority", "cycle"):
                    raise ValueError("Expected mode: spread, priority or cycle.")
                update_mode(self.config, body["mode"])
            elif action == "pair":
                if set(body) != {"name", "host"}:
                    raise ValueError("Expected name and host.")
                name, host = body["name"], body["host"]
                if not isinstance(name, str) or not BRIDGE_NAME.fullmatch(name):
                    raise ValueError("Bridge name must be lowercase letters, digits or underscore.")
                if not isinstance(host, str):
                    raise ValueError("Invalid Bridge IP.")
                private_host(host)
                _check_no_active_reminder(self.state)
                # Only pair discovered mDNS devices or an already configured
                # bridge. Never treat this endpoint as an arbitrary LAN proxy.
                candidates = available_bridges(config["hue"]["bridges"], discover_bridges())
                matches = [c for c in candidates if c["host"] == host]
                if not matches:
                    raise ValueError("Bridge was not discovered. Refresh discovery first.")
                candidate = matches[0]
                old = config["hue"]["bridges"].get(name)
                if old:
                    old_id, new_id = str(old.get("id", "")).upper(), str(candidate.get("id", "")).upper()
                    if (old_id and new_id and old_id != new_id) or (
                        old["host"] != host and not (old_id and old_id == new_id)
                    ):
                        raise ValueError("Bridge name already belongs to another device.")
                    if BridgePool(config["hue"]).has_key(name) and old["host"] == host:
                        return {"ok": True, "message": "Bridge already paired; no changes made."}
                from .app import Hue
                # Hue registration requires pressing the physical bridge button.
                key = Hue(host, None, False).pair()
                save_bridge_key(self.secrets, name, key)
                save_bridge_config(self.config, name, host, candidate.get("id"))
            elif action == "lights":
                if set(body) != {"selected"} or not isinstance(body["selected"], list):
                    raise ValueError("Expected selected list.")
                if len(body["selected"]) > 100:
                    raise ValueError("Too many selected lamps.")
                pool = BridgePool(config["hue"])
                available = set()
                gradient_capable = set()
                for n in pool.names:
                    if not pool.has_key(n):
                        continue
                    for light in pool.lights(n):
                        if ("color" in light or "gradient" in light) and isinstance(light.get("id"), str):
                            available.add((n, light["id"]))
                            if isinstance(light.get("gradient"), dict) and type(light["gradient"].get("points_capable")) is int and light["gradient"]["points_capable"] >= 2:
                                gradient_capable.add((n, light["id"]))
                selected = body["selected"]
                if any(not isinstance(x, dict) or not {"bridge", "id"} <= set(x)
                       or set(x) - {"bridge", "id", "always_gradient"}
                       or type(x.get("always_gradient", False)) is not bool
                       or (x["bridge"], x["id"]) not in available
                       or (x.get("always_gradient", False) and
                           (x["bridge"], x["id"]) not in gradient_capable)
                       for x in selected):
                    raise ValueError("Selection includes a lamp not available from a paired Bridge.")
                keys = [(x["bridge"], x["id"]) for x in selected]
                if len(set(keys)) != len(keys):
                    raise ValueError("Duplicate lamp selection.")
                # Preserve selections belonging to an unpaired bridge.
                retained = [x for x in config["hue"]["lights"]
                            if not pool.has_key(x["bridge"])]
                write_selected_config(self.config, selected + retained)
            else:
                raise ValueError("Unknown operation.")
            return {"ok": True, "message": "Configuration saved."}


def make_handler(manager: Management, address: str, port: int, *, allowed_hostname: str | None = None):
    # Explicitly allow the bound LAN IPv4 and, optionally, this machine's
    # configured short hostname. Never trust arbitrary Host or proxy headers.
    allowed_hosts = {f"{address}:{port}"}
    if allowed_hostname:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", allowed_hostname):
            raise BindicatorError("Invalid permitted LAN hostname.")
        allowed_hosts.add(f"{allowed_hostname.lower()}:{port}")

    class Handler(BaseHTTPRequestHandler):
        server_version = "BindicatorLAN"
        sys_version = ""

        def log_message(self, fmt, *args):
            LOG.info("LAN HTTP %s", fmt % args)

        def respond(self, code: int, payload: dict):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(data)

        def process(self, method):
            request_host = self.headers.get("Host", "").lower()
            if request_host not in allowed_hosts:
                self.respond(400, {"error": "Invalid Host header."})
                return
            path = urlsplit(self.path)
            if path.query or path.fragment:
                self.respond(400, {"error": "Query parameters unsupported."})
                return
            try:
                if method == "GET":
                    # Serve only static assets used by the management UI.
                    static_assets = {
                        "/static/bindicator-soft-banner.webp": ("bindicator-soft-banner.webp", "image/webp"),
                        "/favicon.ico": ("favicon-32.png", "image/png"),
                        "/favicon-32.png": ("favicon-32.png", "image/png"),
                    }
                    if path.path in static_assets:
                        from importlib.resources import files
                        filename, media_type = static_assets[path.path]
                        raw = files("bindicator").joinpath("static", filename).read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", media_type)
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header("Cache-Control", "public, max-age=86400")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Content-Security-Policy", "default-src 'none'")
                        self.send_header("X-Frame-Options", "DENY")
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                    if path.path == "/":
                        from .web_ui import HTML
                        raw = HTML.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("X-Frame-Options", "DENY")
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                    if path.path not in (
                        "/manage/overview", "/manage/calendar-events",
                        "/manage/discovery", "/manage/lights",
                        "/manage/next", "/manage/upcoming",
                    ):
                        self.respond(404, {"error": "Not found."})
                        return
                    routes = {
                        "/manage/overview": manager.overview,
                        "/manage/calendar-events": manager.calendar_event_options,
                        "/manage/discovery": manager.discovery,
                        "/manage/lights": manager.lights,
                        "/manage/next": manager.api.next_collection,
                        "/manage/upcoming": manager.upcoming,
                    }
                    handler = routes.get(path.path)
                    if not handler:
                        self.respond(404, {"error": "Not found."})
                        return
                    self.respond(200, {"data": handler()})
                elif method == "POST":
                    if self.headers.get("Origin") != f"https://{request_host}" or self.headers.get("X-Bindicator-Request") != "management":
                        self.respond(403, {"error": "Invalid Origin/CSRF header."})
                        return
                    if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                        self.respond(415, {"error": "JSON required."})
                        return
                    length = self.headers.get("Content-Length", "")
                    if not length.isdecimal() or int(length) > MAX_BODY:
                        self.respond(413, {"error": "Invalid request size."})
                        return
                    try:
                        payload = json.loads(self.rfile.read(int(length)))
                    except (ValueError, UnicodeError):
                        self.respond(400, {"error": "Invalid JSON."})
                        return
                    if not isinstance(payload, dict):
                        self.respond(400, {"error": "JSON object required."})
                        return
                    action = {
                        "/manage/mode": "mode", "/manage/pair": "pair",
                        "/manage/bridges/delete": "delete_bridge",
                        "/manage/lights": "lights", "/manage/preview": "preview",
                        "/manage/north-yorkshire": "north_yorkshire",
                        "/manage/north-yorkshire/check": "council_check",
                        "/manage/north-yorkshire/refresh": "council_refresh",
                        "/manage/calendar-source": "calendar_source",
                        "/manage/calendar-refresh": "calendar_refresh",
                        "/manage/calendar/check": "source_check",
                        "/manage/calendar/refresh": "active_refresh",
                        "/manage/identify": "identify",
                        "/manage/collections/test": "collection_test",
                        "/manage/colours": "colours", "/manage/events": "events",
                        "/manage/priority": "priority", "/manage/calendar": "calendar",
                        "/manage/schedule": "schedule",
                        "/manage/pause": "api:pause", "/manage/resume": "api:resume",
                        "/manage/toggle": "api:toggle", "/manage/alerts/next": "api:alerts/next",
                    }.get(path.path)
                    if not action:
                        self.respond(404, {"error": "Not found."})
                        return
                    if action == "source_check":
                        response = manager.check_calendar_source(payload)
                    elif action == "active_refresh":
                        response = manager.refresh_active_calendar(payload)
                    elif action == "council_check":
                        response = manager.check_north_yorkshire(payload)
                    elif action == "council_refresh":
                        response = manager.refresh_north_yorkshire(payload)
                    elif action == "preview":
                        response = manager.preview(payload)
                    elif action == "identify":
                        response = manager.identify(payload)
                    elif action == "collection_test":
                        response = manager.test_collection(payload)
                    elif action.startswith("api:"):
                        response = manager.api_action(action[4:], payload)
                    else:
                        response = manager.change(action, payload)
                    self.respond(200, response)
                else:
                    self.respond(405, {"error": "Method not allowed."})
            except ValueError as exc:
                self.respond(400, {"error": str(exc)})
            except BindicatorError as exc:
                LOG.warning("Management error: %s", exc)
                self.respond(409, {"error": str(exc)})
            except Exception:
                LOG.exception("Management server failure.")
                self.respond(500, {"error": "Operation failed. Check server journal."})

        def do_GET(self):
            self.process("GET")

        def do_POST(self):
            self.process("POST")

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bindicator LAN-only management")
    parser.add_argument("--host", required=True, help="Explicit private IPv4 of mrlazy (never 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--allowed-hostname", help="Explicit trusted local hostname (e.g. mrlazy)")
    parser.add_argument("--cert-file", type=Path, default=Path("/etc/bindicator/web.crt"))
    parser.add_argument("--key-file", type=Path, default=Path("/etc/bindicator/web.key"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        host = private_host(args.host)
        if not 1 <= args.port <= 65535:
            raise BindicatorError("Invalid port.")
        manager = Management(args.config, args.secrets_file, args.state_dir)
        with ThreadingHTTPServer((host, args.port), make_handler(manager, host, args.port, allowed_hostname=args.allowed_hostname)) as server:
            server.daemon_threads = True
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.minimum_version = ssl.TLSVersion.TLSv1_2
            tls.load_cert_chain(str(args.cert_file), str(args.key_file))
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            LOG.info("TLS LAN management listening on %s:%s", host, args.port)
            server.serve_forever()
    except (OSError, BindicatorError, ssl.SSLError) as exc:
        LOG.error("Cannot start Bindicator management site: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
