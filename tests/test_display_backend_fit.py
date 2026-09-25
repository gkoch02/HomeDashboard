"""``display.scaling`` and the colour finalize step in ``src.display.backend``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.display.backend import (
    FIT_DISTORTION_THRESHOLD,
    InkyBackend,
    WaveshareBackend,
    WaveshareColorBackend,
    distortion,
    fit_canvas,
    pad_value,
    resolve_scaling,
)
from src.display.driver import WAVESHARE_G_PALETTE
from src.render.quantize import flatten_pixels

CANVAS = (800, 480)
PANORAMIC = (1360, 480)


def _layout(mode="1", preferred_quant=None):
    layout = MagicMock()
    layout.canvas_w, layout.canvas_h = CANVAS
    layout.canvas_mode = mode
    layout.preferred_quantization_mode = preferred_quant
    return layout


def _px(img, x, y):
    return img.convert("RGB").getpixel((x, y))


class TestResolveScaling:
    def test_same_shape_stretches(self):
        assert resolve_scaling("auto", CANVAS, (880, 528)) == "stretch"

    def test_mild_mismatch_still_stretches(self):
        """A 4:3 panel has always been stretched; auto must not change that."""
        assert distortion(CANVAS, (1600, 1200)) == pytest.approx(1.25)
        assert resolve_scaling("auto", CANVAS, (1600, 1200)) == "stretch"

    def test_panoramic_panel_fits(self):
        assert distortion(CANVAS, PANORAMIC) > FIT_DISTORTION_THRESHOLD
        assert resolve_scaling("auto", CANVAS, PANORAMIC) == "fit"

    def test_distortion_is_symmetric(self):
        assert distortion(CANVAS, PANORAMIC) == pytest.approx(distortion(PANORAMIC, CANVAS))

    def test_explicit_modes_win(self):
        assert resolve_scaling("stretch", CANVAS, PANORAMIC) == "stretch"
        assert resolve_scaling("fit", CANVAS, (1600, 1200)) == "fit"

    def test_unknown_value_behaves_as_auto(self):
        assert resolve_scaling("bogus", CANVAS, PANORAMIC) == "fit"
        assert resolve_scaling(MagicMock(), CANVAS, (1600, 1200)) == "stretch"


class TestPadValue:
    def test_one_bit_background_to_l(self):
        assert pad_value(1, "1", "L") == 255
        assert pad_value(0, "1", "L") == 0

    def test_l_background_to_rgb(self):
        assert pad_value(255, "L", "RGB") == (255, 255, 255)
        assert pad_value(40, "L", "RGB") == (40, 40, 40)

    def test_rgb_background_to_each_mode(self):
        assert pad_value((161, 164, 165), "RGB", "RGB") == (161, 164, 165)
        assert pad_value((161, 164, 165), "RGB", "L") == 163
        assert pad_value((161, 164, 165), "RGB", "1") == 1
        assert pad_value((0, 0, 0), "RGB", "1") == 0

    def test_none_is_white(self):
        assert pad_value(None, "1", "L") == 255
        assert pad_value(None, "L", "RGB") == (255, 255, 255)


class TestFitCanvas:
    def test_same_size_is_identity(self):
        img = Image.new("L", CANVAS, 0)
        assert fit_canvas(img, CANVAS, scaling="fit", background=255) is img

    def test_stretch_fills_the_target(self):
        img = Image.new("L", CANVAS, 0)
        out = fit_canvas(img, PANORAMIC, scaling="stretch", background=255)
        assert out.size == PANORAMIC
        assert out.getpixel((0, 240)) == 0
        assert out.getpixel((1359, 240)) == 0

    def test_fit_centres_on_a_padded_plate(self):
        """800x480 onto 1360x480: scale 1, content at x 280..1079, bands either side."""
        img = Image.new("L", CANVAS, 0)
        out = fit_canvas(img, PANORAMIC, scaling="fit", background=255)
        assert out.size == PANORAMIC
        assert out.getpixel((279, 240)) == 255
        assert out.getpixel((280, 240)) == 0
        assert out.getpixel((1079, 240)) == 0
        assert out.getpixel((1080, 240)) == 255

    def test_fit_pads_with_the_given_background(self):
        img = Image.new("RGB", CANVAS, (255, 255, 255))
        out = fit_canvas(img, PANORAMIC, scaling="fit", background=(0, 0, 0))
        assert out.getpixel((10, 10)) == (0, 0, 0)
        assert out.getpixel((680, 240)) == (255, 255, 255)

    def test_fit_letterboxes_a_panoramic_canvas_onto_a_landscape_panel(self):
        img = Image.new("L", PANORAMIC, 0)
        out = fit_canvas(img, CANVAS, scaling="fit", background=255)
        assert out.size == CANVAS
        # 1360x480 at scale 800/1360 → 800x282, centred: rows 99..380 are content.
        assert out.getpixel((400, 90)) == 255
        assert out.getpixel((400, 240)) == 0
        assert out.getpixel((400, 390)) == 255


class TestWaveshareBackendScaling:
    def test_auto_fit_on_panoramic_panel_keeps_1bit_output(self):
        cfg = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
        img = Image.new("1", CANVAS, 0)
        out = WaveshareBackend(cfg).resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout(), background=1
        )
        assert out.mode == "1"
        assert out.size == PANORAMIC
        assert _px(out, 10, 240) == (255, 255, 255)
        assert _px(out, 680, 240) == (0, 0, 0)

    def test_dark_theme_pads_with_ink(self):
        cfg = DisplayConfig(model="epd7in5_V2", width=1360, height=480)
        img = Image.new("1", CANVAS, 1)
        out = WaveshareBackend(cfg).resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout(), background=0
        )
        assert _px(out, 10, 240) == (0, 0, 0)
        assert _px(out, 680, 240) == (255, 255, 255)

    def test_explicit_stretch_is_honoured(self):
        cfg = DisplayConfig(model="epd7in5_V2", width=1360, height=480, scaling="stretch")
        img = Image.new("1", CANVAS, 0)
        out = WaveshareBackend(cfg).resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout(), background=1
        )
        assert _px(out, 10, 240) == (0, 0, 0)

    def test_inky_fit_pads_in_rgb(self):
        cfg = DisplayConfig(provider="inky", width=1360, height=480, scaling="fit")
        img = Image.new("RGB", CANVAS, (0, 0, 0))
        out = InkyBackend(cfg).resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout(), background=(161, 164, 165)
        )
        assert out.mode == "RGB"
        assert out.getpixel((10, 240)) == (161, 164, 165)
        assert out.getpixel((680, 240)) == (0, 0, 0)


class TestWaveshareColorBackend:
    def _cfg(self, **kw):
        return DisplayConfig(model="epd10in85g", width=1360, height=480, **kw)

    def _backend(self, **kw):
        return WaveshareColorBackend(self._cfg(**kw), WAVESHARE_G_PALETTE)

    def test_rgb_canvas_snaps_to_the_four_inks(self):
        img = Image.new("RGB", PANORAMIC, (255, 255, 255))
        img.putpixel((0, 0), (61, 59, 94))  # Spectra blue → black
        img.putpixel((1, 0), (58, 91, 70))  # Spectra green → black
        img.putpixel((2, 0), (156, 72, 75))  # Spectra red → red
        img.putpixel((3, 0), (208, 190, 71))  # Spectra yellow → yellow
        img.putpixel((4, 0), (100, 100, 100))  # dark grey → black
        img.putpixel((5, 0), (200, 200, 200))  # light grey → white
        out = self._backend().resize_and_finalize(
            img, canvas_size=PANORAMIC, layout=_layout(), background=(255, 255, 255)
        )
        assert out.mode == "RGB"
        assert [out.getpixel((x, 0)) for x in range(6)] == [
            (0, 0, 0),
            (0, 0, 0),
            (255, 0, 0),
            (255, 255, 0),
            (0, 0, 0),
            (255, 255, 255),
        ]
        assert set(flatten_pixels(out)) <= set(WAVESHARE_G_PALETTE)

    def test_rgb_canvas_is_fitted_before_the_snap(self):
        img = Image.new("RGB", CANVAS, (255, 0, 0))
        out = self._backend().resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout(), background=(255, 255, 255)
        )
        assert out.size == PANORAMIC
        assert out.getpixel((10, 240)) == (255, 255, 255)
        assert out.getpixel((680, 240)) == (255, 0, 0)

    def test_greyscale_canvas_takes_the_mono_pipeline(self):
        """An L plate is quantized with its own preferred mode, then promoted."""
        img = Image.new("L", PANORAMIC, 100)
        layout = _layout(mode="L", preferred_quant="threshold")
        out = self._backend().resize_and_finalize(
            img, canvas_size=PANORAMIC, layout=layout, background=255
        )
        assert out.mode == "RGB"
        assert set(flatten_pixels(out)) == {(0, 0, 0)}

    def test_greyscale_canvas_dithers_when_the_theme_asks(self):
        img = Image.new("L", PANORAMIC, 128)
        layout = _layout(mode="L", preferred_quant="floyd_steinberg")
        out = self._backend().resize_and_finalize(
            img, canvas_size=PANORAMIC, layout=layout, background=255
        )
        assert set(flatten_pixels(out)) == {(0, 0, 0), (255, 255, 255)}

    def test_one_bit_canvas_of_native_size_is_promoted_unchanged(self):
        img = Image.new("1", PANORAMIC, 1)
        img.putpixel((7, 7), 0)
        out = self._backend().resize_and_finalize(
            img, canvas_size=PANORAMIC, layout=_layout(), background=1
        )
        assert out.mode == "RGB"
        assert out.getpixel((7, 7)) == (0, 0, 0)
        assert out.getpixel((8, 7)) == (255, 255, 255)
