"""The panoramic (1360x480) themes: wide_week, wide_day, wide_forecast.

Layout smoke tests for all three, the pure calendar helpers behind
``wide_day``, and differential render assertions for the states each plate
encodes. Ink is measured with ``tests/inkutils`` on mode-``"1"`` plates rendered
at the themes' native size, so nothing here depends on a resize.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    WeatherAlert,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components import wide_day_panel as wd
from src.render.components import wide_forecast_panel as wf
from src.render.theme import ComponentRegion, ThemeStyle, load_theme
from tests.inkutils import ink

FIXED_NOW = datetime(2026, 4, 6, 10, 30)  # a Monday
TODAY = FIXED_NOW.date()
NATIVE = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
WIDE_THEMES = ("wide_week", "wide_day", "wide_forecast")


def _event(summary, start_h, end_h, day=TODAY, all_day=False, location=None):
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=start_h)
    end = datetime.combine(day, datetime.min.time()) + timedelta(hours=end_h)
    return CalendarEvent(
        summary=summary, start=start, end=end, is_all_day=all_day, location=location
    )


def _weather(**kw):
    base = dict(
        current_temp=42.0,
        current_icon="02d",
        current_description="partly cloudy",
        high=48.0,
        low=35.0,
        humidity=65,
        forecast=[
            DayForecast(TODAY + timedelta(days=i), 45 + i, 33 + i, "01d", "clear", 0.1 * i)
            for i in range(1, 6)
        ],
    )
    base.update(kw)
    return WeatherData(**base)


def _plate():
    img = Image.new("1", (1360, 480), 1)
    return img, ImageDraw.Draw(img)


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


class TestThemes:
    def test_canvas_is_panoramic(self):
        for name in WIDE_THEMES:
            layout = load_theme(name).layout
            assert (layout.canvas_w, layout.canvas_h) == (1360, 480), name

    def test_render_at_native_size(self):
        data = generate_dummy_data(now=FIXED_NOW)
        for name in WIDE_THEMES:
            img = render_dashboard(data, NATIVE, theme=load_theme(name))
            assert img.size == (1360, 480), name
            assert img.mode == "1", name
            assert ink(img) > 2000, f"{name} rendered blank"

    def test_render_on_a_landscape_panel_letterboxes(self):
        """On an 800x480 panel the strip fits as a band, not a stretch."""
        data = generate_dummy_data(now=FIXED_NOW)
        for name in WIDE_THEMES:
            img = render_dashboard(data, DisplayConfig(), theme=load_theme(name))
            assert img.size == (800, 480), name
            # 1360x480 at 800/1360 is 800x282: rows above ~99 and below ~381 are bands.
            assert ink(img, (0, 0, 800, 90)) == 0, name
            assert ink(img, (0, 390, 800, 480)) == 0, name
            assert ink(img, (0, 100, 800, 380)) > 1000, name

    def test_partial_refresh_is_derived_not_declared(self):
        for name in WIDE_THEMES:
            theme = load_theme(name)
            assert theme.layout.supports_partial_refresh is None, name
            assert theme.allows_partial_refresh, name

    def test_wide_week_uses_the_standard_components(self):
        layout = load_theme("wide_week").layout
        assert layout.draw_order == ["header", "week_view", "weather", "birthdays", "info"]
        assert layout.week_view.w + layout.weather.w == 1360
        assert layout.weather.h + layout.birthdays.h + layout.info.h == 480 - layout.header.h

    def test_wide_week_puts_the_calendar_left_and_the_rail_right(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, NATIVE, theme=load_theme("wide_week"))
        assert ink(img, (0, 60, 900, 480)) > 3000
        assert ink(img, (900, 44, 1360, 480)) > 3000


# ---------------------------------------------------------------------------
# wide_day helpers
# ---------------------------------------------------------------------------


class TestEventLanes:
    def test_sequential_events_share_a_lane(self):
        lanes = wd.event_lanes([_event("a", 9, 10), _event("b", 10, 11), _event("c", 11, 12)])
        assert len(lanes) == 1
        assert [e.summary for e in lanes[0]] == ["a", "b", "c"]

    def test_overlaps_open_a_second_lane(self):
        lanes = wd.event_lanes([_event("a", 9, 11), _event("b", 10, 12), _event("c", 11, 12)])
        assert [[e.summary for e in lane] for lane in lanes] == [["a", "c"], ["b"]]

    def test_input_order_does_not_matter(self):
        lanes = wd.event_lanes([_event("b", 10, 12), _event("a", 9, 11)])
        assert [[e.summary for e in lane] for lane in lanes] == [["a"], ["b"]]


class TestTimedEventsForDay:
    """The timeline selects by overlap with the day, not by start date (Codex on #257)."""

    def test_an_event_in_progress_at_midnight_is_included(self):
        overnight = _event("Night shift", 22, 30, day=TODAY - timedelta(days=1))  # 10p–6a
        assert wd.timed_events_for_day([overnight], TODAY) == [overnight]

    def test_an_event_ending_at_midnight_is_not(self):
        yesterday = _event("a", 22, 24, day=TODAY - timedelta(days=1))
        tomorrow = _event("b", 0, 1, day=TODAY + timedelta(days=1))
        assert wd.timed_events_for_day([yesterday, tomorrow], TODAY) == []

    def test_all_day_events_are_left_to_the_chips(self):
        chip = _event("Holiday", 0, 24, all_day=True)
        assert wd.timed_events_for_day([chip, _event("a", 9, 10)], TODAY) == [_event("a", 9, 10)]

    def test_sorted_by_start(self):
        late, early = _event("late", 14, 15), _event("early", 9, 10)
        assert wd.timed_events_for_day([late, early], TODAY) == [early, late]


class TestAxisHours:
    def test_default_window(self):
        assert wd.axis_hours([], TODAY) == (wd.AXIS_MIN_HOUR, wd.AXIS_MAX_HOUR)
        assert wd.axis_hours([_event("a", 9, 10)], TODAY) == (6, 22)

    def test_early_event_widens_the_start(self):
        assert wd.axis_hours([_event("a", 5, 6)], TODAY)[0] == 5

    def test_late_event_widens_the_end_to_the_next_hour(self):
        assert wd.axis_hours([_event("a", 22, 23.5)], TODAY)[1] == 24
        assert wd.axis_hours([_event("a", 22, 23)], TODAY)[1] == 23

    def test_clamped_to_the_day(self):
        crossing = _event("a", 23, 26)  # ends 2a tomorrow
        assert wd.axis_hours([crossing], TODAY) == (6, 24)


class TestEventState:
    def test_states(self):
        evt = _event("a", 10, 11)
        # The vocabulary is day_arc's, shared rather than re-derived.
        assert wd.event_state(evt, FIXED_NOW.replace(hour=9)) == "next"
        assert wd.event_state(evt, FIXED_NOW.replace(hour=10, minute=30)) == "now"
        assert wd.event_state(evt, FIXED_NOW.replace(hour=11, minute=0)) == "past"


class TestUpcomingEvents:
    def test_skips_past_and_all_day_and_sorts(self):
        events = [
            _event("later", 15, 16),
            _event("gone", 8, 9),
            _event("soon", 11, 12),
            _event("allday", 0, 24, all_day=True),
            _event("tomorrow", 9, 10, day=TODAY + timedelta(days=1)),
        ]
        picked = wd.upcoming_events(events, FIXED_NOW, 10)
        assert [e.summary for e in picked] == ["soon", "later", "tomorrow"]

    def test_limit(self):
        events = [_event(str(i), 11 + i, 12 + i) for i in range(6)]
        assert len(wd.upcoming_events(events, FIXED_NOW, 4)) == 4


class TestBirthdays:
    def test_next_occurrence_rolls_to_next_year(self):
        b = Birthday(name="x", date=date(1990, 1, 5))
        assert wd.next_occurrence(b, TODAY) == date(2027, 1, 5)

    def test_next_occurrence_today(self):
        b = Birthday(name="x", date=date(1990, 4, 6))
        assert wd.next_occurrence(b, TODAY) == TODAY

    def test_leap_day_off_leap_years(self):
        b = Birthday(name="x", date=date(1992, 2, 29))
        assert wd.next_occurrence(b, date(2027, 1, 1)) == date(2027, 2, 28)
        assert wd.next_occurrence(b, date(2028, 1, 1)) == date(2028, 2, 29)

    def test_upcoming_within_horizon_sorted(self):
        bdays = [
            Birthday(name="far", date=date(1990, 4, 20)),
            Birthday(name="near", date=date(1990, 4, 9)),
            Birthday(name="today", date=date(1990, 4, 6), age=36),
        ]
        rows = wd.upcoming_birthdays(bdays, TODAY, days=7, limit=5)
        assert [b.name for _, b in rows] == ["today", "near"]


# ---------------------------------------------------------------------------
# wide_day rendering
# ---------------------------------------------------------------------------


def _day_data(events, now=FIXED_NOW, **kw):
    kw.setdefault("weather", _weather())
    return DashboardData(events=events, fetched_at=now, **kw)


class TestWideDayRender:
    BAR_ROW = (300, 90, 1090, 140)  # first lane, across the timeline

    def test_active_event_is_a_solid_bar(self):
        """An active bar is filled; the same event upcoming is only outlined."""
        evt = _event("Design review", 10, 12)
        img_active, d = _plate()
        wd.draw_wide_day(
            d, _day_data([evt], now=FIXED_NOW.replace(hour=11)), TODAY, FIXED_NOW.replace(hour=11)
        )
        img_upcoming, d = _plate()
        wd.draw_wide_day(
            d, _day_data([evt], now=FIXED_NOW.replace(hour=8)), TODAY, FIXED_NOW.replace(hour=8)
        )
        assert ink(img_active, self.BAR_ROW) > 2 * ink(img_upcoming, self.BAR_ROW)

    def test_now_marker_only_when_the_moment_is_on_the_axis(self):
        evt = _event("a", 9, 10)
        on_axis, d = _plate()
        wd.draw_wide_day(d, _day_data([evt]), TODAY, FIXED_NOW)
        off_axis_now = FIXED_NOW.replace(hour=23, minute=30)
        off_axis, d = _plate()
        wd.draw_wide_day(d, _day_data([evt], now=off_axis_now), TODAY, off_axis_now)
        # The marker is a two-pixel vertical rule down the lanes area; the
        # column band around 10:30 gains ink only when the marker is drawn.
        column = (515, 100, 545, 440)
        assert ink(on_axis, column) > ink(off_axis, column) + 300

    def test_short_event_still_gets_a_label(self):
        """A 30-minute bar is 24 px wide — its title is set beside it."""
        evt = _event("Standup", 9, 9.5)
        with_label, d = _plate()
        wd.draw_wide_day(d, _day_data([evt]), TODAY, FIXED_NOW)
        without, d = _plate()
        wd.draw_wide_day(d, _day_data([]), TODAY, FIXED_NOW)
        # Beside the bar, to the right of 9:30 on the axis.
        beside = (485, 92, 640, 138)
        assert ink(with_label, beside) > ink(without, beside) + 150

    def test_overnight_event_gets_a_bar_from_the_axis_start(self):
        """Started yesterday, still running: the bar is clipped to today, not dropped."""
        overnight = _event("Night shift", 22, 31, day=TODAY - timedelta(days=1))  # 10p–7a
        with_bar, d = _plate()
        wd.draw_wide_day(d, _day_data([overnight]), TODAY, FIXED_NOW)
        without, d = _plate()
        wd.draw_wide_day(d, _day_data([]), TODAY, FIXED_NOW)
        # The 6a–7a stretch of the first lane, at the left edge of the axis.
        head = (300, 90, 360, 140)
        assert ink(with_bar, head) > ink(without, head) + 100

    def test_empty_day_says_so(self):
        img, d = _plate()
        wd.draw_wide_day(d, _day_data([]), TODAY, FIXED_NOW)
        busy, d = _plate()
        wd.draw_wide_day(d, _day_data([_event("a", 9, 10)]), TODAY, FIXED_NOW)
        centre = (560, 220, 830, 300)
        assert ink(img, centre) > ink(busy, centre) + 200

    def test_allday_events_become_chips_on_the_title_row(self):
        chip = _event("Conference", 0, 24, all_day=True)
        with_chip, d = _plate()
        wd.draw_wide_day(d, _day_data([chip]), TODAY, FIXED_NOW)
        without, d = _plate()
        wd.draw_wide_day(d, _day_data([]), TODAY, FIXED_NOW)
        title_row_right = (800, 8, 1090, 40)
        assert ink(with_chip, title_row_right) > ink(without, title_row_right) + 300

    def test_overflow_lanes_are_counted(self):
        # Ten mutually overlapping events need ten lanes; seven fit.
        events = [_event(f"e{i}", 9, 12) for i in range(10)]
        img, d = _plate()
        wd.draw_wide_day(d, _day_data(events), TODAY, FIXED_NOW)
        fits, d = _plate()
        wd.draw_wide_day(d, _day_data(events[:2]), TODAY, FIXED_NOW)
        footer = (318, 448, 600, 478)
        assert ink(img, footer) > ink(fits, footer) + 50

    def test_alert_bar_on_the_left_block(self):
        with_alert, d = _plate()
        data = _day_data([], weather=_weather(alerts=[WeatherAlert(event="Wind Advisory")]))
        wd.draw_wide_day(d, data, TODAY, FIXED_NOW)
        without, d = _plate()
        wd.draw_wide_day(d, _day_data([]), TODAY, FIXED_NOW)
        left_lower = (0, 340, 300, 400)
        assert ink(with_alert, left_lower) > ink(without, left_lower) + 1000

    def test_up_next_reaches_into_tomorrow(self):
        tomorrow = _event("Dentist", 9, 10, day=TODAY + timedelta(days=1))
        img, d = _plate()
        wd.draw_wide_day(d, _day_data([tomorrow]), TODAY, FIXED_NOW)
        empty, d = _plate()
        wd.draw_wide_day(d, _day_data([]), TODAY, FIXED_NOW)
        rail = (1092, 40, 1360, 260)
        assert ink(img, rail) != ink(empty, rail)

    def test_weather_unavailable_does_not_crash(self):
        img, d = _plate()
        wd.draw_wide_day(
            d, DashboardData(events=[], weather=None, fetched_at=FIXED_NOW), TODAY, FIXED_NOW
        )
        assert ink(img, (0, 0, 300, 480)) > 500

    def test_default_region_and_style(self):
        img, d = _plate()
        wd.draw_wide_day(d, _day_data([_event("a", 9, 10)]), TODAY, FIXED_NOW)
        assert ink(img) > 1000

    def test_aware_now_is_accepted(self):
        from zoneinfo import ZoneInfo

        aware = FIXED_NOW.replace(tzinfo=ZoneInfo("America/New_York"))
        img, d = _plate()
        wd.draw_wide_day(d, _day_data([_event("a", 10, 11)], now=aware), TODAY, aware)
        assert ink(img) > 1000


# ---------------------------------------------------------------------------
# wide_forecast rendering
# ---------------------------------------------------------------------------


def _forecast_data(weather=None, air=None):
    return DashboardData(
        events=[],
        weather=weather if weather is not None else _weather(),
        air_quality=air,
        fetched_at=FIXED_NOW,
    )


class TestWideForecastRender:
    BAND_ALERTS = (422, 300, 730, 480)
    BAND_AQI = (735, 300, 1045, 480)
    BAND_MOON = (1050, 300, 1360, 480)

    def test_alerts_fill_the_alerts_cell(self):
        with_alert, d = _plate()
        wf.draw_wide_forecast(
            d,
            _forecast_data(_weather(alerts=[WeatherAlert(event="Flood Watch")])),
            TODAY,
            FIXED_NOW,
        )
        without, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(), TODAY, FIXED_NOW)
        assert ink(with_alert, self.BAND_ALERTS) > ink(without, self.BAND_ALERTS) + 1500

    def test_air_quality_cell(self):
        aqi = AirQualityData(aqi=152, category="Unhealthy", pm25=55.0)
        with_aqi, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(air=aqi), TODAY, FIXED_NOW)
        without, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(), TODAY, FIXED_NOW)
        assert ink(with_aqi, self.BAND_AQI) != ink(without, self.BAND_AQI)
        assert ink(with_aqi, self.BAND_AQI) > 800  # the 54-pt numeral

    def test_moon_cell_always_drawn(self):
        img, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(), TODAY, FIXED_NOW)
        assert ink(img, self.BAND_MOON) > 400

    def test_forecast_cards_one_per_day(self):
        one_day = _weather(
            forecast=[DayForecast(TODAY + timedelta(days=1), 45, 33, "01d", "clear", 0.5)]
        )
        img_one, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(one_day), TODAY, FIXED_NOW)
        img_five, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(), TODAY, FIXED_NOW)
        # Five cards put ink in the fifth column; one card spans the row and
        # its separators are gone.
        assert ink(img_five, (1170, 60, 1360, 200)) > 200
        assert ink(img_one, (1170, 60, 1360, 200)) < ink(img_five, (1170, 60, 1360, 200))

    def test_precip_bar_fills_with_probability(self):
        dry = _weather(
            forecast=[DayForecast(TODAY + timedelta(days=1), 45, 33, "01d", "clear", 0.0)]
        )
        wet = _weather(
            forecast=[DayForecast(TODAY + timedelta(days=1), 45, 33, "09d", "rain", 1.0)]
        )
        img_dry, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(dry), TODAY, FIXED_NOW)
        img_wet, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(wet), TODAY, FIXED_NOW)
        bar_row = (430, 205, 1360, 240)
        assert ink(img_wet, bar_row) > ink(img_dry, bar_row) + 2000

    def test_today_is_a_chip(self):
        today_first = _weather(forecast=[DayForecast(TODAY, 45, 33, "01d", "clear", None)])
        tomorrow_first = _weather(
            forecast=[DayForecast(TODAY + timedelta(days=1), 45, 33, "01d", "clear", None)]
        )
        img_today, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(today_first), TODAY, FIXED_NOW)
        img_tomorrow, d = _plate()
        wf.draw_wide_forecast(d, _forecast_data(tomorrow_first), TODAY, FIXED_NOW)
        weekday_row = (422, 10, 1360, 50)
        assert ink(img_today, weekday_row) > ink(img_tomorrow, weekday_row) + 500

    def test_no_weather_renders_a_message(self):
        img, d = _plate()
        wf.draw_wide_forecast(
            d, DashboardData(events=[], weather=None, fetched_at=FIXED_NOW), TODAY, FIXED_NOW
        )
        assert ink(img, (0, 0, 420, 480)) > 300
        assert ink(img, (422, 0, 1360, 296)) > 300  # "No forecast available"

    def test_tint_is_none_on_a_monochrome_style(self):
        assert wf._tint(ThemeStyle()) is None
        assert wf._tint(ThemeStyle(accent_secondary=(255, 255, 0), fg=(0, 0, 0))) == (255, 255, 0)

    def test_region_offset_is_respected(self):
        img = Image.new("1", (1400, 520), 1)
        d = ImageDraw.Draw(img)
        wf.draw_wide_forecast(
            d, _forecast_data(), TODAY, FIXED_NOW, region=ComponentRegion(40, 40, 1360, 480)
        )
        assert ink(img, (0, 0, 1400, 40)) == 0
        assert ink(img, (0, 0, 40, 520)) == 0
