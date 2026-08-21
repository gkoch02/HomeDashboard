"""Tests for src/render/components/tides_panel.py

Covers: _quote_for_panel (key prefix, refresh cadence, fallback),
individual band draw functions (_band_header, _band_events, _band_weather,
_band_forecast, _band_environment, _band_birthdays, _band_quote, _band_host),
and draw_tides (full render, missing data, band distribution).

Assertion discipline (see #229)
-------------------------------
Most of the band tests here used to call their function and assert nothing
at all; the rest asserted ``img.getbbox() is not None``, which on a
mode-``"1"`` plate filled with 1 can never be false. 40 of the 41 tests
passed with every band function stubbed to a no-op.

Ink here means **zero-valued** pixels. Watch the polarity: the header,
weather, environment and quote bands are inverted — filled in ``fg`` with
their text knocked out in ``bg`` — so for those four *more content means
less ink*, and the assertions are written in that direction.

At the whole-plate level the structural measure is ``_inverted_runs``: the
four inverted bands give a fingerprint of which bands were laid down, so
"losing weather drops a band" and "losing the forecast leaves weather and
environment contiguous" are checked directly.

Verification: with every band function and draw_tides stubbed to a no-op,
35 of the 43 tests fail. Of the 8 survivors, 6 are ``_quote_for_panel``
tests that exercise a pure function and never draw; the other two assert
that a band draws *nothing* (``test_no_weather_noop`` and
``test_empty_forecast_list_is_also_a_noop``), which a no-op satisfies by
construction — both were checked instead by making the guard draw a
placeholder and confirming they go red.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from src.data.models import (
    AirQualityData,
    Birthday,
    CalendarEvent,
    DashboardData,
    DayForecast,
    HostData,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.components.tides_panel import (
    _band_birthdays,
    _band_environment,
    _band_events,
    _band_forecast,
    _band_header,
    _band_host,
    _band_quote,
    _band_weather,
    _quote_for_panel,
    draw_tides,
)
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion, ThemeStyle

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
FIXED_TODAY = FIXED_NOW.date()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blank_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), color=1)
    return ImageDraw.Draw(img), img


def _style() -> ThemeStyle:
    return ThemeStyle()


def _weather(**kwargs) -> WeatherData:
    defaults = dict(
        current_temp=65.0,
        high=72.0,
        low=55.0,
        current_description="clear sky",
        current_icon="01d",
        feels_like=63.0,
        humidity=50,
        forecast=[
            DayForecast(
                date=FIXED_TODAY + timedelta(days=i),
                high=70.0 + i,
                low=55.0,
                icon="01d",
                description="clear",
            )
            for i in range(5)
        ],
        sunrise=datetime(2026, 4, 6, 6, 30),
        sunset=datetime(2026, 4, 6, 19, 45),
    )
    defaults.update(kwargs)
    return WeatherData(**defaults)


# ---------------------------------------------------------------------------
# _quote_for_panel
# ---------------------------------------------------------------------------


class TestTidesQuoteForPanel:
    def test_returns_dict_with_text(self):
        q = _quote_for_panel(FIXED_TODAY)
        assert "text" in q and q["text"]

    def test_deterministic_daily(self):
        q1 = _quote_for_panel(FIXED_TODAY)
        q2 = _quote_for_panel(FIXED_TODAY)
        assert q1["text"] == q2["text"]

    def test_tides_prefix_differs_from_scorecard(self):
        """The two panels must not show the same quote on the same plate.

        That is the entire reason the key prefixes exist, so it is asserted
        rather than assumed — the previous version of this test only checked
        that both calls returned a dict, which the prefixes have nothing to
        do with. Sampled across 60 days because a single day agreeing would
        be luck, not a bug.
        """
        from src.render.components.scorecard_panel import _quote_for_panel as sc_quote

        collisions = [
            day
            for day in (FIXED_TODAY + timedelta(days=i) for i in range(60))
            if _quote_for_panel(day)["text"] == sc_quote(day)["text"]
        ]
        assert not collisions, f"tides and scorecard picked the same quote on {collisions}"

    def test_hourly_refresh(self):
        q = _quote_for_panel(FIXED_TODAY, refresh="hourly", now=FIXED_NOW)
        assert "text" in q

    def test_twice_daily_refresh(self):
        am = datetime(2026, 4, 6, 9, 0)
        pm = datetime(2026, 4, 6, 15, 0)
        q_am = _quote_for_panel(FIXED_TODAY, refresh="twice_daily", now=am)
        q_pm = _quote_for_panel(FIXED_TODAY, refresh="twice_daily", now=pm)
        assert "text" in q_am and "text" in q_pm

    def test_fallback_when_no_file(self, monkeypatch, tmp_path):
        from src.render.quotes import DEFAULT_QUOTES

        monkeypatch.setattr("src.render.quotes.DEFAULT_QUOTES_PATH", tmp_path / "nonexistent.json")
        q = _quote_for_panel(FIXED_TODAY)
        assert q in DEFAULT_QUOTES


# ---------------------------------------------------------------------------
# Ink measurement
#
# NOTE the polarity: the header, weather, environment and quote bands are
# INVERTED — filled_rect in fg, with their text knocked out in bg. So for
# those four, *more content means less ink*. Assertions below are written in
# whichever direction the band actually works, not a uniform "more ink".
# ---------------------------------------------------------------------------


def _ink(img: Image.Image, height: int, width: int = 800) -> int:
    """Count ink (value-0) pixels in the top *height* rows."""
    px = flatten_pixels(img)
    return sum(1 for y in range(height) for x in range(width) if px[y * img.width + x] == 0)


def _inverted_runs(img: Image.Image, threshold: float = 0.5, merge_gap: int = 14):
    """(start, end) row ranges of the inverted bands on a full plate.

    A row counts as inverted when most of it is ink; knocked-out text
    interrupts that, so near-adjacent runs are merged. Two inverted bands
    that end up adjacent (because the normal band between them was skipped)
    read as one run — which is itself the signal that a band was dropped.
    """
    width, height = img.size
    px = flatten_pixels(img)
    hot = [
        sum(1 for x in range(width) if px[y * width + x] == 0) > width * threshold
        for y in range(height)
    ]
    runs: list[list[int]] = []
    start = None
    for y, is_hot in enumerate(hot):
        if is_hot and start is None:
            start = y
        elif not is_hot and start is not None:
            runs.append([start, y])
            start = None
    if start is not None:
        runs.append([start, height])
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [tuple(r) for r in merged]


def _inverted_height(img: Image.Image) -> int:
    return sum(end - start for start, end in _inverted_runs(img))


# ---------------------------------------------------------------------------
# Individual band functions
# ---------------------------------------------------------------------------


class TestBandHeader:
    H = 42

    def test_draws_an_inverted_bar_with_text_knocked_out(self):
        draw, img = _blank_draw()
        _band_header(draw, 0, 0, 800, self.H, FIXED_NOW, _style())
        inked = _ink(img, self.H)
        area = 800 * self.H
        assert inked > area * 0.5, "header band is not inverted"
        assert inked < area, "no text was knocked out of the fill"

    def test_header_text_tracks_the_clock(self):
        """Different date/time draws different text into the bar."""
        draw_a, img_a = _blank_draw()
        _band_header(draw_a, 0, 0, 800, self.H, FIXED_NOW, _style())
        draw_b, img_b = _blank_draw()
        _band_header(draw_b, 0, 0, 800, self.H, datetime(2026, 12, 25, 9, 5), _style())
        assert _ink(img_a, self.H) != _ink(img_b, self.H), "header ignores the datetime"


class TestBandEvents:
    H = 54

    def _draw_events(self, events):
        draw, img = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.events = events
        _band_events(draw, 0, 0, 800, self.H, data, FIXED_TODAY, _style())
        return img

    def test_no_events_today(self):
        """The empty state is a message, not a blank band."""
        assert _ink(self._draw_events([]), self.H) > 0

    def test_with_timed_events(self):
        """A timed event replaces the empty-state message."""
        timed = [
            CalendarEvent(
                summary="Morning standup",
                start=datetime(2026, 4, 6, 9, 0),
                end=datetime(2026, 4, 6, 9, 30),
            )
        ]
        assert _ink(self._draw_events(timed), self.H) != _ink(self._draw_events([]), self.H)

    def test_with_all_day_event(self):
        """An all-day event is labelled differently from a timed one."""
        all_day = [
            CalendarEvent(
                summary="Company Holiday",
                start=datetime(2026, 4, 6, 0, 0),
                end=datetime(2026, 4, 7, 0, 0),
                is_all_day=True,
            )
        ]
        timed = [
            CalendarEvent(
                summary="Company Holiday",
                start=datetime(2026, 4, 6, 9, 0),
                end=datetime(2026, 4, 6, 17, 0),
            )
        ]
        assert _ink(self._draw_events(all_day), self.H) != _ink(self._draw_events(timed), self.H), (
            "an all-day event rendered identically to a timed one with the same summary"
        )


class TestBandWeather:
    H = 40

    def _draw_weather(self, weather):
        draw, img = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = weather
        _band_weather(draw, 0, 0, 800, self.H, data, _style())
        return img

    def test_no_weather_data(self):
        """The band still inverts; it just has less to knock out."""
        inked = _ink(self._draw_weather(None), self.H)
        assert inked > 800 * self.H * 0.5, "weather band is not inverted"

    def test_with_weather_data(self):
        """Readings are knocked out of the fill, so ink goes DOWN, not up."""
        assert _ink(self._draw_weather(_weather()), self.H) < _ink(
            self._draw_weather(None), self.H
        ), "weather readings left no mark on the band"

    def test_weather_without_optional_fields(self):
        """Dropping feels-like and humidity removes text, so ink goes back up."""
        full = _ink(self._draw_weather(_weather()), self.H)
        trimmed = _ink(self._draw_weather(_weather(feels_like=None, humidity=None)), self.H)
        assert full < trimmed < _ink(self._draw_weather(None), self.H)


class TestBandForecast:
    H = 50

    def _draw_forecast(self, weather):
        draw, img = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.weather = weather
        _band_forecast(draw, 0, 0, 800, self.H, data, _style())
        return img

    def test_no_weather_noop(self):
        assert _ink(self._draw_forecast(None), self.H) == 0

    def test_with_forecast(self):
        assert _ink(self._draw_forecast(_weather()), self.H) > 0

    def test_empty_forecast_list_is_also_a_noop(self):
        """Weather present but no days is as blank as no weather at all."""
        assert _ink(self._draw_forecast(_weather(forecast=[])), self.H) == 0


class TestBandEnvironment:
    H = 38

    def _draw_env(self, **attrs):
        draw, img = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        for key, value in attrs.items():
            setattr(data, key, value)
        _band_environment(draw, 0, 0, 800, self.H, data, FIXED_TODAY, _style())
        return img

    def test_no_aqi_no_weather(self):
        """Moon phase alone still fills the inverted band."""
        assert _ink(self._draw_env(), self.H) > 800 * self.H * 0.5

    def test_with_aqi_data(self):
        """An AQI reading knocks more out of the fill."""
        aq = AirQualityData(aqi=42, category="Good", pm25=8.0)
        assert _ink(self._draw_env(air_quality=aq), self.H) < _ink(self._draw_env(), self.H)

    def test_with_weather_sunrise_sunset(self):
        assert _ink(self._draw_env(weather=_weather()), self.H) < _ink(self._draw_env(), self.H)

    def test_with_all_data(self):
        """Everything present leaves the least ink of the four combinations."""
        aq = AirQualityData(aqi=42, category="Good", pm25=8.0)
        combos = [
            _ink(self._draw_env(), self.H),
            _ink(self._draw_env(air_quality=aq), self.H),
            _ink(self._draw_env(weather=_weather()), self.H),
            _ink(self._draw_env(air_quality=aq, weather=_weather()), self.H),
        ]
        assert combos[-1] == min(combos), "the all-data band is not the fullest"
        assert len(set(combos)) == 4, "two environment combinations rendered identically"


class TestBandBirthdays:
    H = 36

    def _draw_birthdays(self, n: int):
        draw, img = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.birthdays = [
            Birthday(name=f"Person{i}", date=FIXED_TODAY + timedelta(days=i + 1)) for i in range(n)
        ]
        _band_birthdays(draw, 0, 0, 800, self.H, data, FIXED_TODAY, _style())
        return img

    def test_no_birthdays(self):
        """The empty state is a message, not a blank band."""
        assert _ink(self._draw_birthdays(0), self.H) > 0

    def test_with_birthdays(self):
        """Names replace the empty-state message, and more names draw more."""
        one = _ink(self._draw_birthdays(1), self.H)
        two = _ink(self._draw_birthdays(2), self.H)
        assert one != _ink(self._draw_birthdays(0), self.H)
        assert two > one

    def test_many_birthdays_truncated_at_4(self):
        """The 5th and later entries are dropped — 7 renders exactly like 4."""
        four = _ink(self._draw_birthdays(4), self.H)
        assert _ink(self._draw_birthdays(7), self.H) == four, "more than 4 birthdays were drawn"
        assert four > _ink(self._draw_birthdays(3), self.H), "the 4th birthday was dropped too"


class TestBandQuote:
    H = 86

    def _draw_quote(self, refresh: str, today=FIXED_TODAY, now=FIXED_NOW):
        draw, img = _blank_draw()
        _band_quote(draw, 0, 0, 800, self.H, today, now, _style(), refresh, None)
        return img

    def test_daily_refresh(self):
        """The band inverts and carries a quote knocked out of the fill."""
        inked = _ink(self._draw_quote("daily"), self.H)
        assert 800 * self.H * 0.5 < inked < 800 * self.H

    def test_hourly_refresh(self):
        assert _ink(self._draw_quote("hourly"), self.H) > 0

    def test_twice_daily_refresh(self):
        assert _ink(self._draw_quote("twice_daily"), self.H) > 0

    def test_refresh_modes_select_different_quotes(self):
        """The three cadences bucket differently, so they do not all agree."""
        inks = {m: _ink(self._draw_quote(m), self.H) for m in ("daily", "hourly", "twice_daily")}
        assert len(set(inks.values())) > 1, f"every refresh mode drew the same quote: {inks}"

    def test_quote_changes_with_the_date(self):
        """A daily quote is a function of the day, not a constant."""
        today = _ink(self._draw_quote("daily", today=FIXED_TODAY), self.H)
        later = _ink(self._draw_quote("daily", today=FIXED_TODAY + timedelta(days=40)), self.H)
        assert today != later, "the daily quote did not change over 40 days"


class TestBandHost:
    H = 34

    def _draw_host(self, host):
        draw, img = _blank_draw()
        data = DashboardData(fetched_at=FIXED_NOW)
        data.host_data = host
        _band_host(draw, 0, 0, 800, self.H, data, _style())
        return img

    def test_no_host_data(self):
        """Called directly with no host data the band still renders a placeholder."""
        assert _ink(self._draw_host(None), self.H) > 0

    def test_full_host_data(self):
        """A fully-populated HostData draws more than any lesser case."""
        full = HostData(
            hostname="dashboard-pi",
            uptime_seconds=98765,
            load_1m=0.4,
            ram_used_mb=512,
            ram_total_mb=2048,
            disk_used_gb=8,
            disk_total_gb=32,
            cpu_temp_c=48.2,
            ip_address="10.0.0.5",
        )
        assert _ink(self._draw_host(full), self.H) > _ink(self._draw_host(None), self.H)

    def test_partial_host_data(self):
        """A HostData with one field set is distinguishable from a full one."""
        partial = HostData(hostname="dashboard-pi")
        full = HostData(hostname="dashboard-pi", uptime_seconds=98765, load_1m=0.4)
        assert _ink(self._draw_host(partial), self.H) != _ink(self._draw_host(full), self.H)


# ---------------------------------------------------------------------------
# draw_tides — band composition
# ---------------------------------------------------------------------------


class TestDrawTides:
    def _draw(self, data: DashboardData, now: datetime = FIXED_NOW, **kwargs) -> Image.Image:
        img = Image.new("1", (800, 480), color=1)
        draw = ImageDraw.Draw(img)
        draw_tides(draw, data, now.date(), now, **kwargs)
        return img

    def test_smoke_full_dummy_data(self):
        """All four inverted bands are laid down, in order, without overlapping."""
        img = self._draw(generate_dummy_data(now=FIXED_NOW))
        runs = _inverted_runs(img)
        assert len(runs) == 4, f"expected 4 inverted bands, got {len(runs)}: {runs}"
        for (_, end), (start, _) in zip(runs, runs[1:]):
            assert start > end, f"inverted bands overlap: {runs}"

    def test_smoke_minimal_data(self):
        """Bare DashboardData still lays down the always-present bands."""
        img = self._draw(DashboardData(fetched_at=FIXED_NOW))
        assert len(_inverted_runs(img)) >= 3, "the always-present bands are missing"

    def test_smoke_no_weather(self):
        """Losing weather drops the weather band, so less of the plate inverts."""
        data = generate_dummy_data(now=FIXED_NOW)
        full = self._draw(data)
        data.weather = None
        without = self._draw(data)
        assert _inverted_height(without) < _inverted_height(full), "weather band was still drawn"
        assert len(_inverted_runs(without)) == 3

    def test_smoke_no_weather_no_forecast(self):
        """Weather present but no forecast: the forecast band between the
        weather and environment bands goes, leaving those two contiguous."""
        data = generate_dummy_data(now=FIXED_NOW)
        data.weather = _weather(forecast=[])
        runs = _inverted_runs(self._draw(data))
        assert len(runs) == 3, f"expected weather+environment to merge, got {runs}"
        longest = max(end - start for start, end in runs)
        assert longest > 60, f"no merged weather+environment run found: {runs}"

    def test_smoke_no_air_quality(self):
        """AQI is optional inside the environment band, not a band of its own."""
        data = generate_dummy_data(now=FIXED_NOW)
        with_aq = self._draw(data)
        data.air_quality = None
        without = self._draw(data)
        assert len(_inverted_runs(without)) == len(_inverted_runs(with_aq)), (
            "dropping AQI removed a whole band"
        )
        assert without.tobytes() != with_aq.tobytes(), "the AQI reading was never drawn"

    def test_smoke_no_birthdays(self):
        """The birthdays band is always present; only its content changes."""
        data = generate_dummy_data(now=FIXED_NOW)
        with_b = self._draw(data)
        data.birthdays = []
        without = self._draw(data)
        assert len(_inverted_runs(without)) == len(_inverted_runs(with_b))
        assert without.tobytes() != with_b.tobytes()

    def test_smoke_no_host_data(self):
        """No host data drops the host band and reflows the rest."""
        data = generate_dummy_data(now=FIXED_NOW)
        with_host = self._draw(data)
        data.host_data = None
        without = self._draw(data)
        assert without.tobytes() != with_host.tobytes(), "the host band was drawn anyway"

    def test_custom_region_offset_moves_the_content(self):
        data = generate_dummy_data(now=FIXED_NOW)
        at_origin = self._draw(data, region=ComponentRegion(0, 0, 800, 240))
        lower = self._draw(data, region=ComponentRegion(0, 120, 800, 240))
        assert at_origin.tobytes() != lower.tobytes()
        assert _inverted_runs(lower)[0][0] > _inverted_runs(at_origin)[0][0], (
            "region.y offset did not move the bands down"
        )

    def test_custom_style(self):
        """An inverted style flips which bands are filled."""
        data = generate_dummy_data(now=FIXED_NOW)
        normal = self._draw(data, style=ThemeStyle(fg=0, bg=1))
        flipped = self._draw(data, style=ThemeStyle(fg=1, bg=0))
        assert normal.tobytes() != flipped.tobytes()

    def test_quote_refresh_modes(self):
        """The cadence reaches the quote band rather than being ignored."""
        data = generate_dummy_data(now=FIXED_NOW)
        plates = {m: self._draw(data, quote_refresh=m).tobytes() for m in ("daily", "hourly")}
        assert len(set(plates.values())) > 1, "quote_refresh made no difference to the plate"

    def test_all_optional_bands_absent(self):
        """No weather and no host: both optional bands go, the rest still render."""
        data = DashboardData(fetched_at=FIXED_NOW)
        img = self._draw(data)
        full = self._draw(generate_dummy_data(now=FIXED_NOW))
        assert _inverted_height(img) < _inverted_height(full)
        assert len(_inverted_runs(img)) == 3, "the always-present bands did not all render"
