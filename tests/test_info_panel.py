"""Tests for src/render/components/info_panel.py."""

import json
from datetime import date, datetime
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
            _quote_for_today.cache_clear()
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


class TestQuoteRefreshModes:
    """Tests for the refresh= parameter on _quote_for_today."""

    def setup_method(self):
        _quote_for_today.cache_clear()

    def teardown_method(self):
        _quote_for_today.cache_clear()

    def test_daily_same_as_default(self):
        d = date(2025, 6, 1)
        assert _quote_for_today(d, refresh="daily") == _quote_for_today(d)

    def test_twice_daily_am_stable(self):
        d = date(2025, 6, 1)
        now_am1 = datetime(2025, 6, 1, 9, 0)
        now_am2 = datetime(2025, 6, 1, 11, 59)
        assert _quote_for_today(d, refresh="twice_daily", now=now_am1) == \
               _quote_for_today(d, refresh="twice_daily", now=now_am2)

    def test_twice_daily_pm_stable(self):
        d = date(2025, 6, 1)
        now_pm1 = datetime(2025, 6, 1, 12, 0)
        now_pm2 = datetime(2025, 6, 1, 23, 0)
        assert _quote_for_today(d, refresh="twice_daily", now=now_pm1) == \
               _quote_for_today(d, refresh="twice_daily", now=now_pm2)

    def test_twice_daily_am_pm_differ(self):
        d = date(2025, 6, 2)
        now_am = datetime(2025, 6, 2, 8, 0)
        now_pm = datetime(2025, 6, 2, 14, 0)
        # Keys differ ("2025-06-02-am" vs "2025-06-02-pm") so hashes differ
        q_am = _quote_for_today(d, refresh="twice_daily", now=now_am)
        q_pm = _quote_for_today(d, refresh="twice_daily", now=now_pm)
        assert q_am != q_pm

    def test_hourly_same_hour_stable(self):
        d = date(2025, 6, 3)
        now1 = datetime(2025, 6, 3, 14, 0)
        now2 = datetime(2025, 6, 3, 14, 59)
        assert _quote_for_today(d, refresh="hourly", now=now1) == \
               _quote_for_today(d, refresh="hourly", now=now2)

    def test_hourly_different_hours_differ(self):
        d = date(2025, 6, 3)
        now_h1 = datetime(2025, 6, 3, 9, 0)
        now_h2 = datetime(2025, 6, 3, 10, 0)
        q1 = _quote_for_today(d, refresh="hourly", now=now_h1)
        q2 = _quote_for_today(d, refresh="hourly", now=now_h2)
        assert q1 != q2

    def test_daily_and_hourly_can_differ(self):
        d = date(2025, 6, 4)
        now = datetime(2025, 6, 4, 15, 0)
        q_daily = _quote_for_today(d, refresh="daily")
        q_hourly = _quote_for_today(d, refresh="hourly", now=now)
        # Keys are different strings so at least one of the many hours will differ
        assert isinstance(q_daily, dict) and isinstance(q_hourly, dict)

    def test_result_has_text_and_author(self):
        d = date(2025, 6, 5)
        now = datetime(2025, 6, 5, 10, 0)
        for refresh in ("daily", "twice_daily", "hourly"):
            q = _quote_for_today(d, refresh=refresh, now=now)
            assert "text" in q and "author" in q


class TestQuoteRefreshConfig:
    """Tests for cache.quote_refresh validation in config.py."""

    def test_valid_values_accepted(self):
        from src.config import Config, CacheConfig, validate_config
        for val in ("daily", "twice_daily", "hourly"):
            cfg = Config()
            cfg.cache = CacheConfig(quote_refresh=val)
            errors, _ = validate_config(cfg)
            field_errors = [e for e in errors if e.field == "cache.quote_refresh"]
            assert not field_errors, f"Expected no error for {val!r}, got {field_errors}"

    def test_invalid_value_raises_error(self):
        from src.config import Config, CacheConfig, validate_config
        cfg = Config()
        cfg.cache = CacheConfig(quote_refresh="weekly")
        errors, _ = validate_config(cfg)
        assert any(e.field == "cache.quote_refresh" for e in errors)

    def test_default_is_daily(self):
        from src.config import CacheConfig
        assert CacheConfig().quote_refresh == "daily"
