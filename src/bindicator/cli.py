"""Bindicator command-line interface."""
from __future__ import annotations

import argparse
import fcntl
import os
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .app import (
    DEFAULT_CONFIG, DEFAULT_SECRETS, DEFAULT_STATE_DIR, TZ,
    Bindicator, BindicatorError, load_config, load_secrets,
    ordered_colors, parse_collections,
)
from .bridges import BridgePool, light_key

LOG = logging.getLogger("bindicator")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bindicator",
        description="Zoho Calendar to multi-Bridge Philips Hue bin collection reminders",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--run", action="store_true", help="Run a reminder check (default)")
    action.add_argument(
        "--setup", action="store_true",
        help="Discover Hue Bridges, pair, and select indicator lights (first-run default)"
    )
    action.add_argument("--list-lights", action="store_true", help="List lights on all Hue Bridges")
    action.add_argument(
        "--discover-bridges", action="store_true",
        help="Find Hue Bridges advertised by mDNS on the local network"
    )
    action.add_argument(
        "--setup-bridges", action="store_true",
        help="Interactively pair a Hue Bridge and save its config and key"
    )
    action.add_argument(
        "--configure-lights", action="store_true",
        help="Interactively select lamps and update config.yaml"
    )
    action.add_argument(
        "--pair", metavar="BRIDGE", help="Pair one named Hue Bridge (press its button first)"
    )
    action.add_argument(
        "--check-calendar", action="store_true",
        help="Print matching collections for the next 30 days"
    )
    action.add_argument("--status", action="store_true", help="Show pause status and saved reminder state")
    action.add_argument("--pause", action="store_true", help="Pause all automatic Hue reminders")
    action.add_argument("--resume", action="store_true", help="Resume automatic Hue reminders")
    action.add_argument("--toggle", action="store_true", help="Toggle reminders between paused and active")
    action.add_argument("--dry-run", action="store_true", help="Calculate without changing lamps")
    action.add_argument("--test", metavar="COLOUR", help="Preview colour on configured lamps")
    action.add_argument(
        "--test-bin", metavar="COLLECTIONS", nargs="?", const="__next_collection__",
        help="Preview named bin collections or use --next-collection to read Zoho"
    )
    action.add_argument(
        "--list-bin-types", action="store_true",
        help="List configured collection names accepted by --test-bin"
    )
    parser.add_argument(
        "--bridge", metavar="NAME", help="Filter --list-lights to one named Bridge"
    )
    parser.add_argument(
        "--seconds", type=int, default=None,
        help="Preview duration in seconds (1-60); with --next-collection, omitting it keeps the reminder active"
    )
    parser.add_argument(
        "--next-collection", action="store_true",
        help="Show next collection persistently, or preview with --seconds (1-60)"
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="With --setup, replace existing Hue Bridge, lamp and key settings"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Shared state/cache/lock files must remain accessible to the trusted
    # bindicator group (the systemd service also uses UMask=0007).
    os.umask(0o007)

    try:
        config = load_config(args.config)
        load_secrets(args.secrets_file)
        if args.bridge and not args.list_lights:
            raise BindicatorError("--bridge is only supported with --list-lights.")
        if args.fresh and not args.setup:
            raise BindicatorError("--fresh is only supported with --setup.")
        # --next-collection persists without --seconds and previews with it.
        # --test-bin --next-collection retains the short preview alias.
        if args.test_bin == "__next_collection__" and not args.next_collection:
            raise BindicatorError(
                "Use --next-collection alone, or --test-bin --next-collection."
            )
        if args.next_collection and (
            args.test_bin not in (None, "__next_collection__")
            or args.test is not None
            or any((
                args.run, args.setup, args.list_lights, args.discover_bridges,
                args.setup_bridges, bool(args.pair), args.configure_lights,
                args.check_calendar, args.status, args.pause, args.resume,
                args.toggle, args.dry_run, args.list_bin_types,
            ))
        ):
            raise BindicatorError(
                "--next-collection must be used alone (optionally with --seconds), "
                "or as --test-bin --next-collection."
            )
        if args.seconds is not None and not 1 <= args.seconds <= 60:
            raise BindicatorError("--seconds must be between 1 and 60.")
        pool = BridgePool(config["hue"])  # Bridge credentials fetched only if needed.

        if args.setup:
            if not sys.stdin.isatty():
                raise BindicatorError("--setup requires an interactive terminal.")
            from .setup import guided_setup

            guided_setup(
                args.config, args.secrets_file, args.state_dir,
                fresh=args.fresh,
            )
            return 0

        if args.pair:
            name = args.pair
            if name not in pool.bridges:
                raise BindicatorError(
                    f"Unknown Bridge {name!r}. Configured: {', '.join(pool.names)}."
                )
            print(
                f"Waiting up to 45 seconds for Hue Bridge {name!r} "
                f"({pool.bridges[name]['host']}).",
                flush=True,
            )
            print("Press the physical link button on that Bridge NOW.", flush=True)
            key = pool.pair(name)
            variable = f"BINDICATOR_HUE_KEY_{name.upper()}"
            print(f"Pairing successful. Store this private key as {variable} in secrets.env:")
            print(key)
            return 0

        if args.discover_bridges:
            from .bridge_discovery import discover_bridges

            found = discover_bridges()
            if not found:
                print("No Hue Bridges found via local mDNS.")
                print("If mDNS is blocked, use --setup-bridges to pair configured IPs.")
            for bridge in found:
                matched = next(
                    (
                        name for name, info in pool.bridges.items()
                        if (bridge["id"] and str(info.get("id", "")).upper() == bridge["id"])
                        or info["host"] == bridge["host"]
                    ), None,
                )
                print(
                    f"{bridge['host']:<16} {bridge['id'] or '(ID unknown)':<20} "
                    f"{bridge['name']}"
                    + (f"  [configured: {matched}]" if matched else "")
                )
            return 0

        if args.setup_bridges:
            if not sys.stdin.isatty():
                raise BindicatorError("--setup-bridges requires an interactive terminal.")
            from .bridge_setup import setup_bridge

            setup_bridge(pool, args.config, args.secrets_file)
            return 0

        if args.configure_lights:
            if not sys.stdin.isatty():
                raise BindicatorError("--configure-lights requires an interactive terminal.")
            from .light_selection import configure_lights

            configure_lights(pool, config, args.config)
            return 0

        if args.list_lights:
            from .light_selection import light_capability_label

            names = [args.bridge] if args.bridge else pool.names
            if not names:
                print("No Hue Bridges configured. Run: sudo bindicator --setup")
                return 0
            errors = 0
            for name in names:
                if name not in pool.bridges:
                    raise BindicatorError(f"Unknown Bridge {name!r}. Configured: {', '.join(pool.names)}.")
                print(f"[{name}] {pool.bridges[name]['host']}")
                if not pool.has_key(name):
                    print(
                        f"  Not paired — no application key configured. "
                        f"Pair using: bindicator --pair {name}"
                    )
                    continue
                try:
                    lights = pool.lights(name)
                    if not lights:
                        print("  No lights found.")
                    for light in sorted(
                        lights, key=lambda v: v.get("metadata", {}).get("name", "")
                    ):
                        display_name = light.get("metadata", {}).get("name", "(unnamed)")
                        rid = light.get("id", "?")
                        capable = light_capability_label(light)
                        on = "on" if light.get("on", {}).get("on") else "off"
                        print(f"  {display_name:<30} {rid}  {capable}, {on}")
                except BindicatorError as exc:
                    errors += 1
                    LOG.error("Cannot list lights on %s: %s", name, exc)
            return 1 if errors else 0

        if args.list_bin_types:
            from .bin_preview import available_bin_types

            for event, colour in available_bin_types(config):
                suffix = event.split(" - ", 1)[1] if " - " in event else event
                print(f"{suffix:<30} {colour:<10} event: {event}")
            return 0

        app = Bindicator(config, args.state_dir, pool)
        from .controls import is_paused, set_paused

        if args.pause or args.resume or args.toggle:
            # Use the same lock as the scheduled worker, so an in-progress
            # reminder finishes before pause is committed.
            args.state_dir.mkdir(parents=True, exist_ok=True)
            with (args.state_dir / "run.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                paused = is_paused(args.state_dir)
                desired = not paused if args.toggle else bool(args.pause)
                if desired != paused:
                    # Persist pause before Hue calls: if restoration fails,
                    # the timer must not start controlling lamps again.
                    set_paused(args.state_dir, desired)
                if desired:
                    # Always attempt restoration, even if already paused:
                    # this allows retries after an offline Bridge and
                    # upgrades from versions that left reminders active.
                    had_reminder = bool(
                        app.state["lights"] or app.state.get("manual_until")
                    )
                    if had_reminder:
                        try:
                            app.restore()
                        except BindicatorError as exc:
                            raise BindicatorError(
                                "Bindicator is PAUSED, but one or more lights "
                                "could not be restored. Saved light state was "
                                "retained for retry; run --pause again once "
                                f"the Bridge is reachable. Details: {exc}"
                            ) from exc
                    print(
                        "Bindicator PAUSED — original lamp appearance restored "
                        "where unchanged; scheduled reminders and previews "
                        "will not change Hue lights."
                        if had_reminder else
                        "Bindicator PAUSED — no active reminder to restore; "
                        "scheduled reminders and previews will not change Hue lights."
                    )
                else:
                    print(
                        "Bindicator ACTIVE — reminders will run at the next timer check."
                    )
            return 0

        if args.status:
            print(f"Bindicator: {'PAUSED' if is_paused(args.state_dir) else 'ACTIVE'}")
            print(f"Active collection date: {app.state.get('date') or '(none)'}")
            if app.state.get("manual_until"):
                print(
                    f"Manually activated until: {app.state['manual_until']} 09:00 Europe/London"
                )
            for qualified, record in app.state["lights"].items():
                print(f"  {qualified} -> {record.get('color_name', '?')}")
            return 0

        if args.check_calendar:
            today = datetime.now(TZ).date()
            feed = app.calendar_data()
            found = False
            for n in range(30):
                day = today + timedelta(days=n)
                colors = ordered_colors(
                    parse_collections(feed, day, config["calendar"]["events"]),
                    config["priority"],
                )
                if colors:
                    print(f"{day}: {', '.join(colors)}")
                    found = True
            if not found:
                print("No matching collections in the next 30 days. Check event titles.")
            return 0

        if args.next_collection and args.test_bin is None and args.seconds is None:
            from .bin_preview import next_collection

            args.state_dir.mkdir(parents=True, exist_ok=True)
            with (args.state_dir / "run.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                if is_paused(args.state_dir):
                    raise BindicatorError(
                        "Bindicator is paused to protect your Hue scene. "
                        "Run 'bindicator --resume' before activating a reminder."
                    )
                if app.state["lights"] or app.state.get("manual_until"):
                    raise BindicatorError(
                        "A reminder is already active; refusing to override its "
                        "saved light state. Use --status to inspect it."
                    )
                feed = app.calendar_data()
                collection_day, colours = next_collection(
                    config, feed, datetime.now(TZ)
                )
                print(
                    f"Next collection: {collection_day:%a %d %b %Y} — "
                    f"{', '.join(colours)}", flush=True
                )
                app.apply_collections(collection_day, colours, manual=True)
                print(
                    f"Reminder active until {collection_day} at {config.get('schedule', {}).get('restore', '09:00')} Europe/London. "
                    "Original lamp appearance will be restored on a scheduled "
                    "check at or after that time, unless manually overridden."
                )
            return 0

        if (
            args.test is not None or args.test_bin is not None
            or (args.next_collection and args.seconds is not None)
        ):
            from .bin_preview import next_collection, preview_lights, resolve_bin_types

            args.state_dir.mkdir(parents=True, exist_ok=True)
            with (args.state_dir / "run.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                if is_paused(args.state_dir):
                    raise BindicatorError(
                        "Bindicator is paused to protect your Hue scene. "
                        "Run 'bindicator --resume' before previewing lights."
                    )
                # Do not override any reminder still waiting for restoration.
                if app.state["lights"]:
                    raise BindicatorError(
                        "A scheduled reminder is still active; test after its "
                        "colours have been restored."
                    )
                if args.next_collection:
                    # Fetch once; use the same title matching and recurrence
                    # expansion as the scheduled reminder implementation.
                    feed = app.calendar_data()
                    collection_day, colours = next_collection(
                        config, feed, datetime.now(TZ)
                    )
                    print(
                        "Next collection: "
                        f"{collection_day:%a %d %b %Y} — "
                        f"{', '.join(colours)}", flush=True
                    )
                    label = f"next collection ({collection_day.isoformat()})"
                elif args.test_bin is not None:
                    colours = resolve_bin_types(config, args.test_bin)
                    label = args.test_bin
                else:
                    colour = args.test.casefold()
                    if colour not in config["colors"]:
                        raise BindicatorError(
                            "Unknown colour. Choose from: " + ", ".join(config["colors"])
                        )
                    colours = [colour]
                    label = colour
                if (
                    args.next_collection
                    and args.test_bin is None
                    and args.seconds is not None
                ):
                    from .bin_preview import launch_detached_preview

                    # The child inherits this *same locked file description*.
                    # The parent can close it and return immediately without
                    # permitting a scheduled run or another preview to race
                    # with the worker's delayed Hue restoration.
                    pid = launch_detached_preview(
                        config_path=args.config,
                        secrets_path=args.secrets_file,
                        state_dir=args.state_dir,
                        colours=colours,
                        seconds=args.seconds,
                        lock_fd=lock.fileno(),
                    )
                    print(
                        f"Preview launched in background (PID {pid}) for "
                        f"{args.seconds} seconds. The worker will restore "
                        "the previous lights when finished, unless manually "
                        "changed. Check "
                        f"{args.state_dir / 'preview.log'} for results/errors.",
                        flush=True,
                    )
                    return 0

                print(
                    f"Previewing {label} for up to "
                    f"{args.seconds if args.seconds is not None else 5} seconds "
                    "using configured Hue lamp assignments.", flush=True
                )
                preview_lights(
                    pool, config, colours,
                    seconds=args.seconds if args.seconds is not None else 5,
                )
            print("Preview complete; original colours restored where unchanged.")
            return 0

        # Lock the entire check to prevent races with the timer.
        args.state_dir.mkdir(parents=True, exist_ok=True)
        with (args.state_dir / "run.lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            app.run(datetime.now(TZ), dry_run=args.dry_run)
        return 0

    except (BindicatorError, OSError, BlockingIOError) as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
