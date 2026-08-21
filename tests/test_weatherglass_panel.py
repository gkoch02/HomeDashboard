"""Tests for the weatherglass theme and weatherglass_panel component.

The panel is the largest component in the tree and carries two clusters of
logic that nothing else in the render layer has:

* a rolling pressure history persisted to ``state/`` — the only on-disk state
  written by a component — with malformed-file recovery, an append gap, a
  sample cap, and an atomic write;
* five unit-aware scale functions that decide the thermometer range, the
  comfort band, the freeze/hot thresholds, and the wind label.

Both were previously exercised only incidentally through the pixel-snapshot
suite, which renders every theme at a single pinned moment under imperial
units — so the metric and standard branches and every pressure-history path
had no regression protection.

Assertion discipline (see #229)
-------------------------------
#229 singles this file out: its parametrized sweeps across the AQI scale,
the wind rose and the UV scale are *deliberate* smoke tests and should keep
their shape. They have — the change here is only that they can now fail.
They asserted ``img.getbbox() is not None`` on a white plate with fg=0,
where getbbox reports the bounds of non-zero pixels and so returns the full
canvas whether or not anything was drawn; ``_marks`` counts pixels that
differ from the background instead.

Each sweep also gained one companion test asserting that the range actually
reaches its instrument. The sweep says every value renders; the companion
says the values do not all render *identically*. A compass that ignores the
bearing passes the first and fails the second.

Verification: with ``draw_weatherglass`` stubbed to a no-op, 52 of the 126
tests fail (10 did before). The survivors are the pure scale/format helpers,
the theme-registry cases, and the pressure-history tests, which assert on
files in ``state/`` rather than on pixels.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image, ImageDraw

from src.config import DisplayConfig
from src.data.models import (
    AirQualityData,
    DashboardData,
    WeatherAlert,
    WeatherData,
)
from src.dummy_data import generate_dummy_data
from src.render.canvas import render_dashboard
from src.render.components.weatherglass_panel import (
    _MAX_SAMPLES,
    _MIN_APPEND_GAP,
    _PRESSURE_FILE,
    _TREND_MAX_AGE,
    _TREND_MIN_AGE,
    _fmt_clock,
    _load_prev_pressure,
    _pressure_to_angle,
    _save_pressure_sample,
    _temp_cold_threshold,
    _temp_comfort_band,
    _temp_hot_threshold,
    _temp_scale,
    _wind_unit_label,
    draw_weatherglass,
)
from src.render.quantize import flatten_pixels
from src.render.theme import AVAILABLE_THEMES, ComponentRegion, ThemeStyle, load_theme

FIXED_NOW = datetime(2026, 4, 6, 10, 30)
TODAY = FIXED_NOW.date()
NOW_UTC = datetime(2026, 4, 6, 10, 30, tzinfo=timezone.utc)


def _render(**kwargs):
    data = generate_dummy_data(now=FIXED_NOW)
    theme = load_theme("weatherglass")
    return render_dashboard(data, DisplayConfig(), theme=theme, **kwargs)


def _weather(**overrides) -> WeatherData:
    base = dict(
        current_temp=64.0,
        current_icon="01d",
        current_description="clear sky",
        high=72.0,
        low=51.0,
        humidity=55,
        wind_speed=8.0,
        wind_deg=270.0,
        pressure=1013.0,
        uv_index=4.0,
        location_name="New York",
        units="imperial",
    )
    base.update(overrides)
    return WeatherData(**base)


def _canvas(mode: str = "L", size: tuple[int, int] = (1600, 960)):
    bg = 255 if mode != "RGB" else (255, 255, 255)
    img = Image.new(mode, size, bg)
    return img, ImageDraw.Draw(img)


def _style(mode: str = "L") -> ThemeStyle:
    if mode == "RGB":
        return ThemeStyle(fg=(0, 0, 0), bg=(255, 255, 255))
    return ThemeStyle(fg=0, bg=255)


def _marks(img, box=None) -> int:
    """Pixels differing from the canvas background.

    The honest replacement for ``img.getbbox() is not None`` here: the plate
    is white with fg=0, so getbbox reports the bounds of non-zero pixels and
    returns the full canvas whether or not anything was drawn.
    """
    px = flatten_pixels(img)
    width = img.width
    background = px[0]
    if box is None:
        return sum(1 for v in px if v != background)
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] != background)


def _history(path) -> list[dict]:
    return json.loads(path.read_text())["samples"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestWeatherglassRegistration:
    def test_in_available_themes(self):
        assert "weatherglass" in AVAILABLE_THEMES

    def test_load_theme(self):
        assert load_theme("weatherglass").name == "weatherglass"

    def test_region_is_supersampled_canvas(self):
        layout = load_theme("weatherglass").layout
        assert layout.weatherglass.visible is True
        # 2× supersample; the backend resizes to display resolution via LANCZOS.
        assert (layout.weatherglass.w, layout.weatherglass.h) == (1600, 960)

    def test_threshold_quantization_not_dithering(self):
        """Every shaded zone is hand-stippled, so the plate must not dither.

        Floyd-Steinberg would turn the antialiased instrument rims into
        speckle instead of snapping them to solid black.
        """
        assert load_theme("weatherglass").layout.preferred_quantization_mode == "threshold"


# ---------------------------------------------------------------------------
# Unit-aware scales
# ---------------------------------------------------------------------------


class TestUnitAwareScales:
    @pytest.mark.parametrize(
        "units,lo,hi,symbol",
        [
            ("imperial", 0.0, 110.0, "°F"),
            ("metric", -20.0, 45.0, "°C"),
            ("standard", 253.0, 318.0, "K"),
            (None, 0.0, 110.0, "°F"),
            ("nonsense", 0.0, 110.0, "°F"),
        ],
    )
    def test_temp_scale(self, units, lo, hi, symbol):
        got_lo, got_hi, got_symbol, ticks = _temp_scale(units)
        assert (got_lo, got_hi, got_symbol) == (lo, hi, symbol)
        assert ticks == sorted(ticks), "major ticks must ascend"
        assert lo <= ticks[0] and ticks[-1] <= hi, "ticks must sit inside the scale"

    @pytest.mark.parametrize(
        "units,expected",
        [
            ("imperial", (60.0, 75.0)),
            ("metric", (16.0, 24.0)),
            ("standard", (289.15, 297.15)),
            (None, (60.0, 75.0)),
        ],
    )
    def test_comfort_band(self, units, expected):
        assert _temp_comfort_band(units) == expected

    @pytest.mark.parametrize(
        "units,cold,hot",
        [
            ("imperial", 32.0, 85.0),
            ("metric", 0.0, 30.0),
            ("standard", 273.15, 303.15),
            (None, 32.0, 85.0),
        ],
    )
    def test_freeze_and_hot_thresholds(self, units, cold, hot):
        assert _temp_cold_threshold(units) == cold
        assert _temp_hot_threshold(units) == hot

    @pytest.mark.parametrize("units", ["imperial", "metric", "standard", None])
    def test_thresholds_are_ordered_within_scale(self, units):
        """cold < comfort band < hot, and all of it inside the drawn scale.

        A threshold outside the scale range would silently clamp to the end of
        the thermometer and read as a permanently freezing (or boiling) day.
        """
        lo, hi, _, _ = _temp_scale(units)
        cold = _temp_cold_threshold(units)
        hot = _temp_hot_threshold(units)
        comf_lo, comf_hi = _temp_comfort_band(units)
        assert lo < cold < comf_lo < comf_hi < hot < hi

    @pytest.mark.parametrize(
        "units,label",
        [
            ("imperial", "mph"),
            ("metric", "m/s"),
            ("standard", "m/s"),
            (None, "mph"),
        ],
    )
    def test_wind_unit_label(self, units, label):
        assert _wind_unit_label(units) == label

    def test_scales_are_equivalent_across_unit_systems(self):
        """The three scales must describe the same physical temperatures.

        Otherwise a metric user's comfort band sits at a different real
        temperature than an imperial user's, and the instrument lies.
        """

        def f_to_c(f):
            return (f - 32) * 5 / 9

        imp_cold = _temp_cold_threshold("imperial")
        assert f_to_c(imp_cold) == pytest.approx(_temp_cold_threshold("metric"), abs=0.1)
        assert f_to_c(imp_cold) + 273.15 == pytest.approx(_temp_cold_threshold("standard"), abs=0.1)

        imp_lo, imp_hi = _temp_comfort_band("imperial")
        met_lo, met_hi = _temp_comfort_band("metric")
        assert f_to_c(imp_lo) == pytest.approx(met_lo, abs=1.0)
        assert f_to_c(imp_hi) == pytest.approx(met_hi, abs=1.0)


# ---------------------------------------------------------------------------
# Pressure history — load
# ---------------------------------------------------------------------------


class TestLoadPrevPressure:
    def test_no_state_dir_returns_empty(self):
        assert _load_prev_pressure(None, NOW_UTC) == (None, None)
        assert _load_prev_pressure("", NOW_UTC) == (None, None)

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_prev_pressure(str(tmp_path), NOW_UTC) == (None, None)

    def test_malformed_json_returns_empty(self, tmp_path):
        (tmp_path / _PRESSURE_FILE).write_text("{not json")
        assert _load_prev_pressure(str(tmp_path), NOW_UTC) == (None, None)

    @pytest.mark.parametrize("blob", ["[]", '"a string"', "42", '{"samples": {}}', "{}"])
    def test_non_dict_and_non_list_shapes_return_empty(self, tmp_path, blob):
        (tmp_path / _PRESSURE_FILE).write_text(blob)
        assert _load_prev_pressure(str(tmp_path), NOW_UTC) == (None, None)

    def test_reads_sample_inside_the_trend_window(self, tmp_path):
        ts = NOW_UTC - timedelta(hours=6)
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": ts.isoformat(), "hPa": 1008.0}]})
        )
        prev, got_ts = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == 1008.0
        assert got_ts == ts

    @pytest.mark.parametrize(
        "age,expected",
        [
            (timedelta(minutes=30), None),  # younger than _TREND_MIN_AGE
            (_TREND_MIN_AGE, 1008.0),  # inclusive lower bound
            (timedelta(hours=12), 1008.0),
            (_TREND_MAX_AGE, 1008.0),  # inclusive upper bound
            (timedelta(hours=48), None),  # older than _TREND_MAX_AGE
        ],
    )
    def test_trend_window_bounds(self, tmp_path, age, expected):
        """A too-fresh sample makes the trend needle jitter; a too-old one
        makes it report weather from two days ago."""
        ts = NOW_UTC - age
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": ts.isoformat(), "hPa": 1008.0}]})
        )
        prev, _ = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == expected

    def test_prefers_the_oldest_in_window_sample(self, tmp_path):
        """The trend is most legible against the furthest-back valid reading."""
        samples = [
            {"ts": (NOW_UTC - timedelta(hours=2)).isoformat(), "hPa": 1011.0},
            {"ts": (NOW_UTC - timedelta(hours=20)).isoformat(), "hPa": 1002.0},
            {"ts": (NOW_UTC - timedelta(hours=8)).isoformat(), "hPa": 1006.0},
        ]
        (tmp_path / _PRESSURE_FILE).write_text(json.dumps({"samples": samples}))
        prev, ts = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == 1002.0
        assert ts == datetime.fromisoformat(samples[1]["ts"])

    def test_skips_unusable_entries_but_keeps_reading(self, tmp_path):
        """One corrupt row must not discard the rest of the history."""
        good_ts = NOW_UTC - timedelta(hours=5)
        samples = [
            "not a dict",
            {"ts": 12345, "hPa": 1000.0},  # ts not a string
            {"ts": (NOW_UTC - timedelta(hours=9)).isoformat(), "hPa": "high"},
            {"ts": "not-a-timestamp", "hPa": 1000.0},
            {"hPa": 1000.0},  # no ts
            {"ts": good_ts.isoformat()},  # no hPa
            {"ts": good_ts.isoformat(), "hPa": 1004.0},
        ]
        (tmp_path / _PRESSURE_FILE).write_text(json.dumps({"samples": samples}))
        prev, ts = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == 1004.0
        assert ts == good_ts

    def test_naive_stored_timestamp_is_read_as_utc(self, tmp_path):
        """Legacy rows written without an offset must not be read as local
        time — on a UTC-7 host that would shift every sample by 7 hours."""
        ts = (NOW_UTC - timedelta(hours=6)).replace(tzinfo=None)
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": ts.isoformat(), "hPa": 1007.0}]})
        )
        prev, _ = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == 1007.0

    def test_naive_now_is_treated_as_utc(self, tmp_path):
        ts = NOW_UTC - timedelta(hours=6)
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": ts.isoformat(), "hPa": 1009.0}]})
        )
        prev, _ = _load_prev_pressure(str(tmp_path), NOW_UTC.replace(tzinfo=None))
        assert prev == 1009.0

    def test_offset_aware_now_is_normalised(self, tmp_path):
        """A caller in UTC-7 must resolve the same sample as a UTC caller."""
        ts = NOW_UTC - timedelta(hours=6)
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": ts.isoformat(), "hPa": 1005.0}]})
        )
        local_now = NOW_UTC.astimezone(timezone(timedelta(hours=-7)))
        prev, _ = _load_prev_pressure(str(tmp_path), local_now)
        assert prev == 1005.0

    def test_integer_pressure_is_accepted(self, tmp_path):
        ts = NOW_UTC - timedelta(hours=4)
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": ts.isoformat(), "hPa": 1010}]})
        )
        prev, _ = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == 1010.0
        assert isinstance(prev, float)


# ---------------------------------------------------------------------------
# Pressure history — save
# ---------------------------------------------------------------------------


class TestSavePressureSample:
    def test_no_state_dir_is_a_noop(self, tmp_path):
        """state_dir=None disables history entirely, in both directions."""
        _save_pressure_sample(None, 1013.0, NOW_UTC)  # must not raise
        assert _load_prev_pressure(None, NOW_UTC) == (None, None)
        assert list(tmp_path.iterdir()) == [], "something was written despite no state dir"

    def test_none_pressure_is_not_recorded(self, tmp_path):
        _save_pressure_sample(str(tmp_path), None, NOW_UTC)
        assert not (tmp_path / _PRESSURE_FILE).exists()

    def test_creates_state_dir_and_file(self, tmp_path):
        target = tmp_path / "nested" / "state"
        _save_pressure_sample(str(target), 1013.0, NOW_UTC)
        samples = _history(target / _PRESSURE_FILE)
        assert samples == [{"ts": NOW_UTC.isoformat(), "hPa": 1013.0}]

    def test_appends_when_the_gap_is_wide_enough(self, tmp_path):
        _save_pressure_sample(str(tmp_path), 1010.0, NOW_UTC - timedelta(hours=6))
        _save_pressure_sample(str(tmp_path), 1015.0, NOW_UTC)
        samples = _history(tmp_path / _PRESSURE_FILE)
        assert [s["hPa"] for s in samples] == [1010.0, 1015.0]

    @pytest.mark.parametrize(
        "gap,appended",
        [
            (timedelta(minutes=5), False),
            (_MIN_APPEND_GAP - timedelta(seconds=1), False),
            (_MIN_APPEND_GAP, True),
            (timedelta(hours=1), True),
        ],
    )
    def test_min_append_gap(self, tmp_path, gap, appended):
        """The renderer ticks every 5 minutes; without the gap the history
        would hold 12 near-identical samples an hour and the trend window
        would only ever span the last few minutes."""
        _save_pressure_sample(str(tmp_path), 1010.0, NOW_UTC)
        _save_pressure_sample(str(tmp_path), 1020.0, NOW_UTC + gap)
        samples = _history(tmp_path / _PRESSURE_FILE)
        assert len(samples) == (2 if appended else 1)

    def test_trims_to_the_sample_cap(self, tmp_path):
        existing = [
            {"ts": (NOW_UTC - timedelta(hours=200 - i)).isoformat(), "hPa": 1000.0 + i}
            for i in range(120)
        ]
        (tmp_path / _PRESSURE_FILE).write_text(json.dumps({"samples": existing}))
        _save_pressure_sample(str(tmp_path), 1099.0, NOW_UTC)
        samples = _history(tmp_path / _PRESSURE_FILE)
        assert len(samples) == _MAX_SAMPLES
        assert samples[-1]["hPa"] == 1099.0, "the newest sample must survive the trim"

    def test_malformed_existing_file_is_replaced_not_propagated(self, tmp_path):
        (tmp_path / _PRESSURE_FILE).write_text("{corrupt")
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)
        assert _history(tmp_path / _PRESSURE_FILE) == [{"ts": NOW_UTC.isoformat(), "hPa": 1013.0}]

    def test_non_dict_rows_are_dropped_on_rewrite(self, tmp_path):
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": ["junk", 5, {"ts": "bad", "hPa": 1000.0}]})
        )
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)
        samples = _history(tmp_path / _PRESSURE_FILE)
        assert all(isinstance(s, dict) for s in samples)
        assert samples[-1]["hPa"] == 1013.0

    def test_unparseable_last_timestamp_does_not_block_the_append(self, tmp_path):
        (tmp_path / _PRESSURE_FILE).write_text(
            json.dumps({"samples": [{"ts": "not-a-timestamp", "hPa": 1000.0}]})
        )
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)
        assert len(_history(tmp_path / _PRESSURE_FILE)) == 2

    def test_naive_now_is_persisted_as_aware_utc(self, tmp_path):
        """Every persisted timestamp in the tree is aware, so that subtracting
        it from an aware now never raises TypeError."""
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC.replace(tzinfo=None))
        ts = _history(tmp_path / _PRESSURE_FILE)[0]["ts"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None, "a naive timestamp was persisted"
        assert parsed.utcoffset() == timedelta(0), f"not stored as UTC: {ts}"
        # And it round-trips: subtracting from an aware now must not raise.
        assert (NOW_UTC - parsed) == timedelta(0)

    def test_unwritable_state_dir_degrades_silently(self, tmp_path):
        """History bookkeeping must never break a render."""
        blocker = tmp_path / "state"
        blocker.write_text("i am a file, not a directory")
        _save_pressure_sample(str(blocker), 1013.0, NOW_UTC)  # must not raise
        # The blocker is untouched and the read side degrades to "no history".
        assert blocker.read_text() == "i am a file, not a directory"
        assert _load_prev_pressure(str(blocker), NOW_UTC) == (None, None)

    def test_write_leaves_no_temp_files_behind(self, tmp_path):
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)
        leftovers = [p.name for p in tmp_path.iterdir() if p.name != _PRESSURE_FILE]
        assert leftovers == []

    def test_failed_rename_cleans_up_its_temp_file(self, tmp_path, monkeypatch):
        """The write goes through the shared atomic_write_json helper, which
        re-raises; the panel swallows it locally so a render still completes."""
        import src._io as io_module

        def _boom(*args, **kwargs):
            raise OSError("rename failed")

        monkeypatch.setattr(io_module.os, "replace", _boom)
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)  # must not raise
        assert list(tmp_path.iterdir()) == [], "temp file must not be orphaned"

    def test_uses_the_shared_atomic_write_helper(self, tmp_path, monkeypatch):
        """src/_io.py is the sanctioned way to persist JSON state here."""
        import src.render.components.weatherglass_panel as wg

        calls = []
        real = wg.atomic_write_json

        def _spy(path, data, **kwargs):
            calls.append((path, data))
            return real(path, data, **kwargs)

        monkeypatch.setattr(wg, "atomic_write_json", _spy)
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)
        assert len(calls) == 1
        assert calls[0][1]["samples"][0]["hPa"] == 1013.0

    def test_round_trip_through_load(self, tmp_path):
        _save_pressure_sample(str(tmp_path), 1004.0, NOW_UTC - timedelta(hours=6))
        _save_pressure_sample(str(tmp_path), 1013.0, NOW_UTC)
        prev, ts = _load_prev_pressure(str(tmp_path), NOW_UTC)
        assert prev == 1004.0
        assert ts == NOW_UTC - timedelta(hours=6)


# ---------------------------------------------------------------------------
# Dial mapping
# ---------------------------------------------------------------------------


class TestPressureToAngle:
    def test_rising_pressure_sweeps_left_to_right(self):
        assert _pressure_to_angle(950.0) > _pressure_to_angle(1013.0)
        assert _pressure_to_angle(1013.0) > _pressure_to_angle(1050.0)

    def test_stays_in_the_top_hemisphere(self):
        for p in (800.0, 950.0, 1013.0, 1050.0, 1200.0):
            assert 0.0 <= _pressure_to_angle(p) <= 180.0

    def test_clamps_out_of_range_pressures(self):
        """A sensor spike must pin the needle at the rail, not spin it."""
        assert _pressure_to_angle(500.0) == _pressure_to_angle(900.0)
        assert _pressure_to_angle(2000.0) == _pressure_to_angle(1100.0)


class TestFmtClock:
    def test_formats_in_the_supplied_zone(self):
        dt = datetime(2026, 4, 6, 18, 5, tzinfo=timezone.utc)
        assert _fmt_clock(dt, timezone(timedelta(hours=-5))) == "1:05p"

    def test_naive_datetime_is_formatted_as_given(self):
        assert _fmt_clock(datetime(2026, 4, 6, 6, 30), None) == "6:30a"


# ---------------------------------------------------------------------------
# Panel rendering across data shapes
# ---------------------------------------------------------------------------


class TestDrawWeatherglass:
    def _draw(self, data, *, mode="L", **kwargs):
        img, draw = _canvas(mode)
        draw_weatherglass(
            draw,
            data,
            TODAY,
            FIXED_NOW,
            image=img,
            region=ComponentRegion(0, 0, 1600, 960),
            style=_style(mode),
            **kwargs,
        )
        return img

    @pytest.mark.parametrize("units", ["imperial", "metric", "standard"])
    def test_renders_in_every_unit_system(self, units):
        temps = {"imperial": 64.0, "metric": 18.0, "standard": 291.0}[units]
        data = DashboardData(weather=_weather(units=units, current_temp=temps))
        img = self._draw(data)
        assert _marks(img) > 0

    def test_unit_systems_produce_distinct_plates(self):
        """The scale, comfort band and wind label all change with units — if
        two systems hash identically the unit plumbing is not reaching the
        instruments."""
        plates = {}
        for units, temp in (("imperial", 64.0), ("metric", 18.0), ("standard", 291.0)):
            data = DashboardData(weather=_weather(units=units, current_temp=temp))
            plates[units] = self._draw(data).tobytes()
        assert len(set(plates.values())) == 3

    def test_wind_label_matches_the_unit_system(self):
        """mph vs m/s is drawn text, so the plates must differ on it alone."""
        imperial = self._draw(DashboardData(weather=_weather(units="imperial")))
        metric = self._draw(DashboardData(weather=_weather(units="metric")))
        assert imperial.tobytes() != metric.tobytes()

    def test_renders_without_weather(self):
        assert _marks(self._draw(DashboardData())) > 0

    def test_renders_with_every_optional_field_missing(self):
        data = DashboardData(
            weather=_weather(
                feels_like=None,
                wind_speed=None,
                wind_deg=None,
                pressure=None,
                uv_index=None,
                location_name=None,
                units=None,
            )
        )
        assert _marks(self._draw(data)) > 0

    def test_renders_with_air_quality(self):
        data = DashboardData(
            weather=_weather(),
            air_quality=AirQualityData(aqi=142, category="Unhealthy", pm25=52.3),
        )
        assert _marks(self._draw(data)) > 0

    @pytest.mark.parametrize("aqi", [0, 25, 75, 125, 175, 250, 400, 500])
    def test_renders_across_the_aqi_scale(self, aqi):
        """Each AQI band picks a different ring colour."""
        data = DashboardData(
            weather=_weather(),
            air_quality=AirQualityData(aqi=aqi, category="X", pm25=float(aqi) / 4),
        )
        assert _marks(self._draw(data)) > 0

    def test_alert_cartouche_overlays_the_plate(self):
        plain = self._draw(DashboardData(weather=_weather()))
        alerted = self._draw(
            DashboardData(
                weather=_weather(alerts=[WeatherAlert(event="Severe Thunderstorm Warning")])
            )
        )
        assert plain.tobytes() != alerted.tobytes()

    @pytest.mark.parametrize("temp", [-40.0, 0.0, 32.0, 64.0, 85.0, 110.0, 130.0])
    def test_temperatures_beyond_the_scale_clamp(self, temp):
        data = DashboardData(weather=_weather(current_temp=temp))
        assert _marks(self._draw(data)) > 0

    @pytest.mark.parametrize("deg", [0.0, 45.0, 90.0, 180.0, 270.0, 359.0])
    def test_wind_compass_across_the_rose(self, deg):
        data = DashboardData(weather=_weather(wind_deg=deg))
        assert _marks(self._draw(data)) > 0

    @pytest.mark.parametrize("uv", [0.0, 2.0, 5.5, 8.0, 11.0, 15.0])
    def test_uv_bar_across_the_scale(self, uv):
        data = DashboardData(weather=_weather(uv_index=uv))
        assert _marks(self._draw(data)) > 0

    def test_renders_on_rgb_for_inky(self):
        data = DashboardData(weather=_weather())
        assert _marks(self._draw(data, mode="RGB")) > 0

    def test_polar_latitude_renders(self):
        """Svalbard in April has no sunset — the sun arc must still draw."""
        data = DashboardData(weather=_weather())
        assert _marks(self._draw(data, latitude=78.2, longitude=15.6)) > 0

    def test_unset_coordinates_fall_back_to_owm_times(self):
        data = DashboardData(
            weather=_weather(
                sunrise=datetime(2026, 4, 6, 10, 30, tzinfo=timezone.utc),
                sunset=datetime(2026, 4, 6, 23, 15, tzinfo=timezone.utc),
            )
        )
        # Exact (0.0, 0.0) is the project-wide "unset" convention.
        assert _marks(self._draw(data, latitude=0.0, longitude=0.0)) > 0

    # The parametrized sweeps above are deliberate smoke tests (#229 calls
    # them out as such) — they check that every value in a range renders.
    # These companions check the complementary thing: that the range is
    # actually reaching the instrument. A scale that draws identically at
    # every value passes the sweep and is still broken.

    def test_the_aqi_sweep_reaches_the_badge(self):
        plates = {
            aqi: self._draw(
                DashboardData(
                    weather=_weather(),
                    air_quality=AirQualityData(aqi=aqi, category="X", pm25=float(aqi) / 4),
                )
            ).tobytes()
            for aqi in (0, 75, 175, 400)
        }
        assert len(set(plates.values())) > 1, "every AQI band drew the same badge"

    def test_the_temperature_sweep_reaches_the_thermometer(self):
        plates = {
            temp: self._draw(DashboardData(weather=_weather(current_temp=temp))).tobytes()
            for temp in (0.0, 32.0, 64.0, 110.0)
        }
        assert len(set(plates.values())) > 1, "every temperature drew the same column"

    def test_the_wind_sweep_reaches_the_compass(self):
        plates = {
            deg: self._draw(DashboardData(weather=_weather(wind_deg=deg))).tobytes()
            for deg in (0.0, 90.0, 180.0, 270.0)
        }
        assert len(set(plates.values())) == 4, "the compass needle ignores the bearing"

    def test_the_uv_sweep_reaches_the_bar(self):
        plates = {
            uv: self._draw(DashboardData(weather=_weather(uv_index=uv))).tobytes()
            for uv in (0.0, 5.5, 11.0)
        }
        assert len(set(plates.values())) == 3, "the UV bar ignores the index"

    def test_defaults_are_supplied_when_region_and_style_are_omitted(self):
        img, draw = _canvas("L", (800, 480))
        draw_weatherglass(draw, DashboardData(weather=_weather()), TODAY, FIXED_NOW)
        assert _marks(img) > 0


# ---------------------------------------------------------------------------
# Pressure history integration through the panel
# ---------------------------------------------------------------------------


class TestPanelPressureIntegration:
    def _draw_at(self, tmp_path, pressure, now):
        img, draw = _canvas()
        draw_weatherglass(
            draw,
            DashboardData(weather=_weather(pressure=pressure)),
            now.date(),
            now,
            image=img,
            region=ComponentRegion(0, 0, 1600, 960),
            style=_style(),
            state_dir=str(tmp_path),
        )
        return img

    def test_render_records_a_sample(self, tmp_path):
        self._draw_at(tmp_path, 1013.0, NOW_UTC)
        assert _history(tmp_path / _PRESSURE_FILE) == [{"ts": NOW_UTC.isoformat(), "hPa": 1013.0}]

    def test_no_state_dir_writes_nothing(self, tmp_path):
        """--dry-run / --dummy pass state_dir=None so previews never persist."""
        img, draw = _canvas()
        draw_weatherglass(
            draw,
            DashboardData(weather=_weather()),
            TODAY,
            FIXED_NOW,
            image=img,
            region=ComponentRegion(0, 0, 1600, 960),
            style=_style(),
            state_dir=None,
        )
        assert list(tmp_path.iterdir()) == []

    def test_missing_pressure_records_nothing(self, tmp_path):
        self._draw_at(tmp_path, None, NOW_UTC)
        assert not (tmp_path / _PRESSURE_FILE).exists()

    def test_first_render_sees_no_trend(self, tmp_path):
        """The lookup happens before the save, so a cold start must not read
        back the sample it is about to write."""
        with_history = self._draw_at(tmp_path, 1013.0, NOW_UTC)
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        without = self._draw_at(fresh, 1013.0, NOW_UTC)
        assert with_history.tobytes() == without.tobytes()

    @pytest.mark.parametrize(
        "later_pressure,label",
        [(1030.0, "rising"), (995.0, "falling"), (1013.4, "steady")],
    )
    def test_trend_needle_changes_the_plate(self, tmp_path, later_pressure, label):
        """A prior sample in the window must visibly add a trend needle."""
        self._draw_at(tmp_path, 1013.0, NOW_UTC - timedelta(hours=6))
        with_trend = self._draw_at(tmp_path, later_pressure, NOW_UTC)

        fresh = tmp_path / f"fresh_{label}"
        fresh.mkdir()
        without_trend = self._draw_at(fresh, later_pressure, NOW_UTC)
        assert with_trend.tobytes() != without_trend.tobytes()

    def test_rising_and_falling_trends_differ(self, tmp_path):
        """Rising is drawn green / falling blue on Inky — they must not
        collapse to the same plate.

        Both plates render at the *same* current pressure, so the primary
        needle is identical and only the trend needle can account for the
        difference. Seeding different current pressures would let this pass
        on the primary needle alone, even with the trend needle removed.
        """
        current = 1013.0
        rising_dir = tmp_path / "rising"
        falling_dir = tmp_path / "falling"
        for d in (rising_dir, falling_dir):
            d.mkdir()

        # Histories on opposite sides of the same current reading.
        self._draw_at(rising_dir, current - 20.0, NOW_UTC - timedelta(hours=6))
        self._draw_at(falling_dir, current + 20.0, NOW_UTC - timedelta(hours=6))

        rising = self._draw_at(rising_dir, current, NOW_UTC)
        falling = self._draw_at(falling_dir, current, NOW_UTC)
        assert rising.tobytes() != falling.tobytes()

    def test_steady_trend_differs_from_a_moving_one(self, tmp_path):
        """A delta inside ±1.0 hPa reads as steady and takes the ink colour
        rather than the rising/falling accent."""
        current = 1013.0
        steady_dir = tmp_path / "steady"
        moving_dir = tmp_path / "moving"
        for d in (steady_dir, moving_dir):
            d.mkdir()

        self._draw_at(steady_dir, current - 0.5, NOW_UTC - timedelta(hours=6))
        self._draw_at(moving_dir, current - 20.0, NOW_UTC - timedelta(hours=6))

        steady = self._draw_at(steady_dir, current, NOW_UTC)
        moving = self._draw_at(moving_dir, current, NOW_UTC)
        assert steady.tobytes() != moving.tobytes()

    def test_repeated_ticks_do_not_grow_the_history(self, tmp_path):
        """The default timer fires every 5 minutes."""
        for minute in range(0, 30, 5):
            self._draw_at(tmp_path, 1013.0, NOW_UTC + timedelta(minutes=minute))
        assert len(_history(tmp_path / _PRESSURE_FILE)) == 1


# ---------------------------------------------------------------------------
# Full-theme rendering
# ---------------------------------------------------------------------------


class TestWeatherglassTheme:
    def test_renders_end_to_end(self):
        img = _render()
        assert img.size == (800, 480)
        assert _marks(img) > 0

    def test_render_is_deterministic(self):
        assert _render().tobytes() == _render().tobytes()

    def test_dry_run_render_persists_no_state(self, tmp_path):
        """render_dashboard defaults state_dir to None."""
        _render()
        assert list(tmp_path.iterdir()) == []
