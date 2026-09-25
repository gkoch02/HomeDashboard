"""Tests for src/render/components/message_panel.py.

Assertion discipline (see #229)
-------------------------------
The smoke tests here asserted ``img.getbbox() is not None`` on a mode-``"1"``
plate filled with 1, where every pixel is non-zero and getbbox can never
return None. 10 of the 14 tests passed with ``draw_message`` stubbed to a
no-op.

Ink means **zero-valued** pixels. The typography measure is
``_text_line_heights``: one band of ink per rendered line, whose height
tracks the chosen font size — which is how the responsive size-selection
loop, and its size-20 fallback, become things a test can check rather than
describe.
"""

from PIL import Image, ImageDraw

from src.render.components.message_panel import draw_message
from src.render.quantize import flatten_pixels
from src.render.theme import ComponentRegion, ThemeStyle


def _make_draw(w: int = 800, h: int = 400):
    img = Image.new("1", (w, h), 1)
    return img, ImageDraw.Draw(img)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Ink measurement
# ---------------------------------------------------------------------------

BOX = (0, 0, 800, 400)


def _ink(img: Image.Image, box: tuple[int, int, int, int] = BOX) -> int:
    """Count ink (value-0) pixels inside *box*."""
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[y * width + x] == 0)


def _text_line_heights(img: Image.Image, box: tuple[int, int, int, int] = BOX, min_h: int = 3):
    """Heights of the horizontal bands of ink inside *box*.

    One band per rendered line; each band's height tracks the font size.
    """
    px = flatten_pixels(img)
    width = img.width
    x0, y0, x1, y1 = box
    hot = [any(px[y * width + x] == 0 for x in range(x0, x1)) for y in range(y0, y1)]
    runs = []
    start = None
    for i, is_hot in enumerate(hot):
        if is_hot and start is None:
            start = i
        elif not is_hot and start is not None:
            if i - start >= min_h:
                runs.append(i - start)
            start = None
    if start is not None and len(hot) - start >= min_h:
        runs.append(len(hot) - start)
    return runs


def _render(message: str, **kwargs) -> Image.Image:
    img, draw = _make_draw()
    draw_message(draw, message, **kwargs)
    return img


_LONG = " ".join(["extraordinary"] * 40)


class TestDrawMessageSmoke:
    def test_smoke_short_message(self):
        """A short message is drawn, on few lines."""
        img = _render("Hello")
        assert _ink(img) > 0
        assert len(_text_line_heights(img)) <= 3

    def test_smoke_default_args(self):
        """region=None/style=None fill in the documented defaults."""
        explicit = _render("Hello", region=ComponentRegion(0, 0, 800, 400), style=ThemeStyle())
        assert _render("Hello").tobytes() == explicit.tobytes()

    def test_smoke_custom_region(self):
        """A smaller region keeps the text inside it."""
        region = ComponentRegion(0, 0, 400, 200)
        img = _render("Hello", region=region)
        assert _ink(img, (0, 0, 400, 200)) > 0
        assert _ink(img, (400, 0, 800, 400)) == 0, "text escaped a 400px-wide region"

    def test_smoke_small_region_does_not_crash(self):
        """A region too small for any candidate size still draws via the fallback."""
        img = _render("Hello", region=ComponentRegion(0, 0, 120, 50))
        assert _ink(img, (0, 0, 120, 60)) > 0, "the fallback path drew nothing"

    def test_smoke_custom_style(self):
        """An inverted style is not the same plate as the default."""
        assert (
            _render("Hello", style=ThemeStyle(fg=1, bg=0)).tobytes() != _render("Hello").tobytes()
        )

    def test_empty_string_shows_placeholder(self):
        """An empty message falls back to the placeholder, not a blank plate."""
        empty = _render("")
        assert _ink(empty) > 0
        assert _ink(empty) != _ink(_render("Hello")), "the placeholder is not distinguishable"

    def test_whitespace_only_shows_placeholder(self):
        """Whitespace is stripped first, so it takes the same path as empty."""
        assert _render("   ").tobytes() == _render("").tobytes()

    def test_empty_and_nonempty_differ(self):
        assert _render("").tobytes() != _render("Real message").tobytes()

    def test_very_long_message_wraps_to_many_lines(self):
        """A 40-word message wraps rather than being dropped or set on one line."""
        img = _render(_LONG)
        lines = _text_line_heights(img)
        assert len(lines) > 3, f"a 40-word message did not wrap: {lines}"
        assert len(lines) > len(_text_line_heights(_render("Hello")))

    def test_short_messages_are_set_larger_than_long_ones(self):
        """The size-selection loop picks the largest size that fits.

        Font size shows up as the height of each band of ink, so the short
        message's tallest band must beat the long one's. The old version of
        this test only compared plate bytes, which differ for any reason.
        """
        short_lines = _text_line_heights(_render("Hello"))
        long_lines = _text_line_heights(_render(_LONG))
        assert max(short_lines) > max(long_lines), (
            f"short message not set larger: {max(short_lines)} vs {max(long_lines)}"
        )
        assert len(short_lines) < len(long_lines)

    def test_narrow_region_stays_inside_itself(self):
        """Even a region narrower than one word keeps its text inside.

        This used to document the opposite: ``_wrap_lines`` never broke inside
        a word, so any word wider than ``max_w`` ran past the region edge
        (2475 px of overflow at w=60). ``wrap_lines`` now breaks an over-wide
        word by character (#288), so the only thing left that can push text
        out is the hardcoded 52 px ``h_pad`` — and at these widths it doesn't.
        """
        text = "Hello world this is a longer message"
        for w in (60, 120, 200, 300):
            img = _render(text, region=ComponentRegion(0, 0, w, 400))
            assert _ink(img, (0, 0, w, 400)) > 0, f"nothing drawn at all at w={w}"
            assert _ink(img, (w, 0, 800, 400)) == 0, f"text overflowed the region at w={w}"
        assert _ink(_render(text, region=ComponentRegion(0, 0, 300, 400)), (300, 0, 800, 400)) == 0

    def test_unfittable_message_uses_size_20_fallback(self):
        """Too tall at every candidate size → the size-20, 8-line fallback.

        Checked by the cap rather than by "it rendered": the fallback slices
        to 8 lines, so a message long enough to wrap past that draws the same
        as one much longer still.
        """
        region = ComponentRegion(0, 0, 200, 60)
        forty = _render(_LONG, region=region)
        eighty = _render(" ".join(["extraordinary"] * 80), region=region)
        assert _ink(forty, (0, 0, 200, 400)) > 0, "the fallback drew nothing"
        assert _ink(forty, (0, 0, 200, 400)) == _ink(eighty, (0, 0, 200, 400)), (
            "the 8-line fallback cap is not being applied"
        )


# ---------------------------------------------------------------------------
# Decorative quotation marks
# ---------------------------------------------------------------------------


class TestDrawMessageQuoteMarks:
    def test_quote_marks_frame_the_text_block(self):
        """The marks sit outside the text's own column, one high and one low."""
        img = _render("Short")
        bands = _text_line_heights(img)
        assert len(bands) >= 2, f"expected a mark band and a text band: {bands}"

    def test_with_and_without_message_differ(self):
        assert (
            _render("Short").tobytes()
            != _render("A completely different and longer piece of text here").tobytes()
        )


# ---------------------------------------------------------------------------
# Region / style respected
# ---------------------------------------------------------------------------


class TestDrawMessageRegionStyle:
    def test_different_regions_produce_different_output(self):
        """An offset region moves the content rather than being ignored."""
        at_origin = _render("Same text", region=ComponentRegion(0, 0, 800, 400))
        offset = _render("Same text", region=ComponentRegion(200, 100, 400, 200))
        assert at_origin.tobytes() != offset.tobytes()
        assert _ink(offset, (0, 0, 200, 400)) == 0, "content ignored the region x offset"
