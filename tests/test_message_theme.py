"""Tests for src/render/themes/message.py — the message theme factory."""

from __future__ import annotations

from src.render.theme import Theme, load_theme
from src.render.themes.message import BANNER_H, message_theme


def test_message_theme_factory_returns_theme():
    theme = message_theme()
    assert isinstance(theme, Theme)
    assert theme.name == "message"


def test_message_theme_canvas_dimensions():
    theme = message_theme()
    assert theme.layout.canvas_w == 800
    assert theme.layout.canvas_h == 480


def test_message_theme_hides_default_components():
    """Calendar/birthdays/info are hidden so the message dominates the canvas."""
    layout = message_theme().layout
    assert layout.header.visible is False
    assert layout.week_view.visible is False
    assert layout.birthdays.visible is False
    assert layout.info.visible is False
    assert layout.today_view.visible is False


def test_message_theme_message_region_fills_above_banner():
    layout = message_theme().layout
    msg_h = 480 - BANNER_H
    assert layout.message.x == 0
    assert layout.message.y == 0
    assert layout.message.w == 800
    assert layout.message.h == msg_h


def test_message_theme_weather_banner_at_bottom():
    layout = message_theme().layout
    msg_h = 480 - BANNER_H
    assert layout.weather.x == 0
    assert layout.weather.y == msg_h
    assert layout.weather.w == 800
    assert layout.weather.h == BANNER_H


def test_message_theme_draw_order():
    layout = message_theme().layout
    assert layout.draw_order == ["message", "message_weather"]


def test_message_theme_uses_white_background_with_black_ink():
    style = message_theme().style
    assert style.fg == 0
    assert style.bg == 1
    assert style.invert_header is False
    assert style.invert_today_col is False
    assert style.invert_allday_bars is False


def test_load_theme_returns_message_theme_via_registry():
    theme = load_theme("message")
    assert theme.name == "message"
