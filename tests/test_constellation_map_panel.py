"""Tests for the constellation_map theme + panel + star catalogue."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import DashboardData, WeatherData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.constellation_map_panel import (
    _alt_az_to_chart_xy,
    _is_dark_sky,
    _resolve_observation_time,
    _star_radius,
    _utc,
    draw_constellation_map,
)
from src.render.star_catalog import (
    CONSTELLATIONS,
    LABELED_STARS,
    STARS,
    STARS_BY_NAME,
)
from src.render.theme import AVAILABLE_THEMES, load_theme

NYC_LAT = 40.7128
NYC_LON = -74.0060
TZ = ZoneInfo("America/New_York")
# A clear winter night so Orion + Big Dipper are both up at NYC.
FIXED_NOW = datetime(2026, 1, 15, 22, 0, tzinfo=TZ)
TODAY = FIXED_NOW.date()


def _make_draw(w: int = 800, h: int = 480, mode: str = "L"):
    img = Image.new(mode, (w, h), 0)
    return img, ImageDraw.Draw(img)


def _render(**kwargs):
    data = generate_dummy_data(tz=TZ, now=FIXED_NOW)
    theme = load_theme("constellation_map")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


# ---------------------------------------------------------------------------
# Star catalogue integrity
# ---------------------------------------------------------------------------


class TestStarCatalogIntegrity:
    def test_all_stars_have_unique_names(self):
        names = [s.name for s in STARS]
        assert len(names) == len(set(names)), "duplicate star names"

    def test_stars_by_name_matches_list(self):
        assert set(STARS_BY_NAME) == {s.name for s in STARS}

    def test_ra_in_valid_range(self):
        for s in STARS:
            assert 0.0 <= s.ra < 24.0, f"{s.name} RA out of range"

    def test_dec_in_valid_range(self):
        for s in STARS:
            assert -90.0 <= s.dec <= 90.0, f"{s.name} Dec out of range"

    def test_magnitudes_are_naked_eye(self):
        """Bundled stars must all be visible to the unaided eye (mag ≤ 5)."""
        for s in STARS:
            assert s.mag <= 5.0, f"{s.name} too dim ({s.mag})"

    def test_constellation_segments_reference_known_stars(self):
        """Every line endpoint must exist in the catalogue."""
        for cname, segments in CONSTELLATIONS.items():
            for a, b in segments:
                assert a in STARS_BY_NAME, f"{cname}: unknown star {a}"
                assert b in STARS_BY_NAME, f"{cname}: unknown star {b}"

    def test_labeled_stars_are_in_catalogue(self):
        for name in LABELED_STARS:
            assert name in STARS_BY_NAME

    def test_polaris_is_close_to_pole(self):
        polaris = STARS_BY_NAME["Polaris"]
        assert polaris.dec > 89.0


# ---------------------------------------------------------------------------
# Theme registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_in_available_themes(self):
        assert "constellation_map" in AVAILABLE_THEMES

    def test_load_theme(self):
        t = load_theme("constellation_map")
        assert t.name == "constellation_map"

    def test_region_visible(self):
        t = load_theme("constellation_map")
        assert t.layout.constellation_map.visible is True

    def test_dark_canvas(self):
        """The night-sky theme must have a dark background."""
        t = load_theme("constellation_map")
        assert t.style.bg == 0
        assert t.style.fg == 255

    def test_canvas_mode_is_grayscale(self):
        t = load_theme("constellation_map")
        assert t.layout.canvas_mode == "L"

    def test_prefers_color_on_inky(self):
        t = load_theme("constellation_map")
        assert t.layout.prefer_color_on_inky is True


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------


class TestProjection:
    def test_below_horizon_returns_none(self):
        assert _alt_az_to_chart_xy(-5.0, 180.0, 200) is None

    def test_zenith_lands_at_disc_centre(self):
        x, y = _alt_az_to_chart_xy(90.0, 0.0, 200)
        # Centre of the disc (constants from the panel module)
        from src.render.components.constellation_map_panel import (
            _DISC_CENTER_X,
            _DISC_CENTER_Y,
        )

        assert (x, y) == (_DISC_CENTER_X, _DISC_CENTER_Y)

    def test_horizon_at_north_lands_at_top_of_disc(self):
        x, y = _alt_az_to_chart_xy(0.0, 0.0, 200)
        from src.render.components.constellation_map_panel import (
            _DISC_CENTER_X,
            _DISC_CENTER_Y,
        )

        # Horizon = full radius; North = top → y less than centre by the radius.
        assert x == _DISC_CENTER_X
        assert abs(y - (_DISC_CENTER_Y - 200)) <= 1

    def test_east_lands_to_the_left_of_centre(self):
        """Looking-up orientation: East azimuth maps to negative x."""
        x, _ = _alt_az_to_chart_xy(45.0, 90.0, 200)
        from src.render.components.constellation_map_panel import _DISC_CENTER_X

        assert x < _DISC_CENTER_X

    def test_west_lands_to_the_right_of_centre(self):
        x, _ = _alt_az_to_chart_xy(45.0, 270.0, 200)
        from src.render.components.constellation_map_panel import _DISC_CENTER_X

        assert x > _DISC_CENTER_X


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


class TestUtc:
    def test_naive_treated_as_utc(self):
        dt = datetime(2026, 4, 23, 12, 0)
        assert _utc(dt).tzinfo == timezone.utc

    def test_aware_converted(self):
        dt = datetime(2026, 4, 23, 8, 0, tzinfo=ZoneInfo("America/New_York"))
        assert _utc(dt).tzinfo == timezone.utc
        assert _utc(dt).hour == 12  # 8 EDT = 12 UTC


class TestResolveObservationTime:
    def test_uses_now_when_dark(self):
        # Midnight at NYC → use now directly
        midnight = datetime(2026, 4, 23, 1, 0, tzinfo=timezone.utc)
        out = _resolve_observation_time(midnight, midnight.date(), NYC_LAT, NYC_LON)
        assert out == midnight

    def test_skips_to_solar_midnight_when_daytime(self):
        """Daytime obs should project for tonight's solar midnight (~12h after noon)."""
        noon = datetime(2026, 4, 23, 16, 0, tzinfo=timezone.utc)  # 12 EDT
        out = _resolve_observation_time(noon, noon.date(), NYC_LAT, NYC_LON)
        # Solar midnight should be ~12h after solar noon → roughly 04:00 UTC next day
        delta = (out - noon).total_seconds()
        assert delta > 8 * 3600, "should jump forward into the night"

    def test_returns_now_when_no_lat_lon(self):
        dt = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
        assert _resolve_observation_time(dt, dt.date(), None, None) == dt

    def test_zero_zero_lat_lon_treated_as_unset(self):
        dt = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
        assert _resolve_observation_time(dt, dt.date(), 0.0, 0.0) == dt


class TestIsDarkSky:
    def test_night_at_nyc_is_dark(self):
        night = datetime(2026, 4, 23, 4, 0, tzinfo=timezone.utc)  # 0 EDT
        assert _is_dark_sky(night, night.date(), NYC_LAT, NYC_LON) is True

    def test_assumes_dark_without_coordinates(self):
        dt = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
        assert _is_dark_sky(dt, dt.date(), None, None) is True


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


class TestStarRadius:
    def test_brightest_largest(self):
        assert _star_radius(-1.5) > _star_radius(0.5) > _star_radius(2.5) > _star_radius(4.5)

    def test_dim_stars_are_pixel_dot(self):
        assert _star_radius(4.5) == 1


# ---------------------------------------------------------------------------
# Theme rendering
# ---------------------------------------------------------------------------


class TestConstellationMapRender:
    def test_renders_correct_size(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        assert img.size == (800, 480)
        assert img.mode == "1"  # quantized to 1-bit by Waveshare backend

    def test_renders_non_blank(self):
        img = _render(latitude=NYC_LAT, longitude=NYC_LON)
        # Dark canvas with a few hundred bright pixels — must not be all-zero.
        assert any(p != 0 for p in img.tobytes())

    def test_renders_without_coords(self):
        img = _render()
        assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# Direct draw paths (exercise lat/lon present + lat/lon absent branches)
# ---------------------------------------------------------------------------


class TestDrawConstellationMapDirect:
    def test_defaults_region_and_style(self):
        """Calling with no kwargs uses the default ThemeStyle (fg=0/bg=1).

        On a default style the disc rim and chart text both render in fg=0,
        which is invisible against an all-zero L canvas — so the bbox should
        be ``None``.  The point of this test is to prove the function does
        not raise even when handed defaults that don't match its dark-canvas
        intent.
        """
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_constellation_map(d, data, TODAY, FIXED_NOW)
        # No assertion on bbox — just exercise the default-style path.
        assert img.size == (800, 480)

    def test_with_lat_lon_at_night(self):
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        style = load_theme("constellation_map").style
        draw_constellation_map(
            d, data, TODAY, FIXED_NOW, style=style, latitude=NYC_LAT, longitude=NYC_LON
        )
        assert img.getbbox() is not None
        # A dark-canvas chart drawn with fg=255 should fill many pixels.
        bright = sum(1 for p in img.tobytes() if p > 200)
        assert bright > 50, "expected stars + chrome to brighten the canvas"

    def test_with_lat_lon_during_day_uses_solar_midnight(self):
        """Renders without crashing during daylight (uses tonight's projection)."""
        img, d = _make_draw()
        noon = datetime(2026, 4, 23, 16, 0, tzinfo=ZoneInfo("America/New_York"))
        data = DashboardData(events=[], weather=None)
        draw_constellation_map(d, data, noon.date(), noon, latitude=NYC_LAT, longitude=NYC_LON)
        assert img.getbbox() is not None

    def test_with_zero_zero_lat_lon_falls_back_to_message(self):
        """(0,0) coordinates trigger the explanatory message branch."""
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        # Use the actual theme style so message text renders in fg=255 against
        # the dark L-mode canvas — otherwise the message is fg=0 on a fg=0
        # canvas and getbbox would be None despite the branch having executed.
        style = load_theme("constellation_map").style
        draw_constellation_map(d, data, TODAY, FIXED_NOW, style=style, latitude=0.0, longitude=0.0)
        assert img.getbbox() is not None

    def test_with_weather_location_name_in_footer(self):
        """Weather with a location name should render its footer label."""
        img, d = _make_draw()
        w = WeatherData(
            current_temp=50.0,
            current_icon="01n",
            current_description="clear",
            high=60.0,
            low=40.0,
            humidity=60,
            location_name="Brooklyn",
        )
        data = DashboardData(events=[], weather=w)
        draw_constellation_map(d, data, TODAY, FIXED_NOW, latitude=NYC_LAT, longitude=NYC_LON)
        assert img.getbbox() is not None

    def test_polar_observer_renders_without_crashing(self):
        """At extreme latitudes most stars stay above/below the horizon."""
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        draw_constellation_map(
            d,
            data,
            TODAY,
            FIXED_NOW,
            latitude=85.0,
            longitude=0.0,
        )
        assert img.getbbox() is not None

    def test_southern_hemisphere_observer(self):
        """A southern observer projects correctly (most northern stars below horizon)."""
        img, d = _make_draw()
        data = DashboardData(events=[], weather=None)
        sydney = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
        draw_constellation_map(d, data, sydney.date(), sydney, latitude=-33.87, longitude=151.21)
        assert img.getbbox() is not None
