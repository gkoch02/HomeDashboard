"""``render_dashboard`` on the four-ink Waveshare panel."""

from __future__ import annotations

from datetime import datetime

from src.config import DisplayConfig
from src.display.driver import WAVESHARE_G_PALETTE
from src.dummy_data import generate_dummy_data
from src.render.canvas import (
    _is_color_display,
    _resolve_render_mode,
    _resolve_style,
    _style_palette,
    render_dashboard,
)
from src.render.quantize import INKY_SPECTRA6_PALETTE, WAVESHARE_G_STYLE_PALETTE, flatten_pixels
from src.render.theme import default_theme, load_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
G = DisplayConfig(model="epd10in85g", width=1360, height=480)


class TestDetection:
    def test_g_panel_is_a_colour_display(self):
        assert _is_color_display(G)
        assert _is_color_display(DisplayConfig(provider="inky", model="impression_7_3_2025"))

    def test_mono_and_unknown_are_not(self):
        assert not _is_color_display(DisplayConfig())
        assert not _is_color_display(DisplayConfig(model="epd_fake"))

    def test_render_mode_promotes_a_one_bit_theme_to_rgb(self):
        assert _resolve_render_mode("1", G) == "RGB"
        assert _resolve_render_mode("L", G) == "L"

    def test_style_palette_by_provider(self):
        assert _style_palette(G) is WAVESHARE_G_STYLE_PALETTE
        assert _style_palette(DisplayConfig(provider="inky")) is INKY_SPECTRA6_PALETTE


class TestStyleResolution:
    def test_missing_inks_fold_onto_black(self):
        """The default theme names blue and green roles; the panel has neither."""
        style = _resolve_style(default_theme(), "RGB", G)
        assert style.fg == (0, 0, 0)
        assert style.bg == (255, 255, 255)
        assert style.accent_info == (0, 0, 0)  # blue
        assert style.accent_good == (0, 0, 0)  # green
        assert style.accent_primary == (0, 0, 0)  # default registers blue primary
        assert style.accent_warn == (255, 255, 0)
        assert style.accent_alert == (255, 0, 0)
        assert style.accent_secondary == (255, 0, 0)  # ...and red secondary

    def test_inky_resolution_is_untouched(self):
        style = _resolve_style(
            default_theme(), "RGB", DisplayConfig(provider="inky", model="impression_7_3_2025")
        )
        assert style.accent_info == INKY_SPECTRA6_PALETTE[4]
        assert style.bg == INKY_SPECTRA6_PALETTE[1]


class TestRender:
    def test_landscape_theme_is_pillarboxed_in_palette_colours(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, G, theme=default_theme())
        assert img.mode == "RGB"
        assert img.size == (1360, 480)
        colours = set(flatten_pixels(img))
        assert colours <= set(WAVESHARE_G_PALETTE)
        assert (255, 0, 0) in colours  # the red accents survive
        # Bands either side of the 800-px content are the theme's white.
        assert img.getpixel((10, 240)) == (255, 255, 255)
        assert img.getpixel((1349, 240)) == (255, 255, 255)

    def test_panoramic_theme_fills_the_panel(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, G, theme=load_theme("wide_week"))
        assert img.size == (1360, 480)
        assert set(flatten_pixels(img)) <= set(WAVESHARE_G_PALETTE)
        # Ink reaches both ends: the header band is inverted across the width.
        assert img.getpixel((5, 20)) == (0, 0, 0)
        assert img.getpixel((1354, 20)) == (0, 0, 0)

    def test_greyscale_theme_keeps_its_dither_on_the_colour_panel(self):
        data = generate_dummy_data(now=FIXED_NOW)
        img = render_dashboard(data, G, theme=load_theme("halftone"))
        assert img.mode == "RGB"
        assert set(flatten_pixels(img)) <= set(WAVESHARE_G_PALETTE)
