"""Tests for src/web/state_reader.py — pure read functions."""

import json
from datetime import datetime, timedelta, timezone

from src.web.state_reader import (
    is_quiet_hours_now,
    read_breakers,
    read_cache_ages,
    read_last_success,
    read_log_tail,
    read_quota,
)

# ---------------------------------------------------------------------------
# read_last_success
# ---------------------------------------------------------------------------


def test_read_last_success_missing(tmp_path):
    result = read_last_success(str(tmp_path))
    assert result["timestamp"] is None
    assert result["seconds_since"] is None


def test_read_last_success_recent(tmp_path):
    ts = datetime.now(timezone.utc) - timedelta(seconds=90)
    (tmp_path / "last_success.txt").write_text(ts.isoformat())
    result = read_last_success(str(tmp_path))
    assert result["timestamp"] is not None
    assert 85 <= result["seconds_since"] <= 100  # allow ±5 s clock skew


def test_read_last_success_corrupt(tmp_path):
    (tmp_path / "last_success.txt").write_text("not-a-date")
    result = read_last_success(str(tmp_path))
    assert result["timestamp"] is None


# ---------------------------------------------------------------------------
# read_breakers
# ---------------------------------------------------------------------------


def test_read_breakers_missing(tmp_path):
    result = read_breakers(str(tmp_path))
    for source in ("events", "weather", "birthdays", "air_quality"):
        assert result[source]["state"] == "closed"
        assert result[source]["consecutive_failures"] == 0


def test_read_breakers_open(tmp_path):
    data = {
        "weather": {
            "state": "open",
            "consecutive_failures": 3,
            "last_failure_at": "2026-04-06T10:00:00",
        }
    }
    (tmp_path / "dashboard_breaker_state.json").write_text(json.dumps(data))
    result = read_breakers(str(tmp_path))
    assert result["weather"]["state"] == "open"
    assert result["weather"]["consecutive_failures"] == 3
    # Missing source defaults to closed
    assert result["events"]["state"] == "closed"


def test_read_breakers_corrupt(tmp_path):
    (tmp_path / "dashboard_breaker_state.json").write_text("{bad json")
    result = read_breakers(str(tmp_path))
    # Should not raise; all sources default to closed
    for source in ("events", "weather", "birthdays", "air_quality"):
        assert result[source]["state"] == "closed"


# ---------------------------------------------------------------------------
# read_cache_ages
# ---------------------------------------------------------------------------


def test_read_cache_ages_missing(tmp_path):
    result = read_cache_ages(str(tmp_path), {"weather": 60})
    for source in ("events", "weather", "birthdays", "air_quality"):
        assert result[source]["cache_age_minutes"] is None
        assert result[source]["staleness"] == "unknown"


def test_read_cache_ages_fresh(tmp_path):
    fetched_at = (datetime.now() - timedelta(minutes=5)).isoformat()
    raw = {
        "schema_version": 2,
        "weather": {"fetched_at": fetched_at, "data": {}},
    }
    (tmp_path / "dashboard_cache.json").write_text(json.dumps(raw))
    ttls = {"weather": 60, "events": 120, "birthdays": 1440, "air_quality": 30}
    result = read_cache_ages(str(tmp_path), ttls)
    assert result["weather"]["staleness"] == "fresh"
    assert 4 <= result["weather"]["cache_age_minutes"] <= 6
    # Absent source still returns unknown
    assert result["events"]["staleness"] == "unknown"


def test_read_cache_ages_stale(tmp_path):
    fetched_at = (datetime.now() - timedelta(minutes=200)).isoformat()
    raw = {
        "schema_version": 2,
        "weather": {"fetched_at": fetched_at, "data": {}},
    }
    (tmp_path / "dashboard_cache.json").write_text(json.dumps(raw))
    result = read_cache_ages(str(tmp_path), {"weather": 60})
    assert result["weather"]["staleness"] in ("stale", "expired")


# ---------------------------------------------------------------------------
# read_quota
# ---------------------------------------------------------------------------


def test_read_quota_missing(tmp_path):
    assert read_quota(str(tmp_path)) == {}


def test_read_quota_today(tmp_path):
    data = {"date": "2026-04-06", "counts": {"google": 15, "weather": 3}}
    (tmp_path / "api_quota_state.json").write_text(json.dumps(data))
    result = read_quota(str(tmp_path))
    assert result["google"] == 15
    assert result["weather"] == 3


# ---------------------------------------------------------------------------
# read_log_tail
# ---------------------------------------------------------------------------


def test_read_log_tail_missing(tmp_path):
    assert read_log_tail(str(tmp_path)) == []


def test_read_log_tail_returns_last_n(tmp_path):
    log = "\n".join(f"line {i}" for i in range(200))
    (tmp_path / "dashboard.log").write_text(log)
    result = read_log_tail(str(tmp_path), n=50)
    assert len(result) == 50
    assert result[-1] == "line 199"
    assert result[0] == "line 150"


# ---------------------------------------------------------------------------
# is_quiet_hours_now
# ---------------------------------------------------------------------------


def test_is_quiet_hours_now_type():
    result = is_quiet_hours_now(23, 6)
    assert isinstance(result, bool)
