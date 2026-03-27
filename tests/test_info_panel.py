"""Tests for src/render/components/info_panel.py."""

import json
from datetime import date
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.render.components.info_panel import _quote_for_today, draw_info


class TestQuoteForToday:
    def test_returns_dict_with_text_and_author(self):
        q = _quote_for_today(date(2024, 3, 15))
        assert "text" in q
        assert "author" in q
        assert isinstance(q["text"], str)
        assert isinstance(q["author"], str)

    def test_deterministic_same_day(self):
        d = date(2024, 6, 21)
        q1 = _quote_for_today(d)
        q2 = _quote_for_today(d)
        assert q1 == q2

    def test_different_days_can_differ(self):
        """Two different dates should not always return the same quote
        (statistically near-certain with any real pool)."""
        from datetime import timedelta
        quotes = {
            _quote_for_today(date(2024, 1, 1) + timedelta(days=i))["text"]
            for i in range(10)
        }
        assert len(quotes) > 1

    def test_uses_quotes_json_when_present(self, tmp_path):
        custom = [{"text": "Custom quote", "author": "Custom Author"}]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(custom))

        with patch("src.render.components.info_panel.QUOTES_FILE", qfile):
            q = _quote_for_today(date(2024, 3, 15))

        assert q["text"] == "Custom quote"
        assert q["author"] == "Custom Author"

    def test_falls_back_to_defaults_when_file_missing(self, tmp_path):
        missing = tmp_path / "no_such_file.json"
        with patch("src.render.components.info_panel.QUOTES_FILE", missing):
            q = _quote_for_today(date(2024, 3, 15))
        assert q["text"]  # non-empty

    def test_falls_back_to_defaults_on_corrupt_json(self, tmp_path):
        corrupt = tmp_path / "quotes.json"
        corrupt.write_text("not json {{{")
        with patch("src.render.components.info_panel.QUOTES_FILE", corrupt):
            q = _quote_for_today(date(2024, 3, 15))
        assert q["text"]

    def test_index_within_pool_bounds(self):
        """Hash-mod should never produce an out-of-range index."""
        for day_offset in range(100):
            d = date(2024, 1, 1) + __import__("datetime").timedelta(days=day_offset)
            q = _quote_for_today(d)
            assert q["text"]


class TestDrawInfo:
    def _make_draw(self):
        img = Image.new("1", (800, 480), 1)
        return img, ImageDraw.Draw(img)

    def test_smoke_draws_something(self):
        img, draw = self._make_draw()
        draw_info(draw, date(2024, 3, 15))
        assert img.getbbox() is not None

    def test_smoke_various_dates(self):
        import datetime
        for offset in range(7):
            img, draw = self._make_draw()
            draw_info(draw, date(2024, 1, 1) + datetime.timedelta(days=offset))
            assert img.getbbox() is not None

    def test_long_quote_adapts_to_smaller_font(self, tmp_path):
        """A very long quote triggers the smaller font (regular(12)) path (lines 62-65)."""
        import json
        # Build a quote whose wrapped length exceeds 3 lines at size 14
        long_body = " ".join(["word"] * 120)
        custom = [{"text": long_body, "author": "Verbosity"}]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(custom))

        from src.render.components.info_panel import _quote_for_today
        _quote_for_today.cache_clear()

        with patch("src.render.components.info_panel.QUOTES_FILE", qfile):
            _quote_for_today.cache_clear()
            img, draw = self._make_draw()
            # Use a unique date to avoid the lru_cache returning a stale result
            draw_info(draw, date(2099, 12, 31))
        assert img.getbbox() is not None

    def test_corrupt_quotes_json_falls_back_gracefully(self, tmp_path):
        """Corrupt quotes.json triggers except path (lines 62-63) in _quote_for_today."""
        corrupt = tmp_path / "quotes.json"
        corrupt.write_text("{bad json}")
        from src.render.components.info_panel import _quote_for_today
        _quote_for_today.cache_clear()
        with patch("src.render.components.info_panel.QUOTES_FILE", corrupt):
            _quote_for_today.cache_clear()
            img, draw = self._make_draw()
            draw_info(draw, date(2098, 6, 15))
        assert img.getbbox() is not None

    def test_missing_quotes_file_uses_defaults(self, tmp_path):
        """Missing quotes.json triggers else path (lines 64-65) in _quote_for_today."""
        missing = tmp_path / "nonexistent_quotes.json"
        from src.render.components.info_panel import _quote_for_today
        _quote_for_today.cache_clear()
        with patch("src.render.components.info_panel.QUOTES_FILE", missing):
            _quote_for_today.cache_clear()
            img, draw = self._make_draw()
            draw_info(draw, date(2097, 11, 22))
        assert img.getbbox() is not None
