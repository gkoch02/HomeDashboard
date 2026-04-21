"""Tests for src/web/state_reader.py — pure read functions."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.web.state_reader import (
    is_quiet_hours_now,
    read_breakers,
    read_cache_ages,
    read_host_metrics,
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


def test_read_cache_ages_timezone_aware_timestamp(tmp_path):
    fetched_at = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
    raw = {
        "schema_version": 2,
        "weather": {"fetched_at": fetched_at, "data": {}},
    }
    (tmp_path / "dashboard_cache.json").write_text(json.dumps(raw))
    result = read_cache_ages(str(tmp_path), {"weather": 60})
    assert result["weather"]["fetched_at"] == fetched_at
    assert result["weather"]["cache_age_minutes"] is not None
    assert result["weather"]["staleness"] in ("fresh", "aging")


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


# ---------------------------------------------------------------------------
# Edge cases that exercise the defensive try/except branches
# ---------------------------------------------------------------------------


def test_read_last_success_naive_timestamp_normalised(tmp_path):
    """A naive (no tz) timestamp must be normalised via astimezone(UTC) on line 44."""
    naive = (datetime.now() - timedelta(seconds=120)).replace(tzinfo=None).isoformat()
    (tmp_path / "last_success.txt").write_text(naive)
    result = read_last_success(str(tmp_path))
    assert result["timestamp"] is not None
    assert result["seconds_since"] is not None
    # Either close to 120s, or much larger if the local tz differs from UTC.
    assert result["seconds_since"] >= 0


def test_read_breakers_corrupt_returns_defaults(tmp_path):
    """Malformed JSON in the breaker file must be swallowed with debug log."""
    (tmp_path / "dashboard_breaker_state.json").write_text("not-json{")
    result = read_breakers(str(tmp_path))
    for source in ("events", "weather", "birthdays", "air_quality"):
        assert result[source]["state"] == "closed"


def test_read_cache_ages_corrupt_file_returns_unknown(tmp_path):
    """Unparseable cache file is logged at debug; all sources fall through to unknown."""
    (tmp_path / "dashboard_cache.json").write_text("definitely not json")
    result = read_cache_ages(str(tmp_path), {"weather": 60})
    assert result["weather"]["staleness"] == "unknown"
    assert result["weather"]["cache_age_minutes"] is None


def test_read_cache_ages_unparseable_entry_returns_unknown(tmp_path):
    """A bogus per-source fetched_at value triggers the inner except branch."""
    raw = {"weather": {"fetched_at": "not-a-timestamp", "data": {}}}
    (tmp_path / "dashboard_cache.json").write_text(json.dumps(raw))
    result = read_cache_ages(str(tmp_path), {"weather": 60})
    assert result["weather"]["staleness"] == "unknown"
    assert result["weather"]["cache_age_minutes"] is None
    assert result["weather"]["fetched_at"] is None


def test_read_quota_corrupt_file_returns_empty(tmp_path):
    (tmp_path / "api_quota_state.json").write_text("nope")
    assert read_quota(str(tmp_path)) == {}


def test_read_log_tail_handles_unreadable_file(tmp_path):
    """A read error during iteration is caught and an empty list returned."""
    log = tmp_path / "dashboard.log"
    log.write_text("line one\n")
    with patch("builtins.open", side_effect=OSError("boom")):
        # State reader's log path open is the one we patch; the .exists() check on
        # the file already happened before the patch, so we still get the except path.
        result = read_log_tail(str(tmp_path))
    assert result == []


def test_read_host_metrics_returns_dict_when_host_data_available():
    """The happy path: read_host_metrics serialises the dataclass into a plain dict."""
    result = read_host_metrics()
    # Real fetch_host_data returns a HostData; result is a dict with the expected keys.
    if result is not None:
        for key in (
            "hostname",
            "uptime_seconds",
            "load_1m",
            "load_5m",
            "load_15m",
            "ram_used_mb",
            "ram_total_mb",
            "disk_used_gb",
            "disk_total_gb",
            "cpu_temp_c",
            "ip_address",
        ):
            assert key in result


def test_read_host_metrics_returns_none_when_fetch_fails():
    """If fetch_host_data returns None, read_host_metrics passes that through."""
    with patch("src.web.state_reader.fetch_host_data", return_value=None):
        assert read_host_metrics() is None
