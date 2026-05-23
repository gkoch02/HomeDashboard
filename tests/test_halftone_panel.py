"""Tests for the halftone theme and halftone_panel component."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
from src.render.components.halftone_panel import (
    _illustration_kind,
    _moon_disc,
    _next_event_line,
    _radial_gradient_disc,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()


def _render(**kwargs):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("halftone")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestHalftoneRegistration:
    def test_in_available_themes(self):
        assert "halftone" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("halftone")
        assert t.name == "halftone"

    def test_halftone_region_visible(self):
        t = load_theme("halftone")
        assert t.layout.halftone.visible is True
        assert t.layout.halftone.w == 800
        assert t.layout.halftone.h == 480

    def test_draw_order_only_halftone(self):
        t = load_theme("halftone")
        assert t.layout.draw_order == ["halftone"]

    def test_uses_floyd_steinberg_quantization(self):
        t = load_theme("halftone")
        assert t.layout.canvas_mode == "L"
        assert t.layout.preferred_quantization_mode == "floyd_steinberg"

    def test_color_on_inky(self):
        t = load_theme("halftone")
        assert t.layout.prefer_color_on_inky is True


# ---------------------------------------------------------------------------
# Illustration dispatch
# ---------------------------------------------------------------------------


class TestIllustrationKind:
    @pytest.mark.parametrize(
        "icon,expected",
        [
            ("01d", "sun"),
            ("01n", "moon"),
            ("02d", "partly_cloudy"),
            ("02n", "partly_cloudy"),
            ("03d", "partly_cloudy"),
            ("04d", "overcast"),
            ("09d", "rain"),
            ("10d", "rain"),
            ("10n", "rain"),
            ("11d", "storm"),
            ("13d", "snow"),
            ("50d", "fog"),
            (None, "missing"),
            ("", "missing"),
            ("zz", "missing"),
        ],
    )
    def test_maps_icon_to_kind(self, icon, expected):
        assert _illustration_kind(icon) == expected


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestRadialGradientDisc:
    def test_centre_is_brightest(self):
        disc = _radial_gradient_disc(41, inner_v=255, outer_v=100)
        # Centre pixel should equal inner_v.
        cv, ca = disc.getpixel((20, 20))
        assert cv == 255
        assert ca == 255

    def test_outside_alpha_zero(self):
        disc = _radial_gradient_disc(41, inner_v=255, outer_v=100)
        _v, a = disc.getpixel((0, 0))
        assert a == 0

    def test_returns_LA_mode(self):
        disc = _radial_gradient_disc(21, inner_v=200, outer_v=50)
        assert disc.mode == "LA"


class TestMoonDisc:
    def test_new_moon_is_all_dark(self):
        disc = _moon_disc(41, illumination_pct=0.0, waxing=True)
        # Centre pixel must be in the dark range (~70) for a new moon.
        cv, ca = disc.getpixel((20, 20))
        assert ca == 255
        assert cv < 100

    def test_full_moon_is_all_lit(self):
        disc = _moon_disc(41, illumination_pct=100.0, waxing=True)
        cv, ca = disc.getpixel((20, 20))
        assert ca == 255
        assert cv > 230

    def test_half_moon_has_both_extremes(self):
        disc = _moon_disc(81, illumination_pct=50.0, waxing=True)
        lit_pixels = [disc.getpixel((x, 40))[0] for x in range(20, 60)]
        # Should contain a wide range from dark to bright.
        assert min(lit_pixels) < 100
        assert max(lit_pixels) > 200

    def test_waxing_lights_right_limb(self):
        disc = _moon_disc(81, illumination_pct=50.0, waxing=True)
        left = disc.getpixel((25, 40))[0]
        right = disc.getpixel((55, 40))[0]
        assert right > left

    def test_waning_lights_left_limb(self):
        disc = _moon_disc(81, illumination_pct=50.0, waxing=False)
        left = disc.getpixel((25, 40))[0]
        right = disc.getpixel((55, 40))[0]
        assert left > right


class TestNextEventLine:
    def test_returns_none_when_empty(self):
        assert _next_event_line([], datetime(2026, 4, 6, 10, 0)) is None

    def test_skips_all_day(self):
        ev = CalendarEvent(
            summary="Holiday",
            start=datetime(2026, 4, 6),
            end=datetime(2026, 4, 7),
            is_all_day=True,
        )
        assert _next_event_line([ev], datetime(2026, 4, 6, 10, 0)) is None

    def test_picks_soonest_future(self):
        now = datetime(2026, 4, 6, 10, 0)
        late = CalendarEvent("Late", datetime(2026, 4, 6, 17, 0), datetime(2026, 4, 6, 18, 0))
        soon = CalendarEvent("Soon", datetime(2026, 4, 6, 11, 0), datetime(2026, 4, 6, 12, 0))
        line = _next_event_line([late, soon], now)
        assert line is not None
        assert "Soon" in line
        assert "Late" not in line

    def test_ignores_past_events(self):
        now = datetime(2026, 4, 6, 10, 0)
        past = CalendarEvent("Past", datetime(2026, 4, 6, 8, 0), datetime(2026, 4, 6, 9, 0))
        future = CalendarEvent("Future", datetime(2026, 4, 6, 13, 0), datetime(2026, 4, 6, 14, 0))
        line = _next_event_line([past, future], now)
        assert line is not None
        assert "Future" in line

    def test_handles_aware_now_and_naive_event(self):
        now = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)
        ev = CalendarEvent("X", datetime(2026, 4, 6, 13, 0), datetime(2026, 4, 6, 14, 0))
        line = _next_event_line([ev], now)
        assert line is not None and "X" in line


# ---------------------------------------------------------------------------
# Smoke tests for each illustration branch
# ---------------------------------------------------------------------------


def _data_with_icon(icon: str | None) -> DashboardData:
    """Build a minimal DashboardData with a single weather icon code."""
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
        events=[],
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
        theme = load_theme("halftone")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # Image is 1-bit after Waveshare quantization.
        assert img.mode == "1"
        assert img.size == (800, 480)
        # Some ink must be present (no fully-white render).
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 1000, f"icon {icon!r} produced an empty render"


class TestRenderInkyPath:
    def test_rgb_canvas_does_not_crash(self):
        """Render with the Inky-color path active (RGB canvas)."""
        from dataclasses import replace

        data = _data_with_icon("01d")
        theme = load_theme("halftone")
        cfg = DisplayConfig()
        cfg = replace(cfg, provider="inky", model="impression_7_3_2025", width=800, height=480)
        img = render_dashboard(data, cfg, theme=theme)
        # Inky path renders RGB and does not pre-quantize.
        assert img.mode == "RGB"
        assert img.size == (800, 480)


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
        theme = load_theme("halftone")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


class TestRenderWithDummyData:
    def test_pixel_count_non_trivial(self):
        img = _render()
        assert img.size == (800, 480)
        # Floyd-Steinberg of a procedural greyscale plate should produce
        # tens of thousands of ink pixels.
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 10_000
