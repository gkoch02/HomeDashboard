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
        "icon,kind,is_night",
        [
            ("01d", "sun", False),
            ("01n", "moon", True),
            ("02d", "partly_cloudy", False),
            ("02n", "partly_cloudy", True),
            ("03d", "partly_cloudy", False),
            ("04d", "overcast", False),
            ("09d", "rain", False),
            ("10d", "rain", False),
            ("10n", "rain", True),
            ("11d", "storm", False),
            ("13d", "snow", False),
            ("50d", "fog", False),
            (None, "missing", False),
            ("", "missing", False),
            ("zz", "missing", False),
        ],
    )
    def test_maps_icon_to_kind(self, icon, kind, is_night):
        assert _illustration_kind(icon) == (kind, is_night)


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


class TestNoNextEventLayout:
    """The margin band collapses from 3 rows to 2 (rule re-centred) when
    there is no upcoming non-all-day event to show."""

    def _render_with_events(self, events: list[CalendarEvent]):
        data = generate_dummy_data(now=FIXED_NOW)
        data.events = events
        theme = load_theme("halftone")
        return render_dashboard(data, DisplayConfig(), theme=theme)

    def _band_ink_by_row(self, img):
        """Sum dark pixels in each y-row across the right-text column.

        Returns a list of ink counts indexed by y, restricted to the
        margin band's right-column horizontal range (post-temperature).
        """
        x_lo, x_hi = 320, 770
        y_lo, y_hi = 302, 480  # margin band (after HERO_H + RULE_H = 302)
        return [
            sum(1 for x in range(x_lo, x_hi) if not img.getpixel((x, y)))
            for y in range(y_lo, y_hi)
        ]

    def test_no_next_event_centres_rule(self):
        """With no upcoming event the hairline rule sits near the band's
        vertical centre, splitting NOW and TODAY into two equal zones."""
        img = self._render_with_events([])
        rows = self._band_ink_by_row(img)
        # Margin band starts at y=302, height ≈ 178. Vertical centre ≈ 391.
        # The rule is the brightest single row in the right-column band
        # (its dotted hairline lights up many pixels). Pick the densest
        # row in a ±25 px window around the expected centre.
        band_top = 302
        centre = 391
        window = range(centre - 25 - band_top, centre + 25 - band_top)
        densest_idx = max(window, key=lambda i: rows[i])
        densest_y = band_top + densest_idx
        assert abs(densest_y - centre) <= 12, (
            f"expected rule near y={centre}, found densest row at y={densest_y}"
        )

    def test_with_next_event_rule_is_one_third(self):
        """With an upcoming event the rule sits ~1/3 down the band so
        the lower two zones (TODAY + NEXT) split the remaining height."""
        future = CalendarEvent(
            summary="Standup",
            start=FIXED_NOW + timedelta(hours=2),
            end=FIXED_NOW + timedelta(hours=3),
            is_all_day=False,
            calendar_name="work",
        )
        img = self._render_with_events([future])
        rows = self._band_ink_by_row(img)
        # Margin band y=302..480, height=178. One-third ≈ y=361.
        band_top = 302
        centre = 361
        window = range(centre - 25 - band_top, centre + 25 - band_top)
        densest_idx = max(window, key=lambda i: rows[i])
        densest_y = band_top + densest_idx
        assert abs(densest_y - centre) <= 12, (
            f"expected rule near y={centre}, found densest row at y={densest_y}"
        )


def _hero_ink_count(img, *, x_range=(0, 800), y_range=(0, 280)) -> int:
    """Count black-ink pixels in the given hero-region rectangle of a 1-bit image."""
    x0, x1 = x_range
    y0, y1 = y_range
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if not img.getpixel((x, y)))


class TestIllustrationInkCoverage:
    """Each illustration kind must paint a meaningful amount of ink into the hero.

    These guards catch silent regressions where an illustration helper
    no-ops or paints solid white (which would still pass the render-doesn't-crash
    smoke tests above).
    """

    def _render_with_icon(self, icon: str):
        data = _data_with_icon(icon)
        theme = load_theme("halftone")
        return render_dashboard(data, DisplayConfig(), theme=theme)

    def test_fog_covers_entire_hero(self):
        img = self._render_with_icon("50d")
        # The fog bands span the full width; sample five columns and confirm
        # every one of them has substantial ink (the halftone of the grey
        # bands).
        for x in (40, 200, 400, 600, 760):
            col_ink = sum(1 for y in range(20, 280) if not img.getpixel((x, y)))
            assert col_ink > 30, f"fog column at x={x} only has {col_ink} ink pixels"

    def test_lightning_produces_dark_center(self):
        img = self._render_with_icon("11d")
        # The lightning bolt is solid ink in a narrow vertical strip near the
        # hero centre. Compare ink density inside that strip versus an equally
        # wide strip well to one side.
        centre = _hero_ink_count(img, x_range=(380, 430), y_range=(120, 280))
        side = _hero_ink_count(img, x_range=(80, 130), y_range=(120, 280))
        assert centre > side, (
            f"lightning strip ({centre}) should hold more ink than the "
            f"adjacent stormy-sky strip ({side})"
        )

    def test_overcast_renders_three_clouds(self):
        img = self._render_with_icon("04d")
        # Three layered clouds should leave ink across left, centre, and right
        # thirds of the hero (none of them empty).
        left = _hero_ink_count(img, x_range=(60, 260), y_range=(40, 250))
        centre = _hero_ink_count(img, x_range=(300, 500), y_range=(40, 250))
        right = _hero_ink_count(img, x_range=(540, 740), y_range=(40, 250))
        assert left > 500
        assert centre > 500
        assert right > 500


class TestRenderWithDummyData:
    def test_pixel_count_non_trivial(self):
        img = _render()
        assert img.size == (800, 480)
        # Floyd-Steinberg of a procedural greyscale plate should produce
        # tens of thousands of ink pixels.
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 10_000
