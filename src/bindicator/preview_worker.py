"""Detached timed preview worker.

Invoked internally by launch_detached_preview with the already-locked
run.lock file descriptor. Does not expose an unauthenticated listener.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from .app import BindicatorError, load_config, load_secrets
from .bin_preview import preview_lights
from .bridges import BridgePool

LOG = logging.getLogger("bindicator")


class PreviewInterrupted(Exception):
    """Interrupt the sleep through normal exception unwinding/restoration."""


def _stop_preview(_signum, _frame) -> None:
    raise PreviewInterrupted("Preview worker received a termination signal.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Internal Bindicator preview worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--secrets-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--colours", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    os.umask(0o007)
    # Interrupted waits must unwind preview_lights(...finally: restore...).
    signal.signal(signal.SIGTERM, _stop_preview)
    signal.signal(signal.SIGINT, _stop_preview)

    try:
        with os.fdopen(args.lock_fd, "rb", closefd=True):
            config = load_config(args.config)
            load_secrets(args.secrets_file)
            colours = args.colours.split(",")
            if (
                not colours or any(colour not in config["colors"] for colour in colours)
                or not 1 <= args.seconds <= 60
            ):
                raise BindicatorError("Invalid detached preview arguments.")
            pool = BridgePool(config["hue"])
            LOG.info("Starting %d-second preview: %s", args.seconds, ", ".join(colours))
            preview_lights(pool, config, colours, seconds=args.seconds)
            LOG.info("Preview finished; original lighting restored where unchanged.")
        return 0
    except PreviewInterrupted:
        LOG.warning("Preview interrupted; restoration attempted.")
        return 1
    except (BindicatorError, OSError, ValueError) as exc:
        LOG.error("Detached preview failed: %s", exc)
        return 1
    except Exception:
        LOG.exception("Unexpected error during detached preview.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
