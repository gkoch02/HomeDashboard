"""Tests for src/render/fonts.py — font loader functions."""

import pytest
from PIL import ImageFont

from src.render.fonts import (
    antonio_semibold,
    bold,
    cinzel_semibold,
    medium,
    orbitron_black,
    oxanium,
    oxanium_bold,
    oxanium_extrabold,
    rajdhani,
    rajdhani_semibold,
    regular,
    semibold,
    weather_icon,
)


class TestFontAccessors:
    """Smoke tests — verify each font accessor loads without error."""

    @pytest.mark.parametrize(
        "accessor, size",
        [
            (regular, 12),
            (medium, 12),
            (semibold, 12),
            (bold, 12),
            (weather_icon, 20),
            (cinzel_semibold, 12),
            (oxanium, 12),
            (oxanium_bold, 12),
            (oxanium_extrabold, 12),
            (orbitron_black, 12),
            (rajdhani, 12),
            (rajdhani_semibold, 12),
            (antonio_semibold, 12),
        ],
        ids=lambda v: v.__name__ if callable(v) else None,
    )
    def test_accessor_loads_a_freetype_font(self, accessor, size):
        assert isinstance(accessor(size), ImageFont.FreeTypeFont)

    def test_variable_faces_are_pinned_off_their_axis_default(self):
        """Oxanium's default variation instance is ExtraLight (200).

        Every accessor must pin a weight explicitly; if one stops doing so the
        terminal theme renders as near-invisible hairlines on the panel. Bold
        must therefore lay down measurably more ink than Regular.
        """
        from PIL import Image, ImageDraw

        from tests.inkutils import marks

        def stroke_mass(font):
            img = Image.new("L", (400, 80), 255)
            ImageDraw.Draw(img).text((4, 4), "WEDNESDAY 26", font=font, fill=0)
            return marks(img, background=255)

        assert stroke_mass(oxanium_bold(48)) > stroke_mass(oxanium(48))
        assert stroke_mass(oxanium_extrabold(48)) > stroke_mass(oxanium_bold(48))

    def test_caching_returns_same_object(self):
        """@lru_cache should return the same object on repeated calls."""
        f1 = regular(12)
        f2 = regular(12)
        assert f1 is f2
