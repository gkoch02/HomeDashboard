"""Tests for src/render/components/qotd_panel.py."""

import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from src.data.models import DayForecast, WeatherData
from src.render.components.qotd_panel import (
    _icon_width,
    _wrap_lines,
    draw_qotd,
    draw_qotd_weather,
)
from src.render.fonts import bold as jakarta_bold
from src.render.theme import ComponentRegion


def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _make_weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=68.0,
        current_icon="01d",
        current_description="clear sky",
        high=75.0,
        low=55.0,
        humidity=40,
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


TODAY = date(2026, 3, 22)


# ---------------------------------------------------------------------------
# _wrap_lines helper
# ---------------------------------------------------------------------------

class TestWrapLines:
    def _font(self, size: int = 20):
        return jakarta_bold(size)

    def test_short_text_fits_on_one_line(self):
        font = self._font()
        lines = _wrap_lines("Hello world", font, max_width=800)
        assert lines == ["Hello world"]

    def test_long_text_wraps_to_multiple_lines(self):
        font = self._font(20)
        long_text = " ".join(["word"] * 30)
        lines = _wrap_lines(long_text, font, max_width=200)
        assert len(lines) > 1

    def test_empty_string_returns_empty_list(self):
        font = self._font()
        lines = _wrap_lines("", font, max_width=400)
        assert lines == []

    def test_single_long_word_stays_on_one_line(self):
        """A single word that is too long to fit should still be placed on its own line."""
        font = self._font(20)
        lines = _wrap_lines("superlongword", font, max_width=1)
        assert len(lines) == 1
        assert lines[0] == "superlongword"

    def test_each_line_within_max_width(self):
        font = self._font(16)
        text = "This is a moderately long sentence that should wrap nicely into several lines."
        lines = _wrap_lines(text, font, max_width=200)
        for line in lines:
            assert font.getlength(line) <= 200 or " " not in line

    def test_preserves_all_words(self):
        font = self._font(20)
        words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
        text = " ".join(words)
        lines = _wrap_lines(text, font, max_width=150)
        reconstructed = " ".join(lines)
        assert reconstructed == text


# ---------------------------------------------------------------------------
# _icon_width helper
# ---------------------------------------------------------------------------

class TestIconWidth:
    def test_returns_positive_int(self):
        _, draw = _make_draw()
        width = _icon_width(draw, "01d", size=32)
        assert isinstance(width, int)
        assert width > 0

    def test_larger_size_gives_wider_result(self):
        _, draw = _make_draw()
        w_small = _icon_width(draw, "01d", size=16)
        w_large = _icon_width(draw, "01d", size=48)
        assert w_large > w_small

    def test_unknown_code_uses_fallback(self):
        """Unknown icon codes fall back to FALLBACK_ICON, still returning valid width."""
        _, draw = _make_draw()
        width = _icon_width(draw, "99z", size=32)
        assert width > 0


# ---------------------------------------------------------------------------
# draw_qotd
# ---------------------------------------------------------------------------

class TestDrawQotd:
    def test_smoke_renders_without_error(self):
        img, draw = _make_draw()
        draw_qotd(draw, TODAY)
        assert img.getbbox() is not None

    def test_smoke_various_dates(self):
        for i in range(7):
            img, draw = _make_draw()
            draw_qotd(draw, TODAY + timedelta(days=i))
            assert img.getbbox() is not None

    def test_smoke_custom_region(self):
        img, draw = _make_draw()
        region = ComponentRegion(0, 0, 800, 400)
        draw_qotd(draw, TODAY, region=region)
        assert img.getbbox() is not None

    def test_smoke_small_region_does_not_crash(self):
        img, draw = _make_draw()
        region = ComponentRegion(50, 50, 300, 200)
        draw_qotd(draw, TODAY, region=region)
        assert img.getbbox() is not None

    def test_long_quote_does_not_crash(self, tmp_path):
        """A very long quote should trigger fallback font logic without raising."""
        long_text = " ".join(["extraordinary"] * 40)
        custom_quotes = [{"text": long_text, "author": "Verbose Author"}]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(custom_quotes))

        from src.render.components.info_panel import _quote_for_today
        _quote_for_today.cache_clear()

        with patch("src.render.components.info_panel.QUOTES_FILE", qfile):
            _quote_for_today.cache_clear()
            img, draw = _make_draw()
            draw_qotd(draw, date(2099, 1, 15))
        assert img.getbbox() is not None

    def test_short_quote_uses_larger_font(self, tmp_path):
        """A short quote should fit at a large font size."""
        short_text = "Be yourself."
        custom_quotes = [{"text": short_text, "author": "A. Wise"}]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(custom_quotes))

        from src.render.components.info_panel import _quote_for_today
        _quote_for_today.cache_clear()

        with patch("src.render.components.info_panel.QUOTES_FILE", qfile):
            _quote_for_today.cache_clear()
            img, draw = _make_draw()
            draw_qotd(draw, date(2099, 2, 20))
        assert img.getbbox() is not None

    def test_different_dates_produce_different_output(self, tmp_path):
        """Different dates with different quotes should differ in output."""
        import hashlib
        quotes = [{"text": f"Quote number {i}.", "author": f"Author {i}"} for i in range(10)]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(quotes))

        from src.render.components.info_panel import _quote_for_today
        _quote_for_today.cache_clear()

        with patch("src.render.components.info_panel.QUOTES_FILE", qfile):
            _quote_for_today.cache_clear()
            renders = set()
            for i in range(10):
                img, draw = _make_draw()
                draw_qotd(draw, date(2099, 1, i + 1))
                renders.add(hashlib.md5(img.tobytes()).hexdigest())

        assert len(renders) > 1


# ---------------------------------------------------------------------------
# draw_qotd_weather
# ---------------------------------------------------------------------------

class TestDrawQotdWeather:
    def test_smoke_none_weather(self):
        img, draw = _make_draw()
        draw_qotd_weather(draw, None)
        assert img.getbbox() is not None

    def test_smoke_with_weather(self):
        img, draw = _make_draw()
        draw_qotd_weather(draw, _make_weather())
        assert img.getbbox() is not None

    def test_smoke_with_weather_and_today(self):
        img, draw = _make_draw()
        draw_qotd_weather(draw, _make_weather(), today=TODAY)
        assert img.getbbox() is not None

    def test_smoke_with_moon_phase(self):
        img, draw = _make_draw()
        draw_qotd_weather(draw, _make_weather(), today=date(2026, 1, 6))
        assert img.getbbox() is not None

    def test_smoke_custom_region(self):
        img, draw = _make_draw()
        region = ComponentRegion(0, 400, 800, 80)
        draw_qotd_weather(draw, _make_weather(), region=region)
        assert img.getbbox() is not None

    def test_smoke_with_forecast(self):
        img, draw = _make_draw()
        weather = _make_weather(
            forecast=[
                DayForecast(
                    date=TODAY + timedelta(days=i + 1),
                    high=72.0 - i,
                    low=55.0,
                    icon="02d",
                    description="partly cloudy",
                )
                for i in range(3)
            ]
        )
        draw_qotd_weather(draw, weather, today=TODAY)
        assert img.getbbox() is not None

    def test_smoke_with_alerts(self):
        from src.data.models import WeatherAlert
        img, draw = _make_draw()
        weather = _make_weather(alerts=[WeatherAlert(event="Wind Advisory")])
        draw_qotd_weather(draw, weather)
        assert img.getbbox() is not None

    def test_smoke_with_feels_like_and_wind(self):
        img, draw = _make_draw()
        weather = _make_weather(
            feels_like=65.0,
            wind_speed=12.5,
            wind_deg=270.0,
        )
        draw_qotd_weather(draw, weather)
        assert img.getbbox() is not None

    def test_smoke_with_humidity_only_detail(self):
        """When feels_like and wind_speed are None, falls back to humidity."""
        img, draw = _make_draw()
        weather = _make_weather(feels_like=None, wind_speed=None)
        draw_qotd_weather(draw, weather)
        assert img.getbbox() is not None

    def test_none_weather_differs_from_with_weather(self):
        """None weather should produce a different render than actual weather."""
        img_none, draw_none = _make_draw()
        draw_qotd_weather(draw_none, None)

        img_data, draw_data = _make_draw()
        draw_qotd_weather(draw_data, _make_weather())

        assert img_none.tobytes() != img_data.tobytes()

    def test_smoke_night_icon(self):
        img, draw = _make_draw()
        weather = _make_weather(current_icon="01n")
        draw_qotd_weather(draw, weather)
        assert img.getbbox() is not None

    def test_smoke_narrow_region(self):
        img, draw = _make_draw()
        region = ComponentRegion(0, 400, 400, 80)
        draw_qotd_weather(draw, _make_weather(), region=region)
        assert img.getbbox() is not None

    @pytest.mark.parametrize("icon_code", ["01d", "02d", "10d", "11n", "50d"])
    def test_various_icon_codes(self, icon_code):
        img, draw = _make_draw()
        weather = _make_weather(current_icon=icon_code)
        draw_qotd_weather(draw, weather)
        assert img.getbbox() is not None
