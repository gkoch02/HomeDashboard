"""Tests for src/render/quotes.py — the shared quote store (#217).

Four panels used to carry their own copy of the path, the fallback list, and
the bucket-hash selection. These pin the consolidated behaviour and the new
``quotes.path`` override.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.render import quotes as Q

TODAY = date(2026, 4, 6)


@pytest.fixture(autouse=True)
def _clear_cache():
    Q.cache_clear()
    yield
    Q.cache_clear()


def _store(tmp_path, entries) -> str:
    path = tmp_path / "quotes.json"
    path.write_text(json.dumps(entries))
    return str(path)


class TestBucketKey:
    def test_daily_key_is_just_the_date(self):
        assert Q.bucket_key(TODAY) == "2026-04-06"

    def test_prefix_is_applied(self):
        assert Q.bucket_key(TODAY, prefix="tides-") == "tides-2026-04-06"

    def test_hourly_key_carries_the_hour(self):
        now = datetime(2026, 4, 6, 14, 30)
        assert Q.bucket_key(TODAY, "hourly", now) == "2026-04-06T14"

    def test_twice_daily_flips_at_noon(self):
        am = Q.bucket_key(TODAY, "twice_daily", datetime(2026, 4, 6, 11, 59))
        pm = Q.bucket_key(TODAY, "twice_daily", datetime(2026, 4, 6, 12, 0))
        assert am.endswith("-am")
        assert pm.endswith("-pm")

    def test_unknown_cadence_falls_back_to_daily(self):
        assert Q.bucket_key(TODAY, "weekly") == "2026-04-06"


class TestSelection:
    def test_same_key_always_yields_the_same_quote(self, tmp_path):
        path = _store(tmp_path, [{"text": f"q{i}", "author": "a"} for i in range(20)])
        first = Q.quote_for(TODAY, path=path)
        Q.cache_clear()
        assert Q.quote_for(TODAY, path=path) == first

    def test_prefixes_separate_panels(self, tmp_path):
        """Two panels on one plate must not show the same quote."""
        path = _store(tmp_path, [{"text": f"q{i}", "author": "a"} for i in range(50)])
        picks = {
            Q.quote_for(TODAY, prefix=p, path=path)["text"]
            for p in ("", "tides-", "scorecard-", "moonphase-")
        }
        assert len(picks) > 1

    def test_different_days_rotate(self, tmp_path):
        path = _store(tmp_path, [{"text": f"q{i}", "author": "a"} for i in range(50)])
        picks = {
            Q.quote_for(date(2026, 4, 1) + __import__("datetime").timedelta(days=i), path=path)[
                "text"
            ]
            for i in range(10)
        }
        assert len(picks) > 1

    def test_selection_stays_in_bounds_for_a_one_quote_store(self, tmp_path):
        path = _store(tmp_path, [{"text": "only", "author": "a"}])
        assert Q.quote_for(TODAY, path=path)["text"] == "only"


class TestStoreLoading:
    def test_custom_store_is_used(self, tmp_path):
        path = _store(tmp_path, [{"text": "Custom", "author": "Me"}])
        assert Q.quote_for(TODAY, path=path)["text"] == "Custom"

    def test_missing_store_falls_back(self, tmp_path):
        assert Q.quote_for(TODAY, path=str(tmp_path / "nope.json")) in Q.DEFAULT_QUOTES

    def test_corrupt_store_falls_back(self, tmp_path):
        path = tmp_path / "quotes.json"
        path.write_text("not json {{{")
        assert Q.quote_for(TODAY, path=str(path)) in Q.DEFAULT_QUOTES

    def test_empty_store_falls_back(self, tmp_path):
        """An empty store would make the selection modulo divide by zero."""
        assert Q.quote_for(TODAY, path=_store(tmp_path, [])) in Q.DEFAULT_QUOTES

    def test_non_list_store_falls_back(self, tmp_path):
        assert Q.quote_for(TODAY, path=_store(tmp_path, {"a": 1})) in Q.DEFAULT_QUOTES

    def test_entries_missing_text_fall_back(self):
        """Panels index ["text"] directly, so an entry without it kills a render."""
        import tempfile

        tmp = pathlib.Path(tempfile.mkdtemp())
        assert Q.quote_for(TODAY, path=_store(tmp, [{}])) in Q.DEFAULT_QUOTES

    def test_entries_missing_author_fall_back(self, tmp_path):
        path = _store(tmp_path, [{"text": "orphan"}])
        assert Q.quote_for(TODAY, path=path) in Q.DEFAULT_QUOTES

    def test_bare_string_entries_fall_back(self, tmp_path):
        path = _store(tmp_path, ["just a string"])
        assert Q.quote_for(TODAY, path=path) in Q.DEFAULT_QUOTES

    def test_non_string_text_falls_back(self, tmp_path):
        path = _store(tmp_path, [{"text": 5, "author": "A"}])
        assert Q.quote_for(TODAY, path=path) in Q.DEFAULT_QUOTES

    def test_usable_entries_survive_a_bad_neighbour(self, tmp_path):
        """One typo in a long store should cost that quote, not the whole file."""
        path = _store(tmp_path, [{"text": "good", "author": "A"}, {}, "junk"])
        for _ in range(10):
            Q.cache_clear()
            assert Q.quote_for(TODAY, path=path)["text"] == "good"

    def test_every_selectable_quote_is_drawable(self, tmp_path):
        """The property the panels actually depend on, across many buckets."""
        import datetime as _dt

        path = _store(
            tmp_path,
            [{"text": "ok", "author": "A"}, {}, ["nope"], {"author": "no text"}, 7],
        )
        for i in range(40):
            Q.cache_clear()
            q = Q.quote_for(TODAY + _dt.timedelta(days=i), path=path)
            assert isinstance(q["text"], str) and isinstance(q["author"], str)

    def test_empty_path_uses_the_bundled_store(self):
        assert Q.quote_for(TODAY, path="") == Q.quote_for(TODAY)

    def test_none_path_uses_the_bundled_store(self, monkeypatch, tmp_path):
        path = _store(tmp_path, [{"text": "Redirected", "author": "a"}])
        monkeypatch.setattr(Q, "DEFAULT_QUOTES_PATH", __import__("pathlib").Path(path))
        assert Q.quote_for(TODAY)["text"] == "Redirected"

    def test_cache_is_keyed_on_the_path_too(self, tmp_path):
        """Keying on the bucket alone would serve one store's quote from another."""
        a = _store(tmp_path, [{"text": "from-a", "author": "x"}])
        b_dir = tmp_path / "b"
        b_dir.mkdir()
        b = _store(b_dir, [{"text": "from-b", "author": "x"}])
        assert Q.quote_for(TODAY, path=a)["text"] == "from-a"
        assert Q.quote_for(TODAY, path=b)["text"] == "from-b"


class TestPanelsShareOneLoader:
    """One loader, two prefixes — the point of #217."""

    def test_no_panel_keeps_its_own_quotes_path(self):
        import src.render.components.info_panel as ip
        import src.render.components.moonphase_panel as mp

        for module in (ip, mp):
            assert not hasattr(module, "QUOTES_FILE"), module.__name__

    def test_no_panel_keeps_its_own_fallback_list(self):
        import src.render.components.moonphase_panel as mp

        for module in (mp,):
            assert not hasattr(module, "_DEFAULT_QUOTES"), module.__name__

    def test_panels_keep_independent_selections(self, tmp_path):
        from src.render.quotes import quote_for

        path = _store(tmp_path, [{"text": f"q{i}", "author": "a"} for i in range(80)])
        picks = {quote_for(TODAY, path=path)["text"]} | {
            quote_for(TODAY, prefix=prefix, path=path)["text"] for prefix in ("moonphase-",)
        }
        assert len(picks) > 1

    def test_the_config_path_reaches_the_panels(self, tmp_path):
        from src.render.components.info_panel import draw_info
        from tests.conftest import make_draw
        from tests.inkutils import record_text

        path = _store(tmp_path, [{"text": "Configured", "author": "Me"}])
        _img, draw = make_draw()
        calls = record_text(draw)
        draw_info(draw, TODAY, quotes_path=str(path))
        assert any("Configured" in text for text, _box in calls)


class TestConfigPathEndToEnd:
    def test_quotes_path_reaches_a_rendered_dashboard(self, tmp_path):
        """The config field is worthless if it stops at the panel boundary."""
        from argparse import Namespace
        from pathlib import Path as _Path

        from src.app import DashboardApp
        from src.config import load_config

        quotes = _store(tmp_path, [{"text": "UNIQUEQUOTETOKEN", "author": "Tester"}])

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(f'theme: qotd\nquotes:\n  path: "{quotes}"\n')
        cfg = load_config(str(cfg_path))
        cfg.output_dir = str(tmp_path / "output")
        cfg.state_dir = str(tmp_path / "state")
        _Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
        _Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)

        captured = {}
        import src.app as app_module

        real_render = app_module.render_dashboard

        def _spy(*args, **kwargs):
            captured.update(kwargs)
            return real_render(*args, **kwargs)

        app_module.render_dashboard = _spy
        try:
            DashboardApp(
                cfg,
                Namespace(
                    dry_run=True,
                    dummy=True,
                    theme=None,
                    date=None,
                    force_full_refresh=False,
                    ignore_breakers=False,
                    message=None,
                ),
            ).run()
        finally:
            app_module.render_dashboard = real_render

        assert captured["quotes_path"] == quotes

    def test_unset_quotes_path_passes_none(self, tmp_path):
        from src.config import load_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("")
        assert (load_config(str(cfg_path)).quotes.path or None) is None


class TestQuoteFor:
    def test_returns_dict_with_text_and_author(self):
        q = Q.quote_for(date(2024, 3, 15))
        assert "text" in q
        assert "author" in q
        assert isinstance(q["text"], str)
        assert isinstance(q["author"], str)

    def test_deterministic_same_day(self):
        d = date(2024, 6, 21)
        q1 = Q.quote_for(d)
        q2 = Q.quote_for(d)
        assert q1 == q2

    def test_different_days_can_differ(self):
        """Two different dates should not always return the same quote
        (statistically near-certain with any real pool)."""

        quotes = {Q.quote_for(date(2024, 1, 1) + timedelta(days=i))["text"] for i in range(10)}
        assert len(quotes) > 1

    def test_uses_quotes_json_when_present(self, tmp_path):
        custom = [{"text": "Custom quote", "author": "Custom Author"}]
        qfile = tmp_path / "quotes.json"
        qfile.write_text(json.dumps(custom))

        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", qfile):
            Q.cache_clear()
            q = Q.quote_for(date(2024, 3, 15))

        assert q["text"] == "Custom quote"
        assert q["author"] == "Custom Author"

    def test_falls_back_to_defaults_when_file_missing(self, tmp_path):
        missing = tmp_path / "no_such_file.json"
        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", missing):
            q = Q.quote_for(date(2024, 3, 15))
        assert q["text"]  # non-empty

    def test_falls_back_to_defaults_on_corrupt_json(self, tmp_path):
        corrupt = tmp_path / "quotes.json"
        corrupt.write_text("not json {{{")
        with patch("src.render.quotes.DEFAULT_QUOTES_PATH", corrupt):
            q = Q.quote_for(date(2024, 3, 15))
        assert q["text"]

    def test_index_within_pool_bounds(self):
        """Hash-mod should never produce an out-of-range index."""
        for day_offset in range(100):
            d = date(2024, 1, 1) + __import__("datetime").timedelta(days=day_offset)
            q = Q.quote_for(d)
            assert q["text"]


class TestQuoteRefreshModes:
    """Tests for the refresh= parameter on quote_for."""

    def setup_method(self):
        Q.cache_clear()

    def teardown_method(self):
        Q.cache_clear()

    def test_daily_same_as_default(self):
        d = date(2025, 6, 1)
        assert Q.quote_for(d, refresh="daily") == Q.quote_for(d)

    def test_twice_daily_am_stable(self):
        d = date(2025, 6, 1)
        now_am1 = datetime(2025, 6, 1, 9, 0)
        now_am2 = datetime(2025, 6, 1, 11, 59)
        assert Q.quote_for(d, refresh="twice_daily", now=now_am1) == Q.quote_for(
            d, refresh="twice_daily", now=now_am2
        )

    def test_twice_daily_pm_stable(self):
        d = date(2025, 6, 1)
        now_pm1 = datetime(2025, 6, 1, 12, 0)
        now_pm2 = datetime(2025, 6, 1, 23, 0)
        assert Q.quote_for(d, refresh="twice_daily", now=now_pm1) == Q.quote_for(
            d, refresh="twice_daily", now=now_pm2
        )

    def test_twice_daily_am_pm_differ(self):
        d = date(2025, 6, 2)
        now_am = datetime(2025, 6, 2, 8, 0)
        now_pm = datetime(2025, 6, 2, 14, 0)
        # Keys differ ("2025-06-02-am" vs "2025-06-02-pm") so hashes differ
        q_am = Q.quote_for(d, refresh="twice_daily", now=now_am)
        q_pm = Q.quote_for(d, refresh="twice_daily", now=now_pm)
        assert q_am != q_pm

    def test_hourly_same_hour_stable(self):
        d = date(2025, 6, 3)
        now1 = datetime(2025, 6, 3, 14, 0)
        now2 = datetime(2025, 6, 3, 14, 59)
        assert Q.quote_for(d, refresh="hourly", now=now1) == Q.quote_for(
            d, refresh="hourly", now=now2
        )

    def test_hourly_different_hours_differ(self):
        d = date(2025, 6, 3)
        now_h1 = datetime(2025, 6, 3, 9, 0)
        now_h2 = datetime(2025, 6, 3, 10, 0)
        q1 = Q.quote_for(d, refresh="hourly", now=now_h1)
        q2 = Q.quote_for(d, refresh="hourly", now=now_h2)
        assert q1 != q2

    def test_daily_and_hourly_can_differ(self):
        d = date(2025, 6, 4)
        now = datetime(2025, 6, 4, 15, 0)
        q_daily = Q.quote_for(d, refresh="daily")
        q_hourly = Q.quote_for(d, refresh="hourly", now=now)
        # Keys are different strings so at least one of the many hours will differ
        assert isinstance(q_daily, dict) and isinstance(q_hourly, dict)

    def test_result_has_text_and_author(self):
        d = date(2025, 6, 5)
        now = datetime(2025, 6, 5, 10, 0)
        for refresh in ("daily", "twice_daily", "hourly"):
            q = Q.quote_for(d, refresh=refresh, now=now)
            assert "text" in q and "author" in q
