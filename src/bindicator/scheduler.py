"""Minute-resolution scheduler: invoke Bindicator only when reminder phase changes.

The systemd timer ticks each minute, but network/Hue checks happen once per
successful scheduled phase. Failed checks are retried on the following tick.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, time
from pathlib import Path

from .app import DEFAULT_CONFIG, DEFAULT_STATE_DIR, TZ, load_config

LOG = logging.getLogger("bindicator.scheduler")


def phase_at(now: datetime, schedule: dict) -> str:
    local = now.astimezone(TZ)
    start, restore = time.fromisoformat(schedule["start"]), time.fromisoformat(schedule["restore"])
    if local.time() >= start:
        phase = "active:" + (local.date() + timedelta(days=1)).isoformat()
    elif local.time() < restore:
        phase = "active:" + local.date().isoformat()
    else:
        phase = "idle:" + local.date().isoformat()
    return f'{schedule["start"]}/{schedule["restore"]}:{phase}'


def tick(config_path: Path = DEFAULT_CONFIG,
         state_dir: Path = DEFAULT_STATE_DIR,
         now: datetime | None = None) -> bool:
    config = load_config(config_path)
    phase = phase_at(now or datetime.now(TZ), config["schedule"])
    state_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = state_dir / "schedule-phase.json"
    lockfile = state_dir / "schedule-tick.lock"
    with lockfile.open("a+") as lock:
        # Avoid overlapping invocations of the scheduling CLI.
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            existing = json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if existing.get("phase") == phase:
            return False
        # The existing CLI holds run.lock and owns all Hue restoration rules.
        result = subprocess.run([sys.executable, "-m", "bindicator.cli",
                                 "--config", str(config_path),
                                 "--state-dir", str(state_dir), "--run"],
                                stdin=subprocess.DEVNULL, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError("Scheduled Bindicator check failed; will retry next minute.")
        temp = checkpoint.with_name(".schedule-phase.tmp-" + str(os.getpid()))
        try:
            temp.write_text(json.dumps({"phase": phase}) + "\n", encoding="utf-8")
            os.chmod(temp, 0o660)
            os.replace(temp, checkpoint)
        finally:
            temp.unlink(missing_ok=True)
        return True


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        tick()
        return 0
    except Exception:
        LOG.exception("Scheduled reminder tick failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
