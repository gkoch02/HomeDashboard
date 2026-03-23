"""Tests for src/render/components/fuzzyclock_panel.py."""

from datetime import datetime

import pytest
from PIL import Image, ImageDraw

from src.render.components.fuzzyclock_panel import draw_fuzzyclock, fuzzy_time
from src.render.theme import ComponentRegion, ThemeStyle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draw(w: int = 800, h: int = 480):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 3, 23, hour, minute)


# ---------------------------------------------------------------------------
# fuzzy_time — all 12 buckets
# ---------------------------------------------------------------------------

class TestFuzzyTime:
    # Bucket :00
    def test_on_the_hour(self):
        assert fuzzy_time(_dt(7, 0)) == "seven o'clock"

    def test_rounds_down_to_hour(self):
        assert fuzzy_time(_dt(7, 2)) == "seven o'clock"

    # Bucket :05
    def test_five_past(self):
        assert fuzzy_time(_dt(7, 5)) == "five past seven"

    def test_rounds_to_five_past(self):
        assert fuzzy_time(_dt(7, 6)) == "five past seven"

    # Bucket :10
    def test_ten_past(self):
        assert fuzzy_time(_dt(7, 10)) == "ten past seven"

    # Bucket :15
    def test_quarter_past(self):
        assert fuzzy_time(_dt(7, 15)) == "quarter past seven"

    # Bucket :20
    def test_twenty_past(self):
        assert fuzzy_time(_dt(7, 20)) == "twenty past seven"

    # Bucket :25
    def test_twenty_five_past(self):
        assert fuzzy_time(_dt(7, 25)) == "twenty five past seven"

    # Bucket :30
    def test_half_past(self):
        assert fuzzy_time(_dt(7, 30)) == "half past seven"

    # Bucket :35
    def test_twenty_five_to(self):
        assert fuzzy_time(_dt(7, 35)) == "twenty five to eight"

    # Bucket :40
    def test_twenty_to(self):
        assert fuzzy_time(_dt(7, 40)) == "twenty to eight"

    # Bucket :45
    def test_quarter_to(self):
        assert fuzzy_time(_dt(7, 45)) == "quarter to eight"

    # Bucket :50
    def test_ten_to(self):
        assert fuzzy_time(_dt(7, 50)) == "ten to eight"

    # Bucket :55
    def test_five_to(self):
        assert fuzzy_time(_dt(7, 55)) == "five to eight"

    # ---------------------------------------------------------------------------
    # Special labels
    # ---------------------------------------------------------------------------

    def test_midnight_exact(self):
        assert fuzzy_time(_dt(0, 0)) == "midnight"

    def test_midnight_rounds_to(self):
        assert fuzzy_time(_dt(0, 2)) == "midnight"

    def test_noon_exact(self):
        assert fuzzy_time(_dt(12, 0)) == "noon"

    def test_noon_rounds_to(self):
        assert fuzzy_time(_dt(12, 1)) == "noon"

    # ---------------------------------------------------------------------------
    # Hour roll-over at bucket :55
    # ---------------------------------------------------------------------------

    def test_five_to_noon(self):
        assert fuzzy_time(_dt(11, 55)) == "five to twelve"

    def test_five_to_one_am(self):
        assert fuzzy_time(_dt(0, 55)) == "five to one"

    def test_five_to_midnight(self):
        # 23:57 rounds to :55 bucket → "five to twelve" (the :58 boundary triggers midnight)
        assert fuzzy_time(_dt(23, 57)) == "five to twelve"

    # ---------------------------------------------------------------------------
    # PM hours (12-hour conversion)
    # ---------------------------------------------------------------------------

    def test_pm_hour(self):
        assert fuzzy_time(_dt(19, 30)) == "half past seven"

    def test_one_pm(self):
        assert fuzzy_time(_dt(13, 15)) == "quarter past one"

    # ---------------------------------------------------------------------------
    # Rounding edge cases
    # ---------------------------------------------------------------------------

    def test_rounds_up_at_boundary(self):
        # 7:57 → nearest 5-min = 55 → "five to eight"
        assert fuzzy_time(_dt(7, 57)) == "five to eight"

    def test_rounds_up_crosses_hour(self):
        # 7:58 → nearest 5-min = 60 → rolls over to 8:00 → "eight o'clock"
        assert fuzzy_time(_dt(7, 58)) == "eight o'clock"

    def test_twelve_oclock_am(self):
        # 0:03 rounds to bucket :05 → "five past twelve" (only :00–:02 gives midnight)
        assert fuzzy_time(datetime(2026, 3, 23, 0, 3)) == "five past twelve"

    def test_twelve_oclock_pm(self):
        # 12:03 rounds to bucket :05 → "five past twelve" (only :00–:02 gives noon)
        assert fuzzy_time(datetime(2026, 3, 23, 12, 3)) == "five past twelve"


# ---------------------------------------------------------------------------
# draw_fuzzyclock — smoke tests
# ---------------------------------------------------------------------------

class TestDrawFuzzyclock:
    def test_smoke_default_region(self):
        img, draw = _make_draw()
        result = draw_fuzzyclock(draw, _dt(7, 30))
        assert result is None  # pure side-effect function

    def test_smoke_custom_region(self):
        img, draw = _make_draw()
        region = ComponentRegion(0, 0, 800, 400)
        draw_fuzzyclock(draw, _dt(12, 0), region=region)

    def test_smoke_with_style(self):
        img, draw = _make_draw()
        style = ThemeStyle(fg=0, bg=1)
        draw_fuzzyclock(draw, _dt(23, 45), style=style)

    def test_smoke_midnight(self):
        img, draw = _make_draw()
        draw_fuzzyclock(draw, _dt(0, 0))

    def test_smoke_noon(self):
        img, draw = _make_draw()
        draw_fuzzyclock(draw, _dt(12, 0))

    def test_smoke_small_region(self):
        """Should not crash even in a very small region."""
        img, draw = _make_draw(400, 200)
        region = ComponentRegion(0, 0, 400, 200)
        draw_fuzzyclock(draw, _dt(9, 15), region=region)

    def test_long_phrase_fits(self):
        """'twenty five past eleven' is among the longest phrases — must not crash."""
        img, draw = _make_draw()
        draw_fuzzyclock(draw, _dt(11, 25))
