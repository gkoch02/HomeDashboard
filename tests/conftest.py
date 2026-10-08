"""Shared test helpers.

Plain functions rather than fixtures, imported by name
(``from tests.conftest import make_draw``), so a call site reads like the
local helper it replaced. Only helpers that were copied verbatim between test
files live here; a helper whose body is specific to one theme stays in that
theme's test module. Imports of ``src`` beyond the data models stay inside the
helpers, because this module loads for every test session.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import CalendarEvent, DayForecast, WeatherData

# The pinned render moment the art-theme suites share (a Monday morning).
AGENDA_NOW = datetime(2026, 4, 6, 10, 30)


def make_draw(w: int = 800, h: int = 480):
    """A white mode-"1" plate and its draw handle."""
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def make_weather(**kwargs) -> WeatherData:
    """Mild clear weather with a one-day forecast; keyword arguments override fields."""
    defaults = dict(
        current_temp=55.0,
        current_icon="01d",
        current_description="clear",
        high=60.0,
        low=45.0,
        humidity=50,
        forecast=[
            DayForecast(
                date=date.today() + timedelta(days=1),
                high=58.0,
                low=44.0,
                icon="02d",
                description="cloudy",
            )
        ],
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


def make_clear_weather() -> WeatherData:
    """Warm clear weather with no forecast, for pipeline and cache round-trips."""
    return WeatherData(
        current_temp=68.0,
        current_icon="01d",
        current_description="clear",
        high=75.0,
        low=55.0,
        humidity=40,
    )


def make_meeting_events() -> list[CalendarEvent]:
    """One timed event, for pipeline and cache round-trips."""
    return [
        CalendarEvent(
            summary="Meeting",
            start=datetime(2024, 3, 15, 10, 0),
            end=datetime(2024, 3, 15, 11, 0),
        )
    ]


def all_day_event(start: date, end: date, summary: str = "All Day") -> CalendarEvent:
    return CalendarEvent(
        summary=summary,
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
        is_all_day=True,
    )


def load_source(source: str, cache_dir: str):
    """Decode one source from the cache file the way DataPipeline.fetch() does."""
    from src.fetchers.cache import load_cache_blob, load_cached_source_from_blob

    return load_cached_source_from_blob(source, load_cache_blob(cache_dir))


def agenda_event(
    hour: int,
    minute: int = 0,
    *,
    mins: int = 45,
    name: str = "Meeting",
    day: date = AGENDA_NOW.date(),
    **kw,
) -> CalendarEvent:
    """A timed event on *day* (naive local), *mins* long."""
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
    return CalendarEvent(summary=name, start=start, end=start + timedelta(minutes=mins), **kw)


def agenda_data(
    *, icon: str | None = "01d", events=None, weather: bool = True, now: datetime = AGENDA_NOW
):
    """Dummy data at *now* with the current icon, the events or the weather swapped."""
    from src.dummy_data import generate_dummy_data

    data = generate_dummy_data(now=now)
    if not weather:
        data.weather = None
    elif icon is not None and data.weather is not None:
        data.weather.current_icon = icon
    if events is not None:
        data.events = events
    return data
