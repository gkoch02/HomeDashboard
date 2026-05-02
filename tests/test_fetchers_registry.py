"""Contract tests for ``src.fetchers.registry``.

The registry is the v5 extension point for new data sources. These tests
guard the public shape so adding a fetcher in a follow-up doesn't silently
break the orchestration layer in ``DataPipeline`` or the cache codecs.
"""

from __future__ import annotations

import pytest

from src.fetchers.registry import (
    FetchContext,
    Fetcher,
    all_fetchers,
    get_fetcher,
    register_fetcher,
    registered_names,
    unregister_fetcher,
)


def _dummy_fetcher(name: str) -> Fetcher:
    return Fetcher(
        name=name,
        fetch=lambda ctx: None,
        serialize=lambda v: v,
        deserialize=lambda b: b,
        ttl_minutes=lambda cfg: 60,
        interval_minutes=lambda cfg: 30,
    )


class TestBuiltinRegistry:
    def test_builtin_fetchers_registered(self):
        names = set(registered_names())
        assert {"events", "weather", "birthdays", "air_quality"} <= names

    def test_each_builtin_fetcher_has_required_callables(self):
        for name in ("events", "weather", "birthdays", "air_quality"):
            f = get_fetcher(name)
            assert f is not None
            assert callable(f.fetch)
            assert callable(f.serialize)
            assert callable(f.deserialize)
            assert callable(f.ttl_minutes)
            assert callable(f.interval_minutes)
            assert callable(f.enabled)
            assert callable(f.save_metadata)
            assert callable(f.cache_metadata_valid)
            assert callable(f.log_success)

    def test_air_quality_disabled_when_purpleair_unconfigured(self):
        f = get_fetcher("air_quality")
        assert f is not None

        class _AQ:
            api_key = ""
            sensor_id = 0

        class _Cfg:
            purpleair = _AQ()

        assert f.enabled(_Cfg()) is False

    def test_air_quality_enabled_when_purpleair_configured(self):
        f = get_fetcher("air_quality")
        assert f is not None

        class _AQ:
            api_key = "k"
            sensor_id = 12345

        class _Cfg:
            purpleair = _AQ()

        assert f.enabled(_Cfg()) is True


class TestRegistryMutation:
    def test_register_then_lookup(self):
        f = _dummy_fetcher("__test_register__")
        try:
            register_fetcher(f)
            assert get_fetcher("__test_register__") is f
        finally:
            unregister_fetcher("__test_register__")

    def test_duplicate_registration_is_silent_no_op(self):
        f1 = _dummy_fetcher("__test_dupe__")
        f2 = _dummy_fetcher("__test_dupe__")
        try:
            register_fetcher(f1)
            # Second call must not raise; the first registration wins.
            assert register_fetcher(f2) is f1
            assert get_fetcher("__test_dupe__") is f1
        finally:
            unregister_fetcher("__test_dupe__")

    def test_unregister_unknown_is_noop(self):
        unregister_fetcher("__never_registered__")  # must not raise


class TestEventsCacheMetadata:
    def test_metadata_valid_when_window_matches(self):
        f = get_fetcher("events")
        assert f is not None
        from datetime import date

        ctx = FetchContext(cfg=None, event_window_start=date(2026, 1, 1), event_window_days=7)
        assert f.cache_metadata_valid({"window_start": "2026-01-01", "window_days": 7}, ctx)

    def test_metadata_invalid_when_window_changed(self):
        f = get_fetcher("events")
        assert f is not None
        from datetime import date

        ctx = FetchContext(cfg=None, event_window_start=date(2026, 1, 1), event_window_days=7)
        assert not f.cache_metadata_valid({"window_start": "2026-01-01", "window_days": 14}, ctx)

    def test_save_metadata_emits_window_fields(self):
        f = get_fetcher("events")
        assert f is not None
        from datetime import date

        ctx = FetchContext(cfg=None, event_window_start=date(2026, 1, 1), event_window_days=7)
        md = f.save_metadata(ctx)
        assert md == {"window_start": "2026-01-01", "window_days": 7}


class TestRegistryShapeIsImmutable:
    def test_fetcher_is_frozen(self):
        f = _dummy_fetcher("__frozen__")
        with pytest.raises((AttributeError, TypeError)):
            f.name = "rename"  # type: ignore[misc]

    def test_all_fetchers_returns_a_copy(self):
        before = all_fetchers()
        before.append(_dummy_fetcher("__leak__"))
        after = all_fetchers()
        assert "__leak__" not in [x.name for x in after]
