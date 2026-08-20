"""Tests for src/render/quotes.py — the shared quote store (#217).

Four panels used to carry their own copy of the path, the fallback list, and
the bucket-hash selection. These pin the consolidated behaviour and the new
``quotes.path`` override.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime

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
    """One loader, four prefixes — the point of #217."""

    def test_no_panel_keeps_its_own_quotes_path(self):
        import src.render.components.info_panel as ip
        import src.render.components.moonphase_panel as mp
        import src.render.components.scorecard_panel as sp
        import src.render.components.tides_panel as tp

        for module in (ip, mp, sp, tp):
            assert not hasattr(module, "QUOTES_FILE"), module.__name__

    def test_no_panel_keeps_its_own_fallback_list(self):
        import src.render.components.moonphase_panel as mp
        import src.render.components.scorecard_panel as sp
        import src.render.components.tides_panel as tp

        for module in (mp, sp, tp):
            assert not hasattr(module, "_DEFAULT_QUOTES"), module.__name__

    def test_panels_keep_independent_selections(self, tmp_path):
        from src.render.components.info_panel import _quote_for_today
        from src.render.components.moonphase_panel import (
            _quote_for_panel as moon_quote,
        )
        from src.render.components.scorecard_panel import (
            _quote_for_panel as score_quote,
        )
        from src.render.components.tides_panel import _quote_for_panel as tide_quote

        path = _store(tmp_path, [{"text": f"q{i}", "author": "a"} for i in range(80)])
        picks = {
            fn(TODAY, quotes_path=path)["text"]
            for fn in (_quote_for_today, moon_quote, score_quote, tide_quote)
        }
        assert len(picks) > 1

    def test_the_config_path_reaches_the_panels(self, tmp_path):
        from src.render.components.info_panel import _quote_for_today

        path = _store(tmp_path, [{"text": "Configured", "author": "Me"}])
        assert _quote_for_today(TODAY, quotes_path=path)["text"] == "Configured"


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
