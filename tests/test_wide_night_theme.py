"""wide_night: four marks spaced across an otherwise empty panoramic plate.

The plate's whole job is restraint, so the tests pin what is on it (moon,
temperature, AQI, weather glyph — and nothing when the data is missing), where
it sits (even spacing, one midline), and the colour story on each backend
(black on red on the colour panels; white on black on monochrome, which has no
red).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest
from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import AirQualityData, DashboardData, WeatherData
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components import wide_night_panel as wn
from src.render.random_theme import _EXCLUDED_FROM_POOL, eligible_themes
from src.render.theme import ComponentRegion, ThemeStyle, load_theme
from src.render.themes.wide_night import wide_night_theme
from tests.inkutils import marks

FIXED_NOW = datetime(2026, 4, 6, 22, 30)
TODAY = FIXED_NOW.date()
G_PANEL = DisplayConfig(model="epd10in85g", width=1360, height=480)
MONO = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
REGION = ComponentRegion(0, 0, 1360, 480)
# The style the monochrome path hands the panel: accents collapse onto fg.
MONO_STYLE = ThemeStyle(fg=1, bg=0, accent_primary=1)
BAND = (0, 120, 1360, 360)  # the band the marks live in


def _weather(**kw) -> WeatherData:
    base = dict(
        current_temp=41.6,
        current_icon="01n",
        current_description="clear sky",
        high=48.0,
        low=35.0,
        humidity=65,
    )
    base.update(kw)
    return WeatherData(**base)


def _air(aqi: int = 42) -> AirQualityData:
    return AirQualityData(aqi=aqi, category="Good", pm25=8.0)


def _data(weather=True, air=True) -> DashboardData:
    return DashboardData(
        weather=_weather() if weather else None,
        air_quality=_air() if air else None,
    )


def _plate(data: DashboardData, today: date = TODAY) -> Image.Image:
    img = Image.new("1", (1360, 480), 0)
    wn.draw_wide_night(ImageDraw.Draw(img), data, today, FIXED_NOW, region=REGION, style=MONO_STYLE)
    return img


def _mark_centres(img: Image.Image, min_gap: int = 40, extents: bool = False) -> list:
    """Midpoints (or ``(first, last)`` columns) of the separated groups of lit columns."""
    x0, y0, x1, y1 = BAND
    lit = [x for x in range(x0, x1) if marks(img, (x, y0, x + 1, y1), background=0)]
    groups: list[list[int]] = []
    for x in lit:
        if groups and x - groups[-1][-1] <= min_gap:
            groups[-1].append(x)
        else:
            groups.append([x])
    if extents:
        return [(g[0], g[-1]) for g in groups]
    return [(g[0] + g[-1] + 1) / 2 for g in groups]


class TestMarks:
    def test_all_four_in_order(self):
        kinds = [m.kind for m in wn.marks_for(_data(), TODAY)]
        assert kinds == ["moon", "temperature", "aqi", "weather"]

    def test_temperature_is_rounded_with_a_degree_sign(self):
        temp = next(m for m in wn.marks_for(_data(), TODAY) if m.kind == "temperature")
        assert temp.text == "42°"

    def test_aqi_carries_its_caption(self):
        aqi = next(m for m in wn.marks_for(_data(), TODAY) if m.kind == "aqi")
        assert (aqi.text, aqi.caption) == ("42", "AQI")

    def test_no_sensor_drops_the_aqi(self):
        kinds = [m.kind for m in wn.marks_for(_data(air=False), TODAY)]
        assert kinds == ["moon", "temperature", "weather"]

    def test_no_weather_leaves_the_moon_and_aqi(self):
        kinds = [m.kind for m in wn.marks_for(_data(weather=False), TODAY)]
        assert kinds == ["moon", "aqi"]

    def test_unknown_icon_falls_back(self):
        data = DashboardData(weather=_weather(current_icon="zz"))
        glyph = wn.marks_for(data, TODAY)[-1]
        assert glyph.kind == "weather" and glyph.text == wn.FALLBACK_ICON


class TestSpacing:
    def test_centres_are_evenly_spaced_with_half_gap_margins(self):
        cs = wn.centres(4, 0, 1360)
        assert cs == [170, 510, 850, 1190]
        gaps = {b - a for a, b in zip(cs, cs[1:])}
        assert gaps == {340}
        assert cs[0] == 1360 - cs[-1] == 340 // 2

    def test_rendered_marks_sit_in_their_slices(self):
        img = _plate(_data())
        for cx in wn.centres(4, 0, 1360):
            assert marks(img, (cx - 150, 120, cx + 150, 360), background=0) > 0

    def test_marks_are_centred_in_their_slices(self):
        assert _mark_centres(_plate(_data())) == pytest.approx([170, 510, 850, 1190], abs=3)

    def test_missing_mark_is_respaced_not_left_as_a_gap(self):
        centres = _mark_centres(_plate(_data(air=False)))
        assert centres == pytest.approx(wn.centres(3, 0, 1360), abs=3)

    def test_everything_else_is_ground(self):
        img = _plate(_data())
        assert marks(img, (0, 0, 1360, 120), background=0) == 0
        assert marks(img, (0, 380, 1360, 480), background=0) == 0


class TestMoon:
    def test_crescent_is_drawn_inside_the_whole_disc(self):
        """The phase glyphs ink only the lit part — a crescent alone is a
        sliver half the disc's width, so the ring beneath it must show."""
        crescent = date(2026, 4, 20)
        (moon,) = _mark_centres(_plate(DashboardData(), today=crescent), extents=True)
        assert moon[1] - moon[0] >= 90

    def test_phase_changes_the_plate(self):
        a = _plate(DashboardData(), today=date(2026, 4, 6))
        b = _plate(DashboardData(), today=date(2026, 4, 10))
        assert a.tobytes() != b.tobytes()


class TestColours:
    def test_colour_style_is_black_on_accent(self):
        style = ThemeStyle(fg=(255, 255, 255), bg=(0, 0, 0), accent_primary=(255, 0, 0))
        assert wn.colours(style) == ((255, 0, 0), (0, 0, 0))

    def test_mono_style_is_white_on_black(self):
        assert wn.colours(MONO_STYLE) == (0, 1)

    def test_g_panel_is_black_on_red_in_exact_inks(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, G_PANEL, theme=load_theme("wide_night"))
        assert img.mode == "RGB"
        colours = {c for _, c in img.getcolors(maxcolors=1 << 16)}
        assert colours == {(255, 0, 0), (0, 0, 0)}
        counts = dict((c, n) for n, c in img.getcolors(maxcolors=1 << 16))
        # Largely negative space: the red ground is the overwhelming majority.
        assert counts[(255, 0, 0)] > 0.9 * 1360 * 480

    def test_mono_panel_is_white_on_black(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, MONO, theme=load_theme("wide_night"))
        black = img.convert("L").histogram()[0]
        assert black > 0.9 * 1360 * 480
        assert black < 1360 * 480


class TestTheme:
    def test_panoramic_canvas(self):
        layout = wide_night_theme().layout
        assert (layout.canvas_w, layout.canvas_h) == (1360, 480)
        assert layout.draw_order == ["wide_night"]

    def test_repaints_at_most_hourly(self):
        assert wide_night_theme().layout.repaint_slot_hours == 1

    def test_declines_partial_refresh(self):
        assert not wide_night_theme().allows_partial_refresh

    def test_kept_out_of_random_rotation(self):
        assert "wide_night" in _EXCLUDED_FROM_POOL
        assert "wide_night" not in eligible_themes([], [], panel=(1360, 480))

    def test_default_style_arguments(self):
        img = Image.new("1", (1360, 480), 1)
        wn.draw_wide_night(ImageDraw.Draw(img), _data(), TODAY, FIXED_NOW)
        assert marks(img, BAND, background=0) > 0

    def test_restores_the_callers_fontmode(self):
        img = Image.new("RGB", (1360, 480))
        draw = ImageDraw.Draw(img)
        draw.fontmode = "L"
        style = replace(MONO_STYLE, fg=(255, 255, 255), bg=(0, 0, 0), accent_primary=(255, 0, 0))
        wn.draw_wide_night(draw, _data(), TODAY, FIXED_NOW, region=REGION, style=style)
        assert draw.fontmode == "L"
