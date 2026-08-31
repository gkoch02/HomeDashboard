"""Status blueprint — the main P1 read-only health page.

Routes:
    GET /              HTML status page
    GET /api/status    JSON health snapshot
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from src._time import now_local
from src.fetchers import one_call_health
from src.services.theme import resolve_theme_name
from src.web.event_store import read_recent_events
from src.web.sources import source_names
from src.web.state_reader import (
    config_tz,
    is_quiet_hours_now,
    read_breakers,
    read_cache_ages,
    read_host_metrics,
    read_last_error,
    read_last_success,
    read_quota,
)

status_bp = Blueprint("status", __name__)


def _source_summary(source: str, source_state: dict) -> dict:
    breaker = source_state.get("breaker_state", "closed")
    staleness = source_state.get("staleness", "unknown")
    age = source_state.get("cache_age_minutes")

    if breaker == "open":
        return {
            "severity": "bad",
            "status": "needs_attention",
            "message": "Fetching paused after repeated failures.",
            "detail": "Reset the breaker after checking credentials, network, or the upstream service.",
        }
    if staleness == "expired":
        return {
            "severity": "bad",
            "status": "degraded",
            "message": "Cached data is expired.",
            "detail": "Run a refresh now to fetch fresh data.",
        }
    if staleness == "stale":
        return {
            "severity": "warn",
            "status": "degraded",
            "message": "Using stale cached data.",
            "detail": f"Last successful fetch was about {age:.0f} minutes ago."
            if age
            else "Last successful fetch time is unavailable.",
        }
    if staleness == "aging":
        return {
            "severity": "warn",
            "status": "ok",
            "message": "Cache is getting old but still usable.",
            "detail": f"Last successful fetch was about {age:.0f} minutes ago."
            if age
            else "Last successful fetch time is unavailable.",
        }
    if staleness == "unknown":
        return {
            "severity": "warn",
            "status": "unknown",
            "message": "No cached data yet.",
            "detail": "This source may not have fetched successfully yet.",
        }
    return {
        "severity": "ok",
        "status": "ok",
        "message": "Healthy.",
        "detail": f"Last successful fetch was about {age:.0f} minutes ago."
        if age
        else "Cache is present and current.",
    }


def _one_call_summary(health: dict, configured_version: str) -> dict | None:
    """Summarise One Call health, or ``None`` when there is nothing to report.

    Only a recorded authentication failure is worth surfacing: it is permanent
    and actionable, and it silently removes weather alerts and the UV index
    from every render until someone fixes the subscription. A transient failure
    and an empty record are both normal.

    The record is also checked against the config currently in force, because
    it only refreshes on the next weather fetch — up to a
    ``cache.weather_fetch_interval`` away, and never at all once One Call is
    switched off (the disabled path deliberately records nothing). Without this
    the two documented remedies both leave the banner up: turning One Call off
    keeps a permanent "check one_call_version" warning against a config that no
    longer calls it, and switching 3.0 → 4.0 keeps naming the old version.
    """
    if configured_version == "off":
        return None
    if health.get("outcome") != one_call_health.AUTH_FAILED:
        return None
    if health.get("version") != configured_version:
        return None
    return {
        "severity": "warn",
        "status": "degraded",
        "message": health.get("message") or "One Call requests are being rejected.",
        "detail": (
            "Weather alerts and the UV index are unavailable until this is resolved. "
            "The rest of the weather data is unaffected."
        ),
        "version": health.get("version"),
        "http_status": health.get("http_status"),
        "checked_at": health.get("checked_at"),
    }


def _overall_health(
    last_run_seconds: int | None,
    quiet_hours_active: bool,
    sources: dict[str, dict],
    one_call: dict | None = None,
) -> dict:
    issues: list[dict] = []
    status = "healthy"
    severity = "ok"
    title = "Dashboard healthy"
    detail = "Everything looks normal."

    if quiet_hours_active:
        status = "paused"
        severity = "warn"
        title = "Quiet hours active"
        detail = "Display refresh is paused by schedule."

    if last_run_seconds is None:
        status = "degraded"
        severity = "warn"
        title = "No successful run recorded yet"
        detail = "The dashboard has not written a successful run timestamp."
        issues.append({"kind": "last_run", "severity": "warn", "message": detail})
    elif last_run_seconds > 7200 and not quiet_hours_active:
        status = "degraded"
        severity = "warn"
        title = "Dashboard may be behind"
        detail = "Last successful run was over 2 hours ago."
        issues.append({"kind": "last_run", "severity": "warn", "message": detail})

    # Ahead of the per-source loop deliberately: `issues` is truncated below,
    # and a permanent, actionable misconfiguration should not be crowded out by
    # routine per-source notices.
    if one_call is not None:
        if status == "healthy":
            status = "degraded"
            severity = "warn"
            title = "Dashboard degraded"
            detail = "One or more data sources need a look."
        issues.append({"kind": "one_call", "severity": "warn", "message": one_call["message"]})

    for name, source in sources.items():
        summary = _source_summary(name, source)
        source["summary"] = summary
        if summary["severity"] == "bad":
            if status != "paused":
                status = "needs_attention"
                severity = "bad"
                title = "Dashboard needs attention"
                detail = "One or more data sources are unhealthy."
            issues.append({"kind": name, "severity": "bad", "message": summary["message"]})
        elif summary["severity"] == "warn":
            if status == "healthy":
                status = "degraded"
                severity = "warn"
                title = "Dashboard degraded"
                detail = "One or more data sources need a look."
            issues.append({"kind": name, "severity": "warn", "message": summary["message"]})

    return {
        "status": status,
        "severity": severity,
        "title": title,
        "detail": detail,
        "issues": issues[:4],
    }


def _describe_theme_mode(cfg, effective_theme: str, now: datetime) -> dict:
    schedule_entries = sorted(cfg.theme_schedule.entries, key=lambda e: e.time)
    next_entry = None
    current_hm = now.strftime("%H:%M")
    for entry in schedule_entries:
        if entry.time > current_hm:
            next_entry = entry
            break
    if next_entry is None and schedule_entries:
        next_entry = schedule_entries[0]

    if schedule_entries:
        mode = "scheduled"
        detail = (
            "Theme schedule is active and overrides the base theme once its time window begins."
        )
    elif cfg.theme in ("random", "random_daily", "random_hourly"):
        mode = "randomized"
        detail = "The dashboard is rotating through a pool of themes automatically."
    else:
        mode = "fixed"
        detail = "A single fixed theme is selected."

    return {
        "mode": mode,
        "configured_theme": cfg.theme,
        "effective_theme": effective_theme,
        "detail": detail,
        "next_scheduled_change": (
            {"time": next_entry.time, "theme": next_entry.theme} if next_entry is not None else None
        ),
        "schedule_count": len(schedule_entries),
    }


def _calendar_backend(cfg) -> str:
    """Name the calendar backend that will actually be used.

    Mirrors the dispatch precedence in ``src.fetchers.calendar.fetch_events``:
    CalDAV wins over ICS, which wins over the Google Calendar API. Keeping the
    two in step is what stops the panel from reporting a Google problem to an
    install that never calls Google.
    """
    if cfg.google.caldav_url:
        return "caldav"
    if cfg.google.ical_url:
        return "ics"
    return "google"


def _calendar_integration(cfg, backend: str) -> dict:
    """One row describing the active calendar source."""
    if backend == "caldav":
        target = cfg.google.caldav_calendar_url or cfg.google.caldav_url
        detail = f"Using CalDAV: {target}"
        if cfg.google.caldav_username:
            detail += f" (as {cfg.google.caldav_username})"
        return {"name": "Calendar (CalDAV)", "status": "ok", "detail": detail}

    if backend == "ics":
        extra = len(cfg.google.additional_ical_urls)
        detail = f"Using ICS feed: {cfg.google.ical_url}"
        if extra:
            detail += f" (+{extra} additional feed{'s' if extra != 1 else ''})"
        return {"name": "Calendar (ICS)", "status": "ok", "detail": detail}

    named = bool(cfg.google.calendar_id) and cfg.google.calendar_id != "primary"
    return {
        "name": "Calendar (Google API)",
        "status": "ok" if named else "warn",
        "detail": f"Calendar id: {cfg.google.calendar_id}",
    }


def _build_integrations(cfg, one_call: dict | None = None) -> list[dict]:
    backend = _calendar_backend(cfg)
    birthdays_path = Path(cfg.birthdays.file_path)
    # The service account is only reached on the Google API path — or by the
    # People API when birthdays come from contacts, whatever the calendar
    # backend. Reporting it as missing otherwise is the bug in #214.
    needs_service_account = backend == "google" or cfg.birthdays.source == "contacts"

    items = [
        {
            "name": "OpenWeather",
            "status": "ok" if bool(cfg.weather.api_key) else "missing",
            "detail": "API key configured"
            if cfg.weather.api_key
            else "Weather API key is missing.",
        },
    ]

    # One Call is the only paid part of the weather fetch and the only one that
    # can fail without breaking anything visible, so it gets its own row.
    version = cfg.weather.one_call_version
    if version != "off":
        items.append(
            {
                "name": f"OpenWeather One Call {version}",
                "status": "warn" if one_call is not None else "ok",
                "detail": one_call["message"]
                if one_call is not None
                else "Supplies weather alerts and the UV index.",
            }
        )

    if needs_service_account:
        google_path = Path(cfg.google.service_account_path)
        items.append(
            {
                "name": "Google service account",
                "status": "ok" if google_path.exists() else "missing",
                "detail": f"Found at {google_path}"
                if google_path.exists()
                else f"Expected at {google_path}",
            }
        )

    items.append(_calendar_integration(cfg, backend))
    items.extend(
        [
            {
                "name": "Birthdays source",
                "status": "ok"
                if (cfg.birthdays.source != "file" or birthdays_path.exists())
                else "missing",
                "detail": (
                    f"Source: {cfg.birthdays.source}"
                    if cfg.birthdays.source != "file"
                    else f"File expected at {birthdays_path}"
                ),
            },
            {
                "name": "PurpleAir",
                "status": "ok"
                if (bool(cfg.purpleair.api_key) and bool(cfg.purpleair.sensor_id))
                else "warn",
                "detail": (
                    f"Sensor {cfg.purpleair.sensor_id} configured"
                    if (cfg.purpleair.api_key and cfg.purpleair.sensor_id)
                    else "API key or sensor id missing."
                ),
            },
        ]
    )
    return items


def _build_status() -> dict:
    """Assemble the full status payload from all state sources."""
    cfg = current_app.config["DASH_CFG"]
    state_dir = current_app.config["STATE_DIR"]
    output_dir = current_app.config["OUTPUT_DIR"]
    ttls = current_app.config["SOURCE_TTLS"]

    last_run = read_last_success(output_dir)
    breakers = read_breakers(state_dir)
    cache_ages = read_cache_ages(state_dir, ttls)
    quota = read_quota(state_dir)
    # Everything below is resolved against the *configured* timezone, the same
    # clock the renderer uses. Reading the host clock here put quiet hours,
    # theme_schedule and the daypart/weekday theme_rules on a different wall
    # clock — and near local midnight on a different day (#239).
    now = now_local(config_tz(cfg))
    quiet_hours_active = is_quiet_hours_now(
        cfg.schedule.quiet_hours_start, cfg.schedule.quiet_hours_end, now
    )

    sources: dict = {}
    for source in source_names():
        b = breakers.get(source, {})
        c = cache_ages.get(source, {})
        sources[source] = {
            "breaker_state": b.get("state", "closed"),
            "consecutive_failures": b.get("consecutive_failures", 0),
            "last_failure_at": b.get("last_failure_at"),
            "cache_age_minutes": c.get("cache_age_minutes"),
            "staleness": c.get("staleness", "unknown"),
            "fetched_at": c.get("fetched_at"),
            "quota_today": quota.get(source, quota.get(_quota_key(source), 0)),
        }

    one_call = _one_call_summary(
        one_call_health.read_health(state_dir), cfg.weather.one_call_version
    )
    overall = _overall_health(last_run["seconds_since"], quiet_hours_active, sources, one_call)
    effective_theme = resolve_theme_name(cfg, override_theme=None, now=now)
    theme_info = _describe_theme_mode(cfg, effective_theme, now)

    return {
        "last_run": last_run["timestamp"],
        "seconds_since_run": last_run["seconds_since"],
        "current_theme": effective_theme,
        "quiet_hours_active": quiet_hours_active,
        "quiet_hours_start": cfg.schedule.quiet_hours_start,
        "quiet_hours_end": cfg.schedule.quiet_hours_end,
        "web_auth_enabled": bool(current_app.config.get("WEB_AUTH_ENABLED")),
        "overall": overall,
        "theme_info": theme_info,
        "integrations": _build_integrations(cfg, one_call=one_call),
        "one_call": one_call,
        "recent_events": read_recent_events(state_dir, limit=10),
        "host": read_host_metrics(),
        "sources": sources,
    }


def _quota_key(source: str) -> str:
    """Map source names to quota tracker keys (Google Calendar uses 'google')."""
    return "google" if source == "events" else source


@status_bp.route("/")
def index():
    return render_template("status.html")


@status_bp.route("/api/status")
def api_status():
    return jsonify(_build_status())


@status_bp.route("/api/health")
def api_health():
    """Minimal uptime-monitor probe: HTTP 200 when the last run succeeded, 503 otherwise.

    Healthy means a success marker exists and no error is newer than it.
    An optional ``?max_age=<seconds>`` query parameter additionally requires
    the last success to be at most that old (quiet hours are exempt — the
    renderer intentionally does not run then).
    """
    output_dir = current_app.config["OUTPUT_DIR"]
    cfg = current_app.config["DASH_CFG"]
    success = read_last_success(output_dir)
    error = read_last_error(output_dir, last_success=success)

    healthy = success["timestamp"] is not None and not error["is_current"]
    max_age = request.args.get("max_age", type=int)
    in_quiet = is_quiet_hours_now(
        cfg.schedule.quiet_hours_start,
        cfg.schedule.quiet_hours_end,
        now_local(config_tz(cfg)),
    )
    if healthy and max_age is not None and not in_quiet:
        seconds_since = success.get("seconds_since")
        if seconds_since is None or seconds_since > max_age:
            healthy = False

    body = {
        "healthy": healthy,
        "last_success": success["timestamp"],
        "seconds_since_success": success["seconds_since"],
        "current_error": (
            {"timestamp": error["timestamp"], "exception_type": error["exception_type"]}
            if error["is_current"]
            else None
        ),
    }
    return jsonify(body), (200 if healthy else 503)
