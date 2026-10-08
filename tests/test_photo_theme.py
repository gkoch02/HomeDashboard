"""Tests for the photo theme and the load_and_dither_image() utility.

Covers:
- load_and_dither_image() produces a 1-bit image of the correct size
- load_and_dither_image() inverts values for dark-canvas (bg=0) themes
- _draw_photo_background() with an empty path is a no-op
- _draw_photo_background() with a missing path logs a warning without error
- _draw_photo_background() with a valid image pastes onto the canvas
- _draw_photo_background() on an RGB canvas (Inky) quantizes to palette colors via Bayer
- on the four-ink Waveshare G the photo is left to the backend to dither onto its inks
- photo_theme() factory returns a correctly configured Theme object
- photo theme is registered in AVAILABLE_THEMES and loads correctly
- photo theme is excluded from the random rotation pool
- render_dashboard() with the photo theme produces a valid 1-bit image
- render_dashboard() with photo theme on Inky produces RGB image with palette-only pixels
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.primitives import load_and_dither_image
from src.render.quantize import blend_inky_palette, flatten_pixels
from src.render.theme import AVAILABLE_THEMES, ThemeLayout, ThemeStyle, load_theme
from src.render.themes.photo import _draw_photo_background, photo_theme
from tests.inkutils import ink

INKY = DisplayConfig(provider="inky", model="impression_7_3_2025")
WAVESHARE_G = DisplayConfig(provider="waveshare", model="epd10in85g")

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

    def test_a_photo_of_another_shape_is_cropped_not_squashed(self, tmp_path: Path):
        """A square photo with a black top quarter, onto a 4:1 plate: cropping to fill
        keeps the centre band, which is all white; stretching would squash the black
        quarter into the plate's top rows."""
        img = Image.new("L", (100, 100), 255)
        img.paste(0, (0, 0, 100, 25))
        p = tmp_path / "square.png"
        img.save(p)
        result = load_and_dither_image(str(p), (200, 50), fg=0, bg=1)
        assert ink(result) == 0

    def test_exif_orientation_is_honoured(self, tmp_path: Path):
        """A landscape frame tagged "rotate 90° CW" (as a phone writes a portrait
        shot) shows upright: its black left half becomes the top half."""
        img = Image.new("L", (100, 50), 255)
        img.paste(0, (0, 0, 50, 50))
        exif = Image.Exif()
        exif[0x0112] = 6
        p = tmp_path / "portrait.jpg"
        img.save(p, exif=exif, quality=95)
        result = load_and_dither_image(str(p), (50, 100), fg=0, bg=1)
        assert ink(result, (0, 0, 50, 45)) > 0.9 * 50 * 45
        assert ink(result, (0, 55, 50, 100)) < 0.05 * 50 * 45

    def test_missing_file_raises(self):
        with pytest.raises((FileNotFoundError, OSError)):
            load_and_dither_image("/nonexistent/path/image.jpg", (100, 100), fg=0, bg=1)


# ---------------------------------------------------------------------------
# _draw_photo_background
# ---------------------------------------------------------------------------


class TestDrawPhotoBackground:
    def _make_canvas(self, mode: str = "1") -> Image.Image:
        fill = 1 if mode == "1" else (255, 255, 255) if mode == "RGB" else 255
        return Image.new(mode, (800, 480), fill)

    def _make_layout(self) -> ThemeLayout:
        return ThemeLayout(canvas_w=800, canvas_h=480)

    def _make_style(self, path: str = "") -> ThemeStyle:
        s = ThemeStyle(fg=0, bg=1)
        s.photo_path = path
        return s

    @staticmethod
    def _draw(canvas, layout, style):
        """The photo background as the canvas would call it: Inky for RGB, mono otherwise."""
        config = INKY if canvas.mode == "RGB" else DisplayConfig()
        return _draw_photo_background(canvas, layout, style, config)

    def test_empty_path_is_noop(self):
        """With no path set the canvas should remain untouched."""
        canvas = self._make_canvas()
        original_bytes = canvas.tobytes()
        self._draw(canvas, self._make_layout(), self._make_style(path=""))
        assert canvas.tobytes() == original_bytes

    def test_inky_path_crops_rather_than_stretches(self, tmp_path: Path):
        """The RGB path crops to fill as the 1-bit one does: a square photo whose top
        quarter is black leaves no black once its centre band fills a 5:3 plate."""
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img.paste((0, 0, 0), (0, 0, 100, 18))
        p = tmp_path / "square.png"
        img.save(p)
        canvas = self._make_canvas("RGB")
        self._draw(canvas, self._make_layout(), self._make_style(path=str(p)))
        assert (0, 0, 0) not in set(flatten_pixels(canvas))

    def test_missing_file_logs_warning(self, caplog):
        canvas = self._make_canvas()
        layout = self._make_layout()
        style = self._make_style(path="/nonexistent/does_not_exist.jpg")
        with caplog.at_level(logging.WARNING):
            self._draw(canvas, layout, style)
        assert any("not found" in record.message for record in caplog.records)

    def test_missing_file_leaves_the_canvas_untouched(self):
        canvas = self._make_canvas()
        before = canvas.tobytes()
        layout = self._make_layout()
        style = self._make_style(path="/nonexistent/does_not_exist.jpg")
        self._draw(canvas, layout, style)
        assert canvas.tobytes() == before

    def test_valid_image_pastes_onto_canvas(self, grey_png: Path):
        """After pasting a grey image, the canvas should no longer be all-white."""
        canvas = self._make_canvas()
        layout = self._make_layout()
        style = self._make_style(path=str(grey_png))
        self._draw(canvas, layout, style)
        # After dithering a mid-grey image onto a white canvas we expect some black pixels
        # A purely white canvas would have all bytes == 0xFF; mixed dithering produces others.
        assert canvas.tobytes() != bytes([0xFF] * len(canvas.tobytes()))

    def test_rgb_canvas_pastes_color_image(self, grey_png: Path):
        """On an RGB canvas (Inky path), the photo is quantized to palette colors, not 1-bit."""
        canvas = self._make_canvas(mode="RGB")
        layout = self._make_layout()
        style = self._make_style(path=str(grey_png))
        self._draw(canvas, layout, style)
        assert canvas.mode == "RGB"
        # The canvas should have been modified (no longer all-white)
        white_canvas = bytes([255] * len(canvas.tobytes()))
        assert canvas.tobytes() != white_canvas

    def test_rgb_canvas_falls_back_to_bayer_when_pil_quantize_scrambles_palette(
        self, grey_png: Path, caplog
    ):
        """If PIL's FS quantize produces pixels outside the blended palette, the
        photo theme should fall back to the Bayer path."""
        canvas = self._make_canvas(mode="RGB")
        layout = self._make_layout()
        style = self._make_style(path=str(grey_png))

        # Produce an image that deliberately has a pixel outside the blended palette,
        # so the "set(flatten_pixels(fs_result)) <= blended_set" check fails.
        bad_fs = Image.new("RGB", (800, 480), (42, 42, 42))

        with patch.object(
            Image.Image,
            "quantize",
            lambda self, **kw: bad_fs.convert("P"),
        ):
            with caplog.at_level(logging.DEBUG, logger="src.render.themes.photo"):
                self._draw(canvas, layout, style)

        # After the fallback, the canvas pixels must all be blended palette colours.
        palette_set = set(blend_inky_palette(0.25))
        assert set(flatten_pixels(canvas)) <= palette_set

    def test_exception_during_load_is_logged_and_swallowed(self, caplog, grey_png: Path):
        """An unexpected exception inside the dither path should log and not propagate."""
        canvas = self._make_canvas()
        layout = self._make_layout()
        style = self._make_style(path=str(grey_png))

        with patch(
            "src.render.primitives.load_and_dither_image",
            side_effect=RuntimeError("dither broke"),
        ):
            with caplog.at_level(logging.WARNING, logger="src.render.themes.photo"):
                self._draw(canvas, layout, style)

        assert any("failed to load image" in rec.message for rec in caplog.records)

    def test_rgb_canvas_pixels_are_palette_colors(self, grey_png: Path):
        """All pixels on the RGB canvas should be one of the 6 blended Inky palette colors.

        The photo theme now uses blend_inky_palette(0.25) as the quantization reference
        (matching Pimoroni's InkyE673._palette_blend(saturation=0.5) approach) rather than
        the raw SATURATED palette, so we check against the blended colors.
        """
        from src.render.quantize import blend_inky_palette, flatten_pixels

        canvas = self._make_canvas(mode="RGB")
        layout = self._make_layout()
        style = self._make_style(path=str(grey_png))
        self._draw(canvas, layout, style)
        palette_set = set(blend_inky_palette(0.25))
        pixels = set(flatten_pixels(canvas))
        assert pixels <= palette_set


# ---------------------------------------------------------------------------
# photo_theme factory
# ---------------------------------------------------------------------------


class TestPhotoThemeFactory:
    def test_name(self):
        assert photo_theme().name == "photo"

    def test_has_background_fn(self):
        assert photo_theme().layout.background_fn is not None

    def test_draw_order_is_empty(self):
        assert photo_theme().layout.draw_order == []

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

    def test_renders_inky_rgb_with_color_photo(self, gradient_png: Path):
        """Photo theme on an Inky RGB display should produce an RGB image with palette colors.

        Pixels must be from blend_inky_palette(0.25) — the quantization reference used by
        the photo theme (matching Pimoroni's InkyE673._palette_blend(saturation=0.5)).
        InkyDisplay.show() maps these back to the correct hardware indices via Euclidean
        nearest-color against device.SATURATED_PALETTE.
        """
        from src.render.quantize import blend_inky_palette, flatten_pixels

        data = self._dummy_data()
        theme = load_theme("photo")
        theme.style.photo_path = str(gradient_png)
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        img = render_dashboard(data, cfg, title="Test", theme=theme)
        assert img.mode == "RGB"
        palette_set = set(blend_inky_palette(0.25))
        # All pixels in the photo region (above the header bar) must be blended palette colors
        pixels = set(flatten_pixels(img.crop((0, 0, img.width, img.height - 50))))
        assert pixels <= palette_set


class TestPhotoOnWaveshareG:
    """The four-ink G panel has no blue or green; the photo must dither onto its own inks."""

    @pytest.fixture
    def sky_and_foliage(self, tmp_path: Path) -> Path:
        """Mid-tone sky blue over mid-tone foliage green, light enough to need no black."""
        img = Image.new("RGB", (800, 480))
        img.paste((110, 160, 200), (0, 0, 800, 240))
        img.paste((90, 150, 70), (0, 240, 800, 480))
        p = tmp_path / "landscape.png"
        img.save(p)
        return p

    def _render(self, path: Path) -> Image.Image:
        from datetime import datetime

        theme = load_theme("photo")
        theme.style.photo_path = str(path)
        data = generate_dummy_data(now=datetime(2026, 4, 5, 10, 30))
        return render_dashboard(data, WAVESHARE_G, title="Test", theme=theme)

    def test_uses_only_the_panel_inks(self, sky_and_foliage: Path):
        from src.display.driver import WAVESHARE_G_PALETTE

        img = self._render(sky_and_foliage).convert("RGB")
        assert set(flatten_pixels(img)) <= set(WAVESHARE_G_PALETTE)

    def test_blue_and_green_keep_their_tone(self, sky_and_foliage: Path):
        """Each half keeps the source's lightness instead of collapsing toward black.

        Dithering against the Spectra 6 blue and green first, then snapping them to
        black, took the foliage band from a mean grey of ~120 to ~60.
        """
        from PIL import ImageStat

        source = Image.open(sky_and_foliage).convert("L")
        out = self._render(sky_and_foliage).convert("L")
        for band in ((0, 0, 800, 240), (0, 240, 800, 480)):
            want = ImageStat.Stat(source.crop(band)).mean[0]
            got = ImageStat.Stat(out.crop(band)).mean[0]
            assert abs(got - want) < 25, (band, want, got)

    def test_returns_the_full_canvas_as_art(self, sky_and_foliage: Path):
        canvas = Image.new("RGB", (800, 480), (255, 255, 255))
        style = ThemeStyle(fg=0, bg=1)
        style.photo_path = str(sky_and_foliage)
        layout = ThemeLayout(canvas_w=800, canvas_h=480)
        assert _draw_photo_background(canvas, layout, style, WAVESHARE_G) == [(0, 0, 800, 480)]
