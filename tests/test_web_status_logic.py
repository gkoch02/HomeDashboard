"""Unit tests for the status-route decision table.

Exercises the pure helpers in ``src.web.routes.status`` directly so we can cover
every branch of the severity / title matrix without standing up a full app.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.config import ThemeScheduleConfig, ThemeScheduleEntry
from src.web.routes.status import (
    _describe_theme_mode,
    _overall_health,
    _source_summary,
)

# ---------------------------------------------------------------------------
# _source_summary — each staleness / breaker combination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_state, expected_severity, expected_status",
    [
        ({"breaker_state": "open", "staleness": "fresh"}, "bad", "needs_attention"),
        ({"breaker_state": "closed", "staleness": "expired"}, "bad", "degraded"),
        (
            {"breaker_state": "closed", "staleness": "stale", "cache_age_minutes": 90.0},
            "warn",
            "degraded",
        ),
        (
            {"breaker_state": "closed", "staleness": "stale"},
            "warn",
            "degraded",
        ),  # no age → fallback
        (
            {"breaker_state": "closed", "staleness": "aging", "cache_age_minutes": 30.0},
            "warn",
            "ok",
        ),
        ({"breaker_state": "closed", "staleness": "aging"}, "warn", "ok"),
        ({"breaker_state": "closed", "staleness": "unknown"}, "warn", "unknown"),
        ({"breaker_state": "closed", "staleness": "fresh", "cache_age_minutes": 5.0}, "ok", "ok"),
        ({"breaker_state": "closed", "staleness": "fresh"}, "ok", "ok"),
    ],
)
def test_source_summary_matrix(source_state, expected_severity, expected_status):
    result = _source_summary("weather", source_state)
    assert result["severity"] == expected_severity
    assert result["status"] == expected_status


def test_source_summary_stale_uses_age_in_detail():
    s = _source_summary(
        "events", {"breaker_state": "closed", "staleness": "stale", "cache_age_minutes": 90.0}
    )
    assert "90" in s["detail"]


def test_source_summary_stale_without_age_has_unavailable_detail():
    s = _source_summary("events", {"breaker_state": "closed", "staleness": "stale"})
    assert "unavailable" in s["detail"]


# ---------------------------------------------------------------------------
# _overall_health — each branch of the status transitions
# ---------------------------------------------------------------------------


def _healthy_source():
    return {"breaker_state": "closed", "staleness": "fresh", "cache_age_minutes": 5}


def _bad_source():
    return {"breaker_state": "open", "staleness": "fresh"}


def _warn_source():
    return {"breaker_state": "closed", "staleness": "aging", "cache_age_minutes": 30}


def test_overall_health_all_healthy():
    sources = {"weather": _healthy_source(), "events": _healthy_source()}
    result = _overall_health(30, False, sources)
    assert result["status"] == "healthy"
    assert result["severity"] == "ok"
    assert result["issues"] == []


def test_overall_health_quiet_hours_flags_paused():
    sources = {"weather": _healthy_source()}
    result = _overall_health(30, True, sources)
    assert result["status"] == "paused"
    assert result["severity"] == "warn"
    assert "Quiet hours" in result["title"]


def test_overall_health_no_last_run_seconds_is_degraded():
    sources = {"weather": _healthy_source()}
    result = _overall_health(None, False, sources)
    assert result["status"] == "degraded"
    assert any(iss["kind"] == "last_run" for iss in result["issues"])


def test_overall_health_stale_last_run_not_during_quiet_hours():
    sources = {"weather": _healthy_source()}
    result = _overall_health(10_000, False, sources)
    assert result["status"] == "degraded"
    assert any("2 hours" in iss["message"] for iss in result["issues"])


def test_overall_health_stale_last_run_suppressed_during_quiet_hours():
    """When quiet hours are active, a stale last-run should NOT trigger a degraded
    status (the paused status persists instead)."""
    sources = {"weather": _healthy_source()}
    result = _overall_health(10_000, True, sources)
    assert result["status"] == "paused"
    assert result["severity"] == "warn"


def test_overall_health_bad_source_escalates_to_needs_attention():
    sources = {"weather": _bad_source(), "events": _healthy_source()}
    result = _overall_health(30, False, sources)
    assert result["status"] == "needs_attention"
    assert result["severity"] == "bad"
    assert any(iss["kind"] == "weather" and iss["severity"] == "bad" for iss in result["issues"])


def test_overall_health_bad_source_does_not_override_paused():
    sources = {"weather": _bad_source()}
    result = _overall_health(30, True, sources)
    assert result["status"] == "paused"  # paused wins over needs_attention
    # But the issue still gets appended.
    assert any(iss["severity"] == "bad" for iss in result["issues"])


def test_overall_health_warn_source_downgrades_healthy_to_degraded():
    sources = {"weather": _warn_source()}
    result = _overall_health(30, False, sources)
    assert result["status"] == "degraded"
    assert result["severity"] == "warn"


def test_overall_health_warn_source_does_not_replace_bad_status():
    sources = {"weather": _bad_source(), "events": _warn_source()}
    result = _overall_health(30, False, sources)
    assert result["status"] == "needs_attention"
    # Both issues are surfaced.
    kinds = {iss["kind"] for iss in result["issues"]}
    assert "weather" in kinds
    assert "events" in kinds


def test_overall_health_caps_issues_at_four():
    # Matches the issues[:4] slice in src/web/routes/status.py — update both together.
    sources = {f"src_{i}": _bad_source() for i in range(6)}
    result = _overall_health(30, False, sources)
    assert len(result["issues"]) == 4


# ---------------------------------------------------------------------------
# _describe_theme_mode — next-entry wraparound and mode classification
# ---------------------------------------------------------------------------


def _cfg(theme="default", entries=()):
    schedule = ThemeScheduleConfig(
        entries=[ThemeScheduleEntry(time=t, theme=th) for t, th in entries]
    )
    return SimpleNamespace(theme=theme, theme_schedule=schedule)


def test_describe_theme_mode_fixed():
    cfg = _cfg(theme="terminal")
    info = _describe_theme_mode(cfg, "terminal", datetime(2026, 4, 20, 12, 0))
    assert info["mode"] == "fixed"
    assert info["next_scheduled_change"] is None
    assert info["schedule_count"] == 0


@pytest.mark.parametrize("theme_name", ["random", "random_daily", "random_hourly"])
def test_describe_theme_mode_randomized(theme_name):
    cfg = _cfg(theme=theme_name)
    info = _describe_theme_mode(cfg, "terminal", datetime(2026, 4, 20, 12, 0))
    assert info["mode"] == "randomized"


def test_describe_theme_mode_scheduled_picks_next_entry_later_today():
    cfg = _cfg(theme="default", entries=[("08:00", "terminal"), ("18:00", "fantasy")])
    info = _describe_theme_mode(cfg, "terminal", datetime(2026, 4, 20, 12, 0))
    assert info["mode"] == "scheduled"
    assert info["next_scheduled_change"] == {"time": "18:00", "theme": "fantasy"}


def test_describe_theme_mode_scheduled_wraps_to_first_entry():
    """After the last scheduled entry for the day, next should wrap to the earliest."""
    cfg = _cfg(theme="default", entries=[("08:00", "terminal"), ("18:00", "fantasy")])
    info = _describe_theme_mode(cfg, "fantasy", datetime(2026, 4, 20, 23, 30))
    assert info["mode"] == "scheduled"
    assert info["next_scheduled_change"] == {"time": "08:00", "theme": "terminal"}


def test_describe_theme_mode_scheduled_before_first_entry_uses_first_entry():
    """If all entries are in the future, next should be the earliest."""
    cfg = _cfg(theme="default", entries=[("08:00", "terminal"), ("18:00", "fantasy")])
    info = _describe_theme_mode(cfg, "default", datetime(2026, 4, 20, 3, 0))
    assert info["mode"] == "scheduled"
    assert info["next_scheduled_change"] == {"time": "08:00", "theme": "terminal"}
    assert info["schedule_count"] == 2
