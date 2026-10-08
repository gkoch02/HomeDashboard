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
# The theme's style as the monochrome path hands it to the panel: accents
# collapse onto fg.
MONO_STYLE = replace(wide_night_theme().style, accent_primary=1, accent_secondary=1)
BAND = (0, 0, 1360, 480)
FULL_MOON = date(2026, 5, 1)
NEW_MOON = date(2026, 4, 17)
CRESCENT = date(2026, 4, 20)


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


def _extents(img: Image.Image, min_gap: int = wn.MIN_GAP - 4) -> list[tuple[int, int]]:
    # MIN_GAP is the floor; every real row's gaps are at least that.
    """``(first, last + 1)`` columns of each horizontally separated mark."""
    x0, y0, x1, y1 = BAND
    lit = [x for x in range(x0, x1) if marks(img, (x, y0, x + 1, y1), background=0)]
    groups: list[list[int]] = []
    for x in lit:
        if groups and x - groups[-1][-1] <= min_gap:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [(g[0], g[-1] + 1) for g in groups]


def _gaps(img: Image.Image) -> list[int]:
    """Blank columns before, between and after the marks."""
    edges = [0, *(v for e in _extents(img) for v in e), 1360]
    return [edges[i + 1] - edges[i] for i in range(0, len(edges), 2)]


def _rows(img: Image.Image, box=BAND) -> tuple[int, int]:
    """``(first, last + 1)`` lit rows inside *box*."""
    x0, y0, x1, y1 = box
    lit = [y for y in range(y0, y1) if marks(img, (x0, y, x1, y + 1), background=0)]
    return lit[0], lit[-1] + 1


def _label_top(img: Image.Image) -> int:
    """First row of the label band: the lowest run of lit rows."""
    lit = [y for y in range(480) if marks(img, (0, y, 1360, y + 1), background=0)]
    top = lit[-1]
    while top - 1 in lit:
        top -= 1
    return top


class TestLabels:
    def test_every_mark_is_labelled(self):
        assert [m.caption for m in wn.marks_for(_data(), TODAY)] == [
            "MOON",
            "TEMP",
            "AQI",
            "SKY",
        ]

    def test_labels_share_one_baseline_under_the_row(self):
        img = _plate(_data())
        label_top = _label_top(img)
        _, marks_bottom = _rows(img, (0, 0, 1360, label_top))
        assert label_top - marks_bottom >= wn.LABEL_GAP - 2
        # One band: every label's ink starts on the same row (round letters
        # overshoot flat ones by a pixel).
        for left, right in _extents(img):
            first = _rows(img, (left, label_top, right, 480))[0]
            assert first - label_top <= 1

    def test_labels_are_tracked_out(self):
        font = MONO_STYLE.font_bold(wn.LABEL_PT)
        assert wn.tracked_width("AQI", font) > font.getlength("AQI") + 10

    def test_group_is_centred_on_the_plate(self):
        top, bottom = _rows(_plate(_data()))
        assert abs((top + bottom) / 2 - 240) <= 2


class TestMarks:
    def test_all_four_in_order(self):
        kinds = [m.kind for m in wn.marks_for(_data(), TODAY)]
        assert kinds == ["moon", "temperature", "aqi", "weather"]

    def test_temperature_is_rounded_with_a_degree_sign(self):
        temp = next(m for m in wn.marks_for(_data(), TODAY) if m.kind == "temperature")
        assert temp.text == "42°"

    def test_aqi_is_the_index(self):
        aqi = next(m for m in wn.marks_for(_data(), TODAY) if m.kind == "aqi")
        assert aqi.text == "42"

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
    def test_gaps_are_equal_between_marks_and_at_both_ends(self):
        gaps = _gaps(_plate(_data()))
        assert len(gaps) == 5
        assert max(gaps) - min(gaps) <= 2

    def test_missing_mark_is_respaced_not_left_as_a_gap(self):
        img = _plate(_data(air=False))
        assert len(_extents(img)) == 3
        gaps = _gaps(img)
        assert max(gaps) - min(gaps) <= 2

    def test_full_row_fits_with_at_least_the_minimum_gap(self):
        height = wn.fit_height(wn.marks_for(_data(), TODAY), MONO_STYLE, 1360, 384)
        assert min(_gaps(_plate(_data()))) >= wn.min_gap(height) - 2

    def test_space_inside_a_mark_is_narrower_than_between_marks(self):
        """The degree sign must not read as a mark of its own at any size."""
        for data in (_data(), _data(air=False), _data(weather=True, air=False)):
            ms = wn.marks_for(data, TODAY)
            height = wn.fit_height(ms, MONO_STYLE, 1360, 384)
            temp = next(m for m in ms if m.kind == "temperature")
            font = wn._measure(temp, MONO_STYLE, height).font
            inner = wn.ink_box("°", font)[0] - wn.ink_box(temp.text[:-1], font)[2]
            assert inner < wn.min_gap(height)


class TestHeight:
    def test_a_row_that_fits_is_the_band_fraction_of_the_plate(self):
        """A full moon alone is its whole disc, so it shows the height exactly."""
        img = _plate(DashboardData(), today=FULL_MOON)
        label_top = _label_top(img)
        top, bottom = _rows(img, (0, 0, 1360, label_top))
        assert abs((bottom - top) - wn.BAND_FRACTION * 480) <= 3

    def test_a_row_too_wide_for_80_percent_shrinks_to_fit(self):
        ms = wn.marks_for(_data(), TODAY)
        height = wn.fit_height(ms, MONO_STYLE, 1360, 384)
        assert height < 384
        placed = [wn._measure(m, MONO_STYLE, height) for m in ms]
        assert sum(p.width for p in placed) + 5 * wn.min_gap(height) <= 1360
        # ...and it is the tallest that fits: one step up overflows.
        up = height + 2
        bigger = [wn._measure(m, MONO_STYLE, up) for m in ms]
        assert sum(p.width for p in bigger) + 5 * wn.min_gap(up) > 1360

    def test_every_mark_shares_the_height(self):
        ms = wn.marks_for(_data(), FULL_MOON)
        height = wn.fit_height(ms, MONO_STYLE, 1360, 384)
        for m in ms:
            ref = wn._measure(m, MONO_STYLE, height).ref
            assert abs((ref[3] - ref[1]) - height) <= 3, m.kind

    def test_temperature_uses_the_hero_numeral_face(self):
        temp = next(m for m in wn.marks_for(_data(), TODAY) if m.kind == "temperature")
        placed = wn._measure(temp, MONO_STYLE, 200)
        assert placed.font.path.endswith("Jura-Variable.ttf")

    def test_labels_set_a_three_pixel_stem(self):
        """Jura's heaviest weight laid a 2-px stem at the label size, which read
        thin across a dark room; the label face must hold 3 px, bilevel."""
        box = wn.ink_box("I", MONO_STYLE.font_bold(wn.LABEL_PT))
        assert box[2] - box[0] >= 3


class TestMoon:
    def test_crescent_has_no_outline_on_its_dark_limb(self):
        """The lit sliver alone — no ring around the unlit part of the disc."""
        img = _plate(DashboardData(), today=CRESCENT)
        ((left, right),) = _extents(img)
        top, bottom = _rows(img)
        assert right - left < 0.6 * (bottom - top)

    def test_new_moon_leaves_its_slot_empty_under_the_label(self):
        img = _plate(DashboardData(), today=NEW_MOON)
        label_top = _label_top(img)
        assert marks(img, (0, 0, 1360, label_top), background=0) == 0
        assert marks(img, background=0) > 0  # the MOON label itself

    def test_ink_box_is_the_ink_not_the_cell(self):
        font = wn.weather_icon_font(200)
        glyph = wn.moon_phase_glyph(CRESCENT)
        cell = font.getbbox(glyph)
        ink = wn.ink_box(glyph, font)
        assert ink[2] - ink[0] < 0.6 * (cell[2] - cell[0])

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
        assert counts[(255, 0, 0)] > 0.75 * 1360 * 480

    def test_mono_panel_is_white_on_black(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, MONO, theme=load_theme("wide_night"))
        black = img.convert("L").histogram()[0]
        assert black > 0.75 * 1360 * 480
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


class TestInvert:
    """wide_night_invert: the same plate with ground and ink swapped."""

    def test_colours_swap_on_both_backends(self):
        style = ThemeStyle(fg=(255, 255, 255), bg=(0, 0, 0), accent_primary=(255, 0, 0))
        assert wn.colours(style, invert=True) == ((0, 0, 0), (255, 0, 0))
        assert wn.colours(MONO_STYLE, invert=True) == (1, 0)

    def test_g_panel_is_red_on_black_in_exact_inks(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, G_PANEL, theme=load_theme("wide_night_invert"))
        counts = {c: n for n, c in img.getcolors(maxcolors=1 << 16)}
        assert set(counts) == {(0, 0, 0), (255, 0, 0)}
        assert counts[(0, 0, 0)] > 0.75 * 1360 * 480

    def test_mono_panel_is_black_on_white(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, MONO, theme=load_theme("wide_night_invert"))
        assert img.convert("L").histogram()[255] > 0.75 * 1360 * 480

    def test_same_layout_as_wide_night(self):
        """Every pixel that is ink on one plate is ground on the other."""
        data = generate_dummy_data(now=FIXED_NOW)
        a = render_dashboard(data, MONO, theme=load_theme("wide_night")).convert("L")
        b = render_dashboard(data, MONO, theme=load_theme("wide_night_invert")).convert("L")
        assert a.point(lambda v: 255 - v).tobytes() == b.tobytes()

    def test_inherits_the_repaint_limit_and_stays_out_of_rotation(self):
        from src.render.themes.wide_night_invert import wide_night_invert_theme

        theme = wide_night_invert_theme()
        assert theme.layout.repaint_slot_hours == 1
        assert theme.layout.draw_order == ["wide_night_invert"]
        assert "wide_night_invert" in _EXCLUDED_FROM_POOL


class TestOfflineScale:
    def _moon_rows(self, img: Image.Image) -> int:
        """Height of the first mark (the moon), its label excluded."""
        x0, x1 = _extents(img)[0]
        top, bottom = _rows(img, (x0, 0, x1, _label_top(img) - 1))
        return bottom - top

    def test_a_lone_moon_keeps_the_plate_scale(self):
        """With weather and air quality both offline only the moon is left; it must
        not swell to fill the strip but stay near the size the default row sets."""
        alone = self._moon_rows(_plate(_data(weather=False, air=False)))
        in_row = self._moon_rows(_plate(_data(air=False)))
        assert alone <= 1.1 * in_row, f"lone moon {alone}px vs {in_row}px in the row"
