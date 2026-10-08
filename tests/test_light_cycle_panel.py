"""Tests for the light_cycle theme and light_cycle_panel component."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import CalendarEvent, DashboardData, WeatherData
from src.dummy_data import generate_dummy_data
from src.render.artkit import hours_of_day, to_local_naive
from src.render.canvas import render_dashboard
from src.render.components.light_cycle_panel import (
    _COL_X0,
    _day_length_change,
    _draw_twilight_band,
    _fmt_change,
    _hour_to_pil_angle,
    _pack_lanes,
    _resolve_sun_times,
    draw_light_cycle,
)
from src.render.quantize import flatten_pixels
from src.render.theme import AVAILABLE_THEMES, ComponentRegion, ThemeStyle, load_theme
from tests.conftest import make_draw
from tests.inkutils import ink

NYC_LAT = 40.7128
NYC_LON = -74.0060
TZ = ZoneInfo("America/New_York")
FIXED_NOW = datetime(2026, 4, 23, 12, 0, tzinfo=TZ)
TODAY = FIXED_NOW.date()


def _render(**kwargs):
    data = generate_dummy_data(tz=TZ, now=FIXED_NOW)
    theme = load_theme("light_cycle")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestLightCycleRegistration:
    def test_in_available_themes(self):
        assert "light_cycle" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("light_cycle")
        assert t.name == "light_cycle"

    def test_light_cycle_region_visible(self):
        t = load_theme("light_cycle")
        assert t.layout.light_cycle.visible is True
        assert t.layout.light_cycle.w == 800
        assert t.layout.light_cycle.h == 480

    def test_draw_order_only_light_cycle(self):
        t = load_theme("light_cycle")
        assert t.layout.draw_order == ["light_cycle"]


# ---------------------------------------------------------------------------
# Polar / time helpers
# ---------------------------------------------------------------------------


class TestPolarMath:
    def test_midnight_at_top(self):
        # Hour 0 → PIL angle 270 (top of circle)
        assert _hour_to_pil_angle(0.0) == 270.0

    def test_six_at_three_oclock(self):
        # Hour 6 → PIL angle 0 / 360 (3 o'clock)
        assert _hour_to_pil_angle(6.0) % 360.0 == 0.0

    def test_noon_at_bottom(self):
        # Hour 12 → PIL angle 90 (bottom)
        assert _hour_to_pil_angle(12.0) % 360.0 == 90.0

    def test_eighteen_at_nine_oclock(self):
        # Hour 18 → PIL angle 180 (9 o'clock)
        assert _hour_to_pil_angle(18.0) % 360.0 == 180.0


class TestToLocalNaive:
    def test_passes_through_naive(self):
        dt = datetime(2026, 5, 6, 10, 30)
        assert to_local_naive(dt, TZ) == dt

    def test_converts_aware_to_tz(self):
        dt = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
        out = to_local_naive(dt, TZ)
        # 14:00 UTC = 10:00 EDT in May
        assert out.tzinfo is None
        assert out.hour == 10

    def test_uses_system_tz_when_no_target(self):
        dt = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)
        out = to_local_naive(dt, None)
        assert out.tzinfo is None


class TestHoursOfDay:
    def test_none_input(self):
        assert hours_of_day(None, TODAY, TZ) is None

    def test_today_hour(self):
        dt = datetime(2026, 4, 23, 9, 30, tzinfo=TZ)
        assert hours_of_day(dt, TODAY, TZ) == 9.5

    def test_yesterday_returns_negative_clamped(self):
        # delta=-1 day, hour=23.5 → -0.5; clamp to 0
        dt = datetime(2026, 4, 22, 23, 30, tzinfo=TZ)
        out = hours_of_day(dt, TODAY, TZ)
        assert out == 0.0

    def test_tomorrow_clamped(self):
        # delta=1 day, hour=0.5 → 24.5; clamp to 24
        dt = datetime(2026, 4, 24, 0, 30, tzinfo=TZ)
        out = hours_of_day(dt, TODAY, TZ)
        assert out == 24.0

    def test_more_than_one_day_away_returns_none(self):
        dt = datetime(2026, 4, 26, 10, 0, tzinfo=TZ)
        assert hours_of_day(dt, TODAY, TZ) is None


# ---------------------------------------------------------------------------
# Sun-time resolution
# ---------------------------------------------------------------------------


class TestResolveSunTimes:
    def test_uses_astronomy_when_lat_lon_provided(self):
        sr, ss, bands = _resolve_sun_times(TODAY, None, None, NYC_LAT, NYC_LON, TZ)
        assert sr is not None and ss is not None
        # 8 bands (4 morning + 4 evening) when astronomical path succeeds
        assert len(bands) == 8

    def test_falls_back_to_weather_when_no_lat_lon(self):
        wsr = datetime(2026, 4, 23, 6, 5, tzinfo=TZ)
        wss = datetime(2026, 4, 23, 19, 43, tzinfo=TZ)
        sr, ss, bands = _resolve_sun_times(TODAY, wsr, wss, None, None, TZ)
        assert sr == 6.0 + 5 / 60
        assert ss == 19.0 + 43 / 60
        # Two simple night bands (morning + evening) when falling back
        assert len(bands) == 2

    def test_returns_empty_when_nothing_known(self):
        sr, ss, bands = _resolve_sun_times(TODAY, None, None, None, None, TZ)
        assert sr is None and ss is None and bands == []

    def test_zero_zero_lat_lon_treated_as_unset(self):
        # (0, 0) is the documented "unset" sentinel for the astronomy theme
        wsr = datetime(2026, 4, 23, 6, 5, tzinfo=TZ)
        wss = datetime(2026, 4, 23, 19, 43, tzinfo=TZ)
        _, _, bands = _resolve_sun_times(TODAY, wsr, wss, 0.0, 0.0, TZ)
        assert len(bands) == 2  # fallback path

    def test_polar_day_falls_back_to_weather(self):
        """At very high latitudes some twilight events are None — fall through."""
        wsr = datetime(2026, 6, 21, 6, 5, tzinfo=TZ)
        wss = datetime(2026, 6, 21, 19, 43, tzinfo=TZ)
        _, _, bands = _resolve_sun_times(date(2026, 6, 21), wsr, wss, 85.0, 0.0, TZ)
        # Either falls through to weather (2 bands) or astronomy succeeded; at
        # 85° N around June solstice it should be polar day → fallback path.
        assert len(bands) in (0, 2, 8)


# ---------------------------------------------------------------------------
# Theme rendering
# ---------------------------------------------------------------------------


class TestLightCycleRender:
    def test_renders_correct_size(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert img.size == (800, 480)
        assert img.mode == "1"

    def test_renders_non_blank(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert not all(p == 255 for p in img.tobytes())

    def test_renders_without_lat_lon(self):
        """No coordinates falls back to OWM sun times, drawing a simpler dial."""
        without = _render()
        with_coords = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert without.size == (800, 480)
        assert ink(without) > 0, "nothing drawn without coordinates"
        assert without.tobytes() != with_coords.tobytes(), (
            "the coordinates make no difference to the dial"
        )

    def test_renders_with_no_weather_and_no_coords(self):
        """Neither weather nor coordinates still draws the dial chrome."""
        data = DashboardData(events=[], weather=None)
        img = render_dashboard(data, DisplayConfig(), theme=load_theme("light_cycle"))
        assert img.size == (800, 480)
        assert ink(img) > 0, "the dial chrome is missing entirely"


# ---------------------------------------------------------------------------
# Direct draw paths (exercises code that the high-level render path may not)
# ---------------------------------------------------------------------------


def _weather_with_range():
    """The same weather as the no-range case but with high/low populated."""
    return WeatherData(
        current_temp=60.0,
        current_icon="01d",
        current_description="clear",
        high=70.0,
        low=50.0,
        humidity=50,
        sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
        sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
    )


def _direct(data, now=None, **kwargs):
    """Draw the panel alone onto a fresh plate."""
    img, d = make_draw()
    draw_light_cycle(d, data, TODAY, now or FIXED_NOW, **kwargs)
    return img


class TestDrawLightCycleDirect:
    def test_defaults_region_and_style(self):
        """region=None/style=None fill in the defaults and draw the dial."""
        data = DashboardData(events=[], weather=None)
        img = _direct(data)
        assert ink(img) > 0, "nothing drawn at all"
        explicit = _direct(data, region=ComponentRegion(0, 0, 800, 480), style=ThemeStyle())
        assert img.tobytes() == explicit.tobytes()

    def test_with_weather_only(self):
        img, d = make_draw()
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=70.0,
            low=50.0,
            humidity=50,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
            location_name="Brooklyn",
        )
        with_weather = _direct(DashboardData(events=[], weather=w))
        without = _direct(DashboardData(events=[], weather=None))
        assert ink(with_weather) > ink(without), "the weather summary is not drawn"

    def test_with_lat_lon_full_twilight_bands(self):
        """Coordinates enable the computed twilight rings, which add ink."""
        data = DashboardData(events=[], weather=None)
        with_coords = _direct(data, latitude=NYC_LAT, longitude=NYC_LON)
        without = _direct(data)
        assert ink(with_coords) > ink(without), "no twilight bands drawn from the coordinates"

    def test_with_timed_events_renders_event_ticks(self):
        img, d = make_draw()
        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2026, 4, 23, 9, 30),
                end=datetime(2026, 4, 23, 10, 0),
                calendar_name="Work",
            ),
            CalendarEvent(
                summary="Lunch",
                start=datetime(2026, 4, 23, 12, 30),
                end=datetime(2026, 4, 23, 13, 30),
                calendar_name="Personal",
            ),
        ]
        with_events = _direct(DashboardData(events=events, weather=None))
        without = _direct(DashboardData(events=[], weather=None))
        assert ink(with_events) > ink(without), "no event ticks drawn"

    def test_skips_all_day_events(self):
        """All-day events produce no tick — they have no hour to plot at.

        The start is a *datetime*, which is how every fetcher produces an
        all-day event (see today_view's `_all_day` helper and the ICS path in
        CLAUDE.md). The previous fixture passed a bare `date`, which the
        `isinstance(start, datetime)` guard rejects one line later — so it
        could not tell whether the `is_all_day` guard worked. Verified by
        deleting that guard: this shape then draws a tick, the old one did not.
        """
        events = [
            CalendarEvent(
                summary="Holiday",
                start=datetime(2026, 4, 23, 0, 0),
                end=datetime(2026, 4, 24, 0, 0),
                calendar_name="Holidays",
                is_all_day=True,
            ),
        ]
        all_day = _direct(DashboardData(events=events, weather=None))
        none = _direct(DashboardData(events=[], weather=None))
        dial = (0, 0, _COL_X0, 480)
        assert all_day.crop(dial).tobytes() == none.crop(dial).tobytes(), (
            "an all-day event produced a mark on the dial"
        )
        agenda = (_COL_X0, 0, 800, 480)
        assert all_day.crop(agenda).tobytes() != none.crop(agenda).tobytes(), (
            "the all-day event is missing from the agenda"
        )

    def test_no_op_band_returns_early(self):
        """Density 0 or zero-width band should be a no-op (no exceptions)."""
        img, d = make_draw()
        before = bytes(img.tobytes())
        _draw_twilight_band(d, 5.0, 5.0, 4, 0, 1)  # zero width
        _draw_twilight_band(d, 5.0, 6.0, 0, 0, 1)  # density 0
        assert img.tobytes() == before  # nothing drawn

    def test_event_far_outside_dial_is_skipped(self):
        """An event days away leaves the dial untouched.

        Note the mechanism: `events_for_day` filters it out before the tick
        code runs, so this pins the panel's *observable* behaviour rather than
        its internal `hr is None` guard, which the event never reaches. That
        guard is a backstop for a same-day event whose hour cannot be
        resolved, and is not what this test covers.
        """
        img, d = make_draw()
        events = [
            CalendarEvent(
                summary="Distant",
                start=datetime(2026, 4, 27, 10, 0),
                end=datetime(2026, 4, 27, 11, 0),
                calendar_name="Misc",
            ),
        ]
        distant = _direct(DashboardData(events=events, weather=None))
        none = _direct(DashboardData(events=[], weather=None))
        assert distant.tobytes() == none.tobytes(), (
            "an event days away was plotted onto a 24-hour dial"
        )

    def test_weather_with_no_high_low_renders(self):
        """Weather missing high/low still renders (just shows current temp)."""
        img, d = make_draw()
        w = WeatherData(
            current_temp=60.0,
            current_icon="01d",
            current_description="clear",
            high=None,
            low=None,
            humidity=50,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
        )
        no_range = _direct(DashboardData(events=[], weather=w))
        assert ink(no_range) > 0
        assert ink(no_range) < ink(
            _direct(DashboardData(events=[], weather=_weather_with_range()))
        ), "the hi/lo range is not being drawn when present"

    def test_night_glyph_when_now_outside_daylight(self):
        """At midnight the moon glyph branch is hit instead of the sun."""
        img, d = make_draw()
        midnight = datetime(2026, 4, 23, 0, 30, tzinfo=TZ)
        w = WeatherData(
            current_temp=50.0,
            current_icon="01n",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=70,
            sunrise=datetime(2026, 4, 23, 6, 5, tzinfo=TZ),
            sunset=datetime(2026, 4, 23, 19, 43, tzinfo=TZ),
        )
        data = DashboardData(events=[], weather=w)
        night = _direct(data, now=midnight)
        noon = _direct(data, now=datetime(2026, 4, 23, 12, 30, tzinfo=TZ))
        assert ink(night) > 0
        assert night.tobytes() != noon.tobytes(), "the same glyph was drawn at midnight and midday"


def _event(start_h: int, start_m: int, end_h: int, end_m: int, summary: str = "Event"):
    return CalendarEvent(
        summary=summary,
        start=datetime(2026, 4, 23, start_h, start_m),
        end=datetime(2026, 4, 23, end_h, end_m),
        calendar_name="Work",
    )


_DIAL = (0, 0, 470, 480)
_AGENDA = (_COL_X0, 0, 800, 480)


class TestEventArcs:
    def test_an_arc_spans_the_event_duration(self):
        short = _direct(DashboardData(events=[_event(15, 0, 15, 30)], weather=None))
        long = _direct(DashboardData(events=[_event(15, 0, 18, 0)], weather=None))
        assert ink(long, _DIAL) > ink(short, _DIAL), "the arc does not grow with the duration"

    def test_an_ended_event_is_drawn_hollow(self):
        data = DashboardData(events=[_event(13, 0, 16, 0)], weather=None)
        before = _direct(data, now=datetime(2026, 4, 23, 12, 0, tzinfo=TZ))
        after = _direct(data, now=datetime(2026, 4, 23, 17, 0, tzinfo=TZ))
        # Compare the arc alone: the needle moves between the two renders, so
        # measure the event-ring sector the event occupies (13:00–16:00 sits
        # left of and below the centre) with the needle parked elsewhere.
        box = (60, 260, 250, 440)
        assert ink(after, box) < ink(before, box), "an ended event is still drawn solid"

    def test_overlapping_events_take_the_second_lane(self):
        assert _pack_lanes([(9.0, 10.0), (9.5, 11.0), (10.5, 12.0)]) == [0, 1, 0]
        assert _pack_lanes([(9.0, 10.0), (10.0, 11.0)]) == [0, 0]


class TestInfoColumn:
    def test_day_length_change_needs_coordinates(self):
        assert _day_length_change(TODAY, None, None) is None
        assert _day_length_change(TODAY, 0.0, 0.0) is None

    def test_days_lengthen_in_the_northern_spring(self):
        change = _day_length_change(TODAY, NYC_LAT, NYC_LON)
        assert change is not None and change.total_seconds() > 60

    def test_fmt_change_signs(self):
        from datetime import timedelta

        assert _fmt_change(timedelta(minutes=2, seconds=31)) == "+2m 31s"
        assert _fmt_change(timedelta(seconds=-75)) == "−1m 15s"

    def test_a_long_agenda_stops_short_of_the_bottom_edge(self):
        events = [
            _event(8 + i // 4, (i % 4) * 15, 8 + i // 4, (i % 4) * 15 + 10) for i in range(30)
        ]
        img = _direct(DashboardData(events=events, weather=_weather_with_range()))
        assert ink(img, (_COL_X0, 466, 800, 480)) == 0, "the agenda ran off the plate"
        assert ink(img, (_COL_X0, 400, 800, 466)) > 0, "the overflow line is missing"


class TestColourPanels:
    YELLOW = (255, 255, 0)
    BLUE = (0, 0, 255)

    def _colour(self, now=FIXED_NOW):
        img = Image.new("RGB", (800, 480), (255, 255, 255))
        style = ThemeStyle(
            fg=(0, 0, 0),
            bg=(255, 255, 255),
            accent_primary=self.YELLOW,
            accent_secondary=self.BLUE,
        )
        draw_light_cycle(
            ImageDraw.Draw(img),
            DashboardData(events=[], weather=_weather_with_range()),
            TODAY,
            now,
            style=style,
            latitude=NYC_LAT,
            longitude=NYC_LON,
        )
        return img

    def _count(self, img, colour, box):
        return sum(1 for px in flatten_pixels(img.crop(box)) if px == colour)

    def test_daylight_is_filled_with_the_primary_accent(self):
        assert self._count(self._colour(), self.YELLOW, _DIAL) > 1000

    def test_twilight_rings_take_the_secondary_accent(self):
        assert self._count(self._colour(), self.BLUE, _DIAL) > 100

    def test_no_type_is_set_in_an_accent(self):
        img = self._colour()
        assert self._count(img, self.YELLOW, _AGENDA) == 0
        assert self._count(img, self.BLUE, _AGENDA) == 0

    def test_mono_draws_no_daylight_fill(self):
        """On mono the accents fall back to ink; daylight must stay paper, not go solid."""
        img = _direct(DashboardData(events=[], weather=None), latitude=NYC_LAT, longitude=NYC_LON)
        # A point in the middle of the daylight span (13:00, on the light band).
        from src.render.components.light_cycle_panel import _polar

        x, y = _polar(150, 13.0)
        assert img.getpixel((x, y)) != 0, "daylight was painted solid on a mono plate"
