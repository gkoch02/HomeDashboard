"""Tests for scripts/build_previews.py — the registry-driven preview batch (#219).

The Makefile used to carry a hand-maintained list of 24 theme names that
nothing enforced, so a new theme silently never got a preview. These pin the
"no list to forget" property and the batch's rendering behaviour.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_previews", REPO_ROOT / "scripts" / "build_previews.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_previews"] = module
    spec.loader.exec_module(module)
    return module


bp = _load_script()


class TestThemeCoverage:
    def test_every_registered_theme_is_in_the_batch(self):
        from src.render.themes.registry import all_theme_names

        assert set(all_theme_names()) <= set(bp._theme_names(None))

    def test_the_default_pseudo_theme_is_included(self):
        """docs/themes.md embeds theme_default.png, but it is not in the registry."""
        assert "default" in bp._theme_names(None)

    def test_nothing_is_excluded_today(self):
        assert bp.EXCLUDED == frozenset()

    def test_the_batch_covers_the_themes_the_old_makefile_list_missed(self):
        """The 24-name list omitted twelve themes; all of them render now."""
        previously_missing = {
            "almanac",
            "astronomy",
            "constellation_map",
            "countdown",
            "light_cycle",
            "message",
            "monthly",
            "photo",
            "scorecard",
            "sunrise",
            "tides",
            "weatherglass",
        }
        assert previously_missing <= set(bp._theme_names(None))

    def test_explicit_theme_selection_is_honoured(self):
        assert bp._theme_names(["agenda", "qotd"]) == ["agenda", "qotd"]

    def test_unknown_theme_is_rejected(self):
        with pytest.raises(SystemExit):
            bp._theme_names(["not_a_theme"])

    def test_names_are_sorted_and_unique(self):
        names = bp._theme_names(None)
        assert names == sorted(set(names))


class TestRendering:
    def _render(self, tmp_path, theme, provider="waveshare"):
        cfg = bp._build_config(provider, str(bp.EXAMPLE_CONFIG))
        from datetime import datetime

        now = datetime(2026, 4, 6, 10, 30)
        out = tmp_path / f"theme_{theme}.png"
        bp.render_preview(theme, cfg, now, out)
        return out

    def test_renders_a_png_of_the_expected_size(self, tmp_path):
        out = self._render(tmp_path, "agenda")
        assert out.exists()
        assert Image.open(out).size == (800, 480)

    def test_render_is_reproducible_for_a_pinned_date(self, tmp_path):
        a = self._render(tmp_path, "moonphase").read_bytes()
        (tmp_path / "theme_moonphase.png").unlink()
        b = self._render(tmp_path, "moonphase").read_bytes()
        assert a == b

    def test_message_theme_gets_preview_text(self, tmp_path):
        """Without it the plate is an empty-state placeholder."""
        blank = self._render(tmp_path, "message").read_bytes()
        assert blank
        assert bp.PREVIEW_MESSAGE

    def test_inky_provider_renders_too(self, tmp_path):
        out = self._render(tmp_path, "weather", provider="inky")
        assert Image.open(out).size == (800, 480)

    def test_previews_persist_no_state(self, tmp_path, monkeypatch):
        """A dummy-data preview must not teach the weatherglass barometer."""
        import src.render.canvas as canvas

        captured = {}
        real = canvas.render_dashboard

        def _spy(*args, **kwargs):
            captured.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(bp, "render_dashboard", _spy)
        self._render(tmp_path, "weatherglass")
        assert captured["state_dir"] is None


class TestConfigHandling:
    def test_default_date_matches_the_snapshot_fixture(self):
        assert bp.DEFAULT_DATE == date(2026, 4, 6)

    def test_provider_selects_the_matching_model(self):
        waveshare = bp._build_config("waveshare", str(bp.EXAMPLE_CONFIG))
        inky = bp._build_config("inky", str(bp.EXAMPLE_CONFIG))
        assert waveshare.display.provider == "waveshare"
        assert inky.display.model == "impression_7_3_2025"

    def test_inky_previews_get_an_inky_suffix(self):
        assert bp._SUFFIX["inky"] == "_inky"
        assert bp._SUFFIX["waveshare"] == ""

    def test_bad_date_is_rejected(self):
        with pytest.raises(SystemExit):
            bp.main(["--date", "not-a-date", "--theme", "agenda"])


class TestBatch:
    def test_batch_writes_one_png_per_theme(self, tmp_path):
        rc = bp.main(["--out-dir", str(tmp_path), "--theme", "agenda", "--theme", "qotd"])
        assert rc == 0
        assert {p.name for p in tmp_path.glob("*.png")} == {
            "theme_agenda.png",
            "theme_qotd.png",
        }

    def test_a_failing_theme_does_not_abort_the_batch(self, tmp_path, monkeypatch):
        calls = []
        real = bp.render_preview

        def _flaky(name, cfg, now, out_path):
            calls.append(name)
            if name == "agenda":
                raise RuntimeError("boom")
            return real(name, cfg, now, out_path)

        monkeypatch.setattr(bp, "render_preview", _flaky)
        rc = bp.main(["--out-dir", str(tmp_path), "--theme", "agenda", "--theme", "qotd"])

        assert calls == ["agenda", "qotd"]
        assert (tmp_path / "theme_qotd.png").exists()
        assert rc == 1  # but the failure is still reported
