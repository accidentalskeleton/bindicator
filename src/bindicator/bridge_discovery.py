"""Find Hue Bridges on the LAN using the _hue._tcp.local. mDNS service."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

from .app import BindicatorError

LOG = logging.getLogger("bindicator")
SERVICE = "_hue._tcp.local."


class _HueListener(ServiceListener):
    def __init__(self):
        self.found: list[dict[str, str]] = []
        self.lock = threading.Lock()

    def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        info = zc.get_service_info(service_type, name, timeout=1500)
        if not info:
            return
        addresses = info.parsed_addresses()
        ipv4 = [address for address in addresses if ":" not in address]
        if not ipv4:
            return
        props = {
            k.decode("utf-8", "replace").lower(): v.decode("utf-8", "replace")
            for k, v in info.properties.items()
            if isinstance(k, bytes) and isinstance(v, bytes)
        }
        candidate = {
            "host": ipv4[0],
            "id": props.get("bridgeid", "").upper(),
            "name": name.split("._hue._tcp.", 1)[0],
            "source": "mDNS",
        }
        with self.lock:
            if not any(
                (candidate["id"] and e["id"] == candidate["id"])
                or e["host"] == candidate["host"]
                for e in self.found
            ):
                self.found.append(candidate)

    def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        pass

    def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        self.add_service(zc, service_type, name)


def discover_bridges(duration: float = 4.0) -> list[dict[str, str]]:
    """Return mDNS announcements. No Hue cloud call or credentials needed."""
    listener = _HueListener()
    try:
        with Zeroconf() as zc:
            browser = ServiceBrowser(zc, SERVICE, listener=listener)
            try:
                time.sleep(duration)
            finally:
                browser.cancel()
    except (OSError, ValueError) as exc:
        raise BindicatorError(f"Could not discover Hue Bridges using mDNS: {exc}") from exc
    return sorted(listener.found, key=lambda item: (item["name"], item["host"]))


def bridge_name(candidate: dict, configured: dict) -> str | None:
    """Prefer stable Bridge ID; fall back to matching configured LAN IP."""
    bridge_id = candidate.get("id", "").upper()
    if bridge_id:
        for name, bridge in configured.items():
            if str(bridge.get("id", "")).upper() == bridge_id:
                return name
    for name, bridge in configured.items():
        if bridge.get("host") == candidate.get("host"):
            # Refuse to match different known Bridge IDs even if IPs got reused.
            existing_id = str(bridge.get("id", "")).upper()
            if existing_id and bridge_id and existing_id != bridge_id:
                continue
            return name
    return None


def available_bridges(configured: dict, discovered: list[dict]) -> list[dict]:
    """Merge mDNS discoveries and configured hosts without duplicating Bridges."""
    results = []
    matched = set()
    for item in discovered:
        candidate = dict(item)
        name = bridge_name(candidate, configured)
        if name:
            candidate["configured_as"] = name
            matched.add(name)
        results.append(candidate)
    for name, bridge in configured.items():
        if name in matched:
            continue
        results.append({
            "host": bridge["host"],
            "id": str(bridge.get("id", "")).upper(),
            "name": name,
            "source": "config (not discovered via mDNS)",
            "configured_as": name,
        })
    return results
