from __future__ import annotations

import json
import logging
from datetime import date as _date
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_MORNING_REFRESH_STATE_FILENAME = "morning_refresh_state.json"


def in_quiet_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Return True if `now` falls in the quiet window [start_hour, end_hour)."""
    h = now.hour
    if start_hour > end_hour:
        return h >= start_hour or h < end_hour
    return start_hour <= h < end_hour


def is_morning_startup_window(now: datetime, quiet_hours_end: int) -> bool:
    """Return True during the first 30-minute window after quiet hours end."""
    return now.hour == quiet_hours_end and now.minute < 30


def should_skip_refresh(
    now: datetime,
    quiet_hours_start: int,
    quiet_hours_end: int,
    dry_run: bool,
) -> bool:
    return not dry_run and in_quiet_hours(now, quiet_hours_start, quiet_hours_end)


def _morning_state_path(state_dir: str) -> Path:
    return Path(state_dir) / _MORNING_REFRESH_STATE_FILENAME


def _load_last_morning_refresh(state_dir: str) -> _date | None:
    """Return the last date a morning refresh was recorded, or None on any failure."""
    path = _morning_state_path(state_dir)
    try:
        raw = path.read_text()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        value = payload.get("last_refresh_date")
        if not isinstance(value, str):
            return None
        return _date.fromisoformat(value)
    except (OSError, ValueError):
        return None


def record_morning_refresh(now: datetime, state_dir: str) -> None:
    """Persist today's date as the last morning refresh. Silently logs on failure."""
    path = _morning_state_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_refresh_date": now.date().isoformat()}))
    except OSError as exc:
        logger.warning("Failed to write morning refresh state to %s: %s", path, exc)


def should_force_full_refresh(
    now: datetime,
    quiet_hours_end: int,
    force_full_refresh_flag: bool,
    state_dir: str,
) -> bool:
    if force_full_refresh_flag:
        return True
    if not is_morning_startup_window(now, quiet_hours_end):
        return False
    return _load_last_morning_refresh(state_dir) != now.date()
