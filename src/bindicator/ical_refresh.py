"""Backward-compatible iCalendar wrappers over the shared calendar engine."""
from .calendar_engine import cache_status as _status, refresh_source, calendar_data as _data

def status(config, state_dir):
    return _status("ical", config, state_dir)

def refresh_ical(config, state_dir, *, force=False):
    return refresh_source("ical", config, state_dir, force=force)

def ical_calendar_data(config, state_dir):
    return _data("ical", config, state_dir)
