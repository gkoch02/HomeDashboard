"""Regressions for the fresh-eyes review of the panoramic-panel branch."""

from __future__ import annotations

from datetime import date

from PIL import Image

from src.config import DisplayConfig
from src.display.backend import G_EXACT_REMAP, WaveshareColorBackend, dither_art_regions
from src.display.driver import WAVESHARE_G_PALETTE
from src.render.primitives import next_birthday
from src.render.quantize import INKY_SPECTRA6_PALETTE, flatten_pixels, quantize_to_palette_nearest
from src.render.random_theme import eligible_themes, theme_fits_panel
from src.services.output import _resolve_min_refresh_seconds

LANDSCAPE = (800, 480)
PANORAMIC = (1360, 480)
WIDE = {"wide_week", "wide_day", "wide_forecast", "wide_horizon", "halftone_agenda_wide"}


class TestSpectraAccentsOnTheGPanel:
    def test_solid_spectra_yellow_stays_a_solid_yellow_disc(self):
        """skyart fills the sun with Inky's measured yellow on any RGB canvas;
        diffused as-is against pure yellow it speckles."""
        tile = Image.new("RGB", (92, 92), INKY_SPECTRA6_PALETTE[2])
        plate = Image.new("RGB", (92, 92), (0, 0, 0))
        out = dither_art_regions(
            tile,
            plate,
            [(0, 0, 92, 92)],
            (1.0, 1.0, 0, 0),
            list(WAVESHARE_G_PALETTE),
            remap=G_EXACT_REMAP,
        )
        assert set(flatten_pixels(out)) == {(255, 255, 0)}

    def test_backend_applies_the_remap(self):
        cfg = DisplayConfig(model="epd10in85g", width=1360, height=480)
        img = Image.new("RGB", PANORAMIC, (255, 255, 255))
        img.paste(INKY_SPECTRA6_PALETTE[3], (0, 0, 100, 100))  # Spectra red
        out = WaveshareColorBackend(cfg, WAVESHARE_G_PALETTE).resize_and_finalize(
            img,
            canvas_size=PANORAMIC,
            layout=type("L", (), {"canvas_mode": "1", "preferred_quantization_mode": None})(),
            background=(255, 255, 255),
            dither_regions=[(0, 0, 200, 200)],
        )
        assert set(flatten_pixels(out.crop((0, 0, 100, 100)))) == {(255, 0, 0)}

    def test_blue_and_green_fold_onto_black_inside_a_region(self):
        tile = Image.new("RGB", (20, 20), INKY_SPECTRA6_PALETTE[4])
        plate = Image.new("RGB", (20, 20), (255, 255, 255))
        out = dither_art_regions(
            tile,
            plate,
            [(0, 0, 20, 20)],
            (1.0, 1.0, 0, 0),
            list(WAVESHARE_G_PALETTE),
            remap=G_EXACT_REMAP,
        )
        assert set(flatten_pixels(out)) == {(0, 0, 0)}


class TestNearestQuantizerRewrite:
    def test_matches_a_brute_force_argmin(self):
        import numpy as np

        rng = np.random.default_rng(7)
        arr = rng.integers(0, 256, size=(40, 60, 3), dtype=np.uint8)
        img = Image.fromarray(arr, mode="RGB")
        out = np.asarray(quantize_to_palette_nearest(img, list(WAVESHARE_G_PALETTE)))
        pal = np.array(WAVESHARE_G_PALETTE, dtype=np.int32)
        diff = arr.astype(np.int32)[:, :, None, :] - pal[None, None, :, :]
        expected = pal[np.argmin(np.sum(diff * diff, axis=3), axis=2)].astype(np.uint8)
        assert (out == expected).all()


class TestRandomPoolRespectsThePanelShape:
    def test_landscape_panel_excludes_the_panoramic_themes(self):
        pool = set(eligible_themes([], [], LANDSCAPE))
        assert not pool & WIDE
        assert "halftone_agenda" in pool

    def test_panoramic_panel_keeps_only_the_panoramic_themes(self):
        pool = set(eligible_themes([], [], PANORAMIC))
        assert pool == WIDE

    def test_no_panel_means_no_filter(self):
        assert WIDE <= set(eligible_themes([], []))

    def test_supersampled_canvas_is_the_panels_shape(self):
        assert theme_fits_panel("weatherglass", LANDSCAPE)  # 1600x960 is 800x480's shape
        assert not theme_fits_panel("weatherglass", PANORAMIC)
        assert theme_fits_panel("no_such_theme", LANDSCAPE)

    def test_a_persisted_pick_is_revalidated_against_the_panel(self, tmp_path):
        """A stored pick bypassed the panel filter (Codex review on #257).

        The persisted-choice branch validated against the whole real-theme
        set, so a ``halftone_agenda_wide`` stored for today kept letterboxing
        an 800x480 panel until midnight.
        """
        import json

        from src.render.random_theme import pick_random_theme, pick_random_theme_hourly

        today = date(2026, 3, 22)
        (tmp_path / "random_theme_state.json").write_text(
            json.dumps({"date": "2026-03-22", "theme": "halftone_agenda_wide"})
        )
        assert pick_random_theme([], [], str(tmp_path), today=today) == "halftone_agenda_wide"
        chosen = pick_random_theme([], [], str(tmp_path), today=today, panel=LANDSCAPE)
        assert chosen not in WIDE
        # Reporting only: the stale pick is not what the panel will show.
        (tmp_path / "random_theme_state.json").write_text(
            json.dumps({"date": "2026-03-22", "theme": "halftone_agenda_wide"})
        )
        assert (
            pick_random_theme([], [], str(tmp_path), today=today, persist=False, panel=LANDSCAPE)
            == ""
        )

        from datetime import datetime

        now = datetime(2026, 3, 22, 14, 5)
        (tmp_path / "random_theme_hourly_state.json").write_text(
            json.dumps({"hour": "2026-03-22T14", "theme": "wide_day"})
        )
        assert pick_random_theme_hourly([], [], str(tmp_path), now=now) == "wide_day"
        chosen = pick_random_theme_hourly([], [], str(tmp_path), now=now, panel=LANDSCAPE)
        assert chosen not in WIDE

    def test_a_persisted_pick_that_fits_is_kept(self, tmp_path):
        import json

        from src.render.random_theme import pick_random_theme

        (tmp_path / "random_theme_state.json").write_text(
            json.dumps({"date": "2026-03-22", "theme": "wide_day"})
        )
        assert (
            pick_random_theme([], [], str(tmp_path), today=date(2026, 3, 22), panel=PANORAMIC)
            == "wide_day"
        )


class TestCooldownDefaultFollowsTheSpec:
    def test_four_ink_waveshare_gets_the_colour_default(self):
        assert _resolve_min_refresh_seconds("waveshare", None, "epd10in85g") == 60

    def test_mono_waveshare_keeps_zero(self):
        assert _resolve_min_refresh_seconds("waveshare", None, "epd7in5_V2") == 0

    def test_configured_value_wins(self):
        assert _resolve_min_refresh_seconds("waveshare", 900, "epd10in85g") == 900


class TestNextBirthday:
    def test_this_year_when_ahead(self):
        assert next_birthday(date(1990, 6, 1), date(2026, 4, 6)) == date(2026, 6, 1)

    def test_today_counts(self):
        assert next_birthday(date(1990, 4, 6), date(2026, 4, 6)) == date(2026, 4, 6)

    def test_rolls_to_next_year(self):
        assert next_birthday(date(1990, 1, 5), date(2026, 4, 6)) == date(2027, 1, 5)

    def test_leap_day_off_leap_years(self):
        assert next_birthday(date(1992, 2, 29), date(2027, 1, 1)) == date(2027, 2, 28)
        assert next_birthday(date(1992, 2, 29), date(2028, 1, 1)) == date(2028, 2, 29)
        # Past Feb 28 in a non-leap year: next year, which is a leap year.
        assert next_birthday(date(1992, 2, 29), date(2027, 3, 1)) == date(2028, 2, 29)


class TestPreviewScript:
    def test_aspect_and_suffix_rules(self):
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "build_previews", Path("scripts/build_previews.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._aspect_differs((1360, 480), (800, 480))
        assert not mod._aspect_differs((1600, 960), (800, 480))
        assert mod._default_suffix("waveshare", "epd7in5_V2") == ""
        assert mod._default_suffix("waveshare", "epd10in85g") == "_g"
        assert mod._default_suffix("inky", "impression_7_3_2025") == "_inky"
