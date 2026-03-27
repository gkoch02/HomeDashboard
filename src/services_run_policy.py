from datetime import datetime, tzinfo
import zoneinfo


def resolve_tz(tz_name: str) -> tzinfo:
    """Return a tzinfo for the given IANA name, or the system local timezone for 'local'."""
    if tz_name == "local":
        return datetime.now().astimezone().tzinfo
    return zoneinfo.ZoneInfo(tz_name)


def in_quiet_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Return True if `now` falls in the quiet window [start_hour, end_hour)."""
    h = now.hour
    if start_hour > end_hour:
        return h >= start_hour or h < end_hour
    return start_hour <= h < end_hour


def is_morning_startup(now: datetime, quiet_hours_end: int) -> bool:
    """Return True on the first 30-minute run after quiet hours end."""
    return now.hour == quiet_hours_end and now.minute < 30


def should_skip_refresh(now: datetime, quiet_hours_start: int, quiet_hours_end: int, dry_run: bool) -> bool:
    return not dry_run and in_quiet_hours(now, quiet_hours_start, quiet_hours_end)


def should_force_full_refresh(now: datetime, quiet_hours_end: int, force_full_refresh_flag: bool) -> bool:
    return force_full_refresh_flag or is_morning_startup(now, quiet_hours_end)
