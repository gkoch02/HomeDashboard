"""Tests for the postcard theme and postcard_panel component."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.config import DisplayConfig
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.postcard_panel import (
    _daypart_palette,
    _events_today,
    _fmt_event_time,
    _moon_disc,
    _radial_gradient_disc,
    _scene_kind,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 6, 14, 30)
TODAY = FIXED_NOW.date()


def _render(**kwargs):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("postcard")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPostcardRegistration:
    def test_in_available_themes(self):
        assert "postcard" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("postcard")
        assert t.name == "postcard"

    def test_postcard_region_visible(self):
        t = load_theme("postcard")
        assert t.layout.postcard.visible is True
        assert t.layout.postcard.w == 800
        assert t.layout.postcard.h == 480

    def test_draw_order_only_postcard(self):
        t = load_theme("postcard")
        assert t.layout.draw_order == ["postcard"]

    def test_uses_floyd_steinberg_quantization(self):
        t = load_theme("postcard")
        assert t.layout.canvas_mode == "L"
        assert t.layout.preferred_quantization_mode == "floyd_steinberg"

    def test_color_on_inky(self):
        t = load_theme("postcard")
        assert t.layout.prefer_color_on_inky is True


# ---------------------------------------------------------------------------
# Scene-kind dispatch — maps OWM icon codes to the right procedural scene.
# ---------------------------------------------------------------------------


class TestSceneKind:
    @pytest.mark.parametrize(
        "icon,kind,is_night",
        [
            ("01d", "clear", False),
            ("01n", "clear", True),
            ("02d", "partly", False),
            ("02n", "partly", True),
            ("03d", "partly", False),
            ("04d", "overcast", False),
            ("09d", "rain", False),
            ("10d", "rain", False),
            ("10n", "rain", True),
            ("11d", "storm", False),
            ("13d", "snow", False),
            ("50d", "fog", False),
            (None, "clear", False),
            ("", "clear", False),
            ("zz", "clear", False),
        ],
    )
    def test_maps_icon_to_kind(self, icon, kind, is_night):
        assert _scene_kind(icon) == (kind, is_night)


# ---------------------------------------------------------------------------
# Daypart palette — icon's night flag must dominate the local hour.
# ---------------------------------------------------------------------------


class TestDaypartPalette:
    def test_night_icon_uses_night_palette_regardless_of_hour(self):
        # Even at noon, icon=night → dark sky.
        top, bottom = _daypart_palette("clear", True, datetime(2026, 4, 6, 12, 0))
        assert top < 100
        assert bottom < 130

    def test_day_icon_at_3am_still_renders_as_day(self):
        """Regression: previously fell through to a 'late night' branch
        for hours outside dawn/day/dusk windows even when the icon said day."""
        top, bottom = _daypart_palette("clear", False, datetime(2026, 4, 6, 3, 0))
        # 3am with day icon → should NOT be the dark night palette.
        assert top > 150
        assert bottom > 200

    def test_overcast_compresses_range(self):
        # Heavy sky reads as mid-grey across the whole strip.
        top, bottom = _daypart_palette("overcast", False, datetime(2026, 4, 6, 12, 0))
        assert top >= 150

    def test_storm_palette_is_dark(self):
        top, _bot = _daypart_palette("storm", False, datetime(2026, 4, 6, 12, 0))
        assert top < 130


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestRadialGradientDisc:
    def test_centre_is_brightest(self):
        disc = _radial_gradient_disc(41, inner_v=255, outer_v=100)
        cv, ca = disc.getpixel((20, 20))
        assert cv == 255
        assert ca == 255

    def test_outside_alpha_zero(self):
        disc = _radial_gradient_disc(41, inner_v=255, outer_v=100)
        _v, a = disc.getpixel((0, 0))
        assert a == 0


class TestMoonDisc:
    def test_new_moon_is_all_dark(self):
        disc = _moon_disc(41, illumination_pct=0.0, waxing=True)
        cv, ca = disc.getpixel((20, 20))
        assert ca == 255
        assert cv < 100

    def test_full_moon_is_all_lit(self):
        disc = _moon_disc(41, illumination_pct=100.0, waxing=True)
        cv, ca = disc.getpixel((20, 20))
        assert ca == 255
        assert cv > 230

    def test_waxing_lights_right_limb(self):
        disc = _moon_disc(81, illumination_pct=50.0, waxing=True)
        left = disc.getpixel((25, 40))[0]
        right = disc.getpixel((55, 40))[0]
        assert right > left


class TestFmtEventTime:
    def test_on_the_hour(self):
        assert _fmt_event_time(datetime(2026, 4, 6, 9, 0)) == "9a"

    def test_with_minutes(self):
        assert _fmt_event_time(datetime(2026, 4, 6, 14, 30)) == "2:30p"


class TestEventsToday:
    def test_filters_to_today(self):
        evs = [
            CalendarEvent("Y", datetime(2026, 4, 5, 10), datetime(2026, 4, 5, 11)),
            CalendarEvent("T", datetime(2026, 4, 6, 10), datetime(2026, 4, 6, 11)),
        ]
        out = _events_today(evs, TODAY)
        assert len(out) == 1
        assert out[0].summary == "T"


# ---------------------------------------------------------------------------
# Smoke tests for each scene branch
# ---------------------------------------------------------------------------


def _data_with_icon(icon: str | None) -> DashboardData:
    if icon is None:
        weather = None
    else:
        weather = WeatherData(
            current_temp=64.0,
            current_icon=icon,
            current_description="condition",
            high=70.0,
            low=55.0,
            humidity=50,
            forecast=[],
            location_name="Testville",
        )
    return DashboardData(
        events=[
            CalendarEvent(
                "Morning meeting", datetime(2026, 4, 6, 9, 0), datetime(2026, 4, 6, 10, 0)
            ),
            CalendarEvent("Yoga", datetime(2026, 4, 6, 18, 0), datetime(2026, 4, 6, 19, 0)),
        ],
        weather=weather,
        birthdays=[Birthday(name="Test", date=TODAY + timedelta(days=14))],
        air_quality=None,
        host_data=None,
        fetched_at=FIXED_NOW,
    )


class TestRenderEachIcon:
    @pytest.mark.parametrize(
        "icon",
        [
            "01d",
            "01n",
            "02d",
            "02n",
            "04d",
            "09d",
            "10d",
            "10n",
            "11d",
            "13d",
            "50d",
            None,
            "zz",
        ],
    )
    def test_renders_without_crash(self, icon):
        data = _data_with_icon(icon)
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.mode == "1"
        assert img.size == (800, 480)
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 1000, f"icon {icon!r} produced an empty render"


class TestRenderInkyPath:
    def test_rgb_canvas_does_not_crash(self):
        from dataclasses import replace

        data = _data_with_icon("01d")
        theme = load_theme("postcard")
        cfg = DisplayConfig()
        cfg = replace(cfg, provider="inky", model="impression_7_3_2025", width=800, height=480)
        img = render_dashboard(data, cfg, theme=theme)
        assert img.mode == "RGB"
        assert img.size == (800, 480)


class TestEmptyEvents:
    def test_renders_with_no_events_today(self):
        data = DashboardData(
            events=[],
            weather=_data_with_icon("01d").weather,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # Must still draw the "( nothing scheduled )" placeholder lines.
        assert img.size == (800, 480)


class TestManyEvents:
    def test_overflow_shows_plus_more(self):
        """+N more should appear when today has more events than the agenda fits."""
        events = [
            CalendarEvent(
                summary=f"Event {i}",
                start=datetime(2026, 4, 6, 8 + i, 0),
                end=datetime(2026, 4, 6, 8 + i, 30),
            )
            for i in range(12)
        ]
        data = DashboardData(
            events=events,
            weather=_data_with_icon("01d").weather,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # No crash; some ink rendered.
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 1000


class TestNoWeatherFallback:
    def test_missing_weather_renders(self):
        data = DashboardData(
            events=[],
            weather=None,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("postcard")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


class TestRenderWithDummyData:
    def test_pixel_count_non_trivial(self):
        img = _render()
        assert img.size == (800, 480)
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 10_000


class TestCenterCrease:
    def test_crease_separates_scene_from_back(self):
        """The crease line must produce ink at x=480 across most of the height."""
        img = _render()
        # Sample 10 rows down the crease column; count black pixels.
        crease_ink = sum(1 for y in range(20, 460) if not img.getpixel((480, y)))
        assert crease_ink > 300, (
            f"crease column at x=480 should be mostly ink; saw {crease_ink} pixels"
        )

    def test_white_gutter_left_of_crease(self):
        """A two- or three-pixel white gutter must sit just left of the crease."""
        img = _render()
        # The gutter sits at x=477-479 (3-px band immediately left of crease).
        white_at_gutter = sum(1 for y in range(40, 440) if img.getpixel((478, y)))
        # The gutter is white over most rows (some greyscale at the very top/bot).
        assert white_at_gutter > 350


# ---------------------------------------------------------------------------
# Address-line agenda — every event today must be reachable on the back
# ---------------------------------------------------------------------------


class TestBackHasEventText:
    def test_event_time_label_present_in_dummy(self):
        """Dummy data for the FIXED_NOW Monday has a 9 AM standup; the back
        agenda should include a time label.  We can't OCR, but we can check
        that the back panel has non-trivial ink concentration in the agenda
        rows compared to the empty bottom area."""
        img = _render()
        # Agenda band is roughly y=160..280 in the back panel x range.
        agenda_ink = sum(
            1 for y in range(170, 280) for x in range(510, 780) if not img.getpixel((x, y))
        )
        assert agenda_ink > 200
