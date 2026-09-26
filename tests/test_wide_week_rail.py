"""wide_week's editorial rail: the column left of the standard week grid.

Pure helpers first (what the masthead, NOW/NEXT, birthdays and sky lines say),
then differential renders through ``render_dashboard`` — the rail's accents are
palette indices until the pipeline resolves them, so rendering the component
alone on a bare canvas would draw its labels in the wrong ink.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone

import pytest

from src.config import DisplayConfig
from src.data.models import Birthday, CalendarEvent, DashboardData, WeatherAlert, WeatherData
from src.display.driver import WAVESHARE_G_PALETTE, image_hash
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components import wide_week_rail_panel as rail
from src.render.theme import INKY_YELLOW, load_theme
from tests.inkutils import ink

NATIVE = DisplayConfig(provider="waveshare", model="epd7in5_V2", width=1360, height=480)
NOW = datetime(2026, 4, 6, 10, 30)  # a Monday
RAIL = load_theme("wide_week").layout.wide_week_rail
ALERT_BAND = (0, rail.ALERT_Y, RAIL.w - 2, rail.ALERT_Y + rail.ALERT_H)
NEXT_BAND = (0, rail.NEXT_Y, RAIL.w - 2, rail.NEXT_RULE_Y - 2)
MAST_BAND = (RAIL.w // 2, rail.MAST_LINE_Y - 2, RAIL.w - 2, rail.MAST_RULE_Y - 2)


def _event(summary, start, hours=1.0, all_day=False, location=None):
    return CalendarEvent(
        summary, start, start + timedelta(hours=hours), is_all_day=all_day, location=location
    )


def _weather(**kw) -> WeatherData:
    base = dict(
        current_temp=42.0,
        current_icon="02d",
        current_description="partly cloudy",
        high=48.0,
        low=35.0,
        humidity=60,
    )
    base.update(kw)
    return WeatherData(**base)


G = DisplayConfig(provider="waveshare", model="epd10in85g", width=1360, height=480)
YELLOW = WAVESHARE_G_PALETTE[2]  # the G panel's inks: black, white, yellow, red
assert INKY_YELLOW == 2


def _render_g(data: DashboardData, now: datetime = NOW):
    data.fetched_at = now
    return render_dashboard(data, G, theme=load_theme("wide_week")).convert("RGB")


def _yellow(img, box) -> int:
    return sum(n for n, px in img.crop(box).getcolors(1 << 16) if px == YELLOW)


def _render(data: DashboardData, now: datetime = NOW):
    data.fetched_at = now
    img = render_dashboard(data, NATIVE, theme=load_theme("wide_week"))
    return img.convert("1")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestMasthead:
    def test_iso_week_and_day_of_year(self):
        assert rail.masthead_line(date(2026, 4, 6)) == "WEEK 15 · DAY 96"
        assert rail.masthead_line(date(2027, 1, 1)) == "WEEK 53 · DAY 1"


class TestNowOrNext:
    def test_an_event_in_progress_is_now(self):
        running = _event("Standup", datetime(2026, 4, 6, 10), hours=1)
        later = _event("Lunch", datetime(2026, 4, 6, 12))
        assert rail.now_or_next([later, running], NOW) == ("NOW", running)

    def test_otherwise_the_next_to_start(self):
        done = _event("Standup", datetime(2026, 4, 6, 9))
        later = _event("Lunch", datetime(2026, 4, 6, 12))
        tomorrow = _event("Review", datetime(2026, 4, 7, 9))
        assert rail.now_or_next([tomorrow, done, later], NOW) == ("NEXT", later)

    def test_all_day_events_are_skipped(self):
        holiday = _event("Holiday", datetime(2026, 4, 6), hours=24, all_day=True)
        assert rail.now_or_next([holiday], NOW) is None

    def test_nothing_ahead(self):
        assert rail.now_or_next([_event("Done", datetime(2026, 4, 6, 8))], NOW) is None
        assert rail.now_or_next([], NOW) is None

    def test_it_moves_only_at_event_boundaries(self):
        events = [_event("A", datetime(2026, 4, 6, 11)), _event("B", datetime(2026, 4, 6, 14))]
        picks = [
            rail.now_or_next(events, NOW + timedelta(minutes=m))
            for m in range(0, 30, 5)  # 10:30 to 10:55, no boundary
        ]
        assert all(p == picks[0] for p in picks)


class TestWhenLabel:
    def test_now_shows_the_end(self):
        evt = _event("A", datetime(2026, 4, 6, 10), hours=1.5)
        assert rail.when_label("NOW", evt, NOW) == "until 11:30a"

    def test_next_today_tomorrow_and_later(self):
        assert rail.when_label("NEXT", _event("A", datetime(2026, 4, 6, 14)), NOW) == "2p"
        tomorrow = _event("B", datetime(2026, 4, 7, 9))
        assert rail.when_label("NEXT", tomorrow, NOW) == "Tomorrow 9a"
        later = _event("C", datetime(2026, 4, 9, 9))
        assert rail.when_label("NEXT", later, NOW) == "Thu 9a"


class TestBirthdayLine:
    def test_two_weeks_soonest_first_with_ages(self):
        today = date(2026, 4, 6)
        bdays = [
            Birthday("Alice", date(2000, 4, 18), age=26),
            Birthday("Mom", date(1960, 4, 9)),
            Birthday("Later", date(1990, 5, 30)),
            Birthday("Kid", date(2020, 4, 7), age=6),
            Birthday("Me", date(1985, 4, 6)),
        ]
        assert rail.birthday_line(bdays, today) == (
            "Me · today     Kid 6 · tomorrow     Mom · Thu     Alice 26 · Apr 18"
        )

    def test_entries_flag_today(self):
        entries = rail.birthday_entries(
            [Birthday("Mom", date(1960, 4, 9)), Birthday("Me", date(1985, 4, 6))], date(2026, 4, 6)
        )
        assert entries == [("Me · today", True), ("Mom · Thu", False)]

    def test_none_in_range_is_empty(self):
        assert rail.birthday_line([Birthday("X", date(1990, 9, 1))], date(2026, 4, 6)) == ""


class TestSkyRows:
    def test_coordinates_give_sun_day_and_its_change(self):
        rows = dict(rail.sky_rows(None, date(2026, 4, 6), 51.5, -0.12, timezone.utc))
        assert set(rows) == {"Sun", "Day"}
        assert "–" in rows["Sun"]
        assert rows["Day"].startswith("13h") and "+" in rows["Day"]

    def test_a_naive_clock_reads_the_sun_in_the_longitudes_zone(self):
        # New York in April: sunrise near 6:30a, not the 10:30a a UTC reading gives.
        rows = dict(rail.sky_rows(None, date(2026, 4, 6), 40.71, -74.0, None))
        assert rows["Sun"].startswith("5:") or rows["Sun"].startswith("6:")

    def test_without_coordinates_the_reported_times_and_no_change(self):
        w = _weather(
            sunrise=datetime(2026, 4, 6, 6, 24, tzinfo=timezone.utc),
            sunset=datetime(2026, 4, 6, 19, 51, tzinfo=timezone.utc),
        )
        rows = dict(rail.sky_rows(w, date(2026, 4, 6), 0.0, 0.0, timezone.utc))
        assert rows == {"Sun": "6:24a – 7:51p", "Day": "13h 27m"}

    def test_nothing_known_is_no_rows(self):
        assert rail.sky_rows(None, date(2026, 4, 6), None, None, None) == []


class TestFitQuote:
    def test_a_short_quote_takes_the_largest_size(self):
        pt, lines = rail.fit_quote("Short and sweet.", 360, 78)
        assert pt == rail.QUOTE_PTS[0]
        assert lines == ["Short and sweet."]

    def test_a_long_quote_steps_down_and_is_cut_to_fit(self):
        text = " ".join(["words"] * 120)
        pt, lines = rail.fit_quote(text, 360, 78)
        assert pt == rail.QUOTE_PTS[-1]
        assert len(lines) * (pt + rail.QUOTE_LEAD) + rail.AUTHOR_H <= 78
        assert lines[-1].endswith("…")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRender:
    def test_an_alert_is_an_inverted_bar(self):
        calm = _render(DashboardData(weather=_weather()))
        alert = _render(DashboardData(weather=_weather(alerts=[WeatherAlert("Flood Watch")])))
        assert ink(alert, ALERT_BAND) > ink(calm, ALERT_BAND) + 3000

    def test_the_next_event_is_named(self):
        quiet = _render(DashboardData())
        busy = _render(
            DashboardData(events=[_event("Quarterly Planning Review", datetime(2026, 4, 6, 14))])
        )
        assert image_hash(quiet.crop(NEXT_BAND)) != image_hash(busy.crop(NEXT_BAND))
        assert ink(busy, NEXT_BAND) > ink(quiet, NEXT_BAND)

    def test_a_stale_snapshot_says_so(self):
        fresh = _render(DashboardData())
        stale = _render(DashboardData(is_stale=True))
        assert ink(stale, MAST_BAND) > ink(fresh, MAST_BAND) + 30

    def test_idle_tick_is_stable_and_an_event_boundary_is_not(self):
        data = generate_dummy_data(now=NOW)
        data.content_at = NOW

        def at(when):
            return image_hash(_render(data, now=when))

        assert at(NOW) == at(NOW + timedelta(minutes=10))
        # Monday's 2-2:30p 1:1 starts between these: NEXT becomes NOW.
        assert at(datetime(2026, 4, 6, 13, 55)) != at(datetime(2026, 4, 6, 14, 5))

    @pytest.mark.parametrize("temp", [-40.0, 108.0])
    def test_extreme_readings_stay_in_the_rail(self, temp):
        img = _render(DashboardData(weather=_weather(current_temp=temp)))
        # Nothing of the rail crosses its edge rule into the grid.
        assert ink(img, (RAIL.w, 60, RAIL.w + 4, 200)) == ink(
            _render(DashboardData()), (RAIL.w, 60, RAIL.w + 4, 200)
        )


class TestVisibilitySwitches:
    """``display.show_*`` hide the rail's matching section, not just the grid's."""

    WEATHER_BAND = (0, rail.WEATHER_Y, RAIL.w - 2, rail.ALERT_Y - 2)
    GRID_BAND = (0, rail.GRID_Y, RAIL.w - 2, rail.GRID_RULE_Y - 2)
    BIRTHDAY_BAND = (0, rail.BIRTHDAY_Y, RAIL.w - 2, rail.QUOTE_Y - 2)
    QUOTE_BAND = (0, rail.QUOTE_Y, RAIL.w - 2, 478)

    @staticmethod
    def _render_with(**flags):
        data = generate_dummy_data(now=NOW)
        data.fetched_at = NOW
        cfg = dataclasses.replace(NATIVE, **flags)
        return render_dashboard(data, cfg, theme=load_theme("wide_week")).convert("1")

    def test_show_weather_off_blanks_the_weather_now(self):
        shown = self._render_with()
        hidden = self._render_with(show_weather=False)
        assert ink(shown, self.WEATHER_BAND) > 1000
        assert ink(hidden, self.WEATHER_BAND) == 0

    def test_show_weather_off_drops_the_forecast_and_keeps_the_sky(self):
        shown = self._render_with()
        hidden = self._render_with(show_weather=False)
        left = (0, rail.GRID_Y, RAIL.w // 2 - 20, rail.GRID_RULE_Y - 2)
        right = (RAIL.w // 2 + 20, rail.GRID_Y, RAIL.w - 2, rail.GRID_RULE_Y - 2)
        assert ink(hidden, left) < ink(shown, left) // 4
        assert ink(hidden, right) > 200

    def test_show_birthdays_off_blanks_the_birthdays(self):
        shown = self._render_with()
        hidden = self._render_with(show_birthdays=False)
        assert ink(shown, self.BIRTHDAY_BAND) > 200
        assert ink(hidden, self.BIRTHDAY_BAND) == 0

    def test_show_info_panel_off_blanks_the_quote(self):
        shown = self._render_with()
        hidden = self._render_with(show_info_panel=False)
        assert ink(shown, self.QUOTE_BAND) > 1000
        assert ink(hidden, self.QUOTE_BAND) == 0


class TestNextLocation:
    def test_a_multiline_location_sets_only_its_first_line(self):
        def with_location(loc):
            evt = _event("Dentist", datetime(2026, 4, 6, 14), location=loc)
            return _render(DashboardData(events=[evt]))

        one = with_location("Bright Smiles Dental")
        full = with_location("Bright Smiles Dental\n535 W Hamilton Ave, Campbell, CA")
        # The whole plate, not the band: the street would spill below it,
        # over the rule and into the forecast.
        assert image_hash(one) == image_hash(full)


class TestYellowHighlighter:
    """Yellow is only ever a fill behind ink type, and only where the panel has it."""

    FORECAST = (0, rail.GRID_Y, RAIL.w // 2, rail.GRID_RULE_Y)
    BIRTHDAYS = (0, rail.BIRTHDAY_Y - 3, RAIL.w - 2, rail.BIRTHDAY_Y + 22)

    def test_resolves_to_none_where_it_would_be_ink(self):
        style = load_theme("wide_week").style
        assert rail.highlight(style) is None  # unresolved: accent_warn unset
        from dataclasses import replace

        assert rail.highlight(replace(style, accent_warn=style.fg)) is None
        assert rail.highlight(replace(style, accent_warn=(255, 255, 0))) == (255, 255, 0)

    def test_now_next_sits_on_a_yellow_band(self):
        img = _render_g(DashboardData(events=[_event("Review", datetime(2026, 4, 6, 14))]))
        band = NEXT_BAND
        area = (band[2] - band[0]) * (band[3] - band[1])
        assert _yellow(img, band) > area * 0.6

    def test_rain_chips_only_on_wet_days(self):
        from src.data.models import DayForecast

        def forecast(pop):
            days = [DayForecast(date(2026, 4, 7 + i), 50, 40, "10d", "rain", pop) for i in range(3)]
            return DashboardData(weather=_weather(forecast=days))

        dry = _render_g(forecast(0.05))
        wet = _render_g(forecast(0.8))
        assert _yellow(dry, self.FORECAST) == 0
        assert _yellow(wet, self.FORECAST) > 3 * 300

    def test_a_birthday_today_is_highlighted_and_others_are_not(self):
        soon = _render_g(DashboardData(birthdays=[Birthday("Mom", date(1960, 4, 9))]))
        today = _render_g(DashboardData(birthdays=[Birthday("Mom", date(1960, 4, 6))]))
        assert _yellow(soon, self.BIRTHDAYS) == 0
        assert _yellow(today, self.BIRTHDAYS) > 300

    def test_monochrome_keeps_the_type_without_fills(self):
        img = _render(DashboardData(events=[_event("Review", datetime(2026, 4, 6, 14))]))
        # No band: the NEXT area is mostly paper, with the type still in ink.
        area = (NEXT_BAND[2] - NEXT_BAND[0]) * (NEXT_BAND[3] - NEXT_BAND[1])
        assert 200 < ink(img, NEXT_BAND) < area * 0.3


class TestBilevelType:
    """The rail's type is rasterised bilevel even on an RGB (colour-panel) canvas.

    Antialiased glyph edges on RGB are cut at mid-grey by the four-ink snap,
    which erased Playfair's hairlines on the 10.85" G panel.
    """

    @staticmethod
    def _draw_on_rgb():
        from PIL import Image, ImageDraw

        from src.render.theme import ThemeStyle

        img = Image.new("RGB", (RAIL.w, RAIL.h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        style = ThemeStyle(fg=(0, 0, 0), bg=(255, 255, 255))
        data = generate_dummy_data(now=NOW)
        data.fetched_at = NOW
        rail.draw_wide_week_rail(draw, data, NOW.date(), NOW, region=RAIL, style=style)
        return img, draw

    def test_no_antialiased_pixels_on_an_rgb_plate(self):
        img, _ = self._draw_on_rgb()
        colours = {px for _, px in img.getcolors(1 << 16)}
        assert colours == {(0, 0, 0), (255, 255, 255)}

    def test_the_callers_fontmode_is_restored(self):
        _, draw = self._draw_on_rgb()
        assert draw.fontmode == "L"
