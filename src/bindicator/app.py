"""Bindicator core: calendar discovery, Hue control and safe state restoration."""
from __future__ import annotations

import json
import logging
import os
import re
import time as clock
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

import requests
import yaml
from icalendar import Calendar
import recurring_ical_events

LOG = logging.getLogger("bindicator")
TZ = ZoneInfo("Europe/London")
DEFAULT_CONFIG = Path("/etc/bindicator/config.yaml")
DEFAULT_SECRETS = Path("/etc/bindicator/secrets.env")
DEFAULT_STATE_DIR = Path("/var/lib/bindicator")


class BindicatorError(Exception):
    """Expected configuration, calendar, or bridge failure."""


def load_secrets(path: Path) -> None:
    """Read a minimal KEY=value secrets file without running shell code."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except PermissionError as exc:
        raise BindicatorError(
            f"Cannot read {path}; use sudo or join the bindicator group."
        ) from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            raise BindicatorError(f"Invalid secrets-file entry in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key.isidentifier():
            raise BindicatorError("Invalid environment variable name in secrets file")
        os.environ.setdefault(key, value)


def validate_schedule(schedule: dict) -> dict:
    """Accept an afternoon/evening start and next-morning restore (UK local)."""
    if not isinstance(schedule, dict) or set(schedule) - {"start", "restore"}:
        raise BindicatorError("schedule must contain start and restore times.")
    start = schedule.get("start", "18:00")
    restore = schedule.get("restore", "09:00")
    if (not isinstance(start, str) or not isinstance(restore, str)
        or not re.fullmatch(r"(?:1[2-9]|2[0-3]):[0-5][0-9]", start)
        or not re.fullmatch(r"(?:0[0-9]|1[01]):[0-5][0-9]", restore)):
        raise BindicatorError(
            "Start must be 12:00–23:59 and restore 00:00–11:59 (24-hour HH:MM)."
        )
    return {"start": start, "restore": restore}


def load_config(path: Path) -> dict:
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BindicatorError(f"Cannot load configuration at {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise BindicatorError("Configuration must be a YAML mapping.")
    calendar = config.get("calendar")
    hue = config.get("hue")
    colors = config.get("colors")
    if not isinstance(calendar, dict) or not isinstance(calendar.get("events"), dict):
        raise BindicatorError("calendar.events must map event titles to colour names.")
    from .bridges import normalize_hue_config

    normalize_hue_config(hue)
    if not isinstance(colors, dict) or not 1 <= len(colors) <= 5:
        raise BindicatorError("colors must contain between one and five colours.")
    for name, xy in colors.items():
        if (not isinstance(xy, dict) or
            not all(isinstance(xy.get(k), (float, int)) for k in ("x", "y")) or
            not (0 < xy["x"] < 1 and 0 < xy["y"] < 1 and xy["x"] + xy["y"] < 1)):
            raise BindicatorError(f"Invalid CIE xy coordinates for colour {name!r}.")
    for event, name in calendar["events"].items():
        if not isinstance(event, str) or name not in colors:
            raise BindicatorError(f"Event {event!r} maps to an undefined colour.")
    priority = config.get("priority", list(colors))
    if not isinstance(priority, list) or any(name not in colors for name in priority):
        raise BindicatorError("priority must be a list of configured colour names.")
    config["priority"] = priority
    council = config.get("north_yorkshire", {})
    if not isinstance(council, dict) or set(council) - {"enabled", "uprn", "refresh_days"}:
        raise BindicatorError("north_yorkshire supports only enabled and uprn.")
    if type(council.get("enabled", False)) is not bool:
        raise BindicatorError("north_yorkshire.enabled must be true or false.")
    uprn = council.get("uprn", "")
    if not isinstance(uprn, str):
        raise BindicatorError("north_yorkshire.uprn must be a string.")
    if uprn:
        from .north_yorkshire import validate_uprn
        try:
            validate_uprn(uprn)
        except ValueError as exc:
            raise BindicatorError(str(exc)) from exc
    if council.get("enabled", False) and not uprn:
        raise BindicatorError("Set a North Yorkshire UPRN before enabling this source.")
    refresh_days = council.get("refresh_days", 7)
    if type(refresh_days) is not int or not 1 <= refresh_days <= 90:
        raise BindicatorError("North Yorkshire refresh interval must be 1–90 days.")
    config["north_yorkshire"] = {
        "enabled": council.get("enabled", False), "uprn": uprn,
        "refresh_days": refresh_days,
    }
    refresh = config.get("calendar_refresh", {})
    if not isinstance(refresh, dict) or set(refresh) - {"days"}:
        raise BindicatorError("calendar_refresh accepts a days interval.")
    days = refresh.get("days", council.get("refresh_days", 7))
    if type(days) is not int or not 1 <= days <= 90:
        raise BindicatorError("Calendar refresh interval must be 1–90 days.")
    config["calendar_refresh"] = {"days": days}
    source = config.get("calendar_source")
    if source is not None:
        from .calendar_providers import get_provider
        if not isinstance(source, str):
            raise BindicatorError("calendar_source must be a registered provider ID.")
        try:
            get_provider(source)
        except ValueError as exc:
            raise BindicatorError(str(exc)) from exc
    config["schedule"] = validate_schedule(config.get("schedule", {}))
    return config


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise BindicatorError(f"Missing {name} in the secrets file or environment.")
    return value


def active_collection_date(now: datetime, schedule: dict | None = None) -> date | None:
    """Collection-day window according to validated previous-day/morning times."""
    schedule = schedule or {"start": "18:00", "restore": "09:00"}
    local = now.astimezone(TZ)
    start = time.fromisoformat(schedule["start"])
    restore = time.fromisoformat(schedule["restore"])
    if local.time() >= start:
        return local.date() + timedelta(days=1)
    if local.time() < restore:
        return local.date()
    return None

def collection_events_in_range(
    data: bytes, start_day: date, end_day: date, event_map: dict,
) -> dict[date, list[dict[str, str]]]:
    """Map canonical calendar events to user colours; keep each title distinct."""
    from .calendar_providers import ical_events
    if end_day <= start_day:
        return {}
    try:
        records = ical_events(data, "calendar", start_day, end_day)
    except Exception as exc:
        raise BindicatorError("Unable to parse the iCalendar feed.") from exc
    titles = {str(k).strip().casefold(): (str(k).strip(), v)
              for k, v in event_map.items()}
    result: dict[date, list[dict[str, str]]] = {}
    for record in records:
        match = titles.get(record.title.casefold())
        if match is None:
            continue
        title, colour = match
        found = result.setdefault(record.date, [])
        entry = {"title": title, "colour": colour}
        if entry not in found:
            found.append(entry)
    return result

def collections_in_range(
    data: bytes, start_day: date, end_day: date, event_map: dict,
) -> dict[date, list[str]]:
    """Unique matched bin colours grouped by UK local date."""
    return {
        day: list(dict.fromkeys(item["colour"] for item in items))
        for day, items in collection_events_in_range(
            data, start_day, end_day, event_map
        ).items()
    }


def parse_collections(data: bytes, day: date, event_map: dict) -> list[str]:
    """Return the unique matched bin colours for a given collection date."""
    return collections_in_range(
        data, day, day + timedelta(days=1), event_map
    ).get(day, [])


def ordered_colors(found: list[str], priority: list[str]) -> list[str]:
    rank = {name: index for index, name in enumerate(priority)}
    return sorted(set(found), key=lambda name: (rank.get(name, len(rank)), name))


def assignments(lights: list[str], colors: list[str], mode: str) -> dict[str, str]:
    """Assign collection colours independently to selected lights on each Bridge.

    In spread mode, each Bridge begins at the highest-priority colour,
    regardless of lights selected on another Bridge. A single lamp on any
    Bridge therefore always shows the first (highest-priority) colour.
    """
    if not colors:
        return {}
    bridge_positions: dict[str, int] = {}
    result: dict[str, str] = {}
    for light in lights:
        bridge = light.split("/", 1)[0]
        position = bridge_positions.get(bridge, 0)
        result[light] = colors[position % len(colors)] if mode == "spread" else colors[0]
        bridge_positions[bridge] = position + 1
    return result


def same_xy(a: dict | None, b: dict | None, tolerance: float = 0.015) -> bool:
    return bool(
        isinstance(a, dict) and isinstance(b, dict)
        and all(k in a and k in b and abs(float(a[k]) - float(b[k])) <= tolerance
                for k in ("x", "y"))
    )


def current_xy(light: dict) -> dict | None:
    return (light.get("color") or {}).get("xy")


def _gradient_points(light: dict) -> list[dict] | None:
    """Extract only writable XY point fields from Hue API v2."""
    gradient = light.get("gradient")
    if not isinstance(gradient, dict):
        return None
    points = gradient.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return None
    writable = []
    for point in points:
        if not isinstance(point, dict):
            return None
        xy = point.get("color", {}).get("xy")
        if not isinstance(xy, dict) or not {"x", "y"} <= xy.keys():
            return None
        writable.append({"color": {"xy": {"x": xy["x"], "y": xy["y"]}}})
    return writable


def original_color(light: dict) -> dict | None:
    """Save the prior colour/gradient state without read-only Hue fields."""
    ct = light.get("color_temperature") or {}
    if ct.get("mirek_valid") is True and isinstance(ct.get("mirek"), int):
        return {"color_temperature": {"mirek": ct["mirek"]}}
    points = _gradient_points(light)
    if points is not None:
        restored = {"points": points}
        mode = light["gradient"].get("mode")
        if isinstance(mode, str) and mode:
            restored["mode"] = mode
        return {"gradient": restored}
    xy = current_xy(light)
    if isinstance(xy, dict) and "x" in xy and "y" in xy:
        return {"color": {"xy": {"x": xy["x"], "y": xy["y"]}}}
    return None



def _effect_state(light: dict) -> tuple[str, dict] | None:
    """Return an active built-in effect as a writable Hue API v2 payload.

    Do not copy read-only mode values, metadata, or effect status fields.
    """
    v2 = light.get("effects_v2")
    if isinstance(v2, dict):
        status = v2.get("status")
        if isinstance(status, dict):
            effect = status.get("effect")
            if isinstance(effect, str) and effect not in ("", "no_effect"):
                action: dict = {"effect": effect}
                params = status.get("parameters")
                if isinstance(params, dict):
                    saved_params: dict = {}
                    speed = params.get("speed")
                    if type(speed) in (int, float) and 0 <= speed <= 1:
                        saved_params["speed"] = speed
                    xy = (params.get("color") or {}).get("xy")
                    if isinstance(xy, dict) and {"x", "y"} <= xy.keys():
                        saved_params["color"] = {"xy": {"x": xy["x"], "y": xy["y"]}}
                    ct = (params.get("color_temperature") or {}).get("mirek")
                    if type(ct) is int:
                        saved_params["color_temperature"] = {"mirek": ct}
                    if saved_params:
                        action["parameters"] = saved_params
                return "effects_v2", {"action": action}
    old = light.get("effects")
    if isinstance(old, dict):
        # Hue v2 GET uses effects.status; PUT uses effects.effect.
        # Some older fixtures expose effect directly as well.
        effect = old.get("status", old.get("effect"))
        if isinstance(effect, dict):
            effect = effect.get("effect")
        if isinstance(effect, str) and effect not in ("", "no_effect"):
            return "effects", {"effect": effect}
    return None


def active_effect(light: dict) -> bool:
    """Whether a built-in effect is currently active on this lamp."""
    return _effect_state(light) is not None


def snapshot_light_state(light: dict) -> dict:
    """Capture only writable Hue light properties before any change.

    Static Hue scenes are represented by each lamp's current parameters.
    A dynamic scene or entertainment stream has no reconstructible scene ID
    on the light resource; skip those rather than destroying the animation.
    """
    if light.get("mode") == "streaming":
        raise BindicatorError(
            "Hue Entertainment streaming is active; cannot restore the stream."
        )
    if (light.get("dynamics") or {}).get("status") == "dynamic_palette":
        raise BindicatorError(
            "A dynamic Hue scene is active; its playback cannot be restored "
            "from an individual light snapshot."
        )
    timed = light.get("timed_effects")
    if isinstance(timed, dict) and timed.get("status") not in (None, "no_effect"):
        raise BindicatorError(
            "A timed Hue effect is active; its remaining duration cannot "
            "be restored safely."
        )
    power = (light.get("on") or {}).get("on")
    if type(power) is not bool:
        raise BindicatorError("Hue did not report a reliable on/off state.")
    snapshot = {"on": {"on": power}}
    brightness = (light.get("dimming") or {}).get("brightness")
    if type(brightness) in (int, float) and 0 < brightness <= 100:
        snapshot["dimming"] = {"brightness": brightness}
    effect = _effect_state(light)
    if effect:
        field, body = effect
        snapshot[field] = body
    else:
        color = original_color(light)
        if color:
            snapshot.update(color)
        else:
            raise BindicatorError(
                "Hue did not report a restorable colour or gradient."
            )
    return snapshot


def brightness_unchanged(light: dict, value: object, tolerance: float = 2.0) -> bool:
    """Detect a user brightness change made while the alert was showing."""
    if type(value) not in (int, float):
        return True  # Legacy snapshots did not record brightness.
    # Hue may report a different dim level for an intentionally-off lamp.
    # Respect a manual switch-off and restore its non-power properties.
    if (light.get("on") or {}).get("on") is False:
        return True
    actual = (light.get("dimming") or {}).get("brightness")
    return (
        type(actual) not in (int, float)
        or abs(float(actual) - float(value)) <= tolerance
    )


def restorable_snapshot(record: dict, live: dict) -> dict:
    """Choose a saved writable snapshot, falling back to legacy state."""
    stored = record.get("original_state")
    if isinstance(stored, dict):
        payload = dict(stored)
        # Never switch on a light that was manually turned off during alert.
        if live.get("on", {}).get("on") is False:
            payload.pop("on", None)
        return payload
    original = record.get("original")
    payload = dict(original) if isinstance(original, dict) else {}
    if record.get("original_on") is False and live.get("on", {}).get("on") is True:
        payload["on"] = {"on": False}
    return payload


def alert_effect_override(light: dict) -> dict:
    """Stop an active built-in effect while showing solid bin colours."""
    effect = _effect_state(light)
    if effect is None:
        return {}
    field, _ = effect
    if field == "effects_v2":
        return {"effects_v2": {"action": {"effect": "no_effect"}}}
    return {"effects": {"effect": "no_effect"}}

def gradient_target(light: dict, colors: list[str], palette: dict) -> dict | None:
    """Use the connected light's advertised point count and supported modes."""
    gradient = light.get("gradient")
    if not isinstance(gradient, dict) or len(colors) < 2:
        return None
    capable = gradient.get("points_capable")
    if type(capable) is not int or capable < 2:
        return None
    supported = gradient.get("mode_values")
    if isinstance(supported, list) and "segmented_palette" in supported:
        mode = "segmented_palette"
    elif not isinstance(supported, list) or not supported or "interpolated_palette" in supported:
        mode = "interpolated_palette"
    else:
        # Avoid sending a mode that the Bridge says is unsupported.
        return None
    selected = colors[:capable]
    return {
        "points": [
            {"color": {"xy": dict(palette[color])}}
            for color in selected
        ],
        "mode": mode,
    }


def reminder_target(
    light: dict, colors: list[str], palette: dict, assigned: str, mode: str,
    *, always_gradient: bool = False,
) -> dict:
    """Spread colour on eligible gradient lamps, including per-light overrides."""
    if mode == "spread" or always_gradient:
        gradient = gradient_target(light, colors, palette)
        if gradient:
            return {"gradient": gradient}
    return {"color": {"xy": dict(palette[assigned])}}


def matches_target(live: dict, target: dict) -> bool:
    """Compare requested solid or gradient state, ignoring readonly API fields."""
    expected_gradient = target.get("gradient")
    if isinstance(expected_gradient, dict):
        actual_gradient = live.get("gradient")
        if not isinstance(actual_gradient, dict):
            return False
        expected_mode = expected_gradient.get("mode")
        if expected_mode and actual_gradient.get("mode") != expected_mode:
            return False
        actual_points = _gradient_points(live)
        wanted = expected_gradient.get("points", [])
        return bool(
            actual_points is not None
            and isinstance(wanted, list)
            and len(actual_points) == len(wanted)
            and all(
                same_xy(a["color"]["xy"], b["color"]["xy"])
                for a, b in zip(actual_points, wanted)
            )
        )
    expected = target.get("color", {}).get("xy")
    return same_xy(current_xy(live), expected)


def saved_target(record: dict) -> dict:
    """Read modern gradient or legacy solid reminder state."""
    if isinstance(record.get("applied_gradient"), dict):
        return {"gradient": record["applied_gradient"]}
    return {"color": {"xy": record["applied_xy"]}}


def json_save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic rename to avoid corrupt state after power loss or a crash.
    with NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
        temp = Path(f.name)
        os.chmod(temp, 0o660)
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def atomic_bytes_save(path: Path, content: bytes) -> None:
    """Atomically replace cached data, even if another group member owns it.

    CLI invocations by stu and the systemd service account share a setgid
    state directory. Group-write permission allows replacing a directory
    entry but does not allow chmod on an existing file owned by another user.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with NamedTemporaryFile("wb", dir=path.parent, delete=False) as f:
            temp = Path(f.name)
            os.fchmod(f.fileno(), 0o660)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


class Hue:
    def __init__(self, bridge: str, key: str | None, verify_tls: bool | str = False):
        if "/" in bridge or ":" in bridge or not bridge:
            raise BindicatorError("Hue bridge must be an IP address or DNS hostname.")
        self.base = f"https://{bridge}"
        self.key = key
        self.verify_tls = verify_tls
        if verify_tls is False:
            # Local Hue Bridges typically have certificates not trusted by system CA.
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def request(self, method: str, path: str, payload: dict | None = None):
        headers = {"hue-application-key": self.key} if self.key else {}
        try:
            response = requests.request(
                method, self.base + path, headers=headers, json=payload,
                verify=self.verify_tls, timeout=10,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BindicatorError(
                f"Hue Bridge {method} {path} failed ({type(exc).__name__})."
            ) from exc
        if not isinstance(body, (list, dict)):
            raise BindicatorError("Unexpected Hue Bridge response.")
        if isinstance(body, dict) and body.get("errors"):
            raise BindicatorError(f"Hue Bridge rejected {method} {path}: {body['errors']}")
        return body

    def pair(self, *, timeout_seconds: float = 45, retry_interval: float = 1.5) -> str:
        """Poll the Hue v1 registration endpoint until link-button approval.

        Hue returns error 101 while waiting for physical button authorisation.
        Never retry unrelated errors or obscure an unexpected Bridge response.
        """
        deadline = clock.monotonic() + timeout_seconds
        payload = {"devicetype": "bindicator#mrlazy"}
        while True:
            body = self.request("POST", "/api", payload)
            if not isinstance(body, list) or not body or not isinstance(body[0], dict):
                raise BindicatorError("Unexpected Hue Bridge pairing response.")
            result = body[0]
            success = result.get("success")
            if isinstance(success, dict) and isinstance(success.get("username"), str):
                return success["username"]
            error = result.get("error")
            if not isinstance(error, dict):
                raise BindicatorError("Unexpected Hue Bridge pairing response.")
            if str(error.get("type")) != "101":
                raise BindicatorError(
                    f"Hue Bridge refused pairing: {error.get('description', 'unknown error')}"
                )
            if clock.monotonic() >= deadline:
                raise BindicatorError(
                    "Pairing timed out waiting for the Hue Bridge link button. "
                    "Verify the Bridge address, press its link button and retry."
                )
            clock.sleep(min(retry_interval, max(0, deadline - clock.monotonic())))

    def lights(self) -> list[dict]:
        return self.request("GET", "/clip/v2/resource/light")["data"]

    def light(self, rid: str) -> dict:
        data = self.request("GET", f"/clip/v2/resource/light/{rid}")["data"]
        if not data:
            raise BindicatorError(f"Light {rid} does not exist on this Hue Bridge.")
        return data[0]

    def set(self, rid: str, payload: dict) -> None:
        self.request("PUT", f"/clip/v2/resource/light/{rid}", payload)


class Bindicator:
    def __init__(self, config: dict, state_dir: Path, hue: Hue | None = None):
        self.config = config
        self.state_dir = state_dir
        self.hue = hue
        self.state_path = state_dir / "state.json"
        self.cache_path = state_dir / "calendar.ics"
        try:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.state = {"date": None, "lights": {}}
        except (ValueError, OSError) as exc:
            raise BindicatorError("Unreadable state file; refusing to overwrite it.") from exc
        if not isinstance(self.state, dict) or not isinstance(self.state.get("lights"), dict):
            raise BindicatorError("Invalid state file.")
        # Earlier versions stored unqualified light IDs. Do not guess which
        # Bridge owns them when multiple Bridges are newly configured.
        old_ids = [key for key in self.state["lights"] if "/" not in key]
        if old_ids:
            bridges = config["hue"]["bridges"]
            origin = config["hue"].get("legacy_bridge")
            if origin is None and len(bridges) == 1:
                origin = next(iter(bridges))
            if origin is None:
                raise BindicatorError(
                    "Legacy state contains unqualified light IDs. Set "
                    "hue.legacy_bridge to the original Bridge name first."
                )
            for rid in old_ids:
                qualified = f"{origin}/{rid}"
                if qualified in self.state["lights"]:
                    raise BindicatorError("Conflicting legacy and qualified light state.")
                self.state["lights"][qualified] = self.state["lights"].pop(rid)
            self.save()

    def save(self) -> None:
        json_save(self.state_path, self.state)

    def council_cache_status(self) -> dict:
        """Return refresh metadata without disclosing property identifiers."""
        from .council_refresh import cache_status
        return cache_status(self.config, self.state_dir)

    def refresh_council(self, *, force: bool = False) -> dict:
        from .council_refresh import refresh_council
        return refresh_council(self.config, self.state_dir, force=force)

    def calendar_data(self) -> bytes:
        from .calendar_providers import active_source
        from .calendar_engine import calendar_data
        return calendar_data(active_source(self.config), self.config, self.state_dir)

    def zoho_calendar_data(self, *, allow_cache: bool = True) -> bytes:
        """Read a generic HTTPS iCalendar feed. Disable fallback for tests/refresh."""
        url = required_env("BINDICATOR_ICAL_URL")
        if not url.startswith("https://"):
            raise BindicatorError("Private iCalendar URL must use HTTPS.")
        try:
            from .ical_source import validate_public_ical_url
            validate_public_ical_url(url)
            response = requests.get(url, timeout=20, allow_redirects=False)
            if response.is_redirect:
                raise BindicatorError("iCalendar redirects are not supported; use the direct HTTPS feed URL.")
            response.raise_for_status()
            data = response.content
            if len(data) > 2_000_000:
                raise BindicatorError("iCalendar feed exceeds the 2 MB limit.")
            if b"BEGIN:VCALENDAR" not in data[:4096]:
                raise BindicatorError("URL did not return an iCalendar feed.")
        except (requests.RequestException, BindicatorError, ValueError) as exc:
            # Do not log the private iCal URL, even when an HTTP request fails.
            try:
                if allow_cache and self.cache_path.exists():
                    age = datetime.now().timestamp() - self.cache_path.stat().st_mtime
                    if 0 <= age <= 7 * 86400:
                        LOG.warning("Calendar unavailable; using recent cached copy.")
                        return self.cache_path.read_bytes()
            except OSError as cache_exc:
                raise BindicatorError("Cannot read the cached calendar feed.") from cache_exc
            raise BindicatorError("iCalendar download failed; no valid fresh response was received.") from exc

        # Store the validated download using a newly owned temporary file.
        # Do not chmod the existing cache: it might belong to a different
        # trusted member of the bindicator group (and chmod would raise EPERM).
        try:
            atomic_bytes_save(self.cache_path, data)
        except OSError as exc:
            raise BindicatorError(
                "Cannot update calendar cache; check /var/lib/bindicator permissions."
            ) from exc
        return data

    def collections(self, day: date) -> list[str]:
        found = parse_collections(
            self.calendar_data(), day, self.config["calendar"]["events"]
        )
        return ordered_colors(found, self.config["priority"])

    def restore(self, dry_run: bool = False) -> None:
        if not self.state["lights"]:
            if not dry_run:
                self.state["date"] = None
                self.state.pop("manual_until", None)
                self.state.pop("cycle_started", None)
                self.state.pop("active_colours", None)
                self.save()
            return
        failures = []
        for rid, record in list(self.state["lights"].items()):
            try:
                live = self.hue.light(rid)
                if (
                    not matches_target(live, saved_target(record))
                    or active_effect(live)
                    or not brightness_unchanged(
                        live, record.get("applied_brightness")
                    )
                ):
                    LOG.info(
                        "Light %s changed manually during alert; "
                        "leaving its current appearance alone.", rid
                    )
                else:
                    payload = restorable_snapshot(record, live)
                    if payload:
                        LOG.info("Restoring saved Hue state of %s.", rid)
                        if not dry_run:
                            self.hue.set(rid, payload)
                if not dry_run:
                    del self.state["lights"][rid]
                    self.save()
            except (BindicatorError, KeyError) as exc:
                LOG.error("Could not restore light %s: %s", rid, exc)
                failures.append(rid)
        if not dry_run and not self.state["lights"]:
            self.state["date"] = None
            self.state.pop("manual_until", None)
            self.state.pop("cycle_started", None)
            self.state.pop("active_colours", None)
            self.save()
        if failures:
            raise BindicatorError(f"Could not restore {len(failures)} light(s); will retry.")

    def acknowledge_bins_out(self) -> dict:
        """Dismiss an active collection reminder without pausing future reminders.

        Caller must hold run.lock. Mark the collection before restoring so a
        failed Hue operation cannot allow the timer to reapply the same alert.
        A repeated acknowledgement is harmless and never acknowledges an
        unrelated future collection if no reminder is active.
        """
        active = bool(self.state["lights"] or self.state.get("manual_until"))
        if not active:
            return {"acknowledged": False, "restored": True}
        target = self.state.get("manual_until") or self.state.get("date")
        if not isinstance(target, str):
            raise BindicatorError("Active reminder has no collection date; refusing to discard restoration state.")
        try:
            target_date = date.fromisoformat(target)
        except ValueError as exc:
            raise BindicatorError("Invalid active collection date; refusing to change lights.") from exc
        if target_date.isoformat() != target:
            raise BindicatorError("Invalid active collection date; refusing to change lights.")
        self.state["acknowledged_date"] = target
        self.save()
        self.restore()
        return {"acknowledged": True, "restored": True}

    def run(self, now: datetime, dry_run: bool = False) -> None:
        # Called under run.lock: user pause/resume and manual activation cannot
        # race the scheduled worker.
        from .controls import is_paused

        if is_paused(self.state_dir):
            LOG.info("Bindicator is paused: skipping reminder check and light restoration.")
            return
        if not self.hue:
            raise BindicatorError("Hue client is required.")

        # Acknowledged collections must remain dismissed even if the schedule
        # timer runs repeatedly before the collection morning. Keep the date
        # across restoration; later collection dates are unaffected.
        acknowledged = self.state.get("acknowledged_date")
        manual_until = self.state.get("manual_until")
        if manual_until and manual_until == acknowledged:
            self.restore(dry_run=dry_run)
            manual_until = None
        if manual_until:
            try:
                manual_date = date.fromisoformat(manual_until)
            except (TypeError, ValueError) as exc:
                raise BindicatorError(
                    "Invalid manual reminder expiry; refusing to change lights."
                ) from exc
            due = datetime.combine(manual_date, time.fromisoformat(self.config.get("schedule", {"restore": "09:00"})["restore"]), tzinfo=TZ)
            if now.astimezone(TZ) < due:
                if self.config["hue"].get("mode") == "cycle" and self.state.get("active_colours"):
                    self.apply_collections(manual_date, self.state["active_colours"], cycle_now=now)
                else:
                    LOG.info("Manually activated collection %s still showing; leaving it unchanged.", manual_until)
                return
            LOG.info("Manually activated collection %s is due for restoration.", manual_until)
            self.restore(dry_run=dry_run)
            # The morning restore has finished. Continue through normal
            # scheduling, so later collections are not accidentally missed.

        day = active_collection_date(now, self.config.get("schedule"))
        if day is None:
            LOG.info("Outside reminder window: restore any pending lights.")
            self.restore(dry_run=dry_run)
            return
        if day.isoformat() == acknowledged:
            LOG.info("Collection %s already put out; suppressing reminder.", day)
            self.restore(dry_run=dry_run)
            return
        colors = self.collections(day)
        LOG.info("Collection date %s: %s", day, ", ".join(colors) or "none")
        if not colors:
            self.restore(dry_run=dry_run)
            return
        if self.state.get("date") != day.isoformat():
            self.restore(dry_run=dry_run)
        self.apply_collections(day, colors, dry_run=dry_run, cycle_now=now)

    def apply_collections(
        self, day: date, colors: list[str], *, manual: bool = False,
        dry_run: bool = False, cycle_now: datetime | None = None,
    ) -> None:
        """Apply real reminder colours, preserving original lamp state.

        manual=True pins the reminder until the configured morning restoration time on the
        supplied collection date, independent of ordinary timer windows.
        """
        if not colors:
            raise BindicatorError("No collection colours to display.")
        if manual and (self.state["lights"] or self.state.get("manual_until")):
            raise BindicatorError(
                "A reminder is already active; refusing to override its saved lights."
            )
        ids = [
            f"{item['bridge']}/{item['id']}"
            for item in self.config["hue"].get("lights", [])
        ]
        if not ids:
            raise BindicatorError("Select Hue lights in hue.lights; see --list-lights.")
        mode = self.config["hue"].get("mode", "priority")
        if mode == "cycle":
            # The regular minute scheduler advances one step. No polling of the
            # calendar or extra background worker is needed for manual alerts.
            from datetime import timezone
            tick = (cycle_now or datetime.now(timezone.utc)).timestamp()
            start = self.state.get("cycle_started")
            if not isinstance(start, (int, float)) or self.state.get("date") != day.isoformat():
                start = tick
            sequence = ordered_colors(colors, self.config["priority"])
            index = max(0, int((tick - start) // 60)) % len(sequence)
            desired = {rid: sequence[index] for rid in ids}
        else:
            desired = assignments(ids, colors, mode)
        if dry_run:
            for rid, color in desired.items():
                LOG.info("DRY RUN: light %s => %s", rid, color)
            return
        self.state["date"] = day.isoformat()
        if mode == "cycle":
            self.state["cycle_started"] = start
            self.state["active_colours"] = sequence
        else:
            self.state.pop("cycle_started", None)
            self.state.pop("active_colours", None)
        if manual:
            self.state["manual_until"] = day.isoformat()
        self.save()
        mode = self.config["hue"].get("mode", "priority")
        override_lights = {
            f"{item['bridge']}/{item['id']}"
            for item in self.config["hue"].get("lights", [])
            if item.get("always_gradient") is True
        }
        for rid, color in desired.items():
            previous = self.state["lights"].get(rid)
            live = self.hue.light(rid)
            if "color" not in live and "gradient" not in live:
                LOG.warning("Skipping %s: lamp has no colour capability.", rid)
                continue
            target = reminder_target(live, colors, self.config["colors"], color, mode,
                                     always_gradient=rid in override_lights)
            is_on = live.get("on", {}).get("on") is True
            if previous:
                if (
                    not matches_target(live, saved_target(previous))
                    or active_effect(live)
                    or not brightness_unchanged(
                        live, previous.get("applied_brightness")
                    )
                ):
                    LOG.info("Skipping %s: manual lighting override detected.", rid)
                    continue
                if not is_on:
                    LOG.info("Skipping %s: light switched off during reminder.", rid)
                    continue
                if saved_target(previous) == target:
                    continue
                record = dict(previous)  # Preserve the very first snapshot.
            else:
                if is_on and matches_target(live, target) and not active_effect(live):
                    LOG.info("Light %s already shows %s; no change.", rid, color)
                    continue
                try:
                    snapshot = snapshot_light_state(live)
                except BindicatorError as exc:
                    LOG.warning(
                        "Skipping %s: cannot safely restore its current state: %s",
                        rid, exc
                    )
                    continue
                record = {
                    "original": original_color(live),  # For older Bindicator compatibility
                    "original_on": snapshot["on"]["on"],
                    "original_state": snapshot,
                }
                if "dimming" in snapshot:
                    record["applied_brightness"] = snapshot["dimming"]["brightness"]

            payload = dict(target)
            payload.update(alert_effect_override(live))
            if not is_on:
                payload["on"] = {"on": True}
            record["color_name"] = color
            if "gradient" in target:
                record.pop("applied_xy", None)
                record["applied_gradient"] = target["gradient"]
            else:
                record.pop("applied_gradient", None)
                record["applied_xy"] = target["color"]["xy"]

            # Write the original and intended state to disk BEFORE touching Hue:
            # a lost Hue acknowledgement or crash must not lose restoration data.
            self.state["lights"][rid] = record
            self.save()
            LOG.info("Setting light %s to %s and ensuring it is on.", rid, color)
            self.hue.set(rid, payload)
        # Don't restore lamps removed from selection until morning; avoids
        # unexpectedly changing a lamp during the evening reminder window.
