"""Interactive Hue lamp selection with comment-preserving YAML updates."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .app import BindicatorError
from .bridges import BridgePool, light_key


def light_capability_label(light: dict) -> str:
    """Describe capabilities reported by this specific Hue API v2 light."""
    gradient = light.get("gradient")
    if isinstance(gradient, dict):
        count = gradient.get("points_capable")
        if type(count) is int and count >= 2:
            label = f"gradient, up to {count} colours"
        else:
            label = "gradient (colour-point limit not reported)"
        modes = gradient.get("mode_values")
        if isinstance(modes, list) and "segmented_palette" in modes:
            label += ", segmented"
        pixels = gradient.get("pixel_count")
        if type(pixels) is int and pixels > 0:
            label += f", {pixels} pixels"
        return label
    return "colour" if "color" in light else "no colour control"


def parse_choice(raw: str, count: int) -> list[int] | None:
    """Return zero-based indices in user's order; None means keep settings."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.casefold() in ("q", "quit", "cancel"):
        raise KeyboardInterrupt
    if raw.casefold() in ("none", "clear"):
        return []
    found = []
    for token in raw.split(","):
        token = token.strip()
        if not token.isascii() or not token.isdecimal():
            raise BindicatorError(
                "Enter lamp numbers separated by commas (e.g. 1,3), "
                "'none' to clear, or Enter to keep existing."
            )
        number = int(token)
        if number < 1 or number > count:
            raise BindicatorError(f"Lamp number {number} is not in the list.")
        if number - 1 not in found:
            found.append(number - 1)
    return found


def write_selected_config(path: Path, selection: list[dict]) -> None:
    """Atomically replace only hue.lights, retaining comments and file ownership."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        original = path.stat()
        with path.open(encoding="utf-8") as stream:
            document = yaml.load(stream)
        if not isinstance(document, dict) or not isinstance(document.get("hue"), dict):
            raise BindicatorError("Configuration must contain a hue mapping.")
        if "bridge" in document["hue"] and "bridges" not in document["hue"]:
            # Preserve the original single-Bridge syntax when possible.
            if any(item["bridge"] != "default" for item in selection):
                raise BindicatorError("Cannot mix named Bridges into legacy configuration.")
            items = CommentedSeq([item["id"] for item in selection])
        else:
            items = CommentedSeq()
            for item in selection:
                fields = [("bridge", item["bridge"]), ("id", item["id"])]
                if item.get("always_gradient") is True:
                    fields.append(("always_gradient", True))
                items.append(CommentedMap(fields))
        document["hue"]["lights"] = items
        # Avoid leaving misleading commented examples from an earlier selection.
        # Other user comments, bin events and colour mappings remain untouched.
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False
        ) as stream:
            temp = Path(stream.name)
            try:
                os.fchmod(stream.fileno(), original.st_mode & 0o777)
                if os.geteuid() == 0:
                    os.fchown(stream.fileno(), original.st_uid, original.st_gid)
                elif os.fstat(stream.fileno()).st_gid != original.st_gid:
                    raise BindicatorError(
                        "Configuration directory must inherit the bindicator group."
                    )
                yaml.dump(document, stream)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        os.replace(temp, path)
    except (OSError, ValueError) as exc:
        raise BindicatorError(
            f"Could not update {path}; run 'sudo bindicator --configure-lights' "
            "to write the root-owned configuration."
        ) from exc


def configure_lights(
    pool: BridgePool,
    config: dict,
    config_path: Path,
    prompt: Callable[[str], str] = input,
) -> bool:
    """Pick colour-capable lights from all paired Bridges and save by Hue v2 ID.

    An unpaired Bridge is skipped. A paired Bridge that fails discovery aborts
    safely rather than silently losing an existing selection.
    """
    existing = config["hue"]["lights"]
    selected_before = {light_key(item["bridge"], item["id"]) for item in existing}
    existing_options = {
        light_key(item["bridge"], item["id"]): item.get("always_gradient", False)
        for item in existing
    }
    available: list[dict] = []
    paired_bridges = set()
    for name in pool.names:
        print(f"[{name}] {pool.bridges[name]['host']}")
        if not pool.has_key(name):
            print("  Not paired — skipping this Bridge.")
            continue
        try:
            lights = pool.lights(name)
        except BindicatorError as exc:
            raise BindicatorError(
                f"Could not discover lights on paired Bridge {name!r}: {exc}. "
                "Configuration was not changed."
            ) from exc
        paired_bridges.add(name)
        capable = [
            lamp for lamp in lights
            if isinstance(lamp, dict) and ("color" in lamp or "gradient" in lamp) and isinstance(lamp.get("id"), str)
        ]
        for lamp in sorted(capable, key=lambda v: v.get("metadata", {}).get("name", "")):
            entry = {"bridge": name, "id": lamp["id"]}
            if existing_options.get(light_key(name, lamp["id"])):
                entry["always_gradient"] = True
            key = light_key(name, lamp["id"])
            available.append(entry)
            marker = "x" if key in selected_before else " "
            label = lamp.get("metadata", {}).get("name", "(unnamed)")
            print(
                f"  [{marker}] {len(available):>2}. {label}  ({name}) "
                f"[{light_capability_label(lamp)}]"
            )
        if not capable:
            print("  No colour-capable lights found.")

    if not paired_bridges:
        raise BindicatorError(
            "No paired Hue Bridges; pair at least one before configuring lights."
        )

    # Keep selections on as-yet-unpaired Bridges, so another Bridge becoming
    # temporarily unavailable cannot erase the user's earlier configuration.
    retained = [
        item for item in existing if item["bridge"] not in paired_bridges
    ]
    if retained:
        print(f"Preserving {len(retained)} previously selected lamp(s) on unpaired Bridges.")
    print("In 'spread' mode, colour order restarts independently on each Bridge.")
    print("Gradient-capable lamps can display several collection colours on one lamp.")
    print("Enter lamp numbers (e.g. 1,3), 'none' to clear accessible selections,")
    print("Enter to keep the existing configuration, or 'q' to cancel.")
    try:
        chosen = parse_choice(prompt("Select indicator lights: "), len(available))
    except KeyboardInterrupt:
        print("Cancelled; configuration unchanged.")
        return False

    if chosen is None:
        print("Unchanged.")
        return False

    combined = [available[index] for index in chosen] + retained
    print("New selection:")
    if not combined:
        print("  (no indicator lights selected)")
    for item in combined:
        print(f"  {item['bridge']} / {item['id']}")
    confirmation = prompt(f"Save to {config_path}? [y/N]: ").strip().casefold()
    if confirmation not in ("y", "yes"):
        print("Cancelled; configuration unchanged.")
        return False

    write_selected_config(config_path, combined)
    print(f"Saved {len(combined)} light(s) to {config_path}.")
    return True
