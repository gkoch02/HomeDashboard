"""Tests for src/render/moon_render.py — photo occlusion + procedural fallback.

The photo path is opt-in via ``use_photo=True`` (set only by the
``moonphase_photo`` theme); the default behaviour is the procedural disc.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from src.render import moon_render
from src.render.moon_render import (
    MoonTones,
    _build_lit_mask,
    _lit_span,
    _load_moon_photo,
    _tone_luminance,
    moon_photo_available,
    render_moon_disc,
)

# Phase ages (days) for a 29.53059-day synodic month.
NEW = 0.0
FIRST_QUARTER = 7.38
FULL = 14.77
LAST_QUARTER = 22.15


@pytest.fixture
def fake_photo(tmp_path: Path) -> Path:
    """Write a recognisable greyscale moon photo: bright disc, dark corners."""
    size = 200
    img = Image.new("L", (size, size), 0)
    ImageDraw.Draw(img).ellipse([0, 0, size - 1, size - 1], fill=210)
    p = tmp_path / "moon_full.png"
    img.save(p)
    _load_moon_photo.cache_clear()
    return p


# ---------------------------------------------------------------------------
# Photo loading / availability
# ---------------------------------------------------------------------------


class TestPhotoLoading:
    def test_bundled_asset_is_available(self):
        assert moon_photo_available() is True

    def test_missing_path_returns_none(self, tmp_path):
        _load_moon_photo.cache_clear()
        missing = tmp_path / "nope.png"
        assert _load_moon_photo(str(missing)) is None
        assert moon_photo_available(str(missing)) is False

    def test_loaded_photo_is_square(self, fake_photo):
        img = _load_moon_photo(str(fake_photo))
        assert img is not None and img.mode == "L"
        assert img.size[0] == img.size[1]

    def test_non_square_source_is_centre_cropped(self, tmp_path):
        _load_moon_photo.cache_clear()
        wide = tmp_path / "wide.png"
        Image.new("L", (300, 100), 128).save(wide)
        img = _load_moon_photo(str(wide))
        assert img is not None and img.size == (100, 100)


# ---------------------------------------------------------------------------
# Terminator geometry
# ---------------------------------------------------------------------------


class TestTerminatorGeometry:
    def test_lit_span_waxing_lights_right_limb(self):
        # Waxing crescent: c > 0 so the lit span hugs the right limb.
        x0, x1 = _lit_span(xlim=10.0, c=0.5, waxing=True)
        assert x1 == 10.0 and x0 == 5.0

    def test_lit_span_waning_lights_left_limb(self):
        x0, x1 = _lit_span(xlim=10.0, c=0.5, waxing=False)
        assert x0 == -10.0 and x1 == -5.0

    def test_lit_mask_full_moon_mostly_lit(self):
        mask = _build_lit_mask(80, FULL, 29.53059)
        # Full disc area ≈ pi r^2; nearly all of it should be lit (255).
        lit = sum(1 for p in mask.getdata() if p > 127)
        assert lit > 0.9 * 3.14159 * 40 * 40

    def test_lit_mask_new_moon_dark(self):
        mask = _build_lit_mask(80, NEW, 29.53059)
        assert max(mask.getdata()) == 0

    def test_lit_mask_first_quarter_right_half(self):
        size = 80
        mask = _build_lit_mask(size, FIRST_QUARTER, 29.53059)
        px = mask.load()
        cy = size // 2
        # Right of centre lit, left of centre dark at the equator.
        assert px[size - 8, cy] > 127
        assert px[8, cy] == 0


# ---------------------------------------------------------------------------
# render_moon_disc — photo path (use_photo=True)
# ---------------------------------------------------------------------------


class TestRenderPhotoDisc:
    def _disc_image(self, mode, photo_path, age, dark_canvas):
        bg = 0 if mode != "RGB" else (0, 0, 0)
        img = Image.new(mode, (160, 160), bg)
        draw = ImageDraw.Draw(img)
        tones = MoonTones(lit=255, dark=0, edge=255)
        render_moon_disc(
            img,
            draw,
            80,
            80,
            60,
            age,
            tones,
            use_photo=True,
            dark_canvas=dark_canvas,
            photo_path=str(photo_path),
        )
        return img

    def test_photo_occludes_first_quarter_on_L(self, fake_photo):
        img = self._disc_image("L", fake_photo, FIRST_QUARTER, dark_canvas=True)
        px = img.convert("L").load()
        # Lit (right) limb brighter than the earthshine (left) limb.
        assert px[132, 80] > px[28, 80]

    def test_photo_full_moon_is_bright(self, fake_photo):
        img = self._disc_image("L", fake_photo, FULL, dark_canvas=True)
        assert img.getbbox() is not None
        assert max(img.getdata()) > 0

    def test_photo_new_moon_only_earthshine(self, fake_photo):
        # New moon: no lit region, only faint earthshine.  On the L canvas the
        # disc is dithered to bilevel, so individual pixels reach 255 — but the
        # mean stays low because the earthshine is heavily dimmed.
        img = self._disc_image("L", fake_photo, NEW, dark_canvas=True)
        data = list(img.getdata())
        assert sum(data) / len(data) < 60

    def test_photo_renders_on_rgb_as_greyscale(self, fake_photo):
        img = self._disc_image("RGB", fake_photo, FIRST_QUARTER, dark_canvas=True)
        # Realistic greyscale → r == g == b at a lit pixel.
        r, g, b = img.load()[132, 80]
        assert r == g == b

    def test_light_canvas_inverts_photo(self, fake_photo):
        # On a parchment (light) canvas the lit side reads as dark engraving.
        img = self._disc_image("L", fake_photo, FIRST_QUARTER, dark_canvas=False)
        px = img.load()
        # Lit (right) limb should be darker than the faded (left) earthshine.
        assert px[132, 80] < px[28, 80]

    def test_dark_canvas_inferred_from_tones_when_omitted(self, fake_photo):
        # Omitting dark_canvas infers polarity from the tones' luminance.
        img = Image.new("L", (160, 160), 0)
        draw = ImageDraw.Draw(img)
        render_moon_disc(
            img,
            draw,
            80,
            80,
            60,
            FIRST_QUARTER,
            MoonTones(lit=255, dark=0, edge=255),
            use_photo=True,
            photo_path=str(fake_photo),
        )
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# render_moon_disc — procedural path (the default / fallback)
# ---------------------------------------------------------------------------


class TestProceduralPath:
    def test_use_photo_false_ignores_bundled_asset(self):
        # Default use_photo=False must stay procedural even though the real
        # asset exists — guards the solid-disk `moonphase` theme.
        img = Image.new("L", (160, 160), 0)
        draw = ImageDraw.Draw(img)
        render_moon_disc(img, draw, 80, 80, 60, FULL, MoonTones(lit=255, dark=0, edge=255))
        assert img.getbbox() is not None

    def test_missing_photo_falls_back_to_procedural(self, tmp_path):
        _load_moon_photo.cache_clear()
        missing = tmp_path / "absent.png"
        img = Image.new("L", (160, 160), 0)
        draw = ImageDraw.Draw(img)
        render_moon_disc(
            img,
            draw,
            80,
            80,
            60,
            FULL,
            MoonTones(lit=255, dark=0, edge=255),
            use_photo=True,
            photo_path=str(missing),
        )
        assert img.getbbox() is not None

    def test_bilevel_mode_skips_photo(self, fake_photo):
        # "1" canvases always use the flat procedural path even with use_photo.
        img = Image.new("1", (400, 200), 0)
        draw = ImageDraw.Draw(img)
        render_moon_disc(
            img,
            draw,
            200,
            100,
            40,
            FULL,
            MoonTones(lit=1, dark=0, edge=1),
            use_photo=True,
            photo_path=str(fake_photo),
        )
        x0, y0, x1, y1 = img.getbbox()
        assert abs((x0 + x1) // 2 - 200) <= 2
        assert abs((y0 + y1) // 2 - 100) <= 2


# ---------------------------------------------------------------------------
# Tone luminance helper
# ---------------------------------------------------------------------------


class TestToneLuminance:
    def test_bilevel(self):
        assert _tone_luminance(0) == 0.0
        assert _tone_luminance(1) == 1.0

    def test_greyscale(self):
        assert _tone_luminance(255) == 1.0
        assert _tone_luminance(128) == pytest.approx(0.502, abs=0.01)

    def test_rgb(self):
        assert _tone_luminance((255, 255, 255)) == 1.0
        assert _tone_luminance((0, 0, 0)) == 0.0


@pytest.fixture(autouse=True)
def _restore_photo_cache():
    """Ensure the real bundled-asset cache entry isn't poisoned across tests."""
    yield
    _load_moon_photo.cache_clear()
    assert moon_render.moon_photo_available() is True
