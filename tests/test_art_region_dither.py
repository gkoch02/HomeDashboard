"""Art regions: colour backends error-diffuse declared artwork instead of snapping it."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from PIL import Image

from src.config import DisplayConfig
from src.display.backend import (
    InkyBackend,
    WaveshareColorBackend,
    dither_art_regions,
    map_rect,
    placement,
)
from src.display.driver import WAVESHARE_G_PALETTE
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components import (
    day_arc_panel,
    halftone_agenda_panel,
    halftone_agenda_wide_panel,
    halftone_panel,
)
from src.render.components.registry import RenderContext
from src.render.quantize import INKY_SPECTRA6_PALETTE, flatten_pixels
from src.render.theme import ComponentRegion, load_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
PANORAMIC = (1360, 480)
CANVAS = (800, 480)
GREY = (128, 128, 128)


def _layout(mode="1"):
    layout = MagicMock()
    layout.canvas_mode = mode
    layout.preferred_quantization_mode = None
    return layout


def _colours(img, box):
    return set(flatten_pixels(img.crop(box)))


class TestPlacement:
    def test_identity_when_sizes_match(self):
        assert placement(PANORAMIC, PANORAMIC, "fit") == (1.0, 1.0, 0, 0)

    def test_stretch_scales_each_axis(self):
        sx, sy, ox, oy = placement(CANVAS, (1600, 1200), "stretch")
        assert (sx, sy, ox, oy) == (2.0, 2.5, 0, 0)

    def test_fit_centres(self):
        assert placement(CANVAS, PANORAMIC, "fit") == (1.0, 1.0, 280, 0)

    def test_map_rect_follows_placement_and_clips(self):
        place = placement(CANVAS, PANORAMIC, "fit")
        assert map_rect((0, 0, 800, 100), place, PANORAMIC) == (280, 0, 1080, 100)
        assert map_rect((-50, 0, 2000, 900), place, PANORAMIC) == (230, 0, 1360, 480)


class TestDitherArtRegions:
    def test_region_becomes_a_mixture_and_the_rest_stays_snapped(self):
        source = Image.new("RGB", (200, 40), GREY)
        plate = Image.new("RGB", (200, 40), (0, 0, 0))  # what a nearest snap gives mid-grey
        out = dither_art_regions(
            source, plate, [(0, 0, 100, 40)], (1.0, 1.0, 0, 0), list(WAVESHARE_G_PALETTE)
        )
        inside = _colours(out, (0, 0, 100, 40))
        assert inside == {(0, 0, 0), (255, 255, 255)}
        assert _colours(out, (100, 0, 200, 40)) == {(0, 0, 0)}

    def test_no_regions_is_a_no_op(self):
        plate = Image.new("RGB", (10, 10), (0, 0, 0))
        assert dither_art_regions(plate, plate, None, (1.0, 1.0, 0, 0), []) is plate
        assert dither_art_regions(plate, plate, [], (1.0, 1.0, 0, 0), []) is plate

    def test_empty_rect_is_skipped(self):
        plate = Image.new("RGB", (10, 10), (0, 0, 0))
        out = dither_art_regions(plate, plate, [(5, 5, 5, 9)], (1.0, 1.0, 0, 0), [(0, 0, 0)])
        assert set(flatten_pixels(out)) == {(0, 0, 0)}

    def test_a_solid_ink_stays_solid(self):
        """Error diffusion has nothing to spread on an exact ink."""
        source = Image.new("RGB", (60, 20), (255, 255, 0))
        plate = Image.new("RGB", (60, 20), (0, 0, 0))
        out = dither_art_regions(
            source, plate, [(0, 0, 60, 20)], (1.0, 1.0, 0, 0), list(WAVESHARE_G_PALETTE)
        )
        assert set(flatten_pixels(out)) == {(255, 255, 0)}

    def test_neutral_pixels_never_take_a_coloured_ink(self):
        """A dark grey ramp diffused against the whole palette drifts in hue;
        neutrals must diffuse against black and white alone."""
        source = Image.new("RGB", (400, 60))
        for x in range(400):
            v = 20 + x // 4
            for y in range(60):
                source.putpixel((x, y), (v, v, v))
        plate = Image.new("RGB", (400, 60), (0, 0, 0))
        out = dither_art_regions(
            source, plate, [(0, 0, 400, 60)], (1.0, 1.0, 0, 0), list(INKY_SPECTRA6_PALETTE)
        )
        assert set(flatten_pixels(out)) <= {INKY_SPECTRA6_PALETTE[0], INKY_SPECTRA6_PALETTE[1]}

    def test_orange_becomes_yellow_and_red(self):
        source = Image.new("RGB", (60, 20), (255, 128, 0))
        plate = Image.new("RGB", (60, 20), (0, 0, 0))
        out = dither_art_regions(
            source, plate, [(0, 0, 60, 20)], (1.0, 1.0, 0, 0), list(WAVESHARE_G_PALETTE)
        )
        assert set(flatten_pixels(out)) == {(255, 255, 0), (255, 0, 0)}


class TestBackends:
    def test_g_panel_region_dithers_after_the_snap(self):
        cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
        img = Image.new("RGB", PANORAMIC, GREY)
        out = WaveshareColorBackend(cfg, WAVESHARE_G_PALETTE).resize_and_finalize(
            img,
            canvas_size=PANORAMIC,
            layout=_layout(),
            background=(255, 255, 255),
            dither_regions=[(0, 0, 400, 480)],
        )
        assert _colours(out, (0, 0, 400, 480)) == {(0, 0, 0), (255, 255, 255)}
        assert len(_colours(out, (400, 0, 1360, 480))) == 1

    def test_g_panel_region_is_carried_through_fit(self):
        cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
        img = Image.new("RGB", CANVAS, GREY)
        out = WaveshareColorBackend(cfg, WAVESHARE_G_PALETTE).resize_and_finalize(
            img,
            canvas_size=CANVAS,
            layout=_layout(),
            background=(255, 255, 255),
            dither_regions=[(0, 0, 800, 480)],
        )
        # The canvas lands at x 280..1079; the bands beside it are untouched paper.
        assert _colours(out, (290, 10, 1070, 470)) == {(0, 0, 0), (255, 255, 255)}
        assert _colours(out, (0, 0, 270, 480)) == {(255, 255, 255)}

    def test_inky_region_lands_on_the_measured_inks(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        img = Image.new("RGB", CANVAS, GREY)
        out = InkyBackend(cfg).resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout(), dither_regions=[(0, 0, 400, 480)]
        )
        inside = _colours(out, (0, 0, 400, 480))
        assert inside <= set(INKY_SPECTRA6_PALETTE)
        assert len(inside) >= 2
        assert _colours(out, (400, 0, 800, 480)) == {GREY}  # the driver snaps this later

    def test_inky_greyscale_plate_is_untouched(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        img = Image.new("L", CANVAS, 128)
        out = InkyBackend(cfg).resize_and_finalize(
            img, canvas_size=CANVAS, layout=_layout("L"), dither_regions=[(0, 0, 400, 480)]
        )
        assert out.mode == "L"


class TestRegistration:
    def test_render_context_starts_with_no_regions(self):
        ctx = RenderContext(
            draw=MagicMock(),
            data=MagicMock(),
            today=FIXED_NOW.date(),
            now=FIXED_NOW,
            layout=MagicMock(),
            style=MagicMock(),
        )
        assert ctx.dither_regions == []

    def test_art_rects(self):
        assert halftone_panel.art_rect(ComponentRegion(0, 0, 800, 480)) == (0, 0, 800, 296)
        assert halftone_agenda_panel.art_rect(ComponentRegion(0, 0, 800, 480)) == (0, 0, 372, 292)
        assert halftone_agenda_wide_panel.art_rect(ComponentRegion(0, 0, 1360, 480)) == (
            0,
            0,
            420,
            292,
        )
        assert day_arc_panel.art_rect(ComponentRegion(10, 20, 800, 480)) == (10, 20, 810, 180)

    def test_halftone_agenda_wide_sky_keeps_its_halftone_on_the_four_ink_panel(self):
        """The day sky is a 100–145 grey ramp: a nearest snap makes it solid black,
        error diffusion makes it a black-and-white halftone."""
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather.current_icon = "04d"  # overcast: the sky ramp fills the pane
        cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
        img = render_dashboard(data, cfg, theme=load_theme("halftone_agenda_wide"))
        sky = _colours(img, (10, 10, 400, 60))
        assert (0, 0, 0) in sky and (255, 255, 255) in sky
        # The agenda pane beside it is still solid type: no stray inks in its margin.
        assert _colours(img, (1000, 440, 1340, 470)) <= {(0, 0, 0), (255, 255, 255)}

    def test_halftone_on_inky_sky_is_a_mixture(self):
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather.current_icon = "04d"
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025")
        img = render_dashboard(data, cfg, theme=load_theme("halftone"))
        sky = _colours(img, (10, 10, 790, 60))
        assert sky <= set(INKY_SPECTRA6_PALETTE)
        assert len(sky) >= 2
