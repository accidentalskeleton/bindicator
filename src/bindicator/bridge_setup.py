"""Interactive pairing of discovered Hue Bridges and secure config persistence."""
from __future__ import annotations

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from ruamel.yaml import YAML

from .app import BindicatorError
from .bridge_discovery import available_bridges, discover_bridges, bridge_name
from .bridges import BridgePool

BRIDGE_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
APPLICATION_KEY = re.compile(r"[A-Za-z0-9]{12,256}\Z")


def _atomic_text(path: Path, content: str, *, private: bool = False) -> None:
    """Replace a text file without changing its owner or exposing credentials."""
    if not path.exists():
        raise BindicatorError(f"{path} does not exist. Run the Bindicator installer.")
    existing = path.stat()
    # Never follow a symlink for a root-owned configuration or secrets file.
    if path.is_symlink():
        raise BindicatorError(f"Refusing to update symlink: {path}")
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=f".{path.name}.", delete=False
    ) as stream:
        temp = Path(stream.name)
        try:
            mode = existing.st_mode & 0o777
            if private:
                mode &= 0o660  # trusted bindicator group; never world accessible
            os.fchmod(stream.fileno(), mode)
            # A non-root group member cannot chown files to root. The directory
            # is setgid bindicator so the group is retained; the owner becomes
            # the authorising user, and group access remains restricted.
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), existing.st_uid, existing.st_gid)
            elif os.fstat(stream.fileno()).st_gid != existing.st_gid:
                raise BindicatorError(
                    "Configuration directory must inherit the bindicator group."
                )
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, path)


def save_bridge_config(
    path: Path, name: str, host: str, bridge_id: str | None = None
) -> None:
    """Round-trip YAML update preserving comments and other settings."""
    from io import StringIO

    if not BRIDGE_NAME.fullmatch(name):
        raise BindicatorError("Bridge name must contain lowercase letters, numbers or _.")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    with path.open(encoding="utf-8") as stream:
        document = yaml.load(stream)
    hue = document.get("hue") if isinstance(document, dict) else None
    if not isinstance(hue, dict) or not isinstance(hue.get("bridges"), dict):
        raise BindicatorError("Expected hue.bridges in config.yaml; manual config needed.")
    old = hue["bridges"].get(name)
    if old is not None and not isinstance(old, dict):
        raise BindicatorError(f"Invalid existing Bridge configuration: {name}")
    if old is None:
        hue["bridges"][name] = {"host": host, "verify_tls": False}
    else:
        old["host"] = host
    if bridge_id:
        hue["bridges"][name]["id"] = bridge_id
    out = StringIO()
    yaml.dump(document, out)
    _atomic_text(path, out.getvalue())


def save_bridge_key(path: Path, name: str, key: str) -> None:
    """Safely update only this Bridge's key in the installed secrets file."""
    if not APPLICATION_KEY.fullmatch(key):
        raise BindicatorError("Hue Bridge returned an invalid application key.")
    name = name.upper()
    variable = f"BINDICATOR_HUE_KEY_{name}"
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(variable)}\s*=")
    replacement = f'{variable}="{key}"\n'
    replaced = False
    updated = []
    for line in lines:
        if pattern.match(line):
            if not replaced:
                updated.append(replacement)
                replaced = True
            # Remove redundant duplicate definitions for this key.
        else:
            updated.append(line)
    if not replaced:
        if updated and not updated[-1].endswith("\n"):
            updated[-1] += "\n"
        updated.append(replacement)
    _atomic_text(path, "".join(updated), private=True)



def remove_bridge_config_and_key(
    config_path: Path, secrets_path: Path, name: str,
) -> int:
    """Forget a configured Bridge, its saved selections and its application key.

    Does not delete lamps or registrations on the physical Hue Bridge. Both
    files are prepared before updates; restore the config if secrets writing
    fails to avoid a half-removed local Bridge.
    """
    from io import StringIO

    if not isinstance(name, str) or not BRIDGE_NAME.fullmatch(name):
        raise BindicatorError("Invalid Hue Bridge name.")
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    with config_path.open(encoding="utf-8") as stream:
        original_config = stream.read()
    doc = yaml.load(original_config)
    hue = doc.get("hue") if isinstance(doc, dict) else None
    if not isinstance(hue, dict) or not isinstance(hue.get("bridges"), dict):
        raise BindicatorError("Expected named hue.bridges in config.yaml.")
    if name not in hue["bridges"]:
        raise BindicatorError("The named Hue Bridge is not configured.")
    lights = hue.get("lights", [])
    if not isinstance(lights, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("bridge"), str)
        for item in lights
    ):
        raise BindicatorError("Invalid configured lamp selection; no changes made.")

    removed_count = sum(item["bridge"] == name for item in lights)
    hue["lights"] = [item for item in lights if item["bridge"] != name]
    del hue["bridges"][name]
    output = StringIO()
    yaml.dump(doc, output)
    new_config = output.getvalue()

    original_secrets = secrets_path.read_text(encoding="utf-8")
    variable = f"BINDICATOR_HUE_KEY_{name.upper()}"
    names = {variable}
    if name == "default":
        names.add("BINDICATOR_HUE_KEY")
    key_pattern = re.compile(
        r"^\s*(?:export\s+)?(?:" +
        "|".join(re.escape(key) for key in sorted(names)) + r")\s*="
    )
    new_secrets = "".join(
        line for line in original_secrets.splitlines(keepends=True)
        if not key_pattern.match(line)
    )

    _atomic_text(config_path, new_config)
    try:
        if new_secrets != original_secrets:
            _atomic_text(secrets_path, new_secrets, private=True)
    except BaseException:
        try:
            _atomic_text(config_path, original_config)
        except Exception as restore_error:
            raise BindicatorError(
                "Bridge key removal failed and config rollback failed; inspect local files."
            ) from restore_error
        raise

    for key in names:
        os.environ.pop(key, None)
    return removed_count


def setup_bridge(
    pool: BridgePool,
    config_path: Path,
    secrets_path: Path,
    *,
    prompt: Callable[[str], str] = input,
    discover: Callable[[], list[dict]] = discover_bridges,
) -> bool:
    """Select, pair and persist a Hue Bridge, with an explicit user confirmation."""
    print("Searching for Hue Bridges via local mDNS…")
    discoveries = discover()
    candidates = available_bridges(pool.bridges, discoveries)
    if not candidates:
        raise BindicatorError(
            "No Bridges discovered. Check mDNS or manually configure an IP first."
        )
    for i, candidate in enumerate(candidates, start=1):
        label = candidate.get("configured_as") or "(new)"
        paired = (
            "key configured" if label in pool.bridges and pool.has_key(label)
            else "not paired"
        )
        print(
            f"  {i}. {candidate['host']}  {candidate['name']}  "
            f"[{label}; {paired}; {candidate['source']}]"
        )
    choice = prompt("Select Bridge number to pair (Enter to cancel): ").strip()
    if not choice:
        print("Cancelled; no changes made.")
        return False
    if not choice.isascii() or not choice.isdecimal():
        raise BindicatorError("Enter a numeric Bridge selection.")
    index = int(choice)
    if not 1 <= index <= len(candidates):
        raise BindicatorError("Bridge number out of range.")
    selected = candidates[index - 1]
    name = selected.get("configured_as")
    if not name:
        suggestion = f"hue_{index}"
        name = prompt(f"Name this Bridge [{suggestion}]: ").strip() or suggestion
    if not BRIDGE_NAME.fullmatch(name):
        raise BindicatorError("Invalid Bridge name. Use lowercase letters, digits and _.")
    if name in pool.bridges:
        original_id = str(pool.bridges[name].get("id", "")).upper()
        candidate_id = selected.get("id", "").upper()
        if original_id and candidate_id and original_id != candidate_id:
            raise BindicatorError(
                "Selected Bridge has a different hardware ID than the configured "
                "Bridge with that name. Choose another name."
            )
        if not selected.get("configured_as") and pool.bridges[name]["host"] != selected["host"]:
            raise BindicatorError(
                "Existing Bridge name belongs to another address; "
                "choose a unique name or update its mapping explicitly."
            )

    confirm = prompt(
        f"Pair {name!r} at {selected['host']} and save key/config? [y/N]: "
    ).strip().casefold()
    if confirm not in ("y", "yes"):
        print("Cancelled; no changes made.")
        return False

    print(f"Press the physical Hue link button at {selected['host']} NOW.")
    # No existing application key is necessary for registration.
    from .app import Hue
    info = pool.bridges.get(name, {})
    client = Hue(selected["host"], None, info.get("verify_tls", False))
    key = client.pair()

    # Save key first: if config persistence fails the key is safely retained.
    # Neither the key nor the private calendar URL is printed by this command.
    save_bridge_key(secrets_path, name, key)
    save_bridge_config(config_path, name, selected["host"], selected.get("id"))
    print(
        f"Paired {name} and saved its Bridge address and application key. "
        "You can now run 'bindicator --list-lights'."
    )
    return True
