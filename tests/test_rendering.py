"""Rendering smoke tests — verifies the pipeline produces a valid image."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PIL import Image

from src.config import DisplayConfig
from src.data.models import (
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    WeatherData,
)
from src.render.canvas import _resolve_style, render_dashboard
from src.render.theme import Theme, ThemeLayout, ThemeStyle
from src.render.themes.qotd import qotd_theme


def _make_data(today: date | None = None) -> DashboardData:
    today = today or date(2024, 3, 15)
    now = datetime.combine(today, datetime.min.time().replace(hour=8))
    week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    return DashboardData(
        fetched_at=now,
        events=[
            CalendarEvent(
                summary="Team Standup",
                start=datetime.combine(
                    week_start + timedelta(days=1),
                    datetime.min.time().replace(hour=9),
                ),
                end=datetime.combine(
                    week_start + timedelta(days=1),
                    datetime.min.time().replace(hour=9, minute=30),
                ),
            ),
            CalendarEvent(
                summary="All Day Event",
                start=datetime.combine(week_start + timedelta(days=2), datetime.min.time()),
                end=datetime.combine(week_start + timedelta(days=3), datetime.min.time()),
                is_all_day=True,
            ),
        ],
        weather=WeatherData(
            current_temp=42.0,
            current_icon="02d",
            current_description="partly cloudy",
            high=48.0,
            low=35.0,
            humidity=65,
            forecast=[
                DayForecast(
                    date=today + timedelta(days=1),
                    high=45.0,
                    low=33.0,
                    icon="10d",
                    description="rain",
                ),
                DayForecast(
                    date=today + timedelta(days=2),
                    high=50.0,
                    low=38.0,
                    icon="01d",
                    description="clear",
                ),
                DayForecast(
                    date=today + timedelta(days=3),
                    high=47.0,
                    low=36.0,
                    icon="04d",
                    description="cloudy",
                ),
            ],
        ),
        birthdays=[Birthday(name="Alice", date=today + timedelta(days=5), age=30)],
    )


class TestRenderDashboard:
    def test_returns_pil_image(self):
        data = _make_data()
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert isinstance(result, Image.Image)

    def test_correct_dimensions(self):
        data = _make_data()
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)

    def test_is_1bit_mode(self):
        data = _make_data()
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.mode == "1"

    def test_renders_without_weather(self):
        data = _make_data()
        data.weather = None
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)

    def test_renders_without_events(self):
        data = _make_data()
        data.events = []
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)

    def test_renders_without_birthdays(self):
        data = _make_data()
        data.birthdays = []
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)

    def test_stale_flag_does_not_crash(self):
        data = _make_data()
        data.is_stale = True
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)

    def test_panels_can_be_disabled(self):
        data = _make_data()
        cfg = DisplayConfig(show_weather=False, show_birthdays=False, show_info_panel=False)
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)

    def test_not_all_white(self):
        """Sanity check that something was actually drawn."""
        data = _make_data()
        cfg = DisplayConfig()
        result = render_dashboard(data, cfg)
        assert result.getbbox() is not None, "Expected black pixels but image is all white"

    def test_scales_to_larger_display(self):
        """When width/height differ from 800×480, the image should be scaled."""
        data = _make_data()
        cfg = DisplayConfig(width=1200, height=825)  # epd9in7 resolution
        result = render_dashboard(data, cfg)
        assert result.size == (1200, 825)
        assert result.mode == "1"

    def test_scales_to_smaller_display(self):
        """Downscaling to a smaller display resolution should also work."""
        data = _make_data()
        cfg = DisplayConfig(width=640, height=384)  # epd7in5 V1
        result = render_dashboard(data, cfg)
        assert result.size == (640, 384)
        assert result.mode == "1"

    def test_inky_target_returns_rgb_image(self):
        data = _make_data()
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025", width=800, height=480)
        result = render_dashboard(data, cfg)
        assert result.size == (800, 480)
        assert result.mode == "RGB"

    def test_inky_target_returns_rgb_mode(self):
        """Inky output stays as RGB — pre-quantization is left to the Inky library."""
        data = _make_data()
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025", width=800, height=480)
        result = render_dashboard(data, cfg)
        assert result.mode == "RGB"

    def test_inky_theme_gets_theme_specific_key_accents(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025", width=800, height=480)
        style = _resolve_style(
            Theme(name="fuzzyclock", layout=ThemeLayout(), style=ThemeStyle()),
            render_mode="RGB",
            config=cfg,
        )
        # fuzzyclock key colors: primary=yellow (InkyE673 idx 2), secondary=blue (idx 4)
        # Values are the exact InkyE673 SATURATED_PALETTE entries.
        assert style.accent_primary == (208, 190, 71)
        assert style.accent_secondary == (61, 59, 94)

    def test_qotd_inky_theme_honors_explicit_accent_overrides(self):
        cfg = DisplayConfig(provider="inky", model="impression_7_3_2025", width=800, height=480)
        style = _resolve_style(qotd_theme(), render_mode="RGB", config=cfg)
        assert style.accent_primary == (61, 59, 94)
        assert style.accent_info == (58, 91, 70)

    def test_qotd_waveshare_explicit_inky_accents_fall_back_to_fg(self):
        cfg = DisplayConfig()
        style = _resolve_style(qotd_theme(), render_mode="1", config=cfg)
        assert style.accent_primary == style.fg
        assert style.accent_info == style.fg


class TestGreyscaleCanvas:
    """Verify that a theme opting in to canvas_mode='L' still returns a 1-bit image."""

    def _make_l_theme(self) -> Theme:
        """Minimal L-mode theme: full-canvas header only, no other components."""
        layout = ThemeLayout(
            canvas_w=200,
            canvas_h=100,
            canvas_mode="L",
            draw_order=["header"],
        )
        # L-mode themes must use bg=255 (white) and fg=0 (black)
        style = ThemeStyle(fg=0, bg=255)
        return Theme(name="_test_l", layout=layout, style=style)

    def test_l_canvas_theme_returns_1bit(self):
        data = _make_data()
        cfg = DisplayConfig(width=200, height=100)
        theme = self._make_l_theme()
        result = render_dashboard(data, cfg, theme=theme)
        assert result.mode == "1"

    def test_l_canvas_theme_correct_dimensions(self):
        data = _make_data()
        cfg = DisplayConfig(width=200, height=100)
        theme = self._make_l_theme()
        result = render_dashboard(data, cfg, theme=theme)
        assert result.size == (200, 100)

    def test_l_canvas_theme_non_blank(self):
        """L-mode theme with header should draw something."""
        data = _make_data()
        cfg = DisplayConfig(width=200, height=100)
        theme = self._make_l_theme()
        result = render_dashboard(data, cfg, theme=theme)
        assert result.getbbox() is not None, "Expected black pixels but image is all white"

    def test_l_canvas_with_quantization_modes(self):
        """All three quantization modes should return a valid 1-bit image."""
        data = _make_data()
        theme = self._make_l_theme()
        for mode in ("threshold", "floyd_steinberg", "ordered"):
            cfg = DisplayConfig(width=200, height=100, quantization_mode=mode)
            result = render_dashboard(data, cfg, theme=theme)
            assert result.mode == "1", f"Failed for mode={mode}"
            assert result.size == (200, 100), f"Wrong size for mode={mode}"
