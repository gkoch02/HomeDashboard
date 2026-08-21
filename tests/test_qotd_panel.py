"""Tests for src/render/components/qotd_panel.py.

Assertion discipline (see #229)
-------------------------------
The draw tests here asserted ``img.getbbox() is not None`` on a mode-``"1"``
plate filled with 1, where every pixel is non-zero and getbbox can never
return None. 32 of the 34 tests passed with both draw functions stubbed to
a no-op.

Ink means **zero-valued** pixels. The weather banner has fixed zone
boundaries, so each feature is measured in the zone it owns (icon and
temperature, conditions, forecast columns, moon glyph). For the quote panel
the measure is ``_text_line_heights``: one band of ink per rendered line,
whose height tracks the font size — which is how "this quote was set
larger" becomes something a test can check.

Verification: with ``draw_qotd`` and ``draw_qotd_weather`` stubbed to a
no-op, 27 of the 38 tests fail. Of the 11 survivors, 10 exercise pure
helpers (``_wrap_lines``, ``_icon_width``) or the theme's style and never
draw. The last, ``test_smoke_with_alerts``, asserts the plate does NOT
change, which a no-op satisfies by construction; it was checked by making
the banner draw an alert marker and confirming it goes red.
"""

import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from src.data.models import DayForecast, WeatherAlert, WeatherData
from src.render.components.qotd_panel import (
    _icon_width,
    _wrap_lines,
    draw_qotd,
    draw_qotd_weather,
)
from src.render.fonts import bold as jakarta_bold
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion
from src.render.themes.qotd import qotd_theme


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=68.0,
        current_icon="01d",
        current_description="clear sky",
        high=75.0,
        low=55.0,
        humidity=40,
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


TODAY = date(2026, 3, 22)


# ---------------------------------------------------------------------------
# _wrap_lines helper
# ---------------------------------------------------------------------------


class TestWrapLines:
    def _font(self, size: int = 20):
        return jakarta_bold(size)

    def test_short_text_fits_on_one_line(self):
        font = self._font()
        lines = _wrap_lines("Hello world", font, max_width=800)
        assert lines == ["Hello world"]

    def test_long_text_wraps_to_multiple_lines(self):
        font = self._font(20)
        long_text = " ".join(["word"] * 30)
        lines = _wrap_lines(long_text, font, max_width=200)
        assert len(lines) > 1

    def test_empty_string_returns_empty_list(self):
        font = self._font()
        lines = _wrap_lines("", font, max_width=400)
        assert lines == []

    def test_single_long_word_stays_on_one_line(self):
        """A single word that is too long to fit should still be placed on its own line."""
        font = self._font(20)
        lines = _wrap_lines("superlongword", font, max_width=1)
        assert len(lines) == 1
        assert lines[0] == "superlongword"

    def test_each_line_within_max_width(self):
        font = self._font(16)
        text = "This is a moderately long sentence that should wrap nicely into several lines."
        lines = _wrap_lines(text, font, max_width=200)
        for line in lines:
            assert font.getlength(line) <= 200 or " " not in line

    def test_preserves_all_words(self):
        font = self._font(20)
        words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
        text = " ".join(words)
        lines = _wrap_lines(text, font, max_width=150)
        reconstructed = " ".join(lines)
        assert reconstructed == text


# ---------------------------------------------------------------------------
# _icon_width helper
# ---------------------------------------------------------------------------


class TestIconWidth:
    def test_returns_positive_int(self):
        _, draw = _make_draw()
        width = _icon_width(draw, "01d", size=32)
        assert isinstance(width, int)
        assert width > 0

    def test_larger_size_gives_wider_result(self):
        _, draw = _make_draw()
        w_small = _icon_width(draw, "01d", size=16)
        w_large = _icon_width(draw, "01d", size=48)
        assert w_large > w_small

    def test_unknown_code_uses_fallback(self):
        """Unknown icon codes fall back to FALLBACK_ICON, still returning valid width."""
        _, draw = _make_draw()
        width = _icon_width(draw, "99z", size=32)
        assert width > 0


# ---------------------------------------------------------------------------
# Ink measurement
# ---------------------------------------------------------------------------


def _ink(img: Image.Image, box: tuple[int, int, int, int] | None = None) -> int:
    """Count ink (value-0) pixels, optionally only inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    if box is None:
        return sum(1 for v in px if v == 0)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _ink_x_extent(img: Image.Image, box: tuple[int, int, int, int]):
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    xs = [x for x in range(x0, x1) if any(px[y * width + x] == 0 for y in range(y0, y1))]
    return (xs[0], xs[-1] + 1) if xs else None


def _text_line_heights(img: Image.Image, box: tuple[int, int, int, int], min_h: int = 3):
    """Heights of the horizontal bands of ink inside *box*.

    A proxy for typography: one band per rendered text line, and each band's
    height tracks the font size. Lets "this quote was set larger" be measured
    rather than asserted by eye.
    """
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    hot = [any(px[y * width + x] == 0 for x in range(x0, x1)) for y in range(y0, y1)]
    runs = []
    start = None
    for i, is_hot in enumerate(hot):
        if is_hot and start is None:
            start = i
        elif not is_hot and start is not None:
            if i - start >= min_h:
                runs.append(i - start)
            start = None
    if start is not None and len(hot) - start >= min_h:
        runs.append(len(hot) - start)
    return runs


# The banner's zones, from draw_qotd_weather's own fixed boundaries.
QUOTE_REGION = ComponentRegion(0, 0, 800, 400)
BANNER_REGION = ComponentRegion(0, 400, 800, 80)
QUOTE_BOX = (0, 0, 800, 400)
Z1 = (14, 400, 185, 480)  # icon + temperature
Z2 = (185, 400, 430, 480)  # conditions text
Z3 = (430, 400, 760, 480)  # forecast columns
ZMOON = (760, 400, 800, 480)  # moon glyph


def _banner(weather, today=None, region=BANNER_REGION, style=None) -> Image.Image:
    img, draw = _make_draw()
    draw_qotd_weather(draw, weather, today, region=region, style=style)
    return img


def _quote(today=TODAY, region=QUOTE_REGION, **kwargs) -> Image.Image:
    img, draw = _make_draw()
    draw_qotd(draw, today, region=region, **kwargs)
    return img


def _with_quotes(quotes, tmp_path):
    """Context manager swapping in a custom quote store, cache cleared."""
    from src.render.components.info_panel import _quote_for_today

    qfile = tmp_path / "quotes.json"
    qfile.write_text(json.dumps(quotes))
    _quote_for_today.cache_clear()
    return patch("src.render.quotes.DEFAULT_QUOTES_PATH", qfile)


# ---------------------------------------------------------------------------
# draw_qotd
# ---------------------------------------------------------------------------


class TestDrawQotd:
    def test_renders_the_quote_and_its_attribution(self):
        """More than one text line: the quote body plus the attribution."""
        img = _quote()
        assert _ink(img, QUOTE_BOX) > 0
        assert len(_text_line_heights(img, QUOTE_BOX)) >= 2

    def test_smoke_various_dates(self):
        """Every date renders something, and not all dates render the same."""
        plates = set()
        for offset in range(6):
            img = _quote(TODAY + timedelta(days=offset))
            assert _ink(img, QUOTE_BOX) > 0
            plates.add(img.tobytes())
        assert len(plates) > 1, "the quote never changed across six days"

    def test_smoke_custom_region(self):
        """A smaller region gets a smaller text block, still inside its bounds."""
        small = ComponentRegion(0, 0, 400, 200)
        img = _quote(region=small)
        box = (0, 0, 400, 200)
        assert _ink(img, box) > 0
        assert _ink(img, (0, 200, 800, 480)) == 0, "the quote drew outside its region"

    def test_smoke_small_region_does_not_crash(self):
        """A region too small for any candidate size falls back rather than failing."""
        tiny = ComponentRegion(0, 0, 200, 80)
        img = _quote(region=tiny)
        assert _ink(img, (0, 0, 200, 80)) > 0, "the fallback path drew nothing"

    def test_long_quote_wraps_to_many_lines(self, tmp_path):
        """A very long quote triggers the fallback and wraps, capped at 8 lines."""
        long_text = " ".join(["extraordinary"] * 40)
        with _with_quotes([{"text": long_text, "author": "Verbose Author"}], tmp_path):
            img = _quote(date(2099, 1, 15))
        lines = _text_line_heights(img, QUOTE_BOX)
        assert len(lines) > 3, f"a 40-word quote did not wrap: {lines}"
        assert _ink(img, (0, 400, 800, 480)) == 0, "the quote overflowed its region"

    def test_short_quote_uses_larger_font(self, tmp_path):
        """A short quote is set larger than a long one — measured, not assumed.

        Font size shows up as the height of each band of ink, so the short
        quote's tallest line must beat the long quote's. The previous version
        of this test asserted `getbbox() is not None`, which says nothing
        about size.
        """
        with _with_quotes([{"text": "Be yourself.", "author": "A. Wise"}], tmp_path):
            short = _quote(date(2099, 2, 20))
        long_text = " ".join(["extraordinary"] * 40)
        with _with_quotes([{"text": long_text, "author": "Verbose Author"}], tmp_path):
            long_ = _quote(date(2099, 1, 15))

        short_lines = _text_line_heights(short, QUOTE_BOX)
        long_lines = _text_line_heights(long_, QUOTE_BOX)
        assert max(short_lines) > max(long_lines), (
            f"short quote not set larger: {max(short_lines)} vs {max(long_lines)}"
        )
        assert len(short_lines) < len(long_lines)

    def test_different_dates_produce_different_output(self, tmp_path):
        """Different dates select different quotes."""
        import hashlib

        quotes = [{"text": f"Quote number {i}.", "author": f"Author {i}"} for i in range(10)]
        with _with_quotes(quotes, tmp_path):
            renders = set()
            for i in range(10):
                img, draw = _make_draw()
                draw_qotd(draw, date(2099, 1, i + 1))
                renders.add(hashlib.md5(img.tobytes()).hexdigest())
        assert len(renders) > 1

    def test_qotd_theme_exposes_qotd_specific_accent_overrides(self):
        style = qotd_theme().style
        assert style.accent_primary == 4
        assert style.accent_info == 5


# ---------------------------------------------------------------------------
# draw_qotd_weather
# ---------------------------------------------------------------------------


class TestDrawQotdWeather:
    def test_smoke_none_weather(self):
        """The unavailable message is centred, and no zone content is drawn."""
        img = _banner(None)
        assert _ink(img, Z1) == 0, "an icon was drawn without weather"
        assert _ink(img, ZMOON) == 0, "a moon glyph was drawn without a date"
        extent = _ink_x_extent(img, (0, 400, 800, 480))
        assert extent is not None, "no message drawn"
        midpoint = (extent[0] + extent[1]) / 2
        assert abs(midpoint - 400) < 12, f"message off-centre: {midpoint}"

    def test_smoke_with_weather(self):
        """Icon + temperature land in zone 1, conditions in zone 2."""
        img = _banner(_make_weather())
        assert _ink(img, Z1) > 0, "no icon/temperature"
        assert _ink(img, Z2) > 0, "no conditions text"

    def test_smoke_with_weather_and_today(self):
        """today= adds the moon glyph in its reserved right-hand strip."""
        assert _ink(_banner(_make_weather(), TODAY), ZMOON) > 0
        assert _ink(_banner(_make_weather()), ZMOON) == 0

    def test_smoke_with_moon_phase(self):
        """The glyph tracks the phase, so two distant dates differ."""
        near_new = _ink(_banner(_make_weather(), date(2026, 3, 19)), ZMOON)
        near_full = _ink(_banner(_make_weather(), date(2026, 4, 2)), ZMOON)
        assert near_new > 0 and near_full > 0
        assert near_new != near_full, "the moon glyph is not derived from the date"

    def test_smoke_custom_region(self):
        """A shifted region moves the banner content with it."""
        moved = _banner(_make_weather(), region=ComponentRegion(0, 200, 800, 80))
        assert _ink(moved, (0, 200, 800, 280)) > 0
        assert _ink(moved, (0, 400, 800, 480)) == 0, "content stayed at the default offset"

    def test_smoke_with_forecast(self):
        """Forecast columns fill zone 3, which is empty without them."""
        forecast = [
            DayForecast(
                date=TODAY + timedelta(days=i + 1),
                high=70.0 + i,
                low=52.0,
                icon="01d",
                description="clear",
                precip_chance=0.1,
            )
            for i in range(3)
        ]
        assert _ink(_banner(_make_weather(forecast=forecast)), Z3) > 0
        assert _ink(_banner(_make_weather()), Z3) == 0

    def test_smoke_with_alerts(self):
        """This banner has no alert zone — alerts must not change the plate.

        Asserted as an equality because that is what is true: draw_qotd_weather
        never reads weather.alerts. The qotd theme surfaces alerts nowhere, so
        a change here would be a silent layout regression.
        """
        with_alert = _banner(_make_weather(alerts=[WeatherAlert(event="Heat Advisory")]))
        assert with_alert.tobytes() == _banner(_make_weather()).tobytes()

    def test_smoke_with_feels_like_and_wind(self):
        """The detail line grows when feels-like and wind are available."""
        detailed = _banner(_make_weather(feels_like=64.0, wind_speed=9.0, wind_deg=90.0))
        assert _ink(detailed, Z2) > _ink(_banner(_make_weather()), Z2)

    def test_smoke_with_humidity_only_detail(self):
        """With neither feels-like nor wind the line falls back to humidity."""
        humid_40 = _banner(_make_weather(humidity=40))
        humid_88 = _banner(_make_weather(humidity=88))
        assert _ink(humid_40, Z2) > 0
        assert _ink(humid_40, Z2) != _ink(humid_88, Z2), "the humidity fallback is not drawn"

    def test_none_weather_differs_from_with_weather(self):
        assert _banner(None).tobytes() != _banner(_make_weather()).tobytes()

    def test_smoke_night_icon(self):
        """A night icon is a different glyph from its day counterpart."""
        assert _ink(_banner(_make_weather(current_icon="01n")), Z1) != _ink(
            _banner(_make_weather(current_icon="01d")), Z1
        )

    def test_smoke_narrow_region(self):
        """A narrow region still renders and stays inside its own width."""
        narrow = ComponentRegion(0, 400, 300, 80)
        img = _banner(_make_weather(), region=narrow)
        assert _ink(img, (0, 400, 300, 480)) > 0
        extent = _ink_x_extent(img, (0, 400, 800, 480))
        assert extent is not None and extent[1] <= 300, "content spilled past the narrow region"

    @pytest.mark.parametrize("icon_code", ["01d", "02d", "03d", "04d", "09d", "10d", "11d", "13d"])
    def test_various_icon_codes(self, icon_code):
        """Every code draws an icon in zone 1."""
        assert _ink(_banner(_make_weather(current_icon=icon_code)), Z1) > 0

    def test_distinct_icon_codes_draw_distinct_glyphs(self):
        """The icon map is being consulted, not collapsed to one glyph."""
        inks = {
            code: _ink(_banner(_make_weather(current_icon=code)), Z1)
            for code in ("01d", "03d", "09d", "11d", "13d")
        }
        assert len(set(inks.values())) > 1, f"every icon rendered identically: {inks}"
