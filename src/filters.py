"""Event filtering — hide events from the display based on configurable rules.

Filtering runs between fetch and render so the cache retains all events
(important for incremental sync correctness).
"""

import logging

from src.config import FilterConfig
from src.data.models import CalendarEvent

logger = logging.getLogger(__name__)


def filter_events(
    events: list[CalendarEvent],
    filters: FilterConfig,
) -> list[CalendarEvent]:
    """Return events that pass all filter rules.

    The original list is never modified.  Matching is case-insensitive:
    calendar names use substring matching, keywords use substring matching
    against the event summary.
    """
    if (not filters.exclude_calendars and not filters.exclude_keywords
            and not filters.exclude_all_day):
        return list(events)

    excluded_cals = [c.lower() for c in filters.exclude_calendars]
    excluded_kws = [k.lower() for k in filters.exclude_keywords]

    result: list[CalendarEvent] = []
    for event in events:
        if filters.exclude_all_day and event.is_all_day:
            continue

        if excluded_cals and event.calendar_name is not None:
            cal_lower = event.calendar_name.lower()
            if any(exc in cal_lower for exc in excluded_cals):
                continue

        if excluded_kws:
            summary_lower = event.summary.lower()
            if any(kw in summary_lower for kw in excluded_kws):
                continue

        result.append(event)

    excluded_count = len(events) - len(result)
    if excluded_count:
        logger.info("Filtered out %d events", excluded_count)

    return result
