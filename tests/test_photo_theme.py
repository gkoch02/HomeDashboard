"""Tests for the photo theme and the load_and_dither_image() utility.

Covers:
- load_and_dither_image() produces a 1-bit image of the correct size
- load_and_dither_image() inverts values for dark-canvas (bg=0) themes
- _draw_photo_background() with an empty path is a no-op
- _draw_photo_background() with a missing path logs a warning without error
- _draw_photo_background() with a valid image pastes onto the canvas
- photo_theme() factory returns a correctly configured Theme object
- photo theme is registered in AVAILABLE_THEMES and loads correctly
- photo theme is excluded from the random rotation pool
- render_dashboard() with the photo theme produces a valid 1-bit image
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.primitives import load_and_dither_image
from src.render.theme import AVAILABLE_THEMES, ThemeLayout, ThemeStyle, load_theme
from src.render.themes.photo import _draw_photo_background, photo_theme

FIXED_NOW_STR = "2026-04-05T10:30:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def grey_png(tmp_path: Path) -> Path:
    """Write a small grey PNG and return its path."""
    img = Image.new("RGB", (200, 120), (128, 128, 128))
    p = tmp_path / "test.png"
    img.save(p)
    return p


@pytest.fixture
def gradient_png(tmp_path: Path) -> Path:
    """Write a 256×256 gradient PNG and return its path."""
    img = Image.new("L", (256, 256))
    for y in range(256):
        for x in range(256):
            img.putpixel((x, y), (x + y) // 2)
    p = tmp_path / "gradient.png"
    img.save(p)
    return p


# ---------------------------------------------------------------------------
# load_and_dither_image
# ---------------------------------------------------------------------------


class TestLoadAndDitherImage:
    def test_returns_1bit_image(self, grey_png: Path):
        result = load_and_dither_image(str(grey_png), (100, 60), fg=0, bg=1)
        assert result.mode == "1"

    def test_correct_size(self, grey_png: Path):
        size = (320, 200)
        result = load_and_dither_image(str(grey_png), size, fg=0, bg=1)
        assert result.size == size

    def test_default_canvas_size(self, gradient_png: Path):
        result = load_and_dither_image(str(gradient_png), (800, 480), fg=0, bg=1)
        assert result.size == (800, 480)
        assert result.mode == "1"

    def test_dark_canvas_inverts_values(self, tmp_path: Path):
        """A pure-white image on a dark canvas (bg=0) should produce all-black pixels."""
        white_img = Image.new("RGB", (8, 8), (255, 255, 255))
        p = tmp_path / "white.png"
        white_img.save(p)
        # On a dark canvas, bright areas are inverted → all pixels should be 0 (black)
        result = load_and_dither_image(str(p), (8, 8), fg=1, bg=0)
        # 8×8 has no row-padding; every byte should be 0x00 (all black)
        assert result.tobytes() == bytes(len(result.tobytes()))

    def test_light_canvas_preserves_white(self, tmp_path: Path):
        """A pure-white image on a light canvas (bg=1) should remain white."""
        white_img = Image.new("RGB", (8, 8), (255, 255, 255))
        p = tmp_path / "white.png"
        white_img.save(p)
        result = load_and_dither_image(str(p), (8, 8), fg=0, bg=1)
        # 8×8 has no row-padding bits; every pixel should be white (1)
        assert result.tobytes() == bytes([0xFF] * len(result.tobytes()))

    def test_missing_file_raises(self):
        with pytest.raises((FileNotFoundError, OSError)):
            load_and_dither_image("/nonexistent/path/image.jpg", (100, 100), fg=0, bg=1)


# ---------------------------------------------------------------------------
# _draw_photo_background
# ---------------------------------------------------------------------------


class TestDrawPhotoBackground:
    def _make_canvas(self) -> Image.Image:
        return Image.new("1", (800, 480), 1)

    def _make_layout(self) -> ThemeLayout:
        return ThemeLayout(canvas_w=800, canvas_h=480)

    def _make_style(self, path: str = "") -> ThemeStyle:
        s = ThemeStyle(fg=0, bg=1)
        s.photo_path = path
        return s

    def test_empty_path_is_noop(self):
        """With no path set the canvas should remain untouched."""
        canvas = self._make_canvas()
        original_bytes = canvas.tobytes()
        _draw_photo_background(canvas, self._make_layout(), self._make_style(path=""))
        assert canvas.tobytes() == original_bytes

    def test_missing_file_logs_warning(self, caplog):
        canvas = self._make_canvas()
        layout = self._make_layout()
        style = self._make_style(path="/nonexistent/does_not_exist.jpg")
        with caplog.at_level(logging.WARNING):
            _draw_photo_background(canvas, layout, style)
        assert any("not found" in record.message for record in caplog.records)

    def test_missing_file_does_not_raise(self):
        canvas = self._make_canvas()
        layout = self._make_layout()
        style = self._make_style(path="/nonexistent/does_not_exist.jpg")
        _draw_photo_background(canvas, layout, style)  # must not raise

    def test_valid_image_pastes_onto_canvas(self, grey_png: Path):
        """After pasting a grey image, the canvas should no longer be all-white."""
        canvas = self._make_canvas()
        layout = self._make_layout()
        style = self._make_style(path=str(grey_png))
        _draw_photo_background(canvas, layout, style)
        # After dithering a mid-grey image onto a white canvas we expect some black pixels
        # A purely white canvas would have all bytes == 0xFF; mixed dithering produces others.
        assert canvas.tobytes() != bytes([0xFF] * len(canvas.tobytes()))


# ---------------------------------------------------------------------------
# photo_theme factory
# ---------------------------------------------------------------------------


class TestPhotoThemeFactory:
    def test_name(self):
        assert photo_theme().name == "photo"

    def test_has_background_fn(self):
        assert photo_theme().layout.background_fn is not None

    def test_draw_order_is_header_only(self):
        assert photo_theme().layout.draw_order == ["header"]

    def test_header_at_bottom(self):
        theme = photo_theme()
        header = theme.layout.header
        # Bottom 50 px of 480-px canvas
        assert header.y == 480 - 50
        assert header.h == 50

    def test_invert_header_true(self):
        assert photo_theme().style.invert_header is True

    def test_show_borders_false(self):
        assert photo_theme().style.show_borders is False


# ---------------------------------------------------------------------------
# Theme registry
# ---------------------------------------------------------------------------


class TestPhotoThemeRegistry:
    def test_in_available_themes(self):
        assert "photo" in AVAILABLE_THEMES

    def test_load_theme_returns_photo_theme(self):
        theme = load_theme("photo")
        assert theme.name == "photo"

    def test_excluded_from_random_pool(self):
        from src.render.random_theme import _EXCLUDED_FROM_POOL

        assert "photo" in _EXCLUDED_FROM_POOL


# ---------------------------------------------------------------------------
# render_dashboard smoke tests
# ---------------------------------------------------------------------------


class TestPhotoThemeRendering:
    def _dummy_data(self):
        from datetime import datetime

        return generate_dummy_data(now=datetime(2026, 4, 5, 10, 30))

    def test_renders_without_photo_path(self):
        """Photo theme with no path set should render a plain white canvas + header."""
        data = self._dummy_data()
        theme = load_theme("photo")
        img = render_dashboard(data, DisplayConfig(), title="Test", theme=theme)
        assert img.mode == "1"
        assert img.size == (800, 480)

    def test_renders_with_valid_photo(self, gradient_png: Path):
        """Photo theme with a valid path should render without error."""
        data = self._dummy_data()
        theme = load_theme("photo")
        theme.style.photo_path = str(gradient_png)
        img = render_dashboard(data, DisplayConfig(), title="Test", theme=theme)
        assert img.mode == "1"
        assert img.size == (800, 480)

    def test_renders_with_missing_photo(self):
        """Photo theme with a bad path should gracefully fall back to plain canvas."""
        data = self._dummy_data()
        theme = load_theme("photo")
        theme.style.photo_path = "/nonexistent/image.jpg"
        img = render_dashboard(data, DisplayConfig(), title="Test", theme=theme)
        assert img.mode == "1"
        assert img.size == (800, 480)
