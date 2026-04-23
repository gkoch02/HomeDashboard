"""Tests for src/render/components/message_panel.py."""

from PIL import Image, ImageDraw

from src.render.components.message_panel import draw_message
from src.render.theme import ComponentRegion, ThemeStyle


def _make_draw(w: int = 800, h: int = 400):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


class TestDrawMessageSmoke:
    def test_smoke_short_message(self):
        img, draw = _make_draw()
        draw_message(draw, "Hello, world!")
        assert img.getbbox() is not None

    def test_smoke_default_args(self):
        img, draw = _make_draw()
        draw_message(draw, "Test message")
        # Should not raise and should produce output
        assert img.getbbox() is not None

    def test_smoke_custom_region(self):
        img, draw = _make_draw()
        region = ComponentRegion(0, 0, 800, 400)
        draw_message(draw, "Custom region", region=region)
        assert img.getbbox() is not None

    def test_smoke_small_region_does_not_crash(self):
        img, draw = _make_draw()
        region = ComponentRegion(100, 100, 200, 100)
        draw_message(draw, "Tiny region", region=region)
        assert img.getbbox() is not None

    def test_smoke_custom_style(self):
        img, draw = _make_draw()
        style = ThemeStyle()
        draw_message(draw, "Custom style", style=style)
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# Empty / whitespace message
# ---------------------------------------------------------------------------


class TestDrawMessageEmpty:
    def test_empty_string_shows_placeholder(self):
        img, draw = _make_draw()
        draw_message(draw, "")
        # "(no message)" placeholder should produce pixels
        assert img.getbbox() is not None

    def test_whitespace_only_shows_placeholder(self):
        img, draw = _make_draw()
        draw_message(draw, "   \t\n  ")
        assert img.getbbox() is not None

    def test_empty_and_nonempty_differ(self):
        img_empty, draw_empty = _make_draw()
        draw_message(draw_empty, "")

        img_text, draw_text = _make_draw()
        draw_message(draw_text, "A real message")

        assert img_empty.tobytes() != img_text.tobytes()


# ---------------------------------------------------------------------------
# Font-size fitting algorithm
# ---------------------------------------------------------------------------


class TestDrawMessageFontSizing:
    def test_very_long_message_does_not_crash(self):
        """Extremely long message should hit the size-20 fallback without raising."""
        long_msg = " ".join(["extraordinary"] * 60)
        img, draw = _make_draw()
        draw_message(draw, long_msg)
        assert img.getbbox() is not None

    def test_short_and_long_messages_differ(self):
        """Short message (large font) and long message (small font) render differently."""
        img_short, draw_short = _make_draw()
        draw_message(draw_short, "Hi")

        img_long, draw_long = _make_draw()
        draw_message(draw_long, " ".join(["word"] * 50))

        assert img_short.tobytes() != img_long.tobytes()

    def test_narrow_region_falls_back_gracefully(self):
        """Very narrow region should not crash even when wrapping fails."""
        img, draw = _make_draw(800, 400)
        region = ComponentRegion(0, 0, 60, 400)
        draw_message(draw, "Hello world this is a longer message", region=region)
        assert img.getbbox() is not None

    def test_unfittable_message_uses_size_20_fallback(self):
        """Message too tall even at the smallest size → size-20 fallback path.

        A very short region (below two lines at size 20) combined with a long,
        wrapping message forces the ``if not best_lines`` fallback to run.
        """
        img, draw = _make_draw(800, 200)
        # Narrow + short region: vertical budget < one-line height at size 20,
        # so no size in the loop fits and the fallback limits to 8 lines.
        region = ComponentRegion(0, 0, 200, 60)
        long_msg = " ".join(["extraordinary"] * 40)
        draw_message(draw, long_msg, region=region)
        # We only care that the call completes and produces pixels; the exact
        # wrap count isn't asserted because it depends on font metrics.
        assert img.getbbox() is not None


# ---------------------------------------------------------------------------
# Decorative quotation marks
# ---------------------------------------------------------------------------


class TestDrawMessageQuoteMarks:
    def test_with_and_without_message_differ(self):
        """Two different messages should produce different output (quote marks shift)."""
        img_a, draw_a = _make_draw()
        draw_message(draw_a, "Short")

        img_b, draw_b = _make_draw()
        draw_message(draw_b, "A completely different and longer piece of text here")

        assert img_a.tobytes() != img_b.tobytes()


# ---------------------------------------------------------------------------
# Region / style respected
# ---------------------------------------------------------------------------


class TestDrawMessageRegionStyle:
    def test_different_regions_produce_different_output(self):
        img_a, draw_a = _make_draw()
        draw_message(draw_a, "Same text", region=ComponentRegion(0, 0, 800, 400))

        img_b, draw_b = _make_draw()
        draw_message(draw_b, "Same text", region=ComponentRegion(200, 100, 400, 200))

        assert img_a.tobytes() != img_b.tobytes()
