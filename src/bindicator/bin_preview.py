"""Simulate real bin collections briefly, then restore Hue lamp appearance.

Preview never reads Zoho or writes persisted Bindicator reminder state.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import date, datetime, timedelta
from collections.abc import Callable

from .app import (
    TZ, BindicatorError, active_effect, alert_effect_override, assignments,
    brightness_unchanged, collections_in_range, collection_events_in_range, matches_target, ordered_colors,
    reminder_target, restorable_snapshot, snapshot_light_state,
)
from .bridges import light_key

LOG = logging.getLogger("bindicator")


def available_bin_types(config: dict) -> list[tuple[str, str]]:
    """Return the configured calendar event names and associated colours."""
    return list(config["calendar"]["events"].items())


def resolve_bin_types(config: dict, names: str) -> list[str]:
    """Resolve comma-separated event titles or unique shortened names.

    For example, a configured 'BinDay - Recycling' can be requested as
    either 'BinDay - Recycling' or 'recycling'. No Zoho query is needed.
    """
    mapping = config["calendar"]["events"]
    aliases: dict[str, set[str]] = {}
    for event in mapping:
        variations = {event.strip().casefold()}
        if " - " in event:
            variations.add(event.split(" - ", 1)[1].strip().casefold())
        for alias in variations:
            aliases.setdefault(alias, set()).add(event)

    values = [token.strip().casefold() for token in names.split(",")]
    if not values or any(not value for value in values):
        raise BindicatorError(
            "Specify at least one bin collection type, separated by commas."
        )
    resolved = []
    for name in values:
        options = aliases.get(name, set())
        if not options:
            available = ", ".join(mapping)
            raise BindicatorError(
                f"Unknown collection type {name!r}. Available events: {available}"
            )
        if len(options) > 1:
            raise BindicatorError(
                f"Ambiguous collection type {name!r}; use the full event title."
            )
        event = next(iter(options))
        colour = mapping[event]
        if colour not in resolved:
            resolved.append(colour)
    return ordered_colors(resolved, config["priority"])


def upcoming_collections(
    config: dict,
    calendar_data: bytes,
    now: datetime,
    *,
    limit: int = 5,
    days_ahead: int = 365,
) -> list[dict]:
    """Future collection *dates*, grouped with all exact matching events.

    A single Zoho feed expansion returns up to five distinct days, including
    combined-bin dates as one row. Like next_collection, today is excluded.
    """
    if not 1 <= limit <= 20 or not 1 <= days_ahead <= 366:
        raise ValueError("Invalid upcoming collection window.")
    start = now.astimezone(TZ).date() + timedelta(days=1)
    found = collection_events_in_range(
        calendar_data, start, start + timedelta(days=days_ahead),
        config["calendar"]["events"],
    )
    results = []
    for day in sorted(found)[:limit]:
        rank = {name: i for i, name in enumerate(config["priority"])}
        events = sorted(found[day], key=lambda event: (
            rank.get(event["colour"], len(rank)), event["title"].casefold()
        ))
        results.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "collections": [
                event["title"].split(" - ", 1)[-1]
                for event in events
            ],
            "display_colours": [event["colour"] for event in events],
            "colours": ordered_colors(
                [event["colour"] for event in events], config["priority"]
            ),
        })
    return results


def next_collection(
    config: dict,
    calendar_data: bytes,
    now: datetime,
    days_ahead: int = 365,
) -> tuple[date, list[str]]:
    """Find the next collection strictly after today's UK local date.

    Uses exactly the same event-title matching and recurrence expansion as
    normal Bindicator. A single calendar download covers the whole search.
    """
    today = now.astimezone(TZ).date()
    start = today + timedelta(days=1)
    end = start + timedelta(days=days_ahead)
    found = collections_in_range(
        calendar_data, start, end, config["calendar"]["events"]
    )
    if not found:
        raise BindicatorError(
            f"No matching future bin collection in the next {days_ahead} days. "
            "Check the Zoho feed and calendar.events mapping."
        )
    target_day = min(found)
    return target_day, ordered_colors(found[target_day], config["priority"])



def launch_detached_preview(
    *, config_path: Path, secrets_path: Path, state_dir: Path,
    colours: list[str], seconds: int, lock_fd: int,
) -> int:
    """Hand an already-held run.lock to a detached, short-lived worker.

    The file lock uses an inherited open-file description: closing the
    parent's fd after Popen does not release the lock while the worker holds
    its copy. Thus scheduled runs, another preview and pause cannot overlap
    the preview or its restoration. No Hue credentials enter the argv.
    """
    if not 1 <= seconds <= 60:
        raise BindicatorError("--seconds must be between 1 and 60.")
    if not colours:
        raise BindicatorError("No collection colours supplied.")
    log_path = state_dir / "preview.log"
    # Group-restricted log; O_NOFOLLOW prevents a log-file symlink being
    # followed within this otherwise trusted, group-writable directory.
    fd = os.open(
        log_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o660,
    )
    try:
        with os.fdopen(fd, "ab", buffering=0) as output:
            command = [
                sys.executable, "-m", "bindicator.preview_worker",
                "--config", str(config_path),
                "--secrets-file", str(secrets_path),
                "--state-dir", str(state_dir),
                "--seconds", str(seconds),
                "--lock-fd", str(lock_fd),
                "--colours", ",".join(colours),
            ]
            child = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                pass_fds=(lock_fd,),
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        raise BindicatorError(
            "Could not start the detached preview worker."
        ) from exc
    return child.pid


def identify_light(
    pool,
    ref: str,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Momentarily invert one lamp's power to identify it, then restore.

    Preflight refuses unrecoverable scenes. Only the explicitly requested
    lamp is affected; no configured light selection is changed. A manual
    intervention during the pulse is respected rather than overwritten.
    Callers must hold run.lock and refuse active reminders.
    """
    original_light = pool.light(ref)
    if "color" not in original_light and "gradient" not in original_light:
        raise BindicatorError("Selected light does not support colour indication.")
    original = snapshot_light_state(original_light)
    pulse_on = not original["on"]["on"]
    changed = False
    restored = False
    try:
        # Record intent before sending: the Bridge might apply a write even
        # when the HTTP acknowledgement is lost.
        changed = True
        pool.set(ref, {"on": {"on": pulse_on}})
        sleeper(0.8)
    finally:
        if changed:
            live = pool.light(ref)
            if (live.get("on") or {}).get("on") is pulse_on and not active_effect(live):
                before_brightness = (original.get("dimming") or {}).get("brightness")
                if brightness_unchanged(live, before_brightness):
                    # The identify pulse itself deliberately switched an
                    # originally-on lamp off. Generic reminder restoration
                    # suppresses powering on a manually switched-off lamp,
                    # so here we use the preflight snapshot directly after
                    # verifying the light is still in our pulse state.
                    pool.set(ref, original)
                    restored = True
            if not restored:
                LOG.info("Identify %s: light changed manually; not restoring over user action.", ref)
    return restored


def preview_lights(
    pool,
    config: dict,
    colours: list[str],
    seconds: int = 5,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Use production priority/spread assignment for a short, reversible preview.

    Preflight snapshots each light's writable Hue state (including brightness,
    effects, gradient and power) before any write. Static appearances are
    restored after the test; manual changes are never overwritten.
    """
    if not 1 <= seconds <= 60:
        raise BindicatorError("--seconds must be between 1 and 60.")
    selected = [
        light_key(item["bridge"], item["id"])
        for item in config["hue"]["lights"]
    ]
    if not selected:
        raise BindicatorError(
            "No indicator lamps selected. Run: sudo bindicator --setup"
        )
    if not colours:
        raise BindicatorError("No collection colours supplied.")
    mode = config["hue"].get("mode", "priority")
    override_lights = {
        light_key(item["bridge"], item["id"])
        for item in config["hue"]["lights"]
        if item.get("always_gradient") is True
    }
    desired = assignments(selected, colours, mode)
    originals: dict[str, dict] = {}
    targets: dict[str, dict] = {}
    effect_overrides: dict[str, dict] = {}
    for rid, colour in desired.items():
        light = pool.light(rid)
        if "color" not in light and "gradient" not in light:
            LOG.warning("Skipping non-colour light %s.", rid)
            continue
        target = reminder_target(light, colours, config["colors"], colour, mode,
                                 always_gradient=rid in override_lights)
        was_on = light.get("on", {}).get("on") is True
        if was_on and matches_target(light, target) and not active_effect(light):
            LOG.info("%s already displays %s; leaving it unchanged.", rid, colour)
            continue
        try:
            originals[rid] = snapshot_light_state(light)
        except BindicatorError as exc:
            LOG.warning(
                "Skipping %s: cannot safely restore its current state: %s",
                rid, exc
            )
            continue
        targets[rid] = target
        effect_overrides[rid] = alert_effect_override(light)

    changed = {}
    errors = []
    try:
        for rid, target in targets.items():
            # Add to restoration set *before* the command in case a Bridge
            # applies the change but its HTTP acknowledgement is lost.
            changed[rid] = desired[rid]
            LOG.info("Preview %s: %s", rid, desired[rid])
            payload = dict(target)
            payload.update(effect_overrides[rid])
            if not originals[rid]["on"]["on"]:
                payload["on"] = {"on": True}
            pool.set(rid, payload)
        if changed:
            sleeper(seconds)
        return desired
    finally:
        for rid, colour in changed.items():
            original = originals[rid]
            try:
                live = pool.light(rid)
                original_brightness = (original.get("dimming") or {}).get("brightness")
                if (
                    matches_target(live, targets[rid])
                    and not active_effect(live)
                    and brightness_unchanged(live, original_brightness)
                ):
                    payload = restorable_snapshot({"original_state": original}, live)
                    if payload:
                        pool.set(rid, payload)
                else:
                    LOG.info(
                        "Leaving %s unchanged: scene/brightness changed manually.", rid
                    )
            except Exception as exc:
                LOG.error("Failed to restore preview on %s: %s", rid, exc)
                errors.append(rid)
        if errors:
            raise BindicatorError(
                f"Could not restore preview for {len(errors)} lamp(s): "
                + ", ".join(errors)
            )
