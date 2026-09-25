"""The ``halftone_agenda_wide`` theme: the split-plate agenda on a 1360x480 strip."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DayForecast,
    WeatherAlert,
)
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components import halftone_agenda_wide_panel as hw
from src.render.quantize import flatten_pixels
from src.render.theme import AVAILABLE_THEMES, ThemeStyle, load_theme
from src.render.themes.registry import get_inky_palette
from tests.inkutils import ink

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()
MIDNIGHT = datetime.combine(TODAY, datetime.min.time())
NATIVE = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
RAIL = (hw.RAIL_X, 0, 1360, 480)


def _event(hour: int, minute: int = 0, *, mins: int = 45, name: str = "Meeting", day=TODAY, **kw):
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
    return CalendarEvent(summary=name, start=start, end=start + timedelta(minutes=mins), **kw)


def _data(**kw):
    data = generate_dummy_data(now=FIXED_NOW)
    for key, value in kw.items():
        setattr(data, key, value)
    return data


def _plate(data=None, now=FIXED_NOW, style=None):
    img = Image.new("L", (1360, 480), 255)
    d = ImageDraw.Draw(img)
    hw.draw_halftone_agenda_wide(d, data or _data(), now.date(), now, image=img, style=style)
    return img


class TestRegistration:
    def test_registered_with_palette(self):
        assert "halftone_agenda_wide" in AVAILABLE_THEMES
        assert get_inky_palette("halftone_agenda_wide") == (2, 3)  # yellow, red

    def test_canvas_and_mode(self):
        layout = load_theme("halftone_agenda_wide").layout
        assert (layout.canvas_w, layout.canvas_h) == (1360, 480)
        assert layout.canvas_mode == "L"
        assert layout.preferred_quantization_mode == "floyd_steinberg"
        assert layout.prefer_color_on_inky
        assert layout.draw_order == ["halftone_agenda_wide"]

    def test_declines_partial_refresh_by_derivation(self):
        theme = load_theme("halftone_agenda_wide")
        assert theme.layout.supports_partial_refresh is None
        assert not theme.allows_partial_refresh

    def test_event_window_reaches_two_days_past_the_week(self):
        from src.app import EXTRA_EVENT_DAYS, THEMES_NEEDING_TOMORROW

        assert EXTRA_EVENT_DAYS["halftone_agenda_wide"] == hw.EXTRA_EVENT_DAYS == 2
        assert "halftone_agenda_wide" in THEMES_NEEDING_TOMORROW


class TestGeometry:
    def test_panes_span_the_strip(self):
        assert hw.ART_W + hw.DIVIDER_W + hw.AGENDA_W + hw.DIVIDER_W == hw.RAIL_X
        assert hw.RAIL_X < 1360
        assert hw.HERO_H + hw.RULE_H < 480

    def test_render_native(self):
        img = render_dashboard(_data(), NATIVE, theme=load_theme("halftone_agenda_wide"))
        assert img.size == (1360, 480)
        assert img.mode == "1"
        # Illustration dithers, agenda and rail carry ink.
        assert ink(img, (0, 0, hw.ART_W, hw.HERO_H)) > 5000
        assert ink(img, (hw.ART_W + hw.DIVIDER_W, 0, hw.RAIL_X - hw.DIVIDER_W, 480)) > 2000
        assert ink(img, RAIL) > 1500

    def test_render_on_a_landscape_panel_letterboxes(self):
        img = render_dashboard(_data(), DisplayConfig(), theme=load_theme("halftone_agenda_wide"))
        assert img.size == (800, 480)
        assert ink(img, (0, 0, 800, 90)) == 0

    def test_inky_path_uses_only_palette_colours_plus_greys(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025", width=1360, height=480)
        img = render_dashboard(_data(), cfg, theme=load_theme("halftone_agenda_wide"))
        assert img.mode == "RGB"
        from src.render.quantize import INKY_SPECTRA6_PALETTE

        assert INKY_SPECTRA6_PALETTE[3] in set(flatten_pixels(img))  # red somewhere

    def test_four_ink_panel(self):
        from src.display.driver import WAVESHARE_G_PALETTE

        cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
        img = render_dashboard(_data(), cfg, theme=load_theme("halftone_agenda_wide"))
        assert set(flatten_pixels(img)) <= set(WAVESHARE_G_PALETTE)


class TestHelpers:
    def test_forecast_rows_skip_today_and_sort(self):
        w = _data().weather
        w.forecast = [
            DayForecast(TODAY + timedelta(days=3), 1, 0, "01d", "x"),
            DayForecast(TODAY, 1, 0, "01d", "x"),
            DayForecast(TODAY + timedelta(days=1), 1, 0, "01d", "x"),
        ]
        rows = hw.forecast_rows(w, TODAY, 4)
        assert [fc.date for fc in rows] == [TODAY + timedelta(days=1), TODAY + timedelta(days=3)]
        assert hw.forecast_rows(None, TODAY, 4) == []

    def test_birthday_countdown_labels(self):
        assert hw.birthday_countdown(Birthday("a", date(1990, 4, 6)), TODAY) == (0, "Today!")
        assert hw.birthday_countdown(Birthday("a", date(1990, 4, 7)), TODAY) == (1, "Tomorrow")
        assert hw.birthday_countdown(Birthday("a", date(1990, 4, 20)), TODAY) == (14, "in 14d")
        assert (
            hw.birthday_countdown(Birthday("a", date(1990, 1, 1)), TODAY)[0]
            == (date(2027, 1, 1) - TODAY).days
        )

    def test_leap_day_birthday(self):
        days, _ = hw.birthday_countdown(Birthday("a", date(1992, 2, 29)), date(2027, 2, 1))
        assert days == 27

    def test_upcoming_birthdays_within_horizon(self):
        rows = hw.upcoming_birthdays(
            [Birthday("far", date(1990, 6, 1)), Birthday("near", date(1990, 4, 9))],
            TODAY,
            days=14,
            limit=3,
        )
        assert [r[2].name for r in rows] == ["near"]


class TestRail:
    def test_alert_bar(self):
        d = _data()
        d.weather.alerts = [WeatherAlert(event="Wind Advisory")]
        with_alert = _plate(d)
        base = _data()
        base.weather.alerts = []
        without = _plate(base)
        top = (hw.RAIL_X, 0, 1360, 60)
        assert ink(with_alert, top) > ink(without, top) + 2000

    def test_tomorrow_lists_the_next_days_events(self):
        tomorrow = TODAY + timedelta(days=1)
        d = _data(
            events=[
                _event(9, name="Dentist appointment", day=tomorrow),
                _event(11, name="Architecture review", day=tomorrow),
                _event(14, name="Stakeholder briefing", day=tomorrow),
            ]
        )
        empty = _data(events=[])
        cell = (hw.RAIL_X, 0, 1360, 140)
        assert ink(_plate(d), cell) > ink(_plate(empty), cell) + 600

    def test_rolled_over_rail_names_the_day_after(self):
        """After dark with today's events done, the agenda shows tomorrow and
        the rail the day after — whose weekday name replaces TOMORROW."""
        night = FIXED_NOW.replace(hour=22)
        after = TODAY + timedelta(days=2)
        d = _data(
            events=[
                _event(9, name="Dentist appointment", day=after),
                _event(11, name="Architecture review", day=after),
                _event(14, name="Stakeholder briefing", day=after),
            ]
        )
        d2 = _data(events=[])
        cell = (hw.RAIL_X, 0, 1360, 140)
        assert ink(_plate(d, now=night), cell) > ink(_plate(d2, now=night), cell) + 600
        # And the same events a day earlier are not shown at night: the rail
        # has moved on to the day after tomorrow.
        early = _data(events=[_event(9, name="Dentist appointment", day=TODAY + timedelta(days=1))])
        assert ink(_plate(early, now=night), cell) < ink(_plate(d, now=night), cell)

    def test_forecast_rows_drawn(self):
        d = _data()
        no_fc = _data()
        no_fc.weather.forecast = []
        band = (hw.RAIL_X, 100, 1360, 300)
        assert ink(_plate(d), band) > ink(_plate(no_fc), band) + 800

    def test_birthday_today_inverts(self):
        d = _data(birthdays=[Birthday("Mom", date(1970, 4, 6), age=56)])
        far = _data(birthdays=[Birthday("Mom", date(1970, 4, 16), age=56)])
        assert ink(_plate(d), RAIL) > ink(_plate(far), RAIL) + 1500

    def test_air_quality_cell(self):
        d = _data(air_quality=AirQualityData(aqi=152, category="Unhealthy", pm25=55.0))
        none = _data(air_quality=None)
        bottom = (hw.RAIL_X, 480 - hw.FOOT_H - 10, hw.RAIL_X + 180, 480)
        assert ink(_plate(d), bottom) != ink(_plate(none), bottom)
        assert ink(_plate(d), bottom) > 300

    def test_moon_cell_always_present(self):
        img = _plate(_data())
        assert ink(img, (hw.RAIL_X + 180, 480 - hw.FOOT_H - 10, 1360, 480)) > 200

    def test_rail_is_hardened(self):
        """No mid-greys survive in the rail: every pixel is ink or paper."""
        img = _plate(_data())
        values = {
            img.getpixel((x, y)) for y in range(0, 480, 3) for x in range(hw.RAIL_X + 8, 1360, 3)
        }
        assert values <= {0, 255}


class TestAgenda:
    def test_running_event_inverts(self):
        running = _data(events=[_event(10, mins=90, name="Design review")])
        later = _data(events=[_event(15, mins=90, name="Design review")])
        pane = (hw.ART_W + hw.DIVIDER_W, 60, hw.RAIL_X - hw.DIVIDER_W, 160)
        assert ink(_plate(running), pane) > ink(_plate(later), pane) + 3000

    def test_idle_tick_is_byte_identical(self):
        d = _data(content_at=FIXED_NOW - timedelta(minutes=12))
        a = _plate(d, now=FIXED_NOW)
        b = _plate(d, now=FIXED_NOW + timedelta(minutes=5))
        assert a.tobytes() == b.tobytes()

    def test_no_weather_no_crash(self):
        d = _data(weather=None)
        img = _plate(d)
        assert ink(img, RAIL) > 300  # moon and birthdays still there

    def test_defaults_do_not_crash(self):
        img = Image.new("L", (1360, 480), 255)
        d = ImageDraw.Draw(img)
        hw.draw_halftone_agenda_wide(d, _data(), TODAY, FIXED_NOW)
        assert ink(img) > 1000

    def test_style_default(self):
        img = _plate(_data(), style=ThemeStyle(fg=0, bg=255))
        assert ink(img) > 1000
