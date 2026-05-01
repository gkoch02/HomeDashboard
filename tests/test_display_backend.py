"""Tests for ``src.display.backend`` — the v5 Waveshare/Inky pipeline split."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.display.backend import (
    DisplayBackend,
    InkyBackend,
    WaveshareBackend,
    build_display_backend,
)


def _layout(canvas_w=800, canvas_h=480, mode="1", preferred_quant=None):
    layout = MagicMock()
    layout.canvas_w = canvas_w
    layout.canvas_h = canvas_h
    layout.canvas_mode = mode
    layout.preferred_quantization_mode = preferred_quant
    return layout


def _config(provider="waveshare", width=800, height=480, quant="threshold"):
    cfg = MagicMock()
    cfg.provider = provider
    cfg.width = width
    cfg.height = height
    cfg.quantization_mode = quant
    return cfg


# ---------------------------------------------------------------------------
# build_display_backend
# ---------------------------------------------------------------------------


class TestBuildDisplayBackend:
    def test_waveshare(self):
        backend = build_display_backend(_config(provider="waveshare"))
        assert isinstance(backend, WaveshareBackend)
        assert isinstance(backend, DisplayBackend)

    def test_inky(self):
        backend = build_display_backend(_config(provider="inky"))
        assert isinstance(backend, InkyBackend)
        assert isinstance(backend, DisplayBackend)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown display provider"):
            build_display_backend(_config(provider="oled"))


# ---------------------------------------------------------------------------
# WaveshareBackend
# ---------------------------------------------------------------------------


class TestWaveshareBackend:
    def test_no_resize_no_quantize_for_1bit_canvas(self):
        backend = WaveshareBackend(_config())
        layout = _layout()
        image = Image.new("1", (800, 480), 1)
        out = backend.resize_and_finalize(image, canvas_size=(800, 480), layout=layout)
        # No resize ⇒ unchanged image (still mode "1").
        assert out.mode == "1"
        assert out.size == (800, 480)

    def test_resize_then_quantize_returns_1bit(self):
        backend = WaveshareBackend(_config(width=880, height=528))
        layout = _layout(canvas_w=800, canvas_h=480)
        image = Image.new("1", (800, 480), 1)
        out = backend.resize_and_finalize(image, canvas_size=(800, 480), layout=layout)
        assert out.size == (880, 528)
        assert out.mode == "1"

    def test_l_mode_canvas_is_quantized_even_without_resize(self):
        backend = WaveshareBackend(_config())
        layout = _layout(mode="L")
        image = Image.new("L", (800, 480), 255)
        out = backend.resize_and_finalize(image, canvas_size=(800, 480), layout=layout)
        assert out.mode == "1"

    def test_layout_quantization_mode_overrides_config(self):
        # Use "ordered" Bayer dithering instead of the configured "threshold".
        backend = WaveshareBackend(_config(quant="threshold"))
        layout = _layout(mode="L", preferred_quant="ordered")
        # Solid grey (128) — threshold = either all black or all white;
        # ordered Bayer = mix of both, so the histogram has two peaks.
        image = Image.new("L", (32, 32), 128)
        out = backend.resize_and_finalize(image, canvas_size=(32, 32), layout=layout)
        assert out.mode == "1"
        # Ordered dithering produces a checker — at least one black pixel exists.
        assert 0 in set(out.getdata())


# ---------------------------------------------------------------------------
# InkyBackend
# ---------------------------------------------------------------------------


class TestInkyBackend:
    def test_no_resize_passes_image_through(self):
        backend = InkyBackend(_config(provider="inky"))
        layout = _layout()
        image = Image.new("RGB", (800, 480), "white")
        out = backend.resize_and_finalize(image, canvas_size=(800, 480), layout=layout)
        assert out.size == (800, 480)
        assert out.mode == "RGB"

    def test_resize_converts_to_rgb(self):
        backend = InkyBackend(_config(provider="inky", width=400, height=240))
        layout = _layout()
        image = Image.new("RGB", (800, 480), "white")
        out = backend.resize_and_finalize(image, canvas_size=(800, 480), layout=layout)
        assert out.size == (400, 240)
        assert out.mode == "RGB"

    def test_no_pre_quantization_on_inky(self):
        """Inky relies on its own calibrated palette — backend must not snap colours."""
        backend = InkyBackend(_config(provider="inky"))
        layout = _layout()
        # A 50% grey RGB image must remain RGB greyscale tuples, not get
        # quantized to a 1-bit or palette-snapped image.
        image = Image.new("RGB", (16, 16), (128, 128, 128))
        out = backend.resize_and_finalize(image, canvas_size=(16, 16), layout=layout)
        assert out.mode == "RGB"
        assert (128, 128, 128) in set(out.getdata())
