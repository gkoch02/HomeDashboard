"""Calendar fetcher — dispatcher and birthday extraction.

This module provides the public API for calendar and birthday fetching.
Event fetching dispatches to either the Google Calendar API or ICS feed
backend depending on config.  Birthday extraction supports file, calendar,
and Google Contacts sources.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

from src.config import BirthdayConfig, GoogleConfig
from src.data.models import Birthday, CalendarEvent

# Re-export from sub-modules so existing consumers don't break.
# Tests and other code can continue to ``from src.fetchers.calendar import ...``.
from src.fetchers.calendar_google import (  # noqa: F401
    _apply_delta,
    _build_service,
    _deser_sync_event,
    _fetch_full,
    _fetch_incremental,
    _filter_to_window,
    _load_sync_state,
    _parse_event,
    _save_sync_state,
    _ser_sync_event,
    _today,
    clear_service_caches,
    fetch_google_events,
)
from src.fetchers.calendar_ical import (  # noqa: F401
    _parse_ical_event,
    _url_hostname,
    fetch_from_ical,
)

logger = logging.getLogger(__name__)

_PEOPLE_SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]
_DATE_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_SHORT_RE = re.compile(r"^\d{2}-\d{2}$")

# People API service cache
_people_service_cache: dict[str, Any] = {}


def _clear_people_service_cache() -> None:
    _people_service_cache.clear()


# Preserve the original clear_service_caches behaviour (clears both caches)
_original_clear = clear_service_caches


def clear_service_caches() -> None:  # noqa: F811
    """Clear cached API service objects (useful for testing)."""
    _original_clear()
    _people_service_cache.clear()


def _build_people_service(cfg: GoogleConfig):
    """Build a Google People API service using domain-wide delegation.

    The service account must have domain-wide delegation enabled in Google
    Workspace Admin, and ``cfg.contacts_email`` must be set to the email of
    the user whose contacts should be read.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    key = f"{cfg.service_account_path}:{cfg.contacts_email}"
    if key not in _people_service_cache:
        try:
            creds = service_account.Credentials.from_service_account_file(
                cfg.service_account_path, scopes=_PEOPLE_SCOPES
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load service account credentials from "
                f"{cfg.service_account_path!r}: {exc}"
            ) from exc
        if cfg.contacts_email:
            creds = creds.with_subject(cfg.contacts_email)
        _people_service_cache[key] = build("people", "v1", credentials=creds, cache_discovery=False)
    return _people_service_cache[key]


# ---------------------------------------------------------------------------
# Public API: event fetching (dispatches to Google API or ICS)
# ---------------------------------------------------------------------------

# Keep _fetch_from_ical as an alias for backward compat with mock paths
_fetch_from_ical = fetch_from_ical


def fetch_events(
    cfg: GoogleConfig,
    days: int = 7,
    tz: tzinfo | None = None,
    cache_dir: str | None = None,
) -> list[CalendarEvent]:
    """Return calendar events for the current week across all configured calendars.

    When *cfg.ical_url* is set, events are fetched from that ICS feed URL (and any
    *cfg.additional_ical_urls*) instead of the Google Calendar API.

    When *cache_dir* is provided (Google API path only), sync tokens are stored and
    incremental syncs are used for subsequent calls, reducing API quota consumption.
    """
    if cfg.ical_url:
        urls = [cfg.ical_url] + list(cfg.additional_ical_urls)
        return fetch_from_ical(urls, days=days, tz=tz)

    return fetch_google_events(cfg, days=days, tz=tz, cache_dir=cache_dir)


# ---------------------------------------------------------------------------
# Public API: birthday fetching
# ---------------------------------------------------------------------------


def fetch_birthdays(
    google_cfg: GoogleConfig,
    birthday_cfg: BirthdayConfig,
    tz: tzinfo | None = None,
) -> list[Birthday]:
    """Fetch upcoming birthdays from configured source.

    Sources:
      - ``"file"``      — local JSON file (default)
      - ``"calendar"``  — Google Calendar events matching a keyword
      - ``"contacts"``  — Google Contacts via the People API (requires
                          domain-wide delegation; set ``google.contacts_email``)
    """
    if birthday_cfg.source == "calendar":
        return _birthdays_from_calendar(google_cfg, birthday_cfg, tz=tz)
    if birthday_cfg.source == "contacts":
        return _birthdays_from_contacts(google_cfg, birthday_cfg, tz=tz)
    return _birthdays_from_file(birthday_cfg, tz=tz)


def _birthdays_from_file(cfg: BirthdayConfig, tz: tzinfo | None = None) -> list[Birthday]:
    path = Path(cfg.file_path)
    if not path.exists():
        logger.info("Birthday file not found: %s", path)
        return []

    try:
        with open(path) as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read birthday file %s: %s", path, exc)
        return []

    today = _today(tz)
    lookahead = today + timedelta(days=cfg.lookahead_days)
    birthdays: list[Birthday] = []

    for entry in entries:
        try:
            bday = _parse_birthday_entry(entry, today, lookahead)
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping invalid birthday entry %s: %s", entry, exc)
            continue
        if bday is not None:
            birthdays.append(bday)

    birthdays.sort(key=lambda b: _days_until(b.date, today))
    return birthdays


def _parse_birthday_entry(entry: dict, today: date, lookahead: date) -> Birthday | None:
    name = entry["name"]
    # Accept "MM-DD" or "YYYY-MM-DD"
    raw = entry["date"]
    if _DATE_FULL_RE.match(raw):
        birth_date = date.fromisoformat(raw)
        age = today.year - birth_date.year
        this_year = birth_date.replace(year=today.year)
    elif _DATE_SHORT_RE.match(raw):
        month, day = (int(p) for p in raw.split("-"))
        this_year = date(today.year, month, day)
        age = None
    else:
        raise ValueError(f"Unrecognised date format: {raw!r}")

    # Roll forward to next year if already passed
    if this_year < today:
        this_year = this_year.replace(year=today.year + 1)
        if age is not None:
            age += 1

    if this_year > lookahead:
        return None

    return Birthday(name=name, date=this_year, age=age)


def _birthdays_from_calendar(
    google_cfg: GoogleConfig, birthday_cfg: BirthdayConfig, tz: tzinfo | None = None
) -> list[Birthday]:
    service = _build_service(google_cfg)
    today = _today(tz)
    time_min = datetime.combine(today, datetime.min.time()).astimezone(timezone.utc)
    time_max = time_min + timedelta(days=birthday_cfg.lookahead_days)

    try:
        result = (
            service.events()
            .list(
                calendarId=google_cfg.calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
                q=birthday_cfg.calendar_keyword,
            )
            .execute()
        )
    except Exception as exc:
        logger.warning("Failed to fetch birthday events: %s", exc)
        return []

    birthdays: list[Birthday] = []
    for item in result.get("items", []):
        summary = item.get("summary", "")
        if birthday_cfg.calendar_keyword.lower() not in summary.lower():
            continue
        name = summary.replace(birthday_cfg.calendar_keyword, "").strip(" :'s")
        start_raw = item.get("start", {})
        if "date" in start_raw:
            bday_date = date.fromisoformat(start_raw["date"])
            birthdays.append(Birthday(name=name, date=bday_date))

    birthdays.sort(key=lambda b: _days_until(b.date, today))
    return birthdays


def _birthdays_from_contacts(
    google_cfg: GoogleConfig, birthday_cfg: BirthdayConfig, tz: tzinfo | None = None
) -> list[Birthday]:
    """Fetch birthdays from Google Contacts via the People API.

    Requires the service account to have domain-wide delegation configured
    and ``google.contacts_email`` set to the account whose contacts to read.
    """
    service = _build_people_service(google_cfg)
    today = _today(tz)
    lookahead = today + timedelta(days=birthday_cfg.lookahead_days)

    birthdays: list[Birthday] = []
    page_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {
            "resourceName": "people/me",
            "personFields": "names,birthdays",
            "pageSize": 1000,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = service.people().connections().list(**kwargs).execute()
        except Exception as exc:
            logger.warning("Failed to fetch Google Contacts: %s", exc)
            break

        for person in result.get("connections", []):
            bday = _parse_contact_birthday(person, today, lookahead)
            if bday is not None:
                birthdays.append(bday)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    birthdays.sort(key=lambda b: _days_until(b.date, today))
    return birthdays


def _parse_contact_birthday(person: dict, today: date, lookahead: date) -> Birthday | None:
    """Extract a Birthday from a People API person resource, or None if unusable."""
    names = person.get("names", [])
    if not names:
        return None
    name = names[0].get("displayName", "").strip()
    if not name:
        return None

    bdays = person.get("birthdays", [])
    if not bdays:
        return None
    bday_date_raw = bdays[0].get("date", {})

    month = bday_date_raw.get("month")
    day = bday_date_raw.get("day")
    if month is None or day is None:
        return None

    year: int = bday_date_raw.get("year") or 0
    if year:
        age = today.year - year
        this_year = date(today.year, month, day)
    else:
        age = None
        this_year = date(today.year, month, day)

    if this_year < today:
        this_year = this_year.replace(year=today.year + 1)
        if age is not None:
            age += 1

    if this_year > lookahead:
        return None

    return Birthday(name=name, date=this_year, age=age)


def _days_until(d: date, today: date) -> int:
    delta = (d - today).days
    return delta if delta >= 0 else delta + 365
