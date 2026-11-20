"""Named Hue Bridge clients and qualified light identifiers."""
from __future__ import annotations

import os

from .app import BindicatorError, Hue, required_env


def light_key(bridge_name: str, light_id: str) -> str:
    """Stable state key; different Bridges can have similar light identifiers."""
    return f"{bridge_name}/{light_id}"


class BridgePool:
    """Create local Hue clients lazily, with a separate key per Bridge."""

    def __init__(self, hue_config: dict):
        self.config = hue_config
        self.bridges = hue_config["bridges"]
        self._clients: dict[str, Hue] = {}

    @property
    def names(self) -> list[str]:
        return list(self.bridges)

    @staticmethod
    def _real_key(value: str) -> bool:
        """Treat the documented secrets.env placeholders as unconfigured."""
        value = value.strip()
        return bool(
            value and not value.upper().startswith(("PASTE_", "YOUR_"))
            and value.upper() not in ("CHANGEME", "TODO", "NOT_SET")
        )

    def has_key(self, name: str) -> bool:
        """Whether a Bridge key is supplied (without checking live permissions)."""
        if name not in self.bridges:
            raise BindicatorError(
                f"Unknown Hue Bridge {name!r}. Configured: {', '.join(self.names)}."
            )
        variable = f"BINDICATOR_HUE_KEY_{name.upper()}"
        if self._real_key(os.environ.get(variable, "")):
            return True
        return bool(
            self.config.get("_legacy")
            and name == "default"
            and self._real_key(os.environ.get("BINDICATOR_HUE_KEY", ""))
        )

    def client(self, name: str, *, pairing: bool = False) -> Hue:
        if name not in self.bridges:
            raise BindicatorError(
                f"Unknown Hue Bridge {name!r}. Configured: {', '.join(self.names)}."
            )
        bridge = self.bridges[name]
        if pairing:
            # Pairing does not require an existing application key.
            return Hue(bridge["host"], None, bridge.get("verify_tls", False))
        if name not in self._clients:
            variable = f"BINDICATOR_HUE_KEY_{name.upper()}"
            # Existing single-Bridge installations can keep their old key.
            if self.config.get("_legacy") and name == "default":
                try:
                    key = required_env(variable)
                except BindicatorError:
                    key = required_env("BINDICATOR_HUE_KEY")
            else:
                key = required_env(variable)
            self._clients[name] = Hue(
                bridge["host"], key, bridge.get("verify_tls", False)
            )
        return self._clients[name]

    def pair(self, name: str) -> str:
        return self.client(name, pairing=True).pair()

    def lights(self, name: str) -> list[dict]:
        return self.client(name).lights()

    def _route(self, ref: str) -> tuple[Hue, str]:
        if not isinstance(ref, str) or ref.count("/") != 1:
            raise BindicatorError(f"Invalid qualified Hue light reference: {ref!r}")
        name, light_id = ref.split("/", 1)
        if not light_id:
            raise BindicatorError(f"Missing Hue light ID in reference {ref!r}")
        return self.client(name), light_id

    def light(self, ref: str) -> dict:
        client, light_id = self._route(ref)
        return client.light(light_id)

    def set(self, ref: str, payload: dict) -> None:
        client, light_id = self._route(ref)
        client.set(light_id, payload)


def normalize_hue_config(hue: dict | None) -> None:
    """Validate named Bridges and ordered light selections in-place.

    Original single-Bridge configurations are upgraded at load time.
    """
    import re

    if not isinstance(hue, dict):
        raise BindicatorError("hue must be a YAML mapping.")
    if "bridge" in hue:
        if "bridges" in hue:
            raise BindicatorError("Use either hue.bridge or hue.bridges, not both.")
        host = hue["bridge"]
        if not isinstance(host, str) or not host.strip():
            raise BindicatorError("hue.bridge must be a LAN IP address or hostname.")
        lights = hue.get("lights", [])
        if not isinstance(lights, list) or any(not isinstance(i, str) for i in lights):
            raise BindicatorError("Legacy hue.lights must contain light-ID strings.")
        hue["bridges"] = {
            "default": {"host": host, "verify_tls": hue.get("verify_tls", False)}
        }
        hue["lights"] = [{"bridge": "default", "id": rid} for rid in lights]
        hue["_legacy"] = True
    else:
        hue["_legacy"] = False

    bridges = hue.get("bridges")
    if not isinstance(bridges, dict):
        raise BindicatorError("hue.bridges must be a mapping (it may be empty before setup).")
    for name, details in bridges.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise BindicatorError(
                f"Invalid Bridge name {name!r}: use lowercase letters, numbers and underscores."
            )
        if not isinstance(details, dict):
            raise BindicatorError(f"hue.bridges.{name} must be a YAML mapping.")
        host = details.get("host")
        if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
            raise BindicatorError(
                f"hue.bridges.{name}.host must be a LAN IP or hostname (no scheme or port)."
            )
        if not isinstance(details.get("verify_tls", False), (bool, str)):
            raise BindicatorError(f"hue.bridges.{name}.verify_tls must be bool or CA path.")

    chosen = hue.get("lights", [])
    if not isinstance(chosen, list):
        raise BindicatorError("hue.lights must be a list of {bridge, id} mappings.")
    seen = set()
    for item in chosen:
        if not isinstance(item, dict):
            raise BindicatorError("Each hue.lights entry must have bridge and id fields.")
        if set(item) - {"bridge", "id", "always_gradient"}:
            raise BindicatorError("Unsupported selected Hue light option.")
        if "always_gradient" in item and type(item["always_gradient"]) is not bool:
            raise BindicatorError("always_gradient must be true or false.")
        name, rid = item.get("bridge"), item.get("id")
        if name not in bridges:
            raise BindicatorError(f"Selected light references unknown Hue Bridge {name!r}.")
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9-]{2,64}", rid):
            raise BindicatorError(f"Invalid Hue v2 light ID: {rid!r}.")
        key = light_key(name, rid)
        if key in seen:
            raise BindicatorError(f"Duplicate selected Hue light {key}.")
        seen.add(key)

    legacy_bridge = hue.get("legacy_bridge")
    if legacy_bridge is not None and legacy_bridge not in bridges:
        raise BindicatorError("hue.legacy_bridge must name an existing Bridge.")
    if hue.get("mode", "priority") not in ("priority", "spread", "cycle"):
        raise BindicatorError("hue.mode must be priority, spread or cycle.")
