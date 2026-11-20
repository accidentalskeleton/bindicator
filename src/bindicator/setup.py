"""Primary first-run wizard: discover Bridges, pair, and select Hue lamps."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Callable

from ruamel.yaml import YAML

from .app import BindicatorError, Hue, load_config
from .bridge_discovery import available_bridges, discover_bridges
from .bridge_setup import BRIDGE_NAME, _atomic_text, save_bridge_config, save_bridge_key
from .bridges import BridgePool
from .light_selection import configure_lights, parse_choice


def _check_no_active_reminder(state_dir: Path) -> None:
    """Never discard bridge routing required to restore live lamp colours."""
    path = state_dir / "state.json"
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindicatorError(
            "Cannot inspect existing state.json; refusing to reconfigure Hue Bridges."
        ) from exc
    if not isinstance(state, dict) or not isinstance(state.get("lights"), dict):
        raise BindicatorError("Invalid saved lamp state; refusing to reconfigure.")
    if state["lights"]:
        raise BindicatorError(
            "An active bin reminder has saved lamp colours. Restore them with "
            "'sudo -u bindicator bindicator --run' outside the reminder window "
            "before reconfiguring Bridges."
        )


def _reset_hue_settings(config_path: Path, secrets_path: Path) -> None:
    """Reset only Hue setup, not Zoho settings, mappings or colour definitions."""
    from io import StringIO

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    with config_path.open(encoding="utf-8") as file:
        config = yaml.load(file)
    if not isinstance(config, dict) or not isinstance(config.get("hue"), dict):
        raise BindicatorError("Configuration is missing a Hue settings section.")
    config["hue"].pop("bridge", None)
    config["hue"].pop("legacy_bridge", None)
    config["hue"]["bridges"] = {}
    config["hue"]["lights"] = []
    output = StringIO()
    yaml.dump(config, output)

    # Delete superseded Hue keys, retaining the private Zoho feed URL.
    existing = secrets_path.read_text(encoding="utf-8")
    lines = []
    for line in existing.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if stripped.startswith("BINDICATOR_HUE_KEY=") or stripped.startswith(
            "BINDICATOR_HUE_KEY_"
        ):
            continue
        lines.append(line)
    _atomic_text(config_path, output.getvalue())
    _atomic_text(secrets_path, "".join(lines), private=True)
    for name in list(os.environ):
        if name == "BINDICATOR_HUE_KEY" or name.startswith("BINDICATOR_HUE_KEY_"):
            del os.environ[name]


def _manual_candidate(prompt: Callable[[str], str]) -> dict | None:
    raw = prompt(
        "No bridges discovered. Enter a Hue Bridge LAN IPv4 address "
        "(Enter to cancel): "
    ).strip()
    if not raw:
        return None
    try:
        address = ipaddress.IPv4Address(raw)
    except ipaddress.AddressValueError as exc:
        raise BindicatorError("Enter a valid local IPv4 address.") from exc
    if not address.is_private:
        raise BindicatorError("Bridge addresses must be on a private LAN.")
    return {
        "host": str(address),
        "id": "",
        "name": "Manually entered Hue Bridge",
        "source": "manual",
    }


def guided_setup(
    config_path: Path,
    secrets_path: Path,
    state_dir: Path,
    *,
    fresh: bool = False,
    prompt: Callable[[str], str] = input,
    discover: Callable[[], list[dict]] = discover_bridges,
    choose_lights: Callable = configure_lights,
) -> bool:
    """Automatic discovery is default; manual IP is a fallback only.

    Existing hosts are retained as discovery fallbacks. Explicit --fresh
    resets old Hue settings, but never bin mappings or Zoho credentials.
    """
    _check_no_active_reminder(state_dir)
    config = load_config(config_path)
    original_bridges = config["hue"]["bridges"]
    print("Discovering Hue Bridges on the local network (mDNS)…")
    try:
        discovered = discover()
    except BindicatorError as exc:
        print(f"Local discovery unavailable: {exc}")
        discovered = []

    if fresh:
        # Explicitly reset old manual Hue setup, but only after user confirms.
        answer = prompt(
            "Replace ALL existing Hue Bridge addresses, lamp selections "
            "and stored Hue keys? Type RESET: "
        ).strip()
        if answer != "RESET":
            print("Cancelled; Hue configuration unchanged.")
            return False

    sources = {} if fresh else original_bridges
    candidates = available_bridges(sources, discovered)
    if not candidates:
        manual = _manual_candidate(prompt)
        if manual is None:
            print("No changes made.")
            return False
        candidates = [manual]

    print("Available Hue Bridges:")
    for index, candidate in enumerate(candidates, 1):
        mapped = candidate.get("configured_as", "(new)")
        print(
            f"  {index}. {candidate['host']} — {candidate['name']} "
            f"[{mapped}; {candidate['source']}]"
        )

    # Select discovered Bridges by default. Configured fallback addresses
    # only become the default when discovery returned nothing.
    preferred = [
        i for i, item in enumerate(candidates)
        if item.get("source") == "mDNS"
    ]
    if not preferred:
        preferred = list(range(len(candidates)))
    default_label = ",".join(str(i + 1) for i in preferred)
    raw = prompt(
        f"Bridges to configure (numbers separated by commas) [{default_label}]: "
    ).strip()
    if not raw:
        indexes = preferred
    else:
        try:
            indexes = parse_choice(raw, len(candidates))
        except KeyboardInterrupt:
            print("Cancelled; no changes made.")
            return False
        if indexes is None or not indexes:
            print("No Bridges selected; no changes made.")
            return False

    if fresh:
        _reset_hue_settings(config_path, secrets_path)

    changed = False
    for index in indexes:
        candidate = candidates[index]
        current = load_config(config_path)
        configured = current["hue"]["bridges"]
        name = candidate.get("configured_as") if not fresh else None
        if not name:
            number = 1
            while f"bridge{number}" in configured:
                number += 1
            default_name = f"bridge{number}"
            name = prompt(
                f"Name {candidate['host']} (e.g. office/house) [{default_name}]: "
            ).strip().lower() or default_name
        if not BRIDGE_NAME.fullmatch(name):
            raise BindicatorError(
                "Bridge names must start with a lowercase letter and contain "
                "only lowercase letters, digits or underscores."
            )
        # A name can be reused only when the hardware ID matches, or the
        # user explicitly confirms overwriting an address without an ID.
        existing = configured.get(name)
        if existing is not None:
            known_id = str(existing.get("id", "")).upper()
            discovered_id = str(candidate.get("id", "")).upper()
            if known_id and discovered_id and known_id != discovered_id:
                raise BindicatorError(
                    f"Refusing to reuse {name!r}: its known Bridge ID differs "
                    "from the discovered hardware."
                )
            if existing["host"] != candidate["host"] and not (
                known_id and discovered_id and known_id == discovered_id
            ):
                response = prompt(
                    f"Overwrite {name!r} host {existing['host']} with "
                    f"{candidate['host']}? [y/N]: "
                ).strip().lower()
                if response not in ("y", "yes"):
                    print(f"Skipped {name}.")
                    continue

        known_key = (
            not fresh
            and name in configured
            and BridgePool(current["hue"]).has_key(name)
        )
        # A different host with no stable ID cannot safely use an old key.
        if known_key and existing is not None and (
            existing["host"] == candidate["host"]
            or (
                str(existing.get("id", "")).upper()
                and str(existing.get("id", "")).upper()
                == str(candidate.get("id", "")).upper()
            )
        ):
            print(f"{name}: already paired; keeping its existing application key.")
            save_bridge_config(
                config_path, name, candidate["host"], candidate.get("id")
            )
            changed = True
            continue

        response = prompt(
            f"Pair Bridge {name!r} at {candidate['host']} now? [y/N]: "
        ).strip().lower()
        if response not in ("y", "yes"):
            print(f"Skipped {name}.")
            continue

        print(f"Press the physical link button on {name} ({candidate['host']}) NOW.")
        client = Hue(candidate["host"], None, False)
        try:
            key = client.pair()
        except BindicatorError as exc:
            print(f"Pairing {name} failed: {exc}")
            continue
        # Save key and Bridge mapping only after successful authentication.
        save_bridge_key(secrets_path, name, key)
        save_bridge_config(config_path, name, candidate["host"], candidate.get("id"))
        # Make the new key available immediately to the selection phase.
        os.environ[f"BINDICATOR_HUE_KEY_{name.upper()}"] = key
        changed = True
        print(f"Paired {name}; saved address and application key (not displayed).")

    latest = load_config(config_path)
    pool = BridgePool(latest["hue"])
    if any(pool.has_key(name) for name in pool.names):
        print("Now select the lamps to use as bin indicators.")
        choose_lights(pool, latest, config_path, prompt=prompt)
    else:
        print("No paired Bridges available. Re-run --setup to complete pairing.")
    return changed
