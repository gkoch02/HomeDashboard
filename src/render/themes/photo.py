"""Photo theme — displays a dithered user photo as the full-canvas background.

The photo path is set at runtime via ``ThemeStyle.photo_path``, which is
populated in ``services/render_args.py`` from ``cfg.photo.path``.  If no path is configured or
the file is missing the canvas falls back to a plain background.

No components are drawn (``draw_order`` is empty): the photo fills the canvas
edge to edge with no header bar, title or timestamp.

Configuration::

    theme: photo

    photo:
      path: /home/pi/wallpaper.jpg

Every path turns the photo upright per its EXIF orientation and crops it to
fill the canvas (scaled to cover, centre-cropped), so it is never stretched.

**Waveshare / 1-bit path** — photo is converted to grayscale, cropped with
LANCZOS, and dithered to 1-bit via Floyd-Steinberg.

**Inky Spectra 6 / RGB path** — photo is cropped with LANCZOS and quantized to
the 6-color Spectra 6 palette using Floyd-Steinberg error diffusion against a
*blended* reference palette, ``blend_inky_palette(0.25)``: 25 % of the way from
the pure ideal hues toward the physical SATURATED colors.  The
blended palette forms correct hue decision boundaries — e.g. sky blue maps to
blue rather than white — while still being close enough to the physical colors
that ``InkyDisplay.show()`` can unambiguously recover the correct hardware index
for each quantized pixel.

**Waveshare colour (four-ink G) path** — the cropped photo is pasted undithered
and the whole canvas is returned as an art region, so the backend
Floyd-Steinbergs it onto the panel's own inks. Pre-dithering against the
Spectra 6 palette here would spend the error diffusion on blue and green, which
the G panel lacks and snaps to black.

Editing notes: ``background_fn`` pastes the dithered ``photo.path``; ``draw_order`` is
empty.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.render.theme import Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import Image

    from src.config import DisplayConfig

logger = logging.getLogger(__name__)


def _draw_photo_background(
    image: Image.Image,
    layout: ThemeLayout,
    style: ThemeStyle,
    config: DisplayConfig,
) -> list[tuple[int, int, int, int]] | None:
    """Paste the configured photo onto *image*; return the art region, if any.

    The photo is dithered here for Inky and mono panels. On a four-ink colour
    Waveshare it is pasted as-is and the full canvas returned, for the backend
    to dither onto that panel's inks.
    """
    path = style.photo_path
    if not path:
        return None
    if not Path(path).exists():
        logger.warning("photo theme: image not found: %s", path)
        return None
    try:
        if image.mode == "RGB" and config.provider != "inky":
            from PIL import Image as _Image
            from PIL import ImageOps

            img = ImageOps.exif_transpose(_Image.open(path)).convert("RGB")
            image.paste(
                ImageOps.fit(img, (layout.canvas_w, layout.canvas_h), _Image.Resampling.LANCZOS)
            )
            return [(0, 0, layout.canvas_w, layout.canvas_h)]
        if image.mode == "RGB":
            # Inky Spectra 6 color path: crop then quantize to 6-color palette
            # using the blended reference palette (see the module docstring),
            # which gives each hue a vibrant enough reference for correct
            # nearest-color decisions.
            #
            # Dithering: try PIL's native Floyd-Steinberg first (C implementation,
            # fast on Pi) since FS produces more organic results than Bayer for
            # photos.  PIL's quantize(palette=...) can scramble palette indices in
            # some Pillow 10+ builds; a colour-set sanity check detects this and
            # falls back to the fully-vectorised Bayer path.
            from PIL import Image as _Image
            from PIL import ImageOps

            from src.render.quantize import (
                blend_inky_palette,
                build_palette_image,
                flatten_pixels,
                quantize_to_palette_ordered,
            )

            img = ImageOps.exif_transpose(_Image.open(path)).convert("RGB")
            img = ImageOps.fit(img, (layout.canvas_w, layout.canvas_h), _Image.Resampling.LANCZOS)
            blended = blend_inky_palette(0.25)
            blended_set = set(map(tuple, blended))

            # Attempt fast PIL Floyd-Steinberg.
            palette_img = build_palette_image(blended)
            fs_result = img.quantize(
                palette=palette_img, dither=_Image.Dither.FLOYDSTEINBERG
            ).convert("RGB")

            if set(flatten_pixels(fs_result)) <= blended_set:
                # PIL produced correct colours — use the FS result.
                img = fs_result
            else:
                # Palette indices were scrambled; fall back to vectorised Bayer.
                logger.debug("photo theme: PIL quantize palette check failed, using Bayer fallback")
                img = quantize_to_palette_ordered(img, blended)

            image.paste(img)
        else:
            from src.render.primitives import load_and_dither_image

            dithered = load_and_dither_image(
                path,
                (layout.canvas_w, layout.canvas_h),
                style.fg,
                style.bg,
            )
            image.paste(dithered)
    except Exception as exc:
        logger.warning("photo theme: failed to load image %s: %s", path, exc)
    return None


def photo_theme() -> Theme:
    """Return the ``photo`` theme."""
    layout = ThemeLayout(
        canvas_w=800,
        canvas_h=480,
        draw_order=[],
        background_fn=_draw_photo_background,
    )
    style = ThemeStyle(
        fg=0,
        bg=1,
        show_borders=False,
    )
    return Theme(name="photo", style=style, layout=layout)


def _register() -> None:
    from src.render.theme import INKY_BLUE, INKY_RED
    from src.render.themes.registry import register_theme

    register_theme("photo", photo_theme, inky_palette=(INKY_BLUE, INKY_RED))


_register()
