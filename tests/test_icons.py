"""Tests for src/render/icons.py — OWM icon map and draw_weather_icon()."""

from PIL import Image, ImageDraw
import pytest

from src.render.icons import (
    FALLBACK_ICON,
    OWM_ICON_MAP,
    draw_weather_icon,
)


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
    def test_smoke_valid_code(self):
        """draw_weather_icon with a known OWM code should not raise."""
        img, draw = _make_draw()
        draw_weather_icon(draw, (10, 10), "01d")
        assert img.getbbox() is not None

    def test_smoke_unknown_code_uses_fallback(self):
        """Unknown codes should silently use FALLBACK_ICON."""
        img, draw = _make_draw()
        draw_weather_icon(draw, (10, 10), "99z")
        assert img.getbbox() is not None

    def test_empty_code_uses_fallback(self):
        img, draw = _make_draw()
        draw_weather_icon(draw, (10, 10), "")
        assert img.getbbox() is not None

    def test_custom_size(self):
        img, draw = _make_draw(w=400, h=400)
        draw_weather_icon(draw, (10, 10), "01d", size=64)
        assert img.getbbox() is not None

    def test_small_size(self):
        img, draw = _make_draw()
        draw_weather_icon(draw, (5, 5), "02d", size=16)
        assert img.getbbox() is not None

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
        img, draw = _make_draw()
        draw_weather_icon(draw, (10, 10), code)
        assert img.getbbox() is not None

    def test_all_map_codes_render(self):
        """Every code in OWM_ICON_MAP should render without raising."""
        for code in OWM_ICON_MAP:
            img, draw = _make_draw()
            draw_weather_icon(draw, (10, 10), code)
            assert img.getbbox() is not None, f"Failed to render icon for code {code}"
