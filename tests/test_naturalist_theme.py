"""Tests for the naturalist theme and naturalist_panel component."""

from __future__ import annotations

from datetime import date, datetime, timedelta

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
from src.render.components.naturalist_panel import (
    _feature_points,
    _fmt_time,
    _latin_name,
    _next_event_today,
    _plate_number,
    _roman,
    _season,
    _weather_modifier,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()


def _render(**kwargs):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("naturalist")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestNaturalistRegistration:
    def test_in_available_themes(self):
        assert "naturalist" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("naturalist")
        assert t.name == "naturalist"

    def test_region_visible(self):
        t = load_theme("naturalist")
        assert t.layout.naturalist.visible is True
        assert t.layout.naturalist.w == 800
        assert t.layout.naturalist.h == 480

    def test_draw_order_only_naturalist(self):
        t = load_theme("naturalist")
        assert t.layout.draw_order == ["naturalist"]

    def test_uses_floyd_steinberg_quantization(self):
        t = load_theme("naturalist")
        assert t.layout.canvas_mode == "L"
        assert t.layout.preferred_quantization_mode == "floyd_steinberg"

    def test_color_on_inky(self):
        t = load_theme("naturalist")
        assert t.layout.prefer_color_on_inky is True


# ---------------------------------------------------------------------------
# Season + modifier classification
# ---------------------------------------------------------------------------


class TestSeason:
    @pytest.mark.parametrize(
        "month,season",
        [
            (1, "winter"),
            (2, "winter"),
            (3, "spring"),
            (5, "spring"),
            (6, "summer"),
            (8, "summer"),
            (9, "autumn"),
            (11, "autumn"),
            (12, "winter"),
        ],
    )
    def test_returns_meteorological_season(self, month, season):
        assert _season(date(2026, month, 15)) == season


class TestWeatherModifier:
    @pytest.mark.parametrize(
        "icon,temp,modifier",
        [
            ("10d", 50.0, "rain"),
            ("09n", 50.0, "rain"),
            ("11d", 50.0, "storm"),
            ("13d", 28.0, "snow"),
            ("50d", 50.0, "fog"),
            ("01d", 20.0, "frost"),  # clear + freezing → frost
            ("01d", 50.0, "neutral"),
            ("02d", 50.0, "neutral"),
            (None, None, "neutral"),
        ],
    )
    def test_maps_conditions(self, icon, temp, modifier):
        assert _weather_modifier(icon, temp) == modifier


class TestLatinName:
    def test_summer_neutral(self):
        assert _latin_name("summer", "neutral").startswith("QUERCUS")
        assert "AESTIVALIS" in _latin_name("summer", "neutral")

    def test_winter_snow_appends_suffix(self):
        n = _latin_name("winter", "snow")
        assert "HIBERNALIS" in n
        assert "sub nive" in n

    def test_storm_suffix(self):
        n = _latin_name("summer", "storm")
        assert "sub fulmine" in n


class TestRoman:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (1, "I"),
            (4, "IV"),
            (9, "IX"),
            (40, "XL"),
            (1994, "MCMXCIV"),
            (2026, "MMXXVI"),
        ],
    )
    def test_known_values(self, n, expected):
        assert _roman(n) == expected


class TestPlateNumber:
    def test_returns_roman_string(self):
        s = _plate_number(date(2026, 1, 1))
        # Day-of-year = 1 → "I"
        assert s == "I"

    def test_advances_across_year(self):
        a = _plate_number(date(2026, 1, 1))
        b = _plate_number(date(2026, 6, 1))
        assert a != b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestFmtTime:
    def test_on_the_hour(self):
        assert _fmt_time(datetime(2026, 4, 6, 9, 0)) == "9a"

    def test_with_minutes(self):
        assert _fmt_time(datetime(2026, 4, 6, 14, 30)) == "2:30p"


class TestNextEventToday:
    def test_none_when_empty(self):
        assert _next_event_today([], TODAY, FIXED_NOW) is None

    def test_returns_active_event(self):
        ev = CalendarEvent("Active", datetime(2026, 4, 6, 10, 0), datetime(2026, 4, 6, 11, 0))
        out = _next_event_today([ev], TODAY, FIXED_NOW)
        assert out is not None and out.summary == "Active"

    def test_skips_all_day_for_event_pick(self):
        # All-day still counted when no timed events exist.
        ev = CalendarEvent(
            "Holiday",
            datetime(2026, 4, 6),
            datetime(2026, 4, 7),
            is_all_day=True,
        )
        out = _next_event_today([ev], TODAY, FIXED_NOW)
        # The function only returns timed events as "next", but if there are
        # no timed events it falls back to the first today's event (which can
        # be an all-day).
        assert out is not None

    def test_picks_first_not_yet_ended(self):
        past = CalendarEvent("Done", datetime(2026, 4, 6, 8), datetime(2026, 4, 6, 9))
        future = CalendarEvent("Next", datetime(2026, 4, 6, 13), datetime(2026, 4, 6, 14))
        out = _next_event_today([past, future], TODAY, FIXED_NOW)
        assert out is not None and out.summary == "Next"


class TestFeaturePoints:
    def test_returns_all_four_anchors(self):
        pts = _feature_points()
        assert set(pts.keys()) == {"leaf_top", "node_mid", "branch_low", "root"}
        for key, (x, y) in pts.items():
            assert isinstance(x, int) and isinstance(y, int)


# ---------------------------------------------------------------------------
# Smoke tests for each season + weather modifier
# ---------------------------------------------------------------------------


def _data_for(today: date, *, icon: str = "01d", temp: float = 50.0) -> DashboardData:
    weather = WeatherData(
        current_temp=temp,
        current_icon=icon,
        current_description="condition",
        high=temp + 10,
        low=temp - 10,
        humidity=50,
        forecast=[],
        sunrise=datetime.combine(today, datetime.min.time().replace(hour=6, minute=24)),
        sunset=datetime.combine(today, datetime.min.time().replace(hour=19, minute=51)),
        location_name="Testville",
    )
    return DashboardData(
        events=[
            CalendarEvent(
                "Morning",
                datetime.combine(today, datetime.min.time().replace(hour=9)),
                datetime.combine(today, datetime.min.time().replace(hour=10)),
            ),
        ],
        weather=weather,
        birthdays=[Birthday(name="Test", date=today + timedelta(days=14))],
        air_quality=None,
        host_data=None,
        fetched_at=datetime.combine(today, datetime.min.time().replace(hour=10, minute=30)),
    )


class TestRenderEachSeason:
    @pytest.mark.parametrize(
        "today_str",
        [
            "2026-01-15",  # winter
            "2026-04-15",  # spring
            "2026-07-15",  # summer
            "2026-10-15",  # autumn
        ],
    )
    def test_renders_without_crash(self, today_str):
        today = date.fromisoformat(today_str)
        data = _data_for(today)
        theme = load_theme("naturalist")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.mode == "1"
        assert img.size == (800, 480)
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 3000, f"{today_str} produced an unusually empty plate ({ones} ink pixels)"


class TestRenderEachWeatherModifier:
    @pytest.mark.parametrize(
        "icon,temp",
        [
            ("01d", 20.0),  # frost
            ("01d", 50.0),  # neutral
            ("10d", 60.0),  # rain
            ("11d", 60.0),  # storm
            ("13d", 28.0),  # snow
            ("50d", 50.0),  # fog
        ],
    )
    def test_renders_without_crash(self, icon, temp):
        data = _data_for(TODAY, icon=icon, temp=temp)
        theme = load_theme("naturalist")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 3000


class TestRenderInkyPath:
    def test_rgb_canvas_does_not_crash(self):
        from dataclasses import replace

        data = _data_for(TODAY)
        theme = load_theme("naturalist")
        cfg = DisplayConfig()
        cfg = replace(cfg, provider="inky", model="impression_7_3_2025", width=800, height=480)
        img = render_dashboard(data, cfg, theme=theme)
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
        theme = load_theme("naturalist")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        assert img.size == (800, 480)


class TestEmptyEventsRendersCallout:
    def test_no_events_shows_placeholder(self):
        data = DashboardData(
            events=[],
            weather=_data_for(TODAY).weather,
            birthdays=[],
            air_quality=None,
            host_data=None,
            fetched_at=FIXED_NOW,
        )
        theme = load_theme("naturalist")
        img = render_dashboard(data, DisplayConfig(), theme=theme)
        # No crash; some ink rendered for the four FIG callouts.
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 3000


class TestRenderWithDummyData:
    def test_pixel_count_non_trivial(self):
        img = _render()
        ones = sum(1 for p in img.getdata() if not p)
        assert ones > 8000


# ---------------------------------------------------------------------------
# Specimen frame must contain meaningful ink (the branch + leaves)
# ---------------------------------------------------------------------------


class TestSpecimenInkCoverage:
    """The branch + leaves must paint a meaningful amount of ink into the
    specimen frame area for each season.  This guards against silent no-ops
    where the branch generator misbehaves but the rest of the plate renders."""

    def _count_in(self, img, x_range=(40, 430), y_range=(94, 388)):
        x0, x1 = x_range
        y0, y1 = y_range
        return sum(1 for y in range(y0, y1) for x in range(x0, x1) if not img.getpixel((x, y)))

    def test_summer_has_more_ink_than_winter(self):
        """Summer canopy is much fuller than winter bare branches."""
        summer = render_dashboard(
            _data_for(date(2026, 7, 15)),
            DisplayConfig(),
            theme=load_theme("naturalist"),
        )
        winter = render_dashboard(
            _data_for(date(2026, 1, 15)),
            DisplayConfig(),
            theme=load_theme("naturalist"),
        )
        s = self._count_in(summer)
        w = self._count_in(winter)
        # The summer canopy must paint at least somewhat more ink than winter,
        # which has only the trunk + a few branches.
        assert s > w + 1000, f"summer ({s} ink) should clearly dominate winter ({w} ink)"
