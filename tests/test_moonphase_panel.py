"""Tests for moonphase_panel.py; marks are counted with ``tests.inkutils.marks`` against the
real theme styles, because the plate's polarity differs between ``moonphase`` and its invert.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from src.data.models import DashboardData, WeatherData
from src.render.components.moonphase_panel import (
    _ordinal_suffix,
    draw_moonphase,
)
from src.render.quantize import flatten_pixels
from src.render.quotes import quote_for
from src.render.theme import ComponentRegion, ThemeStyle, load_theme
from tests.conftest import make_draw
from tests.inkutils import marks, record_text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_weather(**overrides) -> WeatherData:
    defaults = dict(
        current_temp=68.0,
        current_icon="02d",
        current_description="partly cloudy",
        high=74.0,
        low=55.0,
        humidity=50,
        sunrise=datetime(2024, 3, 15, 6, 30),
        sunset=datetime(2024, 3, 15, 19, 45),
    )
    defaults.update(overrides)
    return WeatherData(**defaults)


def _make_data(**overrides) -> DashboardData:
    data = DashboardData(weather=_make_weather())
    for k, v in overrides.items():
        setattr(data, k, v)
    return data


TODAY = date(2024, 3, 15)


# ---------------------------------------------------------------------------
# _ordinal_suffix
# ---------------------------------------------------------------------------


class TestOrdinalSuffix:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (1, "st"),
            (2, "nd"),
            (3, "rd"),
            (4, "th"),
            (10, "th"),
            (11, "th"),  # teen exception
            (12, "th"),  # teen exception
            (13, "th"),  # teen exception
            (21, "st"),
            (22, "nd"),
            (23, "rd"),
            (24, "th"),
            (100, "th"),
            (101, "st"),
            (111, "th"),  # teen exception in hundreds
            (112, "th"),
        ],
    )
    def test_suffix(self, n, expected):
        assert _ordinal_suffix(n) == expected


# ---------------------------------------------------------------------------
# quote_for(prefix="moonphase-") — refresh modes
# ---------------------------------------------------------------------------


class TestQuoteForPanel:
    def test_daily_refresh_is_deterministic(self):
        q1 = quote_for(TODAY, refresh="daily", prefix="moonphase-")
        q2 = quote_for(TODAY, refresh="daily", prefix="moonphase-")
        assert q1 == q2

    def test_different_days_may_differ(self):
        """Two different dates should generally produce different quotes.
        This is probabilistic but with 5+ quotes it's extremely reliable."""
        quotes = {
            json.dumps(quote_for(date(2024, 3, d), refresh="daily", prefix="moonphase-"))
            for d in range(1, 20)
        }
        assert len(quotes) > 1

    def test_hourly_refresh_uses_hour(self):
        now_am = datetime(2024, 3, 15, 9, 0)
        now_pm = datetime(2024, 3, 15, 14, 0)
        q_am = quote_for(TODAY, refresh="hourly", now=now_am, prefix="moonphase-")
        q_pm = quote_for(TODAY, refresh="hourly", now=now_pm, prefix="moonphase-")
        # Same date but different hours — they may differ (not guaranteed, but
        # test that the call succeeds and returns a dict with expected keys)
        assert "text" in q_am
        assert "author" in q_pm

    def test_twice_daily_am_pm_differ(self):
        now_am = datetime(2024, 3, 15, 8, 0)
        now_pm = datetime(2024, 3, 15, 13, 0)
        q_am = quote_for(TODAY, refresh="twice_daily", now=now_am, prefix="moonphase-")
        q_pm = quote_for(TODAY, refresh="twice_daily", now=now_pm, prefix="moonphase-")
        assert "text" in q_am
        assert "text" in q_pm

    def test_returns_dict_with_text_and_author(self):
        q = quote_for(TODAY, prefix="moonphase-")
        assert "text" in q
        assert "author" in q

    def test_fallback_to_default_quotes_when_file_missing(self):
        with patch(
            "src.render.quotes.DEFAULT_QUOTES_PATH",
            Path("/nonexistent/path/quotes.json"),
        ):
            q = quote_for(TODAY, prefix="moonphase-")
        assert "text" in q
        assert "author" in q

    def test_fallback_on_corrupt_json(self, tmp_path):
        corrupt_file = tmp_path / "quotes.json"
        corrupt_file.write_text("{ this is not valid json }")
        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", corrupt_file):
            q = quote_for(TODAY, prefix="moonphase-")
        assert "text" in q

    def test_mp_key_prefix_differs_from_info_panel(self):
        """moonphase key prefix 'moonphase-' ensures independence from info_panel."""
        mp_key = f"moonphase-{TODAY.isoformat()}"
        info_key = TODAY.isoformat()
        assert mp_key != info_key


# ---------------------------------------------------------------------------
# Ink measurement
#
# This panel is drawn on greyscale plates whose background may be black
# (moonphase) or white (moonphase_invert), so "ink" here means "differs from
# the canvas background" rather than a fixed value. The real theme styles are
# used below: passing the default ThemeStyle (fg=0, bg=1, a 1-bit style) onto
# an L canvas is a combination the themes never produce, and under it the
# lunar disc renders inverted — bright at new moon, dark at full.
# ---------------------------------------------------------------------------

_HERO_BOX = (250, 96, 550, 290)  # generous box around the hero disc


def _dark_style():
    from src.render.themes.moonphase import moonphase_theme

    return moonphase_theme().style


def _light_style():
    from src.render.themes.moonphase_invert import moonphase_invert_theme

    return moonphase_invert_theme().style


def _render_l(today=None, data=None, *, style=None, background=0, **kwargs):
    """Render on an L plate using a real theme style."""
    img = Image.new("L", (800, 480), background)
    draw = ImageDraw.Draw(img)
    draw_moonphase(
        draw,
        data if data is not None else _make_data(),
        today or TODAY,
        image=img,
        style=style or _dark_style(),
        **kwargs,
    )
    return img


def _hero_lit(img, threshold: int = 140) -> int:
    """Bright pixels inside the hero disc — the sunlit fraction of the moon."""
    px = flatten_pixels(img)
    x0, y0, x1, y1 = _HERO_BOX
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * img.width + x] > threshold)


def _moon_row_extent(img, y0: int = 96, y1: int = 290, threshold: int = 40):
    """(left, right) x-extent of the filmstrip band.

    Counting individual discs would be phase-dependent and unreliable: a
    near-new flanking moon has almost no lit area to detect, and the hero's
    outline ring reads as two separate marks on a scanline. The strip's
    overall span does not have that problem — it is ~670px wide and centred
    at every phase.
    """
    px = flatten_pixels(img)
    width = img.width
    xs = [x for x in range(width) if any(px[y * width + x] > threshold for y in range(y0, y1))]
    return (xs[0], xs[-1] + 1) if xs else None


def _assert_filmstrip(img, note: str = "") -> None:
    """The hero plus its flanking days span most of the plate, centred."""
    extent = _moon_row_extent(img)
    assert extent is not None, f"no filmstrip drawn {note}"
    left, right = extent
    assert right - left > 600, f"filmstrip too narrow ({right - left}px) {note}"
    midpoint = (left + right) / 2
    assert abs(midpoint - 400) < 30, f"filmstrip off-centre at {midpoint} {note}"


class TestBilevelType:
    """Type is rasterised bilevel so the threshold cut cannot erase hairlines."""

    # The lunar-data block and quote: type only, below the separator.
    _TYPE_BAND = (20, 310, 780, 470)

    def _greys(self, img) -> int:
        x0, y0, x1, y1 = self._TYPE_BAND
        px = flatten_pixels(img)
        return sum(
            1 for y in range(y0, y1) for x in range(x0, x1) if 0 < px[y * img.width + x] < 255
        )

    def test_dark_plate_type_has_no_grey_edges(self):
        img = _render_l()
        assert marks(img, self._TYPE_BAND) > 0
        assert self._greys(img) == 0

    def test_light_plate_type_has_no_grey_edges(self):
        img = _render_l(style=_light_style(), background=255)
        assert marks(img, self._TYPE_BAND) > 0
        assert self._greys(img) == 0

    def test_restores_the_callers_fontmode(self):
        img = Image.new("L", (800, 480), 0)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "L"
        draw_moonphase(draw, _make_data(), TODAY, image=img, style=_dark_style())
        assert draw.fontmode == "L"


class TestBareDiscs:
    def test_no_disc_draws_a_limb_ring(self):
        """The hero matches the flanking moons: lit shape only, no outline."""
        from src.render.components import moonphase_panel

        with patch.object(
            moonphase_panel, "render_moon_disc", wraps=moonphase_panel.render_moon_disc
        ) as spy:
            _render_l()
        assert spy.call_count == 7
        assert all(call.kwargs.get("show_edge") is False for call in spy.call_args_list)


class TestDrawMoonphaseSmoke:
    def test_renders_with_full_data(self):
        assert marks(_render_l()) > 0

    def test_returns_none(self):
        _, draw = make_draw()
        assert draw_moonphase(draw, _make_data(), TODAY) is None

    def test_produces_non_blank_image(self):
        """Genuinely non-blank: pixels differ from the background."""
        assert marks(_render_l()) > 0

    def test_draws_the_hero_and_flanking_moons(self):
        """The filmstrip is the hero plus three days each side, spanning the plate."""
        _assert_filmstrip(_render_l())

    def test_renders_without_weather(self):
        """weather=None drops the sun/weather line but keeps the rest."""
        without = _render_l(data=_make_data(weather=None))
        assert marks(without) > 0
        _assert_filmstrip(without, "without weather")
        assert marks(without) != marks(_render_l()), "the weather line is not drawn"

    def test_renders_with_default_region_and_style(self):
        """region=None/style=None fill in the full-canvas defaults."""
        img_default, draw = make_draw()
        draw_moonphase(draw, _make_data(), TODAY, region=None, style=None)
        img_explicit, draw2 = make_draw()
        draw_moonphase(
            draw2,
            _make_data(),
            TODAY,
            region=ComponentRegion(0, 0, 800, 480),
            style=ThemeStyle(),
        )
        assert marks(img_default) > 0
        assert img_default.tobytes() == img_explicit.tobytes()

    def test_renders_with_custom_region(self):
        """A shifted region moves the content with it."""
        at_origin = _render_l(region=ComponentRegion(0, 0, 800, 240))
        lower = _render_l(region=ComponentRegion(0, 120, 800, 240))
        assert marks(at_origin) > 0
        assert at_origin.tobytes() != lower.tobytes()

    def test_renders_with_custom_style(self):
        """The dark and light theme styles produce different plates."""
        dark = _render_l(style=_dark_style(), background=0)
        light = _render_l(style=_light_style(), background=255)
        assert marks(dark) > 0 and marks(light) > 0
        assert dark.tobytes() != light.tobytes()


class TestDrawMoonphasePhases:
    @pytest.mark.parametrize(
        "d",
        [
            date(2024, 1, 11),  # new moon
            date(2024, 1, 18),  # first quarter
            date(2024, 1, 25),  # full moon
            date(2024, 2, 2),  # last quarter
            date(2024, 3, 15),  # waxing crescent
            date(2024, 6, 21),  # summer solstice
            date(2024, 12, 31),  # year boundary
        ],
    )
    def test_renders_across_lunar_cycle(self, d):
        """Every date draws the full filmstrip."""
        img = _render_l(d)
        assert marks(img) > 0
        _assert_filmstrip(img, f"for {d}")

    def test_hero_disc_tracks_illumination(self):
        """The sunlit area of the hero disc follows the phase.

        This is the panel's whole job, so it is measured rather than assumed:
        the lit pixel count must rank the same way the illumination percentage
        does across the cycle.
        """
        from src.render.moon import moon_illumination

        dates = [date(2024, 3, 10), date(2024, 3, 17), date(2024, 3, 25), date(2024, 4, 1)]
        measured = [(moon_illumination(d), _hero_lit(_render_l(d))) for d in dates]
        by_illumination = sorted(measured, key=lambda pair: pair[0])
        lit_values = [lit for _, lit in by_illumination]
        assert lit_values == sorted(lit_values), (
            f"lit area does not follow illumination: {by_illumination}"
        )
        assert lit_values[0] < lit_values[-1] / 10, "new and full moon look nearly the same"

    def test_light_canvas_inverts_the_disc(self):
        """On the parchment variant the lit region is dark, not bright."""
        full_moon = date(2024, 3, 25)
        new_moon = date(2024, 3, 10)
        light_full = _render_l(full_moon, style=_light_style(), background=255)
        light_new = _render_l(new_moon, style=_light_style(), background=255)
        px_full = flatten_pixels(light_full)
        px_new = flatten_pixels(light_new)
        x0, y0, x1, y1 = _HERO_BOX

        def dark_px(px):
            return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * 800 + x] < 120)

        assert dark_px(px_full) > dark_px(px_new) * 10, "the invert theme is not inverting"


class TestDrawMoonphaseCelestialStrip:
    def test_renders_without_sunrise(self):
        base = marks(_render_l())
        assert marks(_render_l(data=_make_data(weather=_make_weather(sunrise=None)))) != base

    def test_renders_without_sunset(self):
        base = marks(_render_l())
        assert marks(_render_l(data=_make_data(weather=_make_weather(sunset=None)))) != base

    def test_renders_without_sunrise_and_sunset(self):
        """Neither time still renders the rest of the panel."""
        neither = _render_l(data=_make_data(weather=_make_weather(sunrise=None, sunset=None)))
        assert marks(neither) > 0
        _assert_filmstrip(neither, "without sun times")
        assert marks(neither) != marks(_render_l())


class TestDrawMoonphaseQuoteRefresh:
    @pytest.mark.parametrize("mode", ["daily", "hourly", "twice_daily"])
    def test_refresh_mode_renders(self, mode):
        assert marks(_render_l(quote_refresh=mode)) > 0

    def test_refresh_modes_can_select_different_quotes(self):
        """The three cadences bucket differently, so they do not all agree."""
        plates = {
            m: _render_l(quote_refresh=m).tobytes() for m in ("daily", "hourly", "twice_daily")
        }
        assert len(set(plates.values())) > 1, "every refresh mode drew the same quote"


# ---------------------------------------------------------------------------
# Integration: via render_dashboard with moonphase theme
# ---------------------------------------------------------------------------


class TestMoonphaseThemeIntegration:
    def test_moonphase_theme_renders_via_canvas(self):
        from PIL import Image as PILImage

        from src.config import DisplayConfig
        from src.render.canvas import render_dashboard
        from src.render.theme import load_theme

        data = _make_data()
        result = render_dashboard(data, DisplayConfig(), theme=load_theme("moonphase"))
        assert isinstance(result, PILImage.Image)
        assert result.size == (800, 480)

    def test_moonphase_invert_theme_renders(self):
        from PIL import Image as PILImage

        from src.config import DisplayConfig
        from src.render.canvas import render_dashboard
        from src.render.theme import load_theme

        data = _make_data()
        result = render_dashboard(data, DisplayConfig(), theme=load_theme("moonphase_invert"))
        assert isinstance(result, PILImage.Image)

    def test_moonphase_in_available_themes(self):
        from src.render.theme import AVAILABLE_THEMES

        assert "moonphase" in AVAILABLE_THEMES
        assert "moonphase_invert" in AVAILABLE_THEMES
        assert "moonphase_photo" in AVAILABLE_THEMES

    def test_moonphase_in_random_pool(self):
        from src.render.random_theme import eligible_themes

        pool = eligible_themes(include=[], exclude=[])
        assert "moonphase" in pool
        assert "moonphase_invert" in pool

    def test_moonphase_photo_theme_renders(self):
        from PIL import Image as PILImage

        from src.config import DisplayConfig
        from src.render.canvas import render_dashboard
        from src.render.theme import load_theme

        data = _make_data()
        result = render_dashboard(data, DisplayConfig(), theme=load_theme("moonphase_photo"))
        assert isinstance(result, PILImage.Image)
        assert result.size == (800, 480)

    def test_photo_flag_only_set_on_photo_theme(self):
        """moonphase stays solid-disk (use_moon_photo False); the photo theme opts in."""
        from src.render.theme import load_theme

        assert load_theme("moonphase").style.use_moon_photo is False
        assert load_theme("moonphase_invert").style.use_moon_photo is False
        assert load_theme("moonphase_photo").style.use_moon_photo is True


# ---------------------------------------------------------------------------
# Procedural moon + lunar-data paths (L / RGB canvases, coordinates)
# ---------------------------------------------------------------------------


class TestDrawMoonphaseProcedural:
    """Dark-canvas rendering, using the theme's own style.

    (#229) These originally passed the default ThemeStyle, whose fg=0 on this
    black canvas leaves almost nothing visible — 2828 marked pixels against
    56541 under the theme's fg=255. Coordinates then made no difference to the
    plate, so a test asserting they did would have failed for the wrong
    reason. Same trap as the one recorded in test_constellation_map_panel.py.
    """

    @staticmethod
    def _style():
        return load_theme("moonphase").style

    def _l_canvas(self, w=800, h=480):
        img = Image.new("L", (w, h), 0)
        return img, ImageDraw.Draw(img)

    def _rgb_canvas(self, w=800, h=480):
        img = Image.new("RGB", (w, h), (0, 0, 0))
        return img, ImageDraw.Draw(img)

    def test_renders_on_l_canvas_with_coords(self):
        img, draw = self._l_canvas()
        now = datetime(2026, 5, 30, 21, 0, tzinfo=timezone.utc)
        draw_moonphase(
            draw,
            _make_data(),
            date(2026, 5, 30),
            image=img,
            latitude=37.77,
            longitude=-122.42,
            now=now,
            style=self._style(),
        )
        assert marks(img) > 0, "the L-canvas plate rendered blank"
        # Coordinates add the moonrise/moonset line, so they change the plate.
        bare, bare_draw = self._l_canvas()
        draw_moonphase(
            bare_draw,
            _make_data(),
            date(2026, 5, 30),
            image=bare,
            now=now,
            style=self._style(),
        )
        assert img.tobytes() != bare.tobytes(), "the coordinates reached nothing"

    def test_renders_on_rgb_canvas(self):
        img, draw = self._rgb_canvas()
        now = datetime(2026, 5, 30, 21, 0, tzinfo=timezone.utc)
        draw_moonphase(
            draw,
            _make_data(),
            date(2026, 5, 30),
            image=img,
            latitude=37.77,
            longitude=-122.42,
            now=now,
        )
        assert marks(img) > 0, "the RGB plate rendered blank"

    def test_supermoon_badge_renders(self):
        """A near-perigee full moon swaps the illumination subtitle for a badge."""
        img, draw = self._l_canvas()
        draw_moonphase(draw, _make_data(), date(2025, 11, 5), image=img, style=self._style())
        ordinary, ordinary_draw = self._l_canvas()
        draw_moonphase(
            ordinary_draw, _make_data(), date(2025, 11, 20), image=ordinary, style=self._style()
        )
        assert marks(img) > 0
        assert img.tobytes() != ordinary.tobytes(), "the supermoon badge never appeared"

    def test_zero_coords_treated_as_unset(self):
        img, draw = self._l_canvas()
        # 0,0 should skip moonrise/moonset and fall back to age only — no crash.
        draw_moonphase(
            draw,
            _make_data(),
            TODAY,
            image=img,
            latitude=0.0,
            longitude=0.0,
            style=self._style(),
        )
        unset, unset_draw = self._l_canvas()
        draw_moonphase(unset_draw, _make_data(), TODAY, image=unset, style=self._style())
        assert marks(img) > 0
        assert img.tobytes() == unset.tobytes(), (
            "(0,0) was treated as a real location rather than as unset"
        )

    def test_no_coords_renders(self):
        img, draw = self._l_canvas()
        draw_moonphase(draw, _make_data(), TODAY, image=img, style=self._style())
        assert marks(img) > 0, "the no-coordinates plate rendered blank"


class TestMoonphaseHelpers:
    def test_usable_coords(self):
        from src.render.primitives import usable_coords

        assert usable_coords(37.0, -122.0) == (37.0, -122.0)
        assert usable_coords(0.0, 0.0) is None
        assert usable_coords(None, -122.0) is None
        assert usable_coords(37.0, None) is None

    def test_moon_tones_modes(self):
        from src.render.components.moonphase_panel import _moon_tones
        from src.render.theme import ThemeStyle

        style = ThemeStyle()
        for mode in ("L", "RGB", "1"):
            for dark in (True, False):
                tones = _moon_tones(style, mode, dark)
                assert tones.lit is not None and tones.dark is not None

    def test_bilevel_disc_centered_at_requested_point(self):
        """The "1"/fallback path must honour cx, cy (regression for PR #183)."""
        from PIL import Image, ImageDraw

        from src.render.moon_render import MoonTones, render_moon_disc

        img = Image.new("1", (400, 200), 0)
        draw = ImageDraw.Draw(img)
        render_moon_disc(img, draw, 200, 100, 40, 14.7, MoonTones(lit=1, dark=0, edge=1))
        x0, y0, x1, y1 = img.getbbox()
        assert abs((x0 + x1) // 2 - 200) <= 2
        assert abs((y0 + y1) // 2 - 100) <= 2


class TestTextStaysInsideTheFrame:
    """A long quote, author and weather description stay inside the plate's frame."""

    LONG_QUOTE = (
        "The most dangerous phrase in the language is 'we have always done it this way', "
        "and the second most dangerous is the confident assumption that whatever worked "
        "last season will keep working simply because nobody has yet bothered to check."
    )
    LONG_AUTHOR = "Rear Admiral Grace Brewster Murray Hopper of the United States Navy Reserve"

    def _texts(self, tmp_path, author: str, text: str = LONG_QUOTE):
        path = tmp_path / "quotes.json"
        path.write_text(json.dumps([{"text": text, "author": author}]))
        weather = _make_weather(current_description="heavy intensity shower rain and drizzle")
        img = Image.new("L", (800, 480), 0)
        draw = ImageDraw.Draw(img)
        calls = record_text(draw)
        draw_moonphase(
            draw,
            _make_data(weather=weather),
            TODAY,
            image=img,
            style=_dark_style(),
            quotes_path=str(path),
        )
        # The data lines and the quote: everything set below the moon row.
        return [(text, box) for text, box in calls if box[1] > 300]

    def test_lines_fit_the_quote_column(self, tmp_path):
        texts = self._texts(tmp_path, "Hopper")
        assert texts
        for text, (x0, _y0, x1, _y1) in texts:
            assert x0 >= 30 and x1 <= 770, f"{text!r} runs to x={x0}..{x1}"
        cut = [t for t, _ in texts if t.endswith("...")]
        assert any("sunrise" in t for t in cut), "the weather line's cut is not marked"
        assert any("sunrise" not in t for t in cut), "the quote's cut is not marked"

    def test_a_long_attribution_fits_the_quote_column(self, tmp_path):
        texts = self._texts(tmp_path, self.LONG_AUTHOR, text="Short.")
        attribution = [(t, box) for t, box in texts if t.startswith("—")]
        assert len(attribution) == 1, "a short quote leaves room for its attribution"
        text, (x0, _y0, x1, _y1) = attribution[0]
        assert text.endswith("...") and x0 >= 30 and x1 <= 770

    @pytest.mark.parametrize("author", ["Plato", "Gregory"])
    def test_an_attribution_shows_whatever_its_letters(self, tmp_path, author):
        """A short quote leaves room for its attribution, descenders or not."""
        texts = self._texts(tmp_path, author, text="Short.")
        assert [t for t, _ in texts if t.startswith("—")] == [f"— {author}"]
        for text, (_x0, _y0, _x1, y1) in texts:
            assert y1 < 480 - 8 - 1, f"{text!r} reaches y={y1}, onto the frame"

    def test_a_two_line_quote_keeps_its_attribution(self, tmp_path):
        """Even spacing leaves a two-line quote's attribution a pixel short of room
        above the frame; it closes the gap rather than being dropped."""
        quote = (
            "In a universe of blind physical forces and genetic replication, some people "
            "are going to get hurt, other people are going to get lucky, and you won't "
            "find any rhyme or reason in it."
        )
        texts = self._texts(tmp_path, "Gregory", text=quote)
        assert [t for t, _ in texts if t.startswith("—")] == ["— Gregory"]
        for text, (_x0, _y0, _x1, y1) in texts:
            assert y1 < 480 - 8 - 1, f"{text!r} reaches y={y1}, onto the frame"

    def test_nothing_is_set_on_the_frame(self, tmp_path):
        texts = self._texts(tmp_path, self.LONG_AUTHOR)
        for text, (_x0, _y0, _x1, y1) in texts:
            # The themes' vine border is the rectangle drawn 8 px in.
            assert y1 < 480 - 8 - 1, f"{text!r} reaches y={y1}, onto the frame"
