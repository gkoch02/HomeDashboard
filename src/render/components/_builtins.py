"""Built-in component adapter registrations.

Each adapter is a thin wrapper that pulls the right arguments out of a
:class:`RenderContext` and delegates to the existing ``draw_*`` function
in its component module. Registering them here keeps the per-component
modules unchanged; future components can register themselves directly
via the ``@register_component`` decorator inside their own module.
"""

from __future__ import annotations

from src.render.components import (
    air_quality_panel,
    astronomy_panel,
    birthday_bar,
    countdown_panel,
    diags_panel,
    fuzzyclock_panel,
    header,
    info_panel,
    message_panel,
    monthly_panel,
    moonphase_panel,
    qotd_panel,
    scorecard_panel,
    sunrise_panel,
    tides_panel,
    timeline_panel,
    today_view,
    weather_full,
    weather_panel,
    week_view,
    year_pulse_panel,
)
from src.render.components.registry import RenderContext, register_component


@register_component("header")
def _header(ctx: RenderContext) -> None:
    header.draw_header(
        ctx.draw,
        ctx.now,
        is_stale=ctx.data.is_stale,
        title=ctx.title,
        source_staleness=ctx.data.source_staleness,
        region=ctx.layout.header,
        style=ctx.style,
    )


@register_component("week_view")
def _week_view(ctx: RenderContext) -> None:
    week_view.draw_week(
        ctx.draw,
        ctx.data.events,
        ctx.today,
        forecast=ctx.data.weather.forecast if ctx.data.weather else None,
        region=ctx.layout.week_view,
        style=ctx.style,
    )


@register_component("weather")
def _weather(ctx: RenderContext) -> None:
    weather_panel.draw_weather(
        ctx.draw,
        ctx.data.weather,
        today=ctx.today,
        air_quality=ctx.data.air_quality,
        region=ctx.layout.weather,
        style=ctx.style,
        staleness=ctx.data.source_staleness.get("weather"),
    )


@register_component("birthdays")
def _birthdays(ctx: RenderContext) -> None:
    birthday_bar.draw_birthdays(
        ctx.draw,
        ctx.data.birthdays,
        ctx.today,
        region=ctx.layout.birthdays,
        style=ctx.style,
        staleness=ctx.data.source_staleness.get("birthdays"),
    )


@register_component("info")
def _info(ctx: RenderContext) -> None:
    info_panel.draw_info(
        ctx.draw,
        ctx.today,
        region=ctx.layout.info,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
    )


@register_component("today_view")
def _today_view(ctx: RenderContext) -> None:
    today_view.draw_today(
        ctx.draw,
        ctx.data.events,
        ctx.today,
        forecast=ctx.data.weather.forecast if ctx.data.weather else None,
        region=ctx.layout.today_view,
        style=ctx.style,
    )


@register_component("qotd")
def _qotd(ctx: RenderContext) -> None:
    qotd_panel.draw_qotd(
        ctx.draw,
        ctx.today,
        region=ctx.layout.qotd,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
    )


@register_component("qotd_weather")
def _qotd_weather(ctx: RenderContext) -> None:
    qotd_panel.draw_qotd_weather(
        ctx.draw,
        ctx.data.weather,
        ctx.today,
        region=ctx.layout.weather,
        style=ctx.style,
    )


@register_component("weather_full")
def _weather_full(ctx: RenderContext) -> None:
    weather_full.draw_weather_full(
        ctx.draw,
        ctx.data.weather,
        ctx.today,
        air_quality=ctx.data.air_quality,
        region=ctx.layout.weather_full,
        style=ctx.style,
    )


@register_component("fuzzyclock")
def _fuzzyclock(ctx: RenderContext) -> None:
    fuzzyclock_panel.draw_fuzzyclock(
        ctx.draw,
        ctx.now,
        region=ctx.layout.fuzzyclock,
        style=ctx.style,
    )


@register_component("fuzzyclock_weather")
def _fuzzyclock_weather(ctx: RenderContext) -> None:
    qotd_panel.draw_qotd_weather(
        ctx.draw,
        ctx.data.weather,
        ctx.today,
        region=ctx.layout.weather,
        style=ctx.style,
    )


@register_component("diags")
def _diags(ctx: RenderContext) -> None:
    diags_panel.draw_diags(
        ctx.draw,
        ctx.data,
        ctx.today,
        region=ctx.layout.diags,
        style=ctx.style,
    )


@register_component("air_quality_full")
def _air_quality_full(ctx: RenderContext) -> None:
    air_quality_panel.draw_air_quality_full(
        ctx.draw,
        ctx.data,
        ctx.today,
        region=ctx.layout.air_quality_full,
        style=ctx.style,
    )


@register_component("moonphase_full")
def _moonphase_full(ctx: RenderContext) -> None:
    moonphase_panel.draw_moonphase(
        ctx.draw,
        ctx.data,
        ctx.today,
        region=ctx.layout.moonphase_full,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
    )


@register_component("message")
def _message(ctx: RenderContext) -> None:
    message_panel.draw_message(
        ctx.draw,
        ctx.message_text or "",
        region=ctx.layout.message,
        style=ctx.style,
    )


@register_component("message_weather")
def _message_weather(ctx: RenderContext) -> None:
    qotd_panel.draw_qotd_weather(
        ctx.draw,
        ctx.data.weather,
        ctx.today,
        region=ctx.layout.weather,
        style=ctx.style,
    )


@register_component("timeline")
def _timeline(ctx: RenderContext) -> None:
    timeline_panel.draw_timeline(
        ctx.draw,
        ctx.data.events,
        ctx.today,
        ctx.now,
        region=ctx.layout.timeline,
        style=ctx.style,
    )


@register_component("year_pulse")
def _year_pulse(ctx: RenderContext) -> None:
    year_pulse_panel.draw_year_pulse(
        ctx.draw,
        ctx.data,
        ctx.today,
        region=ctx.layout.year_pulse,
        style=ctx.style,
    )


@register_component("monthly")
def _monthly(ctx: RenderContext) -> None:
    monthly_panel.draw_monthly(
        ctx.draw,
        ctx.data,
        ctx.today,
        region=ctx.layout.monthly,
        style=ctx.style,
    )


@register_component("sunrise")
def _sunrise(ctx: RenderContext) -> None:
    sunrise_panel.draw_sunrise(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.sunrise,
        style=ctx.style,
    )


@register_component("scorecard")
def _scorecard(ctx: RenderContext) -> None:
    scorecard_panel.draw_scorecard(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.scorecard,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
    )


@register_component("tides")
def _tides(ctx: RenderContext) -> None:
    tides_panel.draw_tides(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.tides,
        style=ctx.style,
        quote_refresh=ctx.quote_refresh,
    )


@register_component("countdown")
def _countdown(ctx: RenderContext) -> None:
    countdown_panel.draw_countdown(
        ctx.draw,
        ctx.countdown_events or [],
        ctx.today,
        region=ctx.layout.countdown,
        style=ctx.style,
    )


@register_component("astronomy")
def _astronomy(ctx: RenderContext) -> None:
    astronomy_panel.draw_astronomy(
        ctx.draw,
        ctx.data,
        ctx.today,
        ctx.now,
        region=ctx.layout.astronomy,
        style=ctx.style,
        latitude=ctx.latitude,
        longitude=ctx.longitude,
    )
