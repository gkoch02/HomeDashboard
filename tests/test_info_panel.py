"""Tests for src/render/components/info_panel.py."""

import json
from datetime import date
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.render.components.info_panel import draw_info
from src.render.quotes import cache_clear as quotes_cache_clear
from src.render.theme import ComponentRegion
from tests.inkutils import ink, record_text


class TestDrawInfo:
    def _make_draw(self):
        img = Image.new("1", (800, 480), 1)
        return img, ImageDraw.Draw(img)

    def test_smoke_draws_something(self):
        img, draw = self._make_draw()
        draw_info(draw, date(2024, 3, 15))
        assert ink(img) > 0, "the info panel drew nothing"

    def test_smoke_various_dates(self):
        import datetime

        plates = set()
        for offset in range(7):
            img, draw = self._make_draw()
            draw_info(draw, date(2024, 1, 1) + datetime.timedelta(days=offset))
            assert ink(img) > 0, f"day +{offset} drew nothing"
            plates.add(img.tobytes())
        assert len(plates) > 1, "the quote never changed across a week"

    def test_a_long_attribution_is_cut_to_the_panel(self, tmp_path):
        path = tmp_path / "quotes.json"
        author = "Rear Admiral Grace Brewster Murray Hopper (attributed, paraphrased)"
        path.write_text(json.dumps([{"text": "Short.", "author": author}]))
        img, draw = self._make_draw()
        calls = record_text(draw)
        region = ComponentRegion(500, 300, 280, 140)
        draw_info(draw, date(2024, 3, 15), region=region, quotes_path=str(path))
        attribution = [(t, box) for t, box in calls if t.startswith("—")]
        assert len(attribution) == 1
        text, box = attribution[0]
        assert text.endswith("...") and box[2] <= region.x + region.w

    def test_long_quote_adapts_to_smaller_font(self, tmp_path):
        """A very long quote triggers the smaller font (regular(12))."""
        import json

        # Build a quote whose wrapped length exceeds 3 lines at size 14
        long_body = " ".join(["word"] * 120)
        custom = [{"text": long_body, "author": "Verbosity"}]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(custom))

        quotes_cache_clear()

        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", qfile):
            quotes_cache_clear()
            img, draw = self._make_draw()
            # Use a unique date to avoid the lru_cache returning a stale result
            draw_info(draw, date(2099, 12, 31))
        assert ink(img) > 0, "the custom quote store rendered nothing"

    def test_corrupt_quotes_json_falls_back_gracefully(self, tmp_path):
        """Corrupt quotes.json falls back to the built-in default quotes."""
        corrupt = tmp_path / "quotes.json"
        corrupt.write_text("{bad json}")
        quotes_cache_clear()
        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", corrupt):
            quotes_cache_clear()
            img, draw = self._make_draw()
            draw_info(draw, date(2098, 6, 15))
        assert ink(img) > 0, "the corrupt-store fallback rendered nothing"

    def test_missing_quotes_file_uses_defaults(self, tmp_path):
        """Missing quotes.json falls back to the built-in default quotes."""
        missing = tmp_path / "nonexistent_quotes.json"
        quotes_cache_clear()
        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", missing):
            quotes_cache_clear()
            img, draw = self._make_draw()
            draw_info(draw, date(2097, 11, 22))
        assert ink(img) > 0, "the missing-store fallback rendered nothing"


class TestQuoteRefreshConfig:
    """Tests for cache.quote_refresh validation in config.py."""

    def test_valid_values_accepted(self):
        from src.config import CacheConfig, Config, validate_config

        for val in ("daily", "twice_daily", "hourly"):
            cfg = Config()
            cfg.cache = CacheConfig(quote_refresh=val)
            errors, _ = validate_config(cfg)
            field_errors = [e for e in errors if e.field == "cache.quote_refresh"]
            assert not field_errors, f"Expected no error for {val!r}, got {field_errors}"

    def test_invalid_value_raises_error(self):
        from src.config import CacheConfig, Config, validate_config

        cfg = Config()
        cfg.cache = CacheConfig(quote_refresh="weekly")
        errors, _ = validate_config(cfg)
        assert any(e.field == "cache.quote_refresh" for e in errors)

    def test_default_is_daily(self):
        from src.config import CacheConfig

        assert CacheConfig().quote_refresh == "daily"
