"""Daily systemd check: refresh whichever collection calendar is active."""
from pathlib import Path
import logging
from .app import DEFAULT_CONFIG, DEFAULT_STATE_DIR, load_config, BindicatorError
from .calendar_providers import active_source
from . import calendar_engine
from .app import load_secrets, DEFAULT_SECRETS

LOG = logging.getLogger("bindicator.council.job")


def run(config_path: Path = DEFAULT_CONFIG, state_dir: Path = DEFAULT_STATE_DIR) -> bool:
    config = load_config(config_path)
    load_secrets(DEFAULT_SECRETS)
    result = calendar_engine.refresh_source(active_source(config), config, state_dir)
    if result.get("error"):
        raise BindicatorError(result["error"])
    return result["refreshed"]


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        refreshed = run()
        LOG.info("Collection calendar check complete; refreshed=%s", refreshed)
        return 0
    except (BindicatorError, OSError):
        LOG.exception("Scheduled calendar refresh failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
