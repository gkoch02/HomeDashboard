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


def _allday(name: str, day=TODAY) -> CalendarEvent:
    start = datetime.combine(day, datetime.min.time())
    return CalendarEvent(summary=name, start=start, end=start + timedelta(days=1), is_all_day=True)


def _colour(data, now=FIXED_NOW):
    """Render through the four-ink 10.85" backend; pixels come back as its inks."""
    data.fetched_at = now
    cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
    return render_dashboard(data, cfg, theme=load_theme("halftone_agenda_wide"))


def _inks(img, box) -> set:
    return set(flatten_pixels(img.crop(box)))


YELLOW = (255, 255, 0)
RED = (255, 0, 0)
AGENDA = (hw.ART_W + hw.DIVIDER_W, 0, hw.RAIL_X - hw.DIVIDER_W, 480)


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

        assert EXTRA_EVENT_DAYS["halftone_agenda_wide"] == 2
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
    def test_the_plate_does_not_repaint_at_event_boundaries(self):
        """The whole point of this pane: an event starting, running or ending
        changes nothing on the plate, so the panel is not written for it."""
        d = _data(
            events=[_event(10, mins=60, name="Design review"), _event(13, mins=60)],
            content_at=FIXED_NOW - timedelta(minutes=12),
        )
        before = _plate(d, now=FIXED_NOW.replace(hour=9))
        during = _plate(d, now=FIXED_NOW.replace(hour=10, minute=30))
        after = _plate(d, now=FIXED_NOW.replace(hour=14))
        assert before.tobytes() == during.tobytes() == after.tobytes()

    def test_no_accent_in_the_agenda_pane_on_a_colour_panel(self):
        from src.render.canvas import render_dashboard as _render

        d = _data(events=[_event(10, mins=60), _event(15, mins=60)])
        cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
        img = _render(d, cfg, theme=load_theme("halftone_agenda_wide"))
        pane = img.crop((hw.ART_W + hw.DIVIDER_W, 0, hw.RAIL_X - hw.DIVIDER_W, 480))
        assert (255, 0, 0) not in set(flatten_pixels(pane))

    def test_colour_plate_does_not_repaint_at_event_boundaries(self):
        """The event accents key on the kind of event, never the clock."""
        d = _data(
            events=[_event(10, mins=60), _event(13, mins=60), _allday("Offsite")],
            content_at=FIXED_NOW - timedelta(minutes=12),
        )
        before = _colour(d, now=FIXED_NOW.replace(hour=9))
        during = _colour(d, now=FIXED_NOW.replace(hour=10, minute=30))
        after = _colour(d, now=FIXED_NOW.replace(hour=14))
        assert before.tobytes() == during.tobytes() == after.tobytes()

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


# ---------------------------------------------------------------------------
# The wide agenda: strip, durations, gaps, next-up accent
# ---------------------------------------------------------------------------

AGENDA_X0 = hw.ART_W + hw.DIVIDER_W + hw.AGENDA_PAD_X
AGENDA_X1 = hw.RAIL_X - hw.DIVIDER_W - hw.AGENDA_PAD_X
STRIP_BAND = (AGENDA_X0, 44, AGENDA_X1, 80)
ROWS_BAND = (AGENDA_X0, 100, AGENDA_X1, 456)


def _agenda_data(events, now=FIXED_NOW):
    d = _data(events=events, content_at=FIXED_NOW - timedelta(minutes=12))
    return d


class TestAgendaHelpers:
    def test_fmt_duration(self):
        assert hw.fmt_duration(45) == "45m"
        assert hw.fmt_duration(60) == "1h"
        assert hw.fmt_duration(90) == "1h 30m"
        assert hw.fmt_duration(0) == "0m"

    def test_booked_minutes_counts_overlaps_once(self):
        a = _event(9, mins=120)  # 9–11
        b = _event(10, mins=120)  # 10–12
        assert hw.booked_minutes([a, b]) == 180
        allday = _event(0, mins=24 * 60, is_all_day=True)
        assert hw.booked_minutes([a, allday]) == 120

    def test_booked_minutes_clips_multi_day_events_to_the_day(self):
        """A timed event running for days books only today's part (#311)."""
        long = _event(8, mins=6 * 24 * 60)  # 08:00 today → +6 days
        assert hw.booked_minutes([long], TODAY) == 16 * 60
        overnight = _event(0, mins=60, day=TODAY - timedelta(days=1))
        overnight.end = overnight.start + timedelta(hours=26)  # yesterday 00:00 → today 02:00
        assert hw.booked_minutes([overnight], TODAY) == 120

    def test_gap_after(self):
        events = [_event(9, mins=60), _event(10, minute=30, mins=30), _event(14, mins=60)]
        assert hw.gap_after(events, 0) == 30
        assert hw.gap_after(events, 1) == 180
        assert hw.gap_after(events, 2) is None

    def test_gap_after_measures_from_the_latest_end(self):
        long = _event(9, mins=240)  # 9–1p
        short = _event(10, mins=30)  # inside it
        later = _event(14, mins=60)
        assert hw.gap_after([long, short, later], 1) == 60  # from 1p, not 10:30

    def test_gap_after_skips_all_day(self):
        allday = _event(0, mins=24 * 60, is_all_day=True)
        events = [allday, _event(9, mins=60), _event(12, mins=60)]
        assert hw.gap_after(events, 0) is None
        assert hw.gap_after(events, 1) == 120

    def test_wide_metrics_drops_gaps_before_shrinking_type_too_far(self):
        roomy = hw.wide_metrics(2, 1, 340)
        assert roomy[0] == 3 and roomy[6] is True
        dense = hw.wide_metrics(9, 8, 340)
        assert dense[6] is False
        assert hw.wide_metrics(40, 0, 340) == hw._WIDE_TIERS[-1]

    def test_strip_hours(self):
        assert hw.strip_hours([], TODAY) == (6, 22)
        assert hw.strip_hours([_event(5, mins=30)], TODAY)[0] == 5
        assert hw.strip_hours([_event(22, mins=90)], TODAY)[1] == 24


class TestAgendaRender:
    def test_schedule_strip_has_a_block_per_event(self):
        busy = _plate(_agenda_data([_event(9, mins=60), _event(15, mins=120)]))
        empty = _plate(_agenda_data([]))
        assert ink(busy, STRIP_BAND) > ink(empty, STRIP_BAND) + 500

    def test_gap_marker_appears_for_a_long_gap_only(self):
        # Both events upcoming and on whole hours either way, so the rows share
        # one treatment and one time-cell shape; only the marker differs.
        short_gap = _plate(_agenda_data([_event(13, mins=60), _event(14, mins=60)]))
        long_gap = _plate(_agenda_data([_event(13, mins=60), _event(17, mins=60)]))
        # Same two rows either way; the long gap adds a labelled rule between them.
        assert ink(long_gap, ROWS_BAND) > ink(short_gap, ROWS_BAND) + 150

    def test_duration_column_at_the_right_margin(self):
        timed = _plate(_agenda_data([_event(15, mins=90, name="Review")]))
        allday = _plate(_agenda_data([_event(0, mins=24 * 60, name="Review", is_all_day=True)]))
        column = (AGENDA_X1 - hw.DURATION_W, 100, AGENDA_X1, 200)
        assert ink(timed, column) > ink(allday, column) + 100

    def test_rollover_is_the_one_clock_driven_change(self):
        """After dark with today's events done the agenda shows tomorrow — one
        repaint a day, and the reason the theme fetches the extra days."""
        d = _agenda_data([_event(9, mins=60), _event(9, mins=60, day=TODAY + timedelta(days=1))])
        evening = _plate(d, now=FIXED_NOW.replace(hour=17))
        night = _plate(d, now=FIXED_NOW.replace(hour=22))
        assert evening.tobytes() != night.tobytes()
        header = (AGENDA_X0 - 6, 10, AGENDA_X0 + 200, 44)
        assert ink(night, header) > ink(evening, header) + 1500  # the inverted chip

    def test_header_meta_reports_booked_time_and_next(self):
        one = _plate(_agenda_data([_event(15, mins=60)]))
        none = _plate(_agenda_data([]))
        meta = (AGENDA_X1 - 320, 14, AGENDA_X1, 44)
        assert ink(one, meta) > ink(none, meta) + 200

    def test_overflow_line_when_the_day_runs_past_the_pane(self):
        many = [_event(7 + i, mins=45, name=f"Event {i}") for i in range(14)]
        img = _plate(_agenda_data(many))
        few = _plate(_agenda_data(many[:3]))
        bottom = (AGENDA_X0, 420, AGENDA_X1, 456)
        assert ink(img, bottom) > ink(few, bottom)

    def test_idle_tick_is_still_byte_identical(self):
        d = _agenda_data([_event(9, mins=60), _event(13, mins=60)])
        a = _plate(d, now=FIXED_NOW)
        b = _plate(d, now=FIXED_NOW + timedelta(minutes=4))
        assert a.tobytes() == b.tobytes()


# ---------------------------------------------------------------------------
# Colour accents on the four-ink panel
# ---------------------------------------------------------------------------


class TestColourAccents:
    def test_timed_event_tick_is_yellow(self):
        timed = _colour(_data(events=[_event(10, mins=60)]))
        empty = _colour(_data(events=[]))
        rows = (AGENDA[0], 100, AGENDA[2], 400)
        assert YELLOW in _inks(timed, rows)
        assert YELLOW not in _inks(empty, rows)

    def test_all_day_tick_is_red(self):
        allday = _colour(_data(events=[_allday("Spring Break")]))
        timed = _colour(_data(events=[_event(10, mins=60)]))
        assert RED in _inks(allday, AGENDA)
        assert RED not in _inks(timed, AGENDA)

    def test_all_day_tick_stays_outlined_on_monochrome(self):
        """Both accents are ink on mono, so the outline is what tells them apart."""
        allday = _plate(_data(events=[_allday("Spring Break")]))
        timed = _plate(_data(events=[_event(10, mins=60)]))
        tick_x = hw.ART_W + hw.DIVIDER_W + hw.AGENDA_PAD_X + hw._WIDE_TIERS[0][2] + 1
        box = (tick_x, 110, tick_x + 2, 130)
        assert ink(timed, box) == 2 * 20
        assert ink(allday, box) == 0

    def test_dateline_is_red(self):
        img = _colour(_data())
        dateline = (0, 440, hw.ART_W // 2, 480)
        assert RED in _inks(img, dateline)

    def test_updated_stamp_is_yellow(self):
        img = _colour(_data(events=[]))
        footer = (AGENDA[0], 480 - hw.FOOTER_H, AGENDA[2], 480)
        assert YELLOW in _inks(img, footer)


class TestBirthdays:
    def _quiet(self, n: int):
        people = [Birthday(f"Person {i}", date(1990, 4, 7 + i)) for i in range(n)]
        d = _data(events=[], birthdays=people)
        d.weather.alerts = []
        return _plate(d)

    def test_up_to_five_rows_on_a_quiet_day(self):
        band = (hw.RAIL_X, 0, 1360, 480 - hw.FOOT_H - 4)
        four, five, six = (ink(self._quiet(n), band) for n in (4, 5, 6))
        assert five > four + 100
        assert six == five
