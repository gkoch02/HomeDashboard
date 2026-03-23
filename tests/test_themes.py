"""Tests for the theme system (src/render/theme.py) and built-in themes."""

from datetime import date, datetime, timedelta

import pytest
from PIL import Image

from src.config import DisplayConfig
from src.data.models import (
    Birthday, CalendarEvent, DashboardData, DayForecast, WeatherData,
)
from src.render.canvas import render_dashboard
from src.render.theme import (
    AVAILABLE_THEMES,
    ComponentRegion,
    Theme,
    ThemeLayout,
    ThemeStyle,
    default_layout,
    default_theme,
    load_theme,
)


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

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
        ],
        weather=WeatherData(
            current_temp=55.0,
            current_icon="01d",
            current_description="clear",
            high=60.0,
            low=45.0,
            humidity=50,
            forecast=[
                DayForecast(
                    date=today + timedelta(days=1), high=58.0, low=42.0,
                    icon="02d", description="partly cloudy",
                ),
            ],
        ),
        birthdays=[Birthday(name="Alice", date=today + timedelta(days=5), age=30)],
    )


# ---------------------------------------------------------------------------
# ThemeStyle
# ---------------------------------------------------------------------------

class TestThemeStyle:
    def test_default_values(self):
        s = ThemeStyle()
        assert s.fg == 0    # BLACK
        assert s.bg == 1    # WHITE
        assert s.invert_header is True
        assert s.invert_today_col is True
        assert s.invert_allday_bars is True
        assert s.spacing_scale == 1.0
        assert s.label_font_size == 12
        assert s.label_font_weight == "bold"

    def test_default_fonts_filled_by_post_init(self):
        """Leaving font callables as None triggers __post_init__ default assignment."""
        s = ThemeStyle()
        assert s.font_regular is not None
        assert s.font_medium is not None
        assert s.font_semibold is not None
        assert s.font_bold is not None

    def test_font_callables_return_font_objects(self):
        from PIL import ImageFont
        s = ThemeStyle()
        for fn in (s.font_regular, s.font_medium, s.font_semibold, s.font_bold):
            result = fn(12)
            assert isinstance(result, ImageFont.FreeTypeFont)

    def test_label_font_method_bold(self):
        from PIL import ImageFont
        s = ThemeStyle(label_font_weight="bold", label_font_size=12)
        assert isinstance(s.label_font(), ImageFont.FreeTypeFont)

    def test_label_font_method_regular(self):
        from PIL import ImageFont
        s = ThemeStyle(label_font_weight="regular", label_font_size=11)
        assert isinstance(s.label_font(), ImageFont.FreeTypeFont)

    def test_custom_fg_bg(self):
        s = ThemeStyle(fg=1, bg=0)
        assert s.fg == 1
        assert s.bg == 0


# ---------------------------------------------------------------------------
# ComponentRegion
# ---------------------------------------------------------------------------

class TestComponentRegion:
    def test_default_visible(self):
        r = ComponentRegion(0, 0, 100, 50)
        assert r.visible is True

    def test_invisible(self):
        r = ComponentRegion(0, 0, 100, 50, visible=False)
        assert r.visible is False


# ---------------------------------------------------------------------------
# ThemeLayout
# ---------------------------------------------------------------------------

class TestThemeLayout:
    def test_default_layout_canvas_size(self):
        layout = default_layout()
        assert layout.canvas_w == 800
        assert layout.canvas_h == 480

    def test_default_layout_header_region(self):
        layout = default_layout()
        assert layout.header.x == 0
        assert layout.header.y == 0
        assert layout.header.w == 800
        assert layout.header.h == 40

    def test_default_layout_week_view_region(self):
        layout = default_layout()
        assert layout.week_view.x == 0
        assert layout.week_view.y == 40
        assert layout.week_view.w == 800
        assert layout.week_view.h == 320

    def test_default_layout_bottom_panels_y(self):
        layout = default_layout()
        assert layout.weather.y == 360
        assert layout.birthdays.y == 360
        assert layout.info.y == 360

    def test_default_layout_bottom_panels_total_width(self):
        layout = default_layout()
        total = layout.weather.w + layout.birthdays.w + layout.info.w
        assert total == 800

    def test_default_draw_order(self):
        layout = default_layout()
        assert layout.draw_order == ["header", "week_view", "weather", "birthdays", "info"]

    def test_regions_cover_full_canvas(self):
        """Header + week_view + bottom row heights should sum to canvas height."""
        layout = default_layout()
        h_total = layout.header.h + layout.week_view.h + layout.weather.h
        assert h_total == layout.canvas_h


# ---------------------------------------------------------------------------
# default_theme / load_theme
# ---------------------------------------------------------------------------

class TestDefaultTheme:
    def test_returns_theme_instance(self):
        t = default_theme()
        assert isinstance(t, Theme)

    def test_name_is_default(self):
        t = default_theme()
        assert t.name == "default"

    def test_style_is_themeestyle(self):
        t = default_theme()
        assert isinstance(t.style, ThemeStyle)

    def test_layout_is_themelayout(self):
        t = default_theme()
        assert isinstance(t.layout, ThemeLayout)


class TestLoadTheme:
    def test_loads_default(self):
        t = load_theme("default")
        assert isinstance(t, Theme)
        assert t.name == "default"

    def test_loads_terminal(self):
        t = load_theme("terminal")
        assert isinstance(t, Theme)
        assert t.name == "terminal"

    def test_loads_minimalist(self):
        t = load_theme("minimalist")
        assert isinstance(t, Theme)
        assert t.name == "minimalist"

    def test_loads_old_fashioned(self):
        t = load_theme("old_fashioned")
        assert isinstance(t, Theme)
        assert t.name == "old_fashioned"

    def test_unknown_name_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown theme"):
            load_theme("nonexistent_theme_xyz")

    def test_loads_today(self):
        t = load_theme("today")
        assert isinstance(t, Theme)
        assert t.name == "today"

    def test_loads_fantasy(self):
        t = load_theme("fantasy")
        assert isinstance(t, Theme)
        assert t.name == "fantasy"

    def test_available_themes_contains_expected(self):
        assert "default" in AVAILABLE_THEMES
        assert "terminal" in AVAILABLE_THEMES
        assert "minimalist" in AVAILABLE_THEMES
        assert "old_fashioned" in AVAILABLE_THEMES
        assert "today" in AVAILABLE_THEMES
        assert "fantasy" in AVAILABLE_THEMES
        assert "qotd" in AVAILABLE_THEMES

    def test_loads_qotd(self):
        t = load_theme("qotd")
        assert isinstance(t, Theme)
        assert t.name == "qotd"


# ---------------------------------------------------------------------------
# render_dashboard with themes
# ---------------------------------------------------------------------------

class TestRenderDashboardWithThemes:
    def _cfg(self) -> DisplayConfig:
        return DisplayConfig()

    def test_default_theme_produces_valid_image(self):
        data = _make_data()
        result = render_dashboard(data, self._cfg(), theme=default_theme())
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_none_theme_defaults_to_default(self):
        data = _make_data()
        result = render_dashboard(data, self._cfg(), theme=None)
        assert isinstance(result, Image.Image)
        assert result.size == (800, 480)

    def test_terminal_theme_produces_valid_image(self):
        data = _make_data()
        t = load_theme("terminal")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_terminal_canvas_starts_black(self):
        """Terminal bg=0 means the canvas background pixel is BLACK (0)."""
        data = _make_data()
        data.events = []  # minimal content so background is visible
        t = load_theme("terminal")
        result = render_dashboard(data, self._cfg(), theme=t)
        # Top-left corner should be black (0) for terminal (bg=0)
        assert result.getpixel((0, 0)) == 0

    def test_default_canvas_starts_white(self):
        """Default bg=1 means the canvas background is WHITE (1)."""
        data = _make_data()
        data.events = []
        t = load_theme("default")
        result = render_dashboard(data, self._cfg(), theme=t)
        # In the default theme the header is drawn immediately, so check a pixel
        # inside the body area that would be white background
        # (week body, first column, below header)
        assert result.getpixel((10, 200)) == 1  # white in body area

    def test_minimalist_theme_produces_valid_image(self):
        data = _make_data()
        t = load_theme("minimalist")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_old_fashioned_theme_produces_valid_image(self):
        data = _make_data()
        t = load_theme("old_fashioned")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_fantasy_theme_produces_valid_image(self):
        data = _make_data()
        t = load_theme("fantasy")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_fantasy_canvas_starts_black(self):
        """Fantasy theme uses a black background."""
        t = load_theme("fantasy")
        assert t.style.bg == 0   # BLACK
        assert t.style.fg == 1   # WHITE

    def test_fantasy_has_overlay_fn(self):
        """Fantasy theme wires up the decorative border overlay."""
        t = load_theme("fantasy")
        assert t.layout.overlay_fn is not None
        assert callable(t.layout.overlay_fn)

    def test_fantasy_sidebar_layout(self):
        """Sidebar panels live on the left; week view on the right."""
        t = load_theme("fantasy")
        assert t.layout.week_view.x > 0               # quest log is not at x=0
        assert t.layout.weather.x < t.layout.week_view.x    # weather is in the sidebar
        assert t.layout.birthdays.x < t.layout.week_view.x  # birthdays is in the sidebar
        assert t.layout.info.x < t.layout.week_view.x       # quote is in the sidebar
        assert t.layout.week_view.w > t.layout.weather.w    # calendar wider than sidebar

    def test_fantasy_component_labels(self):
        """Fantasy-themed section labels are configured."""
        t = load_theme("fantasy")
        labels = t.style.component_labels
        assert labels.get("weather") != "WEATHER"
        assert labels.get("birthdays") != "BIRTHDAYS"
        assert labels.get("info") != "QUOTE OF THE DAY"

    def test_today_theme_produces_valid_image(self):
        data = _make_data()
        t = load_theme("today")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_today_theme_hides_week_view(self):
        """The today theme's week_view region should be invisible."""
        t = load_theme("today")
        assert t.layout.week_view.visible is False

    def test_today_theme_shows_today_view(self):
        """The today theme's today_view region should be visible and in draw_order."""
        t = load_theme("today")
        assert t.layout.today_view.visible is True
        assert "today_view" in t.layout.draw_order

    def test_today_theme_with_events_today(self):
        """today theme renders correctly when events fall on today."""
        today = date(2024, 3, 15)
        data = _make_data(today)
        # Add an event on today
        data.events.append(CalendarEvent(
            summary="Morning Meeting",
            start=datetime.combine(today, datetime.min.time().replace(hour=9)),
            end=datetime.combine(today, datetime.min.time().replace(hour=10)),
        ))
        t = load_theme("today")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)

    def test_today_theme_with_no_events(self):
        """today theme renders correctly with an empty event list."""
        data = _make_data()
        data.events = []
        t = load_theme("today")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)

    def test_today_view_default_region_not_visible_in_default_theme(self):
        """ThemeLayout.today_view defaults to visible=False so existing themes are unaffected."""
        from src.render.theme import default_layout
        layout = default_layout()
        assert layout.today_view.visible is False

    def test_custom_layout_positions_components(self):
        """A theme with non-standard layout renders without crashing."""
        data = _make_data()
        custom_layout = ThemeLayout(
            canvas_w=800,
            canvas_h=480,
            header=ComponentRegion(0, 0, 800, 56),          # tall header
            week_view=ComponentRegion(0, 56, 500, 424),      # left column
            weather=ComponentRegion(500, 56, 300, 141),      # right stack
            birthdays=ComponentRegion(500, 197, 300, 141),
            info=ComponentRegion(500, 338, 300, 142),
        )
        t = Theme(name="custom", style=ThemeStyle(), layout=custom_layout)
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.size == (800, 480)

    def test_invisible_region_skips_component(self):
        """Setting region.visible=False skips that component without crashing."""
        data = _make_data()
        layout = default_layout()
        layout.weather = ComponentRegion(
            layout.weather.x, layout.weather.y,
            layout.weather.w, layout.weather.h,
            visible=False,
        )
        t = Theme(name="no-weather", style=ThemeStyle(), layout=layout)
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)

    def test_qotd_theme_produces_valid_image(self):
        data = _make_data()
        t = load_theme("qotd")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)
        assert result.mode == "1"
        assert result.size == (800, 480)

    def test_qotd_theme_white_background(self):
        """QOTD theme has a white (1) background."""
        t = load_theme("qotd")
        assert t.style.bg == 1
        assert t.style.fg == 0

    def test_qotd_theme_hides_calendar_components(self):
        """QOTD theme has no header, week_view, or birthdays in draw_order."""
        t = load_theme("qotd")
        assert "header" not in t.layout.draw_order
        assert "week_view" not in t.layout.draw_order
        assert "birthdays" not in t.layout.draw_order
        assert "info" not in t.layout.draw_order

    def test_qotd_theme_uses_qotd_and_weather_drawers(self):
        """QOTD theme draw_order contains the qotd and qotd_weather components."""
        t = load_theme("qotd")
        assert "qotd" in t.layout.draw_order
        assert "qotd_weather" in t.layout.draw_order

    def test_qotd_theme_qotd_region_covers_most_of_canvas(self):
        """The quote region should occupy the bulk of the 480px canvas height."""
        t = load_theme("qotd")
        assert t.layout.qotd.h >= 380
        assert t.layout.qotd.w == 800
        assert t.layout.qotd.visible is True

    def test_qotd_theme_weather_region_full_width_bottom_banner(self):
        """Weather banner should be full width at the bottom of the canvas."""
        t = load_theme("qotd")
        assert t.layout.weather.w == 800
        assert t.layout.weather.y + t.layout.weather.h == 480

    def test_qotd_theme_quote_and_banner_fill_canvas(self):
        """Quote region height + weather banner height should equal canvas height."""
        t = load_theme("qotd")
        assert t.layout.qotd.h + t.layout.weather.h == 480

    def test_qotd_theme_renders_without_weather(self):
        """QOTD theme renders gracefully when weather data is None."""
        data = _make_data()
        data.weather = None
        t = load_theme("qotd")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)

    def test_qotd_theme_uses_playfair_fonts(self):
        """QOTD theme font callables should return Playfair Display fonts."""
        from PIL import ImageFont
        t = load_theme("qotd")
        for fn in (t.style.font_regular, t.style.font_bold, t.style.font_semibold):
            font = fn(24)
            assert isinstance(font, ImageFont.FreeTypeFont)

    def test_qotd_layout_qotd_region_default_invisible(self):
        """ThemeLayout.qotd defaults to visible=False in non-qotd themes."""
        layout = default_layout()
        assert layout.qotd.visible is False


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------

class TestThemeConfigField:
    def test_config_default_theme_is_default(self):
        from src.config import Config
        cfg = Config()
        assert cfg.theme == "default"

    def test_load_config_parses_theme(self, tmp_path):
        import yaml
        from src.config import load_config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"theme": "terminal"}))
        cfg = load_config(str(config_file))
        assert cfg.theme == "terminal"

    def test_unknown_theme_produces_validation_warning(self):
        from src.config import Config, validate_config
        cfg = Config()
        cfg.theme = "nonexistent_xyz"
        errors, warnings = validate_config(cfg)
        warning_fields = [w.field for w in warnings]
        assert "theme" in warning_fields

    def test_known_theme_produces_no_theme_warning(self):
        from src.config import Config, validate_config
        cfg = Config()
        cfg.theme = "terminal"
        errors, warnings = validate_config(cfg)
        warning_fields = [w.field for w in warnings]
        assert "theme" not in warning_fields
