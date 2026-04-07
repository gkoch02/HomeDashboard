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

The photo is converted to grayscale, resized to fit the canvas with LANCZOS
resampling, and dithered to 1-bit using Floyd-Steinberg diffusion before being
pasted onto the canvas.  For dark-canvas variants (``fg=1, bg=0``) the
grayscale values are inverted so bright photo areas appear as white pixels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.render.theme import ComponentRegion, Theme, ThemeLayout, ThemeStyle

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

_INFO_BAR_H = 50  # height of the bottom info bar in pixels


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
        # Reuse the header component at the bottom of the canvas as an info bar.
        header=ComponentRegion(0, 480 - _INFO_BAR_H, 800, _INFO_BAR_H),
        draw_order=["header"],
        background_fn=_draw_photo_background,
    )
    style = ThemeStyle(
        fg=0,
        bg=1,
        invert_header=True,  # inverted bar at bottom (black fill, white text)
        invert_today_col=False,
        invert_allday_bars=False,
        show_borders=False,
    )
    return Theme(name="photo", style=style, layout=layout)
