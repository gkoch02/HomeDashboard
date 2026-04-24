"""Evaluator for ``theme_rules`` — context-aware auto theming.

Rules are ordered; first-match-wins.  A rule matches when every *set* field in
its ``when`` condition evaluates truthy against the current context.  Unset
(None) fields don't constrain.  Rules whose conditions reference a data source
that is unavailable (e.g. weather when no weather data was fetched) silently
skip without matching — this is by design so that offline boots fall through to
``theme_schedule`` / ``cfg.theme``.

Kept as a small pure module so it's easy to test and easy to extend.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from src.data.models import DashboardData

UPCOMING_SOON_MINUTES = 30
BUSY_DAY_THRESHOLD = 5

# Calendar states derived from the events source (everything except birthday_today).
_EVENT_DERIVED_STATES = frozenset({"empty", "done", "active", "upcoming_soon", "busy"})


def _listify(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v).lower() for v in val]
    return [str(val).lower()]


def _current_daypart(now: datetime, weather) -> str:
    """Return the daypart bucket for *now*.

    When sunrise/sunset are known:
    - ``dawn``:  [sunrise-90min, sunrise+90min]
    - ``dusk``:  [sunset-60min, sunset+60min]
    - ``morning``:   after dawn, before local noon
    - ``afternoon``: after local noon, before dusk
    - ``night``: before dawn or after dusk

    Otherwise fixed clock ranges are used.  Rules always match against the
    more specific ``morning``/``afternoon`` values; callers that configure
    ``daypart: day`` get a broader match (day = morning ∪ afternoon) handled
    at the rule level.
    """
    hour = now.hour + now.minute / 60
    now_min = hour * 60
    if weather is not None and weather.sunrise and weather.sunset:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        sr = weather.sunrise.replace(tzinfo=None) if weather.sunrise.tzinfo else weather.sunrise
        ss = weather.sunset.replace(tzinfo=None) if weather.sunset.tzinfo else weather.sunset
        sr_min = (sr - midnight).total_seconds() / 60
        ss_min = (ss - midnight).total_seconds() / 60
        if abs(now_min - sr_min) <= 90:
            return "dawn"
        if abs(now_min - ss_min) <= 60:
            return "dusk"
        if sr_min <= now_min <= ss_min:
            # Split day at local noon so ``morning``/``afternoon`` buckets work
            # even when sunrise/sunset data is available.
            return "morning" if now_min < 12 * 60 else "afternoon"
        return "night"
    # Fallback: fixed clock ranges (no sunrise/sunset data available)
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 20:
        return "dusk"
    return "night"


def _current_season(now: datetime) -> str:
    """Return the N-hemisphere meteorological season for *now*."""
    m = now.month
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    if m in (9, 10, 11):
        return "fall"
    return "winter"


def _current_weekday(now: datetime) -> tuple[str, str]:
    """Return (day_name, weekend_or_weekday) for *now* in lowercase."""
    name = now.strftime("%A").lower()
    is_weekend = now.weekday() >= 5
    return name, "weekend" if is_weekend else "weekday"


def _match_season(rule_vals: list[str], current: str) -> bool:
    # Treat "fall" and "autumn" as synonyms
    if "autumn" in rule_vals:
        rule_vals = [v if v != "autumn" else "fall" for v in rule_vals]
    return current in rule_vals


def _match_weekday(rule_vals: list[str], day_name: str, weekend_key: str) -> bool:
    return any(v in (day_name, weekend_key) for v in rule_vals)


def _overlaps_today(event, today: date) -> bool:
    """True if *event* covers *today*.

    All-day events use inclusive-start / exclusive-end date overlap (the iCal
    convention, matching ``events_for_day`` in ``render/primitives.py``).
    Timed events count on the day their start falls in.
    """
    if event.is_all_day:
        sd = event.start.date() if isinstance(event.start, datetime) else event.start
        ed = event.end.date() if isinstance(event.end, datetime) else event.end
        return sd <= today < ed
    return event.start.date() == today


def _calendar_states(now: datetime, data: DashboardData) -> set[str]:
    """Return the set of calendar-state tokens that apply right now.

    A single rule value matches if it appears in this set.  States are not
    mutually exclusive (e.g. a day with 6 events one of which is in progress
    is both ``busy`` and ``active``).  Event-derived states are only emitted
    when the events source was actually loaded (fresh or cached); likewise for
    birthdays.  This prevents a fetch outage with no usable cache from firing
    ``empty`` rules spuriously.  ``now`` is normalized to naive local time to
    match the wall-clock convention used by calendar fetchers.
    """
    # CalendarEvent.start/end are naive local wall-clock (see _parse_event in
    # fetchers/calendar_google.py and calendar_ical.py).  Strip any tzinfo so
    # direct comparisons work even when the caller hands us an aware ``now``.
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    today = now.date()
    states: set[str] = set()

    if "events" in data.source_staleness:
        todays_events = [e for e in data.events if _overlaps_today(e, today)]
        timed_today = [e for e in todays_events if not e.is_all_day]
        if not todays_events:
            states.add("empty")
        else:
            if timed_today and all(e.end <= now for e in timed_today):
                states.add("done")
            if any(e.start <= now < e.end for e in timed_today):
                states.add("active")
            soon_cutoff = now + timedelta(minutes=UPCOMING_SOON_MINUTES)
            if any(now < e.start <= soon_cutoff for e in timed_today):
                states.add("upcoming_soon")
            if len(todays_events) >= BUSY_DAY_THRESHOLD:
                states.add("busy")

    if "birthdays" in data.source_staleness and any(
        b.date.month == today.month and b.date.day == today.day for b in data.birthdays
    ):
        states.add("birthday_today")

    return states


def _rule_matches(rule, now: datetime, data: DashboardData | None) -> bool:
    """Return True iff every *set* field in ``rule.when`` matches the context."""
    when = rule.when
    weather = data.weather if data is not None else None

    # Weather main
    if when.weather is not None:
        if weather is None:
            return False
        current = (weather.current_description or "").lower()
        # OWM's ``current_description`` is the descriptive text ("light rain",
        # "scattered clouds").  We match any configured category as a substring.
        want = _listify(when.weather)
        if not any(token and token in current for token in want):
            return False

    # Weather alerts
    if when.weather_alert_present is not None:
        if weather is None:
            return False
        has_alerts = bool(weather.alerts)
        if has_alerts != when.weather_alert_present:
            return False

    # Daypart
    if when.daypart is not None:
        dp = _current_daypart(now, weather)
        want = _listify(when.daypart)
        # ``day`` is an alias for morning ∪ afternoon so users can configure
        # a simple "daytime" rule without enumerating both halves.
        if "day" in want and dp in ("morning", "afternoon"):
            pass
        elif dp not in want:
            return False

    # Season
    if when.season is not None:
        season = _current_season(now)
        want = _listify(when.season)
        if not _match_season(want, season):
            return False

    # Weekday
    if when.weekday is not None:
        day_name, weekend_key = _current_weekday(now)
        want = _listify(when.weekday)
        if not _match_weekday(want, day_name, weekend_key):
            return False

    # Calendar
    if when.calendar is not None:
        if data is None:
            return False
        states = _calendar_states(now, data)
        want = _listify(when.calendar)
        if not any(v in states for v in want):
            return False

    return True


def resolve_rule_theme(rules: Iterable, now: datetime, data: DashboardData | None) -> str | None:
    """Return the theme from the first matching rule, or ``None`` if none match."""
    for rule in rules:
        if _rule_matches(rule, now, data):
            return rule.theme
    return None
