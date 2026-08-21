"""Tests for src/render/icons.py — OWM icon map and draw_weather_icon()."""

import pytest
from PIL import Image, ImageDraw

from src.render.icons import (
    FALLBACK_ICON,
    OWM_ICON_MAP,
    draw_weather_icon,
)
from src.render.quantize import flatten_pixels


def _make_draw(w: int = 200, h: int = 200):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


class TestOWMIconMap:
    # Expected OWM icon codes (9 day + 9 night = 18 total)
    _DAY_CODES = ["01d", "02d", "03d", "04d", "09d", "10d", "11d", "13d", "50d"]
    _NIGHT_CODES = ["01n", "02n", "03n", "04n", "09n", "10n", "11n", "13n", "50n"]

    def test_map_has_18_entries(self):
        assert len(OWM_ICON_MAP) == 18

    def test_all_day_codes_present(self):
        for code in self._DAY_CODES:
            assert code in OWM_ICON_MAP, f"Missing day code: {code}"

    def test_all_night_codes_present(self):
        for code in self._NIGHT_CODES:
            assert code in OWM_ICON_MAP, f"Missing night code: {code}"

    def test_all_values_are_nonempty_strings(self):
        for code, glyph in OWM_ICON_MAP.items():
            assert isinstance(glyph, str), f"Value for {code} is not a string"
            assert len(glyph) > 0, f"Empty glyph for {code}"

    def test_glyphs_are_unicode(self):
        """All glyphs should be single-character Unicode strings."""
        for code, glyph in OWM_ICON_MAP.items():
            assert len(glyph) == 1, f"Glyph for {code} should be single char, got {len(glyph)}"

    def test_clear_sky_day_glyph(self):
        assert OWM_ICON_MAP["01d"] == "\uf00d"

    def test_clear_sky_night_glyph(self):
        assert OWM_ICON_MAP["01n"] == "\uf02e"

    def test_scattered_clouds_same_day_and_night(self):
        """03d and 03n share the same glyph (no visual distinction)."""
        assert OWM_ICON_MAP["03d"] == OWM_ICON_MAP["03n"]

    def test_thunderstorm_same_day_and_night(self):
        """11d and 11n share the same thunderstorm glyph."""
        assert OWM_ICON_MAP["11d"] == OWM_ICON_MAP["11n"]

    def test_rain_day_differs_from_night(self):
        """10d (rain day) and 10n (rain night) should differ."""
        assert OWM_ICON_MAP["10d"] != OWM_ICON_MAP["10n"]


class TestFallbackIcon:
    def test_fallback_is_nonempty_string(self):
        assert isinstance(FALLBACK_ICON, str)
        assert len(FALLBACK_ICON) > 0

    def test_fallback_not_in_map_values(self):
        """The fallback icon should be distinct from normal map entries."""
        # This ensures it's visually distinguishable (N/A indicator)
        assert FALLBACK_ICON == "\uf07b"

    def test_fallback_not_used_for_valid_codes(self):
        """Valid icon codes should resolve to something other than the fallback."""
        for code in OWM_ICON_MAP:
            assert OWM_ICON_MAP[code] != FALLBACK_ICON


class TestDrawWeatherIcon:
    """Ink means zero-valued pixels; the plate is white, so getbbox on it
    reports the full canvas whether or not a glyph was drawn (#229)."""

    @staticmethod
    def _ink(img) -> int:
        return sum(1 for v in flatten_pixels(img) if v == 0)

    @staticmethod
    def _ink_bbox(img):
        px = flatten_pixels(img)
        width = img.width
        xs, ys = [], []
        for y in range(img.height):
            row = y * width
            for x in range(width):
                if px[row + x] == 0:
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None

    def _draw(self, code, size=48, fill=0, w=200, h=200):
        img, draw = _make_draw(w=w, h=h)
        draw_weather_icon(draw, (10, 10), code, size=size, fill=fill)
        return img

    def test_smoke_valid_code(self):
        """A known code puts a glyph on the plate, at the requested origin."""
        img = self._draw("01d")
        assert self._ink(img) > 0, "no glyph drawn"
        bbox = self._ink_bbox(img)
        assert bbox is not None and bbox[0] >= 10 and bbox[1] >= 10

    def test_smoke_unknown_code_uses_fallback(self):
        """Two different unknown codes render identically — and unlike a known one.

        That is what "uses the fallback" means; the previous assertion could
        not distinguish a fallback glyph from any other.
        """
        assert self._draw("99z").tobytes() == self._draw("qqq").tobytes()
        assert self._draw("99z").tobytes() != self._draw("01d").tobytes()

    def test_empty_code_uses_fallback(self):
        """An empty code takes the same path as an unrecognised one."""
        assert self._draw("").tobytes() == self._draw("99z").tobytes()

    def test_custom_size(self):
        """A larger size draws a proportionally larger glyph."""
        small = self._ink_bbox(self._draw("01d", size=48))
        large = self._ink_bbox(self._draw("01d", size=64, w=400, h=400))
        assert small is not None and large is not None
        assert (large[2] - large[0]) > (small[2] - small[0]), "size= did not widen the glyph"
        assert (large[3] - large[1]) > (small[3] - small[1]), "size= did not heighten the glyph"

    def test_small_size(self):
        """A 16px glyph is smaller than the 48px default, not merely present."""
        tiny = self._ink_bbox(self._draw("02d", size=16))
        default = self._ink_bbox(self._draw("02d", size=48))
        assert tiny is not None and default is not None
        assert (tiny[2] - tiny[0]) < (default[2] - default[0])

    def test_custom_fill_color(self):
        """Render with both fill=0 and fill=1, verify outputs differ."""
        img0, draw0 = _make_draw()
        draw_weather_icon(draw0, (20, 20), "01d", size=48, fill=0)

        img1, draw1 = _make_draw()
        draw_weather_icon(draw1, (20, 20), "01d", size=48, fill=1)

        # fill=0 (black on white) should differ from fill=1 (white on white)
        assert img0.tobytes() != img1.tobytes()

    @pytest.mark.parametrize("code", ["01d", "02d", "10d", "11n", "50n"])
    def test_various_valid_codes(self, code):
        """Each known code draws, and draws something other than the fallback."""
        img = self._draw(code)
        assert self._ink(img) > 0
        assert img.tobytes() != self._draw("99z").tobytes(), (
            f"{code} fell through to the fallback glyph"
        )

    def test_all_map_codes_render(self):
        """Every mapped code draws a glyph, and the map is not one glyph repeated."""
        inks = {}
        fallback = self._draw("99z").tobytes()
        for code in OWM_ICON_MAP:
            img = self._draw(code)
            assert self._ink(img) > 0, f"Failed to render icon for code {code}"
            assert img.tobytes() != fallback, f"{code} rendered as the fallback"
            inks[code] = self._ink(img)
        # Day/night pairs legitimately share a glyph, so this is a floor rather
        # than one-distinct-per-code.
        assert len(set(inks.values())) > len(OWM_ICON_MAP) // 2, (
            f"the icon map collapses to too few glyphs: {sorted(set(inks.values()))}"
        )
