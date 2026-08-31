"""The one place that turns a ``Config`` into ``render_dashboard()`` arguments.

Two callers render the dashboard: ``DashboardApp._run()`` and the web UI's
``POST /api/preview``. The preview passed a *subset* of the renderer's
arguments, so several themes previewed as something the real render would never
produce — ``photo`` with no photo (the one theme whose entire content is the
config value being previewed), ``countdown`` with no events, a custom
``quotes.path`` store ignored, and the documented ``(0.0, 0.0)`` "unset"
coordinate sentinel passed through raw, so ``astronomy`` / ``light_cycle`` /
``moonphase`` / ``day_arc`` / ``constellation_map`` computed sun and moon
geometry for the Gulf of Guinea instead of showing their unset-coordinates
fallback. That is exactly the surface the preview exists to de-risk, so the
assembly lives here and both callers go through it (#240).
"""

from __future__ import annotations

from typing import Any


def coords_or_none(latitude: float, longitude: float) -> tuple[float | None, float | None]:
    """Return the pair, or ``(None, None)`` for the "unset" sentinel.

    Exactly ``(0.0, 0.0)`` means "not configured" — the same convention
    ``validate_config()`` warns about. Any other coordinate (the equator or the
    prime meridian alone included) is passed through so twilight math can run.
    """
    if latitude == 0.0 and longitude == 0.0:
        return None, None
    return latitude, longitude


def build_render_kwargs(
    cfg,
    theme,
    theme_name: str,
    *,
    message: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Assemble the keyword arguments for ``render_dashboard()``.

    Also applies the one piece of config that reaches the renderer through the
    theme rather than a kwarg: the ``photo`` theme's image path.

    ``state_dir`` is passed explicitly rather than read from *cfg* because it
    is the caller's decision, not the config's — previews and ``--dry-run`` /
    ``--dummy`` runs pass ``None`` so dummy pressure readings never corrupt the
    weatherglass barometer trend of the next real run.
    """
    if theme_name == "photo":
        theme.style.photo_path = cfg.photo.path

    lat, lon = coords_or_none(cfg.weather.latitude, cfg.weather.longitude)
    return {
        "title": cfg.title,
        "theme": theme,
        "quote_refresh": cfg.cache.quote_refresh,
        "quotes_path": cfg.quotes.path or None,
        "message_text": message,
        "countdown_events": list(cfg.countdown.events),
        "latitude": lat,
        "longitude": lon,
        "state_dir": state_dir,
    }
