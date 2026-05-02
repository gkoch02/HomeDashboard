"""Display backend abstraction.

The :class:`DisplayBackend` ABC unifies the post-render image pipeline that
v4 forked across two paths in ``canvas.py`` (and again in ``output.py``):

- :class:`WaveshareBackend` handles 1-bit eInk: resize via LANCZOS into a
  greyscale image, then quantize to ``"1"`` via the configured algorithm.
- :class:`InkyBackend` handles Spectra-6 colour: resize via LANCZOS in
  RGB and hand off to the Inky library for palette mapping at write time.

Adding a new display family is a single new backend subclass plus a
``build_display_backend`` branch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from src.config import DisplayConfig
from src.render.quantize import quantize_for_display


class DisplayBackend(ABC):
    """Backend-specific resize + finalize for a rendered canvas."""

    @abstractmethod
    def resize_and_finalize(
        self, image: Image.Image, *, canvas_size: tuple[int, int], layout
    ) -> Image.Image:
        """Resize *image* to the configured display size and finalize it.

        ``layout`` is the active ``ThemeLayout`` (used for canvas-mode and
        the optional ``preferred_quantization_mode``). Kept ``Any`` to
        avoid an import cycle on ``src.render.theme``.
        """


class WaveshareBackend(DisplayBackend):
    """1-bit eInk pipeline.

    LANCZOS-resizes onto an ``"L"`` canvas (so the dither input is grey),
    then quantizes to ``"1"`` using the configured algorithm.
    """

    def __init__(self, config: DisplayConfig):
        self._config = config

    def resize_and_finalize(
        self, image: Image.Image, *, canvas_size: tuple[int, int], layout
    ) -> Image.Image:
        target = (self._config.width, self._config.height)
        needs_resize = target != canvas_size
        if needs_resize:
            l_image = image if layout.canvas_mode == "L" else image.convert("L")
            image = l_image.resize(target, Image.Resampling.LANCZOS)
        # Quantize whenever a resize happened (LANCZOS produces grey pixels)
        # or the canvas itself was rendered in greyscale.
        if needs_resize or layout.canvas_mode == "L":
            quant_mode = layout.preferred_quantization_mode or self._config.quantization_mode
            image = quantize_for_display(image, quant_mode)
        return image


class InkyBackend(DisplayBackend):
    """Inky Spectra-6 pipeline.

    Pre-quantization is intentionally skipped — the Inky library performs
    its own calibrated palette mapping at write time, and pre-quantizing
    with an approximated palette would snap LANCZOS grey pixels onto the
    wrong physical ink.
    """

    def __init__(self, config: DisplayConfig):
        self._config = config

    def resize_and_finalize(
        self, image: Image.Image, *, canvas_size: tuple[int, int], layout
    ) -> Image.Image:
        target = (self._config.width, self._config.height)
        if target != canvas_size:
            image = image.convert("RGB").resize(target, Image.Resampling.LANCZOS)
        return image


def build_display_backend(config: DisplayConfig) -> DisplayBackend:
    """Return the :class:`DisplayBackend` matching *config.provider*."""
    if config.provider == "inky":
        return InkyBackend(config)
    if config.provider == "waveshare":
        return WaveshareBackend(config)
    raise ValueError(
        f"Unknown display provider {config.provider!r}; expected 'waveshare' or 'inky'"
    )
