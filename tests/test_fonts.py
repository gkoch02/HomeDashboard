"""Tests for src/render/fonts.py — font loader functions."""

from PIL import ImageFont

from src.render.fonts import (
    bold,
    medium,
    regular,
    semibold,
    weather_icon,
)


class TestFontAccessors:
    """Smoke tests — verify each font accessor loads without error."""

    def test_regular(self):
        assert isinstance(regular(12), ImageFont.FreeTypeFont)

    def test_medium(self):
        assert isinstance(medium(12), ImageFont.FreeTypeFont)

    def test_semibold(self):
        assert isinstance(semibold(12), ImageFont.FreeTypeFont)

    def test_bold(self):
        assert isinstance(bold(12), ImageFont.FreeTypeFont)

    def test_weather_icon(self):
        assert isinstance(weather_icon(20), ImageFont.FreeTypeFont)

    def test_caching_returns_same_object(self):
        """@lru_cache should return the same object on repeated calls."""
        f1 = regular(12)
        f2 = regular(12)
        assert f1 is f2


class TestGetVariableFont:
    """Test _get_variable_font (lines 15-17) via a mock that supports variation axes."""

    def test_get_variable_font_calls_set_variation_by_axes(self):
        from unittest.mock import MagicMock, patch
        from src.render.fonts import _get_variable_font

        mock_font = MagicMock()
        mock_font.set_variation_by_axes = MagicMock()

        with patch("src.render.fonts.ImageFont.truetype", return_value=mock_font):
            _get_variable_font.cache_clear()
            result = _get_variable_font("SomeFontVariable.ttf", 14, 600)

        mock_font.set_variation_by_axes.assert_called_once_with([600])
        assert result is mock_font

    def test_get_variable_font_is_cached(self):
        from unittest.mock import MagicMock, patch
        from src.render.fonts import _get_variable_font

        mock_font = MagicMock()
        mock_font.set_variation_by_axes = MagicMock()

        with patch("src.render.fonts.ImageFont.truetype", return_value=mock_font):
            _get_variable_font.cache_clear()
            f1 = _get_variable_font("CachedFont.ttf", 12, 400)
            f2 = _get_variable_font("CachedFont.ttf", 12, 400)

        assert f1 is f2
