"""Photo theme — displays a dithered user photo as the full-canvas background.

The photo path is set at runtime via ``ThemeStyle.photo_path``, which is
populated in ``app.py`` from ``cfg.photo.path``.  If no path is configured or
the file is missing the canvas falls back to a plain white background with only
the header bar rendered.

The existing ``header`` component is reused, repositioned to a 50 px inverted
bar at the bottom of the canvas, showing the dashboard title and timestamp.
No other components are drawn — the photo is the primary content.

Configuration::

    theme: photo

    photo:
      path: /home/pi/wallpaper.jpg

**Waveshare / 1-bit path** — photo is converted to grayscale, resized with
LANCZOS, and dithered to 1-bit via Floyd-Steinberg.

**Inky Spectra 6 / RGB path** — photo is resized with LANCZOS and quantized to
the 6-color Spectra 6 palette using Floyd-Steinberg error diffusion against a
*blended* reference palette (50/50 mix of the physical SATURATED colors and
pure ideal hues, mirroring ``InkyE673._palette_blend(saturation=0.5)``).  The
blended palette forms correct hue decision boundaries — e.g. sky blue maps to
blue rather than white — while still being close enough to the physical colors
that ``InkyDisplay.show()`` can unambiguously recover the correct hardware index
for each quantized pixel.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.render.theme import Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)


def _draw_photo_background(
    image: Image.Image,
    layout: ThemeLayout,
    style: ThemeStyle,
) -> None:
    """Load, dither, and paste the configured photo onto *image*."""
    path = style.photo_path
    if not path:
        return
    if not Path(path).exists():
        logger.warning("photo theme: image not found: %s", path)
        return
    try:
        if image.mode == "RGB":
            # Inky Spectra 6 color path: resize then quantize to 6-color palette
            # using the blended reference palette (50/50 SATURATED + DESATURATED),
            # which mirrors InkyE673._palette_blend(saturation=0.5) and gives each
            # hue a vibrant enough reference for correct nearest-color decisions.
            #
            # Dithering: try PIL's native Floyd-Steinberg first (C implementation,
            # fast on Pi) since FS produces more organic results than Bayer for
            # photos.  PIL's quantize(palette=...) can scramble palette indices in
            # some Pillow 10+ builds; a colour-set sanity check detects this and
            # falls back to the fully-vectorised Bayer path.
            from PIL import Image as _Image

            from src.render.quantize import (
                blend_inky_palette,
                build_palette_image,
                quantize_to_palette_ordered,
            )

            img = _Image.open(path).convert("RGB")
            img = img.resize((layout.canvas_w, layout.canvas_h), _Image.Resampling.LANCZOS)
            blended = blend_inky_palette(0.25)
            blended_set = set(map(tuple, blended))

            # Attempt fast PIL Floyd-Steinberg.
            palette_img = build_palette_image(blended)
            fs_result = img.quantize(
                palette=palette_img, dither=_Image.Dither.FLOYDSTEINBERG
            ).convert("RGB")

            if set(fs_result.getdata()) <= blended_set:
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("photo theme: failed to load image %s: %s", path, exc)


def photo_theme() -> Theme:
    """Return the ``photo`` theme."""
    layout = ThemeLayout(
        canvas_w=800,
        canvas_h=480,
        header=None,
        draw_order=[],
        background_fn=_draw_photo_background,
    )
    style = ThemeStyle(
        fg=0,
        bg=1,
        show_borders=False,
    )
    return Theme(name="photo", style=style, layout=layout)
