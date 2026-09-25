"""Display backend abstraction.

The :class:`DisplayBackend` ABC unifies the post-render image pipeline that
v4 forked across two paths in ``canvas.py`` (and again in ``output.py``):

- :class:`WaveshareBackend` handles 1-bit eInk: resize via LANCZOS into a
  greyscale image, then quantize to ``"1"`` via the configured algorithm.
- :class:`WaveshareColorBackend` handles the Waveshare "G" family (black,
  white, yellow, red): resize in RGB, then snap every pixel to the panel's
  four inks so the driver's own palette mapping has nothing left to decide.
- :class:`InkyBackend` handles Spectra-6 colour: resize via LANCZOS in
  RGB and hand off to the Inky library for palette mapping at write time.

All three share :func:`fit_canvas` for the resize, which either stretches the
canvas onto the panel (the historical behaviour) or scales it to fit and pads
the remainder with the plate's background, per ``display.scaling``.

Adding a new display family is a single new backend subclass plus a
``build_display_backend`` branch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from src.config import DisplayConfig
from src.display.driver import get_display_spec
from src.render.quantize import quantize_for_display, quantize_to_palette_nearest

Fill = int | tuple[int, int, int]

SCALING_MODES: tuple[str, ...] = ("auto", "stretch", "fit")

#: ``scaling: auto`` stretches until the stretch would bend the aspect ratio by
#: more than this factor, then fits instead. A third is well past what any
#: 4:3 or 16:10 panel asks of the 800x480 canvas (the 1600x1200 case is 1.25,
#: and it has always been stretched), and well short of what a panoramic
#: 1360x480 strip asks (1.7) — where a stretched week grid is unreadable.
FIT_DISTORTION_THRESHOLD = 4 / 3


def distortion(canvas_size: tuple[int, int], target: tuple[int, int]) -> float:
    """How far stretching *canvas_size* onto *target* bends the aspect ratio (≥ 1.0)."""
    cw, ch = canvas_size
    tw, th = target
    ratio = (tw / th) / (cw / ch)
    return ratio if ratio >= 1.0 else 1.0 / ratio


def resolve_scaling(mode: object, canvas_size: tuple[int, int], target: tuple[int, int]) -> str:
    """Turn the configured ``display.scaling`` into ``"stretch"`` or ``"fit"``.

    Anything that is not one of the two explicit modes is treated as ``auto``
    — the config validator reports an unknown value separately, and a render
    must not fail over it.
    """
    if mode in ("stretch", "fit"):
        return str(mode)
    return "fit" if distortion(canvas_size, target) > FIT_DISTORTION_THRESHOLD else "stretch"


def _as_rgb(background: Fill | None, image_mode: str) -> tuple[int, int, int]:
    """Read a ``ThemeStyle.bg`` value, written for *image_mode*, as an RGB triple."""
    if background is None:
        return (255, 255, 255)
    if isinstance(background, tuple):
        return background
    if image_mode == "1":
        return (255, 255, 255) if background else (0, 0, 0)
    v = max(0, min(255, int(background)))
    return (v, v, v)


def pad_value(background: Fill | None, image_mode: str, to_mode: str) -> Fill:
    """The padding fill for :func:`fit_canvas`, expressed in *to_mode*.

    *background* is the theme's ``bg`` as written for *image_mode* — ``0``/``1``
    on a ``"1"`` canvas, ``0``–``255`` on ``"L"``, a triple on ``"RGB"``.
    """
    r, g, b = _as_rgb(background, image_mode)
    if to_mode == "RGB":
        return (r, g, b)
    lum = round(0.299 * r + 0.587 * g + 0.114 * b)
    if to_mode == "1":
        return 1 if lum > 127 else 0
    return lum


def fit_canvas(
    image: Image.Image,
    target: tuple[int, int],
    *,
    scaling: str,
    background: Fill,
) -> Image.Image:
    """Resize *image* to *target* by stretching or by fitting on a padded plate.

    *image* must already be in an interpolating mode (``"L"`` or ``"RGB"``);
    Pillow silently drops to nearest-neighbour for ``"1"``. *background* is the
    padding fill in that same mode. ``"stretch"`` reproduces the historical
    LANCZOS resize exactly; ``"fit"`` keeps the aspect ratio and centres the
    scaled canvas, so a landscape theme on a panoramic panel sits between two
    bands of background instead of being pulled wide.
    """
    if image.size == target:
        return image
    if scaling != "fit":
        return image.resize(target, Image.Resampling.LANCZOS)
    cw, ch = image.size
    tw, th = target
    scale = min(tw / cw, th / ch)
    nw = max(1, round(cw * scale))
    nh = max(1, round(ch * scale))
    scaled = image.resize((nw, nh), Image.Resampling.LANCZOS)
    plate = Image.new(image.mode, target, background)
    plate.paste(scaled, ((tw - nw) // 2, (th - nh) // 2))
    return plate


class DisplayBackend(ABC):
    """Backend-specific resize + finalize for a rendered canvas."""

    @abstractmethod
    def resize_and_finalize(
        self,
        image: Image.Image,
        *,
        canvas_size: tuple[int, int],
        layout,
        background: Fill | None = None,
    ) -> Image.Image:
        """Resize *image* to the configured display size and finalize it.

        ``layout`` is the active ``ThemeLayout`` (used for canvas-mode and
        the optional ``preferred_quantization_mode``). Kept ``Any`` to
        avoid an import cycle on ``src.render.theme``. ``background`` is the
        theme's ``bg`` in the canvas's own mode; it fills the bands when
        ``display.scaling`` resolves to ``fit``.
        """


def _target(config: DisplayConfig) -> tuple[int, int]:
    return (config.width, config.height)


def _scaling(config: DisplayConfig, canvas_size: tuple[int, int]) -> str:
    return resolve_scaling(getattr(config, "scaling", "auto"), canvas_size, _target(config))


class WaveshareBackend(DisplayBackend):
    """1-bit eInk pipeline.

    LANCZOS-resizes onto an ``"L"`` canvas (so the dither input is grey),
    then quantizes to ``"1"`` using the configured algorithm.
    """

    def __init__(self, config: DisplayConfig):
        self._config = config

    def resize_and_finalize(
        self,
        image: Image.Image,
        *,
        canvas_size: tuple[int, int],
        layout,
        background: Fill | None = None,
    ) -> Image.Image:
        target = _target(self._config)
        needs_resize = target != canvas_size
        if needs_resize:
            pad = pad_value(background, image.mode, "L")
            l_image = image if image.mode == "L" else image.convert("L")
            image = fit_canvas(
                l_image, target, scaling=_scaling(self._config, canvas_size), background=pad
            )
        # Quantize whenever a resize happened (LANCZOS produces grey pixels)
        # or the canvas itself was rendered in greyscale.
        if needs_resize or layout.canvas_mode == "L":
            quant_mode = layout.preferred_quantization_mode or self._config.quantization_mode
            image = quantize_for_display(image, quant_mode)
        return image


class WaveshareColorBackend(DisplayBackend):
    """Waveshare "G" (black / white / yellow / red) pipeline.

    A plate rendered in greyscale (a ``"1"`` or ``"L"`` canvas) goes through the
    same resize-and-quantize the 1-bit backend runs — a dithered art theme keeps
    its engraving — and is then promoted to RGB for the driver. A plate rendered
    in RGB is resized in RGB and every pixel snapped to the nearest of the four
    inks. The snap is a hard cut rather than a dither: the canvas was drawn in
    the panel's own inks, so the only intermediate values are antialiased glyph
    edges and resize blur, and dithering those would speckle the type.
    """

    def __init__(self, config: DisplayConfig, palette: tuple[tuple[int, int, int], ...]):
        self._config = config
        self._palette = list(palette)

    def resize_and_finalize(
        self,
        image: Image.Image,
        *,
        canvas_size: tuple[int, int],
        layout,
        background: Fill | None = None,
    ) -> Image.Image:
        target = _target(self._config)
        needs_resize = target != canvas_size
        scaling = _scaling(self._config, canvas_size)
        if image.mode in ("1", "L"):
            source_mode = image.mode
            pad = pad_value(background, source_mode, "L")
            l_image = image if source_mode == "L" else image.convert("L")
            if needs_resize:
                l_image = fit_canvas(l_image, target, scaling=scaling, background=pad)
            if needs_resize or source_mode == "L":
                quant_mode = layout.preferred_quantization_mode or self._config.quantization_mode
                l_image = quantize_for_display(l_image, quant_mode)
            return l_image.convert("RGB")
        rgb = image.convert("RGB")
        if needs_resize:
            pad = pad_value(background, image.mode, "RGB")
            rgb = fit_canvas(rgb, target, scaling=scaling, background=pad)
        return quantize_to_palette_nearest(rgb, self._palette)


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
        self,
        image: Image.Image,
        *,
        canvas_size: tuple[int, int],
        layout,
        background: Fill | None = None,
    ) -> Image.Image:
        target = _target(self._config)
        if target != canvas_size:
            pad = pad_value(background, image.mode, "RGB")
            image = fit_canvas(
                image.convert("RGB"),
                target,
                scaling=_scaling(self._config, canvas_size),
                background=pad,
            )
        return image


def build_display_backend(config: DisplayConfig) -> DisplayBackend:
    """Return the :class:`DisplayBackend` matching *config.provider* and model."""
    if config.provider == "inky":
        return InkyBackend(config)
    if config.provider == "waveshare":
        spec = get_display_spec("waveshare", config.model)
        if spec is not None and spec.palette is not None:
            return WaveshareColorBackend(config, spec.palette)
        return WaveshareBackend(config)
    raise ValueError(
        f"Unknown display provider {config.provider!r}; expected 'waveshare' or 'inky'"
    )
