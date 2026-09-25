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
from src.render.quantize import (
    INKY_SPECTRA6_PALETTE,
    WAVESHARE_G_STYLE_PALETTE,
    quantize_for_display,
    quantize_to_palette_fs,
    quantize_to_palette_nearest,
)

Fill = int | tuple[int, int, int]
Rect = tuple[int, int, int, int]

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


def placement(
    canvas_size: tuple[int, int], target: tuple[int, int], scaling: str
) -> tuple[float, float, int, int]:
    """``(scale_x, scale_y, offset_x, offset_y)`` mapping canvas coordinates onto the panel.

    The same arithmetic :func:`fit_canvas` uses to place the resized canvas,
    exposed so a rectangle declared in canvas coordinates (an art region) can
    be found again on the finished plate.
    """
    cw, ch = canvas_size
    tw, th = target
    if (cw, ch) == (tw, th):
        return (1.0, 1.0, 0, 0)
    if scaling != "fit":
        return (tw / cw, th / ch, 0, 0)
    scale = min(tw / cw, th / ch)
    nw = max(1, round(cw * scale))
    nh = max(1, round(ch * scale))
    return (scale, scale, (tw - nw) // 2, (th - nh) // 2)


def map_rect(rect: Rect, place: tuple[float, float, int, int], bounds: tuple[int, int]) -> Rect:
    """Carry a canvas-coordinate *rect* onto the panel through *place*, clipped to *bounds*."""
    sx, sy, ox, oy = place
    x0, y0, x1, y1 = rect
    bw, bh = bounds
    return (
        max(0, min(bw, round(x0 * sx) + ox)),
        max(0, min(bh, round(y0 * sy) + oy)),
        max(0, min(bw, round(x1 * sx) + ox)),
        max(0, min(bh, round(y1 * sy) + oy)),
    )


#: A pixel whose channels differ by no more than this is neutral: it is
#: diffused against black and white alone, never a coloured ink.
NEUTRAL_SPREAD = 8


def _neutral_inks(palette: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], ...]:
    """The palette's darkest and lightest entries, as the two neutral inks."""
    darkest = min(palette, key=sum)
    lightest = max(palette, key=sum)
    return (darkest, lightest)


#: Spectra-6 style values → the four-ink panel's inks, index for index. The
#: art helpers (``skyart.accent_yellow``, ``artkit.accent_red``) fill with the
#: measured Inky values on any RGB canvas, whichever panel is configured;
#: outside an art region the nearest-colour snap lands those on the right ink,
#: and inside one they must be remapped *before* diffusion, or a solid disc of
#: (208,190,71) is diffused against (255,255,0) and comes out speckled.
G_EXACT_REMAP: dict[tuple[int, int, int], tuple[int, int, int]] = dict(
    zip(INKY_SPECTRA6_PALETTE, WAVESHARE_G_STYLE_PALETTE)
)


def dither_art_regions(
    source: Image.Image,
    plate: Image.Image,
    regions: list[Rect] | None,
    place: tuple[float, float, int, int],
    palette: list[tuple[int, int, int]],
    remap: dict[tuple[int, int, int], tuple[int, int, int]] | None = None,
) -> Image.Image:
    """Floyd-Steinberg the declared art *regions* onto *plate*, in the panel's inks.

    A colour panel shows a handful of inks, and the finalize step snaps every
    pixel to the nearest one — right for type and rules, which must stay
    solid, and wrong for an illustration, whose gradients flatten to one ink
    and whose tones outside the ink set (an orange sky over yellow and red)
    are lost. A panel that draws artwork declares the rectangle it occupies
    via ``RenderContext.dither_regions``; here each such rectangle is cut from
    *source* — the resized canvas *before* any snap — error-diffused onto the
    palette so mixed tones become halftone mixtures of the inks, and pasted
    over *plate*. Everything outside the regions is left as the caller
    finalized it.

    Neutral pixels (channels within ``NEUTRAL_SPREAD`` of each other) are
    diffused against black and white only, which is exactly what the same
    themes' greyscale path does, so the engraving matches across panels.
    Diffusing them against the whole palette instead lets the accumulated
    error drift in hue and sprinkles a dark sky with red and green dots.
    Coloured pixels take the full palette, where a tone the panel lacks
    becomes a mixture of the inks it has; diffusion has no error to spread on
    an exact ink, so a solid yellow disc stays solid. *remap* names exact
    colours to substitute first — the Spectra-6 accents the art helpers draw
    with, onto the panel's own inks — so they *are* exact inks by the time
    they are diffused.
    """
    if not regions:
        return plate
    import numpy as np

    dark, light = _neutral_inks(palette)
    for rect in regions:
        x0, y0, x1, y1 = map_rect(rect, place, plate.size)
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        tile = source.crop((x0, y0, x1, y1)).convert("RGB")
        arr = np.array(tile, dtype=np.int16)
        if remap:
            for src_rgb, dst_rgb in remap.items():
                hit = np.all(arr == np.array(src_rgb, dtype=np.int16), axis=2)
                if hit.any():
                    arr[hit] = np.array(dst_rgb, dtype=np.int16)
            tile = Image.fromarray(arr.astype(np.uint8), mode="RGB")
        neutral = (arr.max(axis=2) - arr.min(axis=2)) <= NEUTRAL_SPREAD
        # Greys: the 1-bit engraving, mapped onto the panel's two neutral inks.
        bilevel = np.asarray(tile.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG))
        grey = np.where(bilevel[:, :, None], np.array(light, np.uint8), np.array(dark, np.uint8))
        if neutral.all():
            out = grey
        else:
            colour = np.asarray(quantize_to_palette_fs(tile, palette), dtype=np.uint8)
            out = np.where(neutral[:, :, None], grey, colour)
        plate.paste(Image.fromarray(out.astype(np.uint8), mode="RGB"), (x0, y0))
    return plate


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
    sx, sy, ox, oy = placement(image.size, target, scaling)
    cw, ch = image.size
    scaled = image.resize(
        (max(1, round(cw * sx)), max(1, round(ch * sy))), Image.Resampling.LANCZOS
    )
    plate = Image.new(image.mode, target, background)
    plate.paste(scaled, (ox, oy))
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
        dither_regions: list[Rect] | None = None,
    ) -> Image.Image:
        """Resize *image* to the configured display size and finalize it.

        ``layout`` is the active ``ThemeLayout`` (used for canvas-mode and
        the optional ``preferred_quantization_mode``). Kept ``Any`` to
        avoid an import cycle on ``src.render.theme``. ``background`` is the
        theme's ``bg`` in the canvas's own mode; it fills the bands when
        ``display.scaling`` resolves to ``fit``. ``dither_regions`` are the
        canvas-coordinate rectangles panels declared as artwork; a colour
        backend error-diffuses those onto its inks instead of snapping them
        (see :func:`dither_art_regions`). The 1-bit backend ignores them —
        its whole plate already dithers per the theme's quantizer.
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
        dither_regions: list[Rect] | None = None,
    ) -> Image.Image:
        del dither_regions  # a 1-bit plate dithers as a whole, per the theme's quantizer
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
        dither_regions: list[Rect] | None = None,
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
        plate = quantize_to_palette_nearest(rgb, self._palette)
        return dither_art_regions(
            rgb,
            plate,
            dither_regions,
            placement(canvas_size, target, scaling),
            self._palette,
            remap=G_EXACT_REMAP,
        )


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
        dither_regions: list[Rect] | None = None,
    ) -> Image.Image:
        target = _target(self._config)
        scaling = _scaling(self._config, canvas_size)
        if target != canvas_size:
            pad = pad_value(background, image.mode, "RGB")
            image = fit_canvas(
                image.convert("RGB"),
                target,
                scaling=scaling,
                background=pad,
            )
        if image.mode == "RGB" and dither_regions:
            # Diffuse onto the panel's measured inks, so the driver's own
            # nearest-colour mapping at write time is the identity on them.
            image = dither_art_regions(
                image,
                image.copy(),
                dither_regions,
                placement(canvas_size, target, scaling),
                INKY_SPECTRA6_PALETTE,
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
