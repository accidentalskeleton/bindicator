"""Backward-compatible North Yorkshire wrappers over the shared calendar engine."""
from .calendar_engine import cache_status as _status, refresh_source, calendar_data as _data

def cache_status(config, state_dir):
    return _status("council", config, state_dir)

def refresh_council(config, state_dir, *, force=False):
    return refresh_source("council", config, state_dir, force=force)

def council_calendar_data(config, state_dir):
    return _data("council", config, state_dir)
