"""Tests for src/display/driver.py — display registries and drivers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.display.driver import (
    DRY_RUN_HISTORY,
    INKY_MODEL_INIT,
    INKY_MODELS,
    WAVESHARE_COLOR_MODELS,
    WAVESHARE_FAST_INIT,
    WAVESHARE_MODELS,
    WAVESHARE_TRICOLOR_MODELS,
    DryRunDisplay,
    InkyDisplay,
    WaveshareDisplay,
    build_display_driver,
    get_display_spec,
    image_changed,
    persist_image_hash,
    supported_display_models,
)


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "output"


@pytest.fixture
def display(output_dir):
    return DryRunDisplay(output_dir=str(output_dir))


def _make_image() -> Image.Image:
    return Image.new("1", (800, 480), 1)


class TestDryRunDisplayInit:
    def test_creates_output_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        DryRunDisplay(output_dir=str(nested))
        assert nested.is_dir()

    def test_existing_directory_ok(self, output_dir):
        output_dir.mkdir(parents=True)
        DryRunDisplay(output_dir=str(output_dir))  # no exception


class TestDryRunDisplayShow:
    def test_creates_latest_png(self, display, output_dir):
        display.show(_make_image())
        assert (output_dir / "latest.png").exists()

    def test_creates_timestamped_png(self, display, output_dir):
        display.show(_make_image())
        pngs = list(output_dir.glob("dashboard_*.png"))
        assert len(pngs) == 1

    def test_latest_png_is_valid_image(self, display, output_dir):
        display.show(_make_image())
        loaded = Image.open(output_dir / "latest.png")
        assert loaded.size == (800, 480)

    def test_multiple_shows_create_multiple_timestamped(self, display, output_dir):
        import time

        display.show(_make_image())
        time.sleep(1.1)  # ensure different second → different filename
        display.show(_make_image())
        pngs = list(output_dir.glob("dashboard_*.png"))
        assert len(pngs) == 2

    def test_latest_png_overwritten_each_call(self, display, output_dir):
        img1 = Image.new("1", (800, 480), 0)  # all black
        img2 = Image.new("1", (800, 480), 1)  # all white

        display.show(img1)
        display.show(img2)

        # File was rewritten (sizes may differ between all-black and all-white PNGs)
        loaded = Image.open(output_dir / "latest.png")
        assert loaded.size == (800, 480)


class TestDryRunDisplayClear:
    def test_clear_does_not_raise(self, display):
        display.clear()  # should be a no-op, no exception


class TestWaveshareModels:
    def test_registry_contains_default_model(self):
        assert "epd7in5_V2" in WAVESHARE_MODELS

    def test_registry_contains_larger_models(self):
        assert "epd7in5_HD" in WAVESHARE_MODELS
        assert "epd13in3k" in WAVESHARE_MODELS

    def test_registry_drops_modules_that_do_not_exist_upstream(self):
        # Neither module exists in waveshare/e-Paper (the 9.7" panel is
        # IT8951-driven); selecting them failed at import on the first
        # hardware write (#266).
        assert "epd9in7" not in WAVESHARE_MODELS
        assert "epd7in5_V3" not in WAVESHARE_MODELS

    def test_default_model_dimensions(self):
        _, w, h = WAVESHARE_MODELS["epd7in5_V2"]
        assert w == 800
        assert h == 480

    def test_epd7in5_hd_dimensions(self):
        _, w, h = WAVESHARE_MODELS["epd7in5_HD"]
        assert w == 880
        assert h == 528

    def test_epd13in3k_dimensions(self):
        # The vendor driver's EPD_WIDTH / EPD_HEIGHT. It used to be registered
        # as 1600x1200, and getbuffer() answers a mismatched image with a blank
        # buffer — a white panel with no error (#266).
        _, w, h = WAVESHARE_MODELS["epd13in3k"]
        assert w == 960
        assert h == 680

    def test_fast_init_and_tricolor_tables_name_registered_models(self):
        assert set(WAVESHARE_FAST_INIT) <= set(WAVESHARE_MODELS)
        assert set(WAVESHARE_TRICOLOR_MODELS) <= set(WAVESHARE_MODELS)
        assert not set(WAVESHARE_FAST_INIT) & set(WAVESHARE_COLOR_MODELS)

    def test_fast_init_names_match_the_vendor_drivers(self):
        # init_fast on the 7.5" V2, init_Fast on the tri-colour 7.5".
        assert WAVESHARE_FAST_INIT == {"epd7in5_V2": "init_fast", "epd7in5b_V2": "init_Fast"}

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("epd7in5_V2", True),
            ("epd7in5b_V2", True),
            ("epd7in5", False),
            ("epd7in5_HD", False),
            ("epd13in3k", False),
            ("epd10in85g", False),
        ],
    )
    def test_spec_partial_refresh_is_a_per_model_fact(self, model, expected):
        # Every mono model used to claim partial refresh; all but the V2 then
        # raised AttributeError on the first partial write (#268).
        assert get_display_spec("waveshare", model).supports_partial_refresh is expected

    def test_all_entries_have_module_path(self):
        for name, (module_path, w, h) in WAVESHARE_MODELS.items():
            assert module_path.startswith("waveshare_epd."), name
            assert w > 0 and h > 0, name


class TestSupportedDisplayModels:
    """Cover the provider-filter and no-filter branches."""

    def test_no_provider_returns_all_models_sorted(self):
        models = supported_display_models()
        assert models == sorted(models)
        # Should include both Inky and Waveshare models.
        assert "impression_7_3_2025" in models
        assert "epd7in5_V2" in models

    def test_filter_to_inky_returns_only_inky_models(self):
        models = supported_display_models(provider="inky")
        assert "impression_7_3_2025" in models
        assert "epd7in5_V2" not in models

    def test_filter_to_waveshare_returns_only_waveshare_models(self):
        models = supported_display_models(provider="waveshare")
        assert "epd7in5_V2" in models
        assert "impression_7_3_2025" not in models

    def test_unknown_provider_returns_empty(self):
        assert supported_display_models(provider="bogus") == []


class TestInkyModels:
    def test_registry_contains_2025_model(self):
        assert "impression_7_3_2025" in INKY_MODELS

    def test_2025_model_dimensions(self):
        w, h = INKY_MODELS["impression_7_3_2025"]
        assert w == 800
        assert h == 480

    def test_display_spec_for_inky(self):
        spec = get_display_spec("inky", "impression_7_3_2025")
        assert spec is not None
        assert spec.render_mode == "RGB"
        assert spec.supports_partial_refresh is False

    def test_all_models_have_init_entry(self):
        for model in INKY_MODELS:
            assert model in INKY_MODEL_INIT, f"INKY_MODEL_INIT missing entry for '{model}'"

    def test_2025_model_init_uses_inky_e673(self):
        module_path, class_name, kwargs = INKY_MODEL_INIT["impression_7_3_2025"]
        assert module_path == "inky"
        assert class_name == "InkyE673"
        assert kwargs == {}


class TestWaveshareDisplayInit:
    def test_valid_model_accepted(self):
        d = WaveshareDisplay(model="epd7in5_V2")
        assert d.model == "epd7in5_V2"

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown Waveshare model"):
            WaveshareDisplay(model="epd_does_not_exist")

    def test_native_dimensions_from_model(self):
        d = WaveshareDisplay(model="epd7in5_HD")
        assert d.native_width == 880
        assert d.native_height == 528

    def test_partial_refresh_is_dropped_for_a_model_without_a_fast_waveform(self, caplog):
        with caplog.at_level("WARNING", logger="src.display.driver"):
            d = WaveshareDisplay(model="epd7in5_HD", enable_partial=True)
        assert d.enable_partial is False
        assert "not supported on Waveshare model epd7in5_HD" in caplog.text

    def test_partial_refresh_is_kept_for_a_model_with_a_fast_waveform(self):
        assert WaveshareDisplay(model="epd7in5_V2", enable_partial=True).enable_partial is True
        assert WaveshareDisplay(model="epd7in5b_V2", enable_partial=True).enable_partial is True

    def test_native_dimensions_default_model(self):
        d = WaveshareDisplay(model="epd7in5_V2")
        assert d.native_width == 800
        assert d.native_height == 480


class TestWaveshareDisplayHardware:
    """Tests for WaveshareDisplay methods that require mocked hardware."""

    def _make_mock_epd(
        self, methods=("init", "init_fast", "display", "getbuffer", "sleep", "Clear")
    ):
        """A mock shaped like a vendor ``EPD`` class: only *methods* exist.

        ``spec_set`` makes an unlisted attribute raise AttributeError, the way
        the real ``epd7in5`` / ``epd7in5_HD`` drivers do for ``init_fast``.
        """
        epd = MagicMock(spec_set=list(methods))
        if "getbuffer" in methods:
            epd.getbuffer.return_value = bytearray(b"\x00" * 8)
        return epd

    def _make_mock_module(self, epd):
        mod = MagicMock()
        mod.EPD.return_value = epd
        return mod

    def test_get_epd_imports_module(self):
        epd = self._make_mock_epd()
        mod = self._make_mock_module(epd)
        d = WaveshareDisplay(model="epd7in5_V2")
        with patch("importlib.import_module", return_value=mod):
            result = d._get_epd()
        assert result is epd

    def test_get_epd_caches_instance(self):
        epd = self._make_mock_epd()
        mod = self._make_mock_module(epd)
        d = WaveshareDisplay(model="epd7in5_V2")
        with patch("importlib.import_module", return_value=mod) as mock_import:
            d._get_epd()
            d._get_epd()
        # importlib.import_module should only be called once (result is cached)
        assert mock_import.call_count == 1

    def test_show_full_refresh(self):
        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = True

        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=False)
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image)

        epd.init.assert_called_once()
        epd.display.assert_called_once()
        epd.sleep.assert_called_once()
        tracker.record_full.assert_called_once()
        tracker.save.assert_called_once()

    def test_show_partial_refresh(self):
        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = False

        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image)

        epd.init_fast.assert_called_once()
        epd.display.assert_called_once()
        tracker.record_partial.assert_called_once()

    def test_show_force_full_overrides_partial(self):
        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = False

        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image, force_full=True)

        epd.init.assert_called_once()
        tracker.record_full.assert_called_once()

    def _show(self, d, epd, image=None, needs_full=False, **kw):
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = needs_full
        image = image or Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            d.show(image, **kw)
        return tracker

    def test_tricolor_full_refresh_sends_black_plane_and_blank_red_plane(self):
        # epd7in5b_V2.display(imageblack, imagered): one buffer raised
        # TypeError on every write (#267).
        epd = self._make_mock_epd(("init", "init_Fast", "display", "getbuffer", "sleep", "Clear"))
        epd.getbuffer.return_value = bytearray(b"\xaa" * 16)
        d = WaveshareDisplay(model="epd7in5b_V2", enable_partial=False)
        tracker = self._show(d, epd)

        epd.init.assert_called_once()
        (black, red), _ = epd.display.call_args
        assert black == bytearray(b"\xaa" * 16)
        # getbuffer() XORs with 0xFF, so a white image is 0x00 bytes; the
        # driver sends the red plane as given, so "no red" is all zeros.
        assert red == bytearray(16)
        tracker.record_full.assert_called_once()

    def test_tricolor_partial_refresh_uses_init_Fast(self):
        epd = self._make_mock_epd(("init", "init_Fast", "display", "getbuffer", "sleep", "Clear"))
        d = WaveshareDisplay(model="epd7in5b_V2", enable_partial=True)
        tracker = self._show(d, epd)

        epd.init_Fast.assert_called_once()
        epd.init.assert_not_called()
        assert len(epd.display.call_args.args) == 2
        tracker.record_partial.assert_called_once()

    def test_mono_model_without_fast_waveform_takes_the_full_path(self):
        # The real epd7in5_HD driver has init() only; with partial refresh on,
        # the second run used to die with AttributeError and, having recorded
        # no partial, die again every tick after (#268).
        epd = self._make_mock_epd(("init", "display", "getbuffer", "sleep", "Clear"))
        d = WaveshareDisplay(model="epd7in5_HD", enable_partial=True)
        tracker = self._show(d, epd, image=Image.new("1", (880, 528), 1))

        epd.init.assert_called_once()
        epd.display.assert_called_once_with(epd.getbuffer.return_value)
        tracker.record_full.assert_called_once()
        tracker.record_partial.assert_not_called()

    def test_registered_fast_init_missing_from_driver_falls_back_to_full(self, caplog):
        # The registry promises init_fast, the installed library lacks it.
        epd = self._make_mock_epd(("init", "display", "getbuffer", "sleep", "Clear"))
        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        with caplog.at_level("WARNING", logger="src.display.driver"):
            tracker = self._show(d, epd)

        epd.init.assert_called_once()
        tracker.record_full.assert_called_once()
        assert "no fast waveform method" in caplog.text

    def test_fast_init_lookup_accepts_either_spelling(self):
        # A driver whose author spelt it the other way still gets its fast path.
        epd = self._make_mock_epd(("init", "init_Fast", "display", "getbuffer", "sleep", "Clear"))
        d = WaveshareDisplay(model="epd7in5_V2", enable_partial=True)
        tracker = self._show(d, epd)

        epd.init_Fast.assert_called_once()
        tracker.record_partial.assert_called_once()

    def test_show_sleeps_even_on_display_error(self):
        """epd.sleep() must be called even if display() raises."""
        epd = self._make_mock_epd()
        epd.display.side_effect = RuntimeError("display failed")
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = True

        d = WaveshareDisplay(model="epd7in5_V2")
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
        ):
            with pytest.raises(RuntimeError):
                d.show(image)
        epd.sleep.assert_called_once()

    def test_show_swallows_tracker_save_error(self, caplog):
        """A failure in tracker.save() must be logged but never propagate."""
        import logging

        epd = self._make_mock_epd()
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = True
        tracker.save.side_effect = OSError("disk full")

        d = WaveshareDisplay(model="epd7in5_V2")
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
            caplog.at_level(logging.WARNING),
        ):
            d.show(image)  # must not raise
        epd.sleep.assert_called_once()
        assert any("save refresh state" in rec.message for rec in caplog.records)

    def test_show_swallows_epd_sleep_error(self, caplog):
        """A failure in epd.sleep() must be logged but never propagate."""
        import logging

        epd = self._make_mock_epd()
        epd.sleep.side_effect = RuntimeError("sleep failed")
        tracker = MagicMock()
        tracker.needs_full_refresh.return_value = True

        d = WaveshareDisplay(model="epd7in5_V2")
        image = Image.new("1", (800, 480), 1)
        with (
            patch.object(d, "_get_epd", return_value=epd),
            patch("src.display.refresh_tracker.RefreshTracker.load", return_value=tracker),
            caplog.at_level(logging.WARNING),
        ):
            d.show(image)  # must not raise
        assert any("EPD sleep failed" in rec.message for rec in caplog.records)

    def test_clear(self):
        epd = self._make_mock_epd()
        d = WaveshareDisplay(model="epd7in5_V2")
        with patch.object(d, "_get_epd", return_value=epd):
            d.clear()
        epd.init.assert_called_once()
        epd.Clear.assert_called_once()
        epd.sleep.assert_called_once()


class TestInkyDisplayInit:
    def test_valid_model_accepted(self):
        d = InkyDisplay(model="impression_7_3_2025")
        assert d.model == "impression_7_3_2025"

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown Inky model"):
            InkyDisplay(model="inky_does_not_exist")

    def test_native_dimensions(self):
        d = InkyDisplay(model="impression_7_3_2025")
        assert d.native_width == 800
        assert d.native_height == 480


class TestInkyDisplayHardware:
    def _make_mock_device(self):
        device = MagicMock()
        device.set_image = MagicMock()
        device.show = MagicMock()
        # InkyE673 SATURATED_PALETTE: 6 ink colours + Clear at index 6.
        # Order: 0=Black, 1=White, 2=Yellow, 3=Red, 4=Blue, 5=Green, 6=Clear
        device.SATURATED_PALETTE = [
            [0, 0, 0],
            [161, 164, 165],
            [208, 190, 71],
            [156, 72, 75],
            [61, 59, 94],
            [58, 91, 70],
            [255, 255, 255],
        ]
        return device

    def test_get_device_uses_direct_init(self):
        device = self._make_mock_device()
        mock_cls = MagicMock(return_value=device)
        mod = MagicMock()
        mod.InkyE673 = mock_cls
        d = InkyDisplay(model="impression_7_3_2025")
        with patch("importlib.import_module", return_value=mod) as mock_import:
            result = d._get_device()
        mock_import.assert_called_once_with("inky")
        mock_cls.assert_called_once_with()
        assert result is device

    def test_show_writes_correct_palette_index_to_buf(self):
        # show() bypasses set_image() entirely — computes nearest SATURATED_PALETTE index
        # per pixel via numpy, applies the InkyE673 controller remap [0,1,2,3,5,6], and
        # writes a 2-D (height × width) array to device.buf so show()'s flip/rotation works.
        import numpy as np

        device = self._make_mock_device()
        d = InkyDisplay(model="impression_7_3_2025")
        # Solid blue image — InkyE673 SATURATED_PALETTE index 4 = (61, 59, 94), nearest.
        # After remap [0,1,2,3,5,6]: remap[4] = 5 → controller position 5.
        image = Image.new("RGB", (800, 480), (61, 59, 94))
        with patch.object(d, "_get_device", return_value=device):
            d.show(image)
        device.set_image.assert_not_called()
        device.show.assert_called_once()
        assert device.buf.shape == (480, 800)  # 2-D (height, width), matches set_image()
        assert device.buf.dtype == np.uint8
        assert np.all(device.buf == 5)  # palette idx 4 (blue) → remap[4] = controller 5

    def test_clear_fills_buf_with_white_index(self):
        import numpy as np

        device = self._make_mock_device()
        d = InkyDisplay(model="impression_7_3_2025")
        with patch.object(d, "_get_device", return_value=device):
            d.clear()
        device.set_image.assert_not_called()
        device.show.assert_called_once()
        assert device.buf.shape == (480, 800)  # 2-D (height, width), matches set_image()
        assert device.buf.dtype == np.uint8
        assert np.all(device.buf == 1)  # 1 = White ink


class TestBuildDisplayDriver:
    def test_builds_waveshare_driver(self):
        driver = build_display_driver(provider="waveshare", model="epd7in5_V2")
        assert isinstance(driver, WaveshareDisplay)

    def test_builds_inky_driver(self):
        driver = build_display_driver(provider="inky", model="impression_7_3_2025")
        assert isinstance(driver, InkyDisplay)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown display provider"):
            build_display_driver(provider="future", model="x")


class TestImageChanged:
    def test_returns_true_when_no_hash_file(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        assert image_changed(image, str(tmp_path)) is True

    def test_returns_false_when_image_unchanged(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        persist_image_hash(image, str(tmp_path))  # record as displayed
        assert image_changed(image, str(tmp_path)) is False

    def test_returns_true_when_image_differs(self, tmp_path):
        img1 = Image.new("1", (100, 100), 1)
        img2 = Image.new("1", (100, 100), 0)
        persist_image_hash(img1, str(tmp_path))  # record img1 as displayed
        assert image_changed(img2, str(tmp_path)) is True

    def test_persist_writes_hash_file(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        persist_image_hash(image, str(tmp_path))
        hash_file = tmp_path / "last_image_hash.txt"
        assert hash_file.exists()
        assert len(hash_file.read_text().strip()) == 64  # SHA-256 hex digest

    def test_compare_does_not_persist(self, tmp_path):
        """Regression (#207): image_changed must be a pure comparison — the
        hash is only recorded via persist_image_hash after a successful
        hardware write, so a failed show() retries instead of skipping."""
        image = Image.new("1", (100, 100), 1)
        assert image_changed(image, str(tmp_path)) is True
        assert not (tmp_path / "last_image_hash.txt").exists()
        # Still "changed" until something persists it.
        assert image_changed(image, str(tmp_path)) is True

    def test_treats_corrupt_hash_file_as_changed(self, tmp_path):
        image = Image.new("1", (100, 100), 1)
        hash_file = tmp_path / "last_image_hash.txt"
        hash_file.write_text("not-a-valid-hash\n")
        # Different hash → treated as changed
        assert image_changed(image, str(tmp_path)) is True

    def test_handles_unreadable_hash_file(self, tmp_path):
        """If the hash file can't be read, treat the image as changed."""
        image = Image.new("1", (100, 100), 1)
        hash_file = tmp_path / "last_image_hash.txt"
        hash_file.write_text("anything")
        with patch("pathlib.Path.read_text", side_effect=OSError("no perm")):
            result = image_changed(image, str(tmp_path))
        assert result is True

    def test_persist_swallows_write_failure(self, tmp_path):
        """A failed hash write must log, not raise, so publish() completes."""
        image = Image.new("1", (100, 100), 1)
        with patch("pathlib.Path.write_text", side_effect=OSError("read-only")):
            persist_image_hash(image, str(tmp_path))  # must not raise


class TestDryRunHistoryPruning:
    """Timestamped dry-run PNGs used to accumulate forever (#245).

    They are gitignored, so they never showed up in ``git status`` while
    quietly filling the card at ~50-100 KB each, and ``make dry`` / preview
    loops produce them in bulk.
    """

    def _plate(self):
        return Image.new("1", (8, 8), 1)

    def _history(self, tmp_path):
        return sorted(p.name for p in tmp_path.glob("dashboard_*.png"))

    def test_history_is_capped_at_keep(self, tmp_path):
        display = DryRunDisplay(output_dir=str(tmp_path), keep=3)
        for i in range(6):
            (tmp_path / f"dashboard_2026010{i}_120000.png").write_bytes(b"")
        display.show(self._plate())

        assert len(self._history(tmp_path)) == 3

    def test_the_newest_files_are_the_ones_kept(self, tmp_path):
        display = DryRunDisplay(output_dir=str(tmp_path), keep=2)
        for day in range(1, 5):
            (tmp_path / f"dashboard_2026010{day}_120000.png").write_bytes(b"")
        display.show(self._plate())

        kept = self._history(tmp_path)
        assert kept[0] == "dashboard_20260104_120000.png"
        assert len(kept) == 2
        # The run's own frame is the newest and is always among them.
        assert kept[-1].startswith("dashboard_")

    def test_latest_png_is_never_pruned(self, tmp_path):
        display = DryRunDisplay(output_dir=str(tmp_path), keep=1)
        for day in range(1, 5):
            (tmp_path / f"dashboard_2026010{day}_120000.png").write_bytes(b"")
        display.show(self._plate())

        assert (tmp_path / "latest.png").exists()

    def test_unrelated_pngs_are_left_alone(self, tmp_path):
        display = DryRunDisplay(output_dir=str(tmp_path), keep=1)
        (tmp_path / "theme_agenda.png").write_bytes(b"")
        (tmp_path / "dashboard_20260101_120000.png").write_bytes(b"")
        display.show(self._plate())

        assert (tmp_path / "theme_agenda.png").exists()

    def test_a_short_history_is_untouched(self, tmp_path):
        display = DryRunDisplay(output_dir=str(tmp_path), keep=20)
        display.show(self._plate())
        display.show(self._plate())

        assert len(self._history(tmp_path)) >= 1

    def test_pruning_failure_does_not_break_the_preview(self, tmp_path, monkeypatch):
        display = DryRunDisplay(output_dir=str(tmp_path), keep=0)
        monkeypatch.setattr(Path, "unlink", _raise_oserror)
        (tmp_path / "dashboard_20260101_120000.png").write_bytes(b"")

        display.show(self._plate())

        assert (tmp_path / "latest.png").exists()

    def test_default_cap_is_the_module_constant(self, tmp_path):
        assert DryRunDisplay(output_dir=str(tmp_path)).keep == DRY_RUN_HISTORY


def _raise_oserror(*args, **kwargs):
    raise OSError("read-only filesystem")
