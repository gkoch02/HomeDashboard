"""Google Calendar API fetcher — full and incremental sync.

Supports incremental sync via Google Calendar sync tokens: after the first full
fetch for a calendar, subsequent calls use the ``nextSyncToken`` from the
previous response so only changed events are transferred.  Sync state is
persisted to ``<cache_dir>/calendar_sync_state.json``.
"""

import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import GoogleConfig
from src.data.models import CalendarEvent

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_SYNC_STATE_FILENAME = "calendar_sync_state.json"


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _today(tz: tzinfo | None) -> date:
    if tz is None:
        return date.today()
    return datetime.now(tz).date()


# ---------------------------------------------------------------------------
# Service building + cache
# ---------------------------------------------------------------------------

# Cache the built service object so fetch_events and fetch_birthdays reuse it
# within the same process run (fix: service built twice).
#
# Note: service account tokens auto-refresh via the google-auth library, so
# caching the service object is safe for the typical hourly-cron use case.
# The Google client library does not expose per-request HTTP timeouts;
# callers rely on the ThreadPoolExecutor timeout in main.py (120s) as the
# upper bound on any single API call.
_service_cache: dict[str, Any] = {}


def clear_service_caches() -> None:
    """Clear cached API service objects (useful for testing)."""
    _service_cache.clear()


def _build_service(cfg: GoogleConfig):
    key = cfg.service_account_path
    if key not in _service_cache:
        try:
            creds = service_account.Credentials.from_service_account_file(
                cfg.service_account_path, scopes=_SCOPES
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load service account credentials from "
                f"{cfg.service_account_path!r}: {exc}"
            ) from exc
        _service_cache[key] = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service_cache[key]


# ---------------------------------------------------------------------------
# Sync state persistence
# ---------------------------------------------------------------------------


def _load_sync_state(cache_dir: str) -> dict:
    """Load per-calendar sync state (tokens + stored events).  Returns {} if absent."""
    path = Path(cache_dir) / _SYNC_STATE_FILENAME
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Sync state read failed: %s", exc)
        return {}


def _save_sync_state(state: dict, cache_dir: str) -> None:
    """Persist per-calendar sync state atomically."""
    path = Path(cache_dir) / _SYNC_STATE_FILENAME
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    except Exception as exc:
        logger.warning("Sync state write failed: %s", exc)


# ---------------------------------------------------------------------------
# Google Calendar API event fetching
# ---------------------------------------------------------------------------


def fetch_google_events(
    cfg: GoogleConfig,
    days: int = 7,
    tz: tzinfo | None = None,
    cache_dir: str | None = None,
) -> list[CalendarEvent]:
    """Return calendar events via the Google Calendar API for the current week.

    When *cache_dir* is provided, sync tokens are stored and incremental syncs
    are used for subsequent calls, reducing API quota consumption.
    """
    service = _build_service(cfg)

    today = _today(tz)
    # Start from Monday of the current week to match the Mon–Sun week view
    week_start = today - timedelta(days=today.weekday())
    time_min = datetime.combine(week_start, datetime.min.time()).astimezone(timezone.utc)
    time_max = time_min + timedelta(days=days)

    sync_state = _load_sync_state(cache_dir) if cache_dir else {}

    calendar_ids = [cfg.calendar_id] + list(cfg.additional_calendars)
    events: list[CalendarEvent] = []

    for cal_id in calendar_ids:
        cal_state = sync_state.get(cal_id, {})
        sync_token: str | None = cal_state.get("sync_token")
        stored: list[dict] = cal_state.get("events", [])

        if sync_token:
            delta_items, cal_name, new_token, needs_reset = _fetch_incremental(
                service, cal_id, sync_token, tz=tz
            )
            if needs_reset:
                logger.info("Sync token expired for %s — performing full sync", cal_id)
                sync_token = None  # fall through to full sync below
            else:
                merged = _apply_delta(stored, delta_items, cal_name, tz=tz)
                week_events = _filter_to_window(merged, time_min, time_max, tz=tz)
                sync_state[cal_id] = {"sync_token": new_token, "events": merged}
                events.extend(week_events)
                logger.info(
                    "Incremental sync %s: %d delta items → %d in week window",
                    cal_id,
                    len(delta_items),
                    len(week_events),
                )
                continue  # skip full sync below

        # Full sync (first run or after sync token expiry)
        cal_events, cal_name, new_token = _fetch_full(service, cal_id, time_min, time_max, tz=tz)
        sync_state[cal_id] = {
            "sync_token": new_token,
            "events": [_ser_sync_event(e) for e in cal_events],
        }
        events.extend(cal_events)
        logger.info("Full sync %s: %d events, token=%s", cal_id, len(cal_events), bool(new_token))

    if cache_dir:
        _save_sync_state(sync_state, cache_dir)

    events.sort(key=lambda e: e.start)
    return events


def _fetch_full(
    service,
    calendar_id: str,
    time_min: datetime,
    time_max: datetime,
    tz: tzinfo | None = None,
) -> tuple[list[CalendarEvent], str, str | None]:
    """Full sync: paginate through all events in [time_min, time_max).

    Returns ``(events, calendar_name, next_sync_token)``.  ``next_sync_token``
    is ``None`` when the API does not return one (should not happen in practice).
    """
    params: dict = dict(
        calendarId=calendar_id,
        timeMin=time_min.isoformat(),
        timeMax=time_max.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=250,
    )

    events: list[CalendarEvent] = []
    cal_name = calendar_id
    next_sync_token: str | None = None
    page_token: str | None = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        try:
            result = service.events().list(**params).execute()
        except Exception as exc:
            logger.warning("Failed to fetch calendar %s: %s", calendar_id, exc)
            break

        cal_name = result.get("summary", calendar_id)
        for item in result.get("items", []):
            event = _parse_event(item, cal_name, tz=tz)
            if event is not None:
                events.append(event)

        page_token = result.get("nextPageToken")
        if not page_token:
            next_sync_token = result.get("nextSyncToken")
            break

    return events, cal_name, next_sync_token


def _fetch_incremental(
    service,
    calendar_id: str,
    sync_token: str,
    tz: tzinfo | None = None,
) -> tuple[list[dict], str, str | None, bool]:
    """Incremental sync using a ``syncToken``.

    Returns ``(delta_items, calendar_name, new_sync_token, needs_reset)``.
    *needs_reset* is ``True`` when the token is invalid (HTTP 410 Gone) or any
    other error occurs — the caller should fall back to a full sync.
    *delta_items* are raw Google Calendar API event dicts (not ``CalendarEvent``
    objects) so that ``status="cancelled"`` items can be used for deletion.
    """
    params: dict = dict(
        calendarId=calendar_id,
        syncToken=sync_token,
        singleEvents=True,
        maxResults=250,
    )

    delta_items: list[dict] = []
    cal_name = calendar_id
    new_token: str | None = None
    page_token: str | None = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        try:
            result = service.events().list(**params).execute()
        except HttpError as exc:
            if exc.resp.status == 410:
                logger.debug("Sync token for %s returned 410 Gone", calendar_id)
                return [], calendar_id, None, True
            logger.warning("Incremental sync failed for %s: %s", calendar_id, exc)
            return [], calendar_id, None, True
        except Exception as exc:
            logger.warning("Incremental sync failed for %s: %s", calendar_id, exc)
            return [], calendar_id, None, True

        cal_name = result.get("summary", calendar_id)
        delta_items.extend(result.get("items", []))

        page_token = result.get("nextPageToken")
        if not page_token:
            new_token = result.get("nextSyncToken")
            break

    return delta_items, cal_name, new_token, False


def _apply_delta(
    stored: list[dict],
    delta_items: list[dict],
    calendar_name: str,
    tz: tzinfo | None = None,
) -> list[dict]:
    """Merge incremental delta items into the stored serialised event list.

    Cancelled events (``status="cancelled"``) are removed; new and updated
    events are upserted by ``event_id``.  Events without an ID are left as-is.
    """
    by_id: dict[str, dict] = {d["event_id"]: d for d in stored if d.get("event_id")}
    # Preserve events without IDs (e.g. from before incremental sync was added)
    no_id = [d for d in stored if not d.get("event_id")]

    for item in delta_items:
        event_id = item.get("id")
        if not event_id:
            continue
        if item.get("status") == "cancelled":
            by_id.pop(event_id, None)
        else:
            event = _parse_event(item, calendar_name, tz=tz)
            if event is not None:
                event.event_id = event_id
                by_id[event_id] = _ser_sync_event(event)

    return list(by_id.values()) + no_id


def _filter_to_window(
    stored: list[dict],
    time_min: datetime,
    time_max: datetime,
    tz: tzinfo | None = None,
) -> list[CalendarEvent]:
    """Deserialise stored event dicts and filter to those overlapping [time_min, time_max)."""
    # Convert UTC window bounds to naive local for comparison with naive event datetimes
    if tz is not None:
        win_start = time_min.astimezone(tz).replace(tzinfo=None)
        win_end = time_max.astimezone(tz).replace(tzinfo=None)
    else:
        win_start = time_min.replace(tzinfo=None)
        win_end = time_max.replace(tzinfo=None)

    win_start_date = win_start.date()
    win_end_date = win_end.date()

    result: list[CalendarEvent] = []
    for d in stored:
        event = _deser_sync_event(d)
        if event.is_all_day:
            s = event.start.date() if isinstance(event.start, datetime) else event.start
            e = event.end.date() if isinstance(event.end, datetime) else event.end
            # Google all-day events use exclusive end date (end = day after last
            # day), so e > win_start_date correctly excludes events that ended
            # before the window.
            if s < win_end_date and e > win_start_date:
                result.append(event)
        else:
            start = event.start
            if start.tzinfo is not None:
                # tz-aware: compare directly with UTC window
                if time_min <= start < time_max:
                    result.append(event)
            else:
                # naive local wall-clock
                if win_start <= start < win_end:
                    result.append(event)
    return result


# ---------------------------------------------------------------------------
# Sync state serialisation helpers
# ---------------------------------------------------------------------------


def _ser_sync_event(e: CalendarEvent) -> dict:
    """Serialise a CalendarEvent for the sync state store (includes event_id)."""
    return {
        "event_id": e.event_id,
        "summary": e.summary,
        "start": e.start.isoformat(),
        "end": e.end.isoformat(),
        "is_all_day": e.is_all_day,
        "location": e.location,
        "calendar_name": e.calendar_name,
    }


def _deser_sync_event(d: dict) -> CalendarEvent:
    """Deserialise a sync state event dict back to a CalendarEvent."""
    return CalendarEvent(
        summary=d["summary"],
        start=datetime.fromisoformat(d["start"]),
        end=datetime.fromisoformat(d["end"]),
        is_all_day=d.get("is_all_day", False),
        location=d.get("location"),
        calendar_name=d.get("calendar_name"),
        event_id=d.get("event_id"),
    )


def _parse_event(item: dict, calendar_name: str, tz: tzinfo | None = None) -> CalendarEvent | None:
    summary = item.get("summary", "(no title)")
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})

    if "date" in start_raw:
        # All-day event — dates are plain strings like "2024-03-15"
        start = datetime.combine(date.fromisoformat(start_raw["date"]), datetime.min.time())
        end = datetime.combine(date.fromisoformat(end_raw["date"]), datetime.min.time())
        is_all_day = True
    elif "dateTime" in start_raw:
        start = datetime.fromisoformat(start_raw["dateTime"])
        end = datetime.fromisoformat(end_raw["dateTime"])
        # Convert to local tz and strip tzinfo so all datetimes are naive local-wall-clock.
        if tz is not None and start.tzinfo is not None:
            start = start.astimezone(tz).replace(tzinfo=None)
            end = end.astimezone(tz).replace(tzinfo=None)
        is_all_day = False
    else:
        logger.debug("Skipping event with no start time: %s", summary)
        return None

    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        is_all_day=is_all_day,
        location=item.get("location"),
        calendar_name=calendar_name,
        event_id=item.get("id"),
    )
