import json
import hashlib
from datetime import date
from functools import lru_cache
from pathlib import Path
from PIL import ImageDraw

from src.render import layout as L
from src.render.primitives import hline, draw_text_wrapped, wrap_lines
from src.render.theme import ComponentRegion, ThemeStyle

QUOTES_FILE = Path(__file__).parent.parent.parent.parent / "config" / "quotes.json"

DEFAULT_QUOTES = [
    {
        "text": "The best time to plant a tree was 20 years ago. The second best time is now.",
        "author": "Chinese Proverb",
    },
    {"text": "Do what you can, with what you have, where you are.", "author": "Theodore Roosevelt"},
    {"text": "It is not the mountain we conquer, but ourselves.", "author": "Edmund Hillary"},
    {"text": "The only way to do great work is to love what you do.", "author": "Steve Jobs"},
    {"text": "Simplicity is the ultimate sophistication.", "author": "Leonardo da Vinci"},
    {"text": "Well done is better than well said.", "author": "Benjamin Franklin"},
    {"text": "In the middle of difficulty lies opportunity.", "author": "Albert Einstein"},
    {"text": "Be yourself; everyone else is already taken.", "author": "Oscar Wilde"},
    {"text": "Not all those who wander are lost.", "author": "J.R.R. Tolkien"},
    {"text": "The journey of a thousand miles begins with one step.", "author": "Lao Tzu"},
    {"text": "What we think, we become.", "author": "Buddha"},
    {"text": "Happiness depends upon ourselves.", "author": "Aristotle"},
    {"text": "Turn your wounds into wisdom.", "author": "Oprah Winfrey"},
    {"text": "Act as if what you do makes a difference. It does.", "author": "William James"},
    {"text": "Everything you can imagine is real.", "author": "Pablo Picasso"},
    {"text": "Whatever you are, be a good one.", "author": "Abraham Lincoln"},
    {"text": "The best revenge is massive success.", "author": "Frank Sinatra"},
    {"text": "Life shrinks or expands in proportion to one's courage.", "author": "Anais Nin"},
    {"text": "It always seems impossible until it's done.", "author": "Nelson Mandela"},
    {"text": "Strive not to be a success, but rather to be of value.", "author": "Albert Einstein"},
    {"text": "Stay hungry, stay foolish.", "author": "Stewart Brand"},
    {"text": "The mind is everything. What you think you become.", "author": "Buddha"},
    {"text": "An unexamined life is not worth living.", "author": "Socrates"},
    {"text": "Dwell on the beauty of life.", "author": "Marcus Aurelius"},
    {"text": "We suffer more often in imagination than in reality.", "author": "Seneca"},
    {"text": "No pressure, no diamonds.", "author": "Thomas Carlyle"},
    {
        "text": "What lies behind us and what lies before us are tiny matters"
                " compared to what lies within us.",
        "author": "Ralph Waldo Emerson",
    },
    {"text": "The purpose of our lives is to be happy.", "author": "Dalai Lama"},
    {"text": "You must be the change you wish to see in the world.", "author": "Mahatma Gandhi"},
    {"text": "Life is what happens when you're busy making other plans.", "author": "John Lennon"},
    {"text": "Get busy living or get busy dying.", "author": "Stephen King"},
]


@lru_cache(maxsize=1)
def _quote_for_today(today: date) -> dict:
    """Deterministically pick a quote based on the date."""
    if QUOTES_FILE.exists():
        try:
            quotes = json.loads(QUOTES_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            quotes = DEFAULT_QUOTES
    else:
        quotes = DEFAULT_QUOTES

    # Hash the date so it rotates daily but is stable within a day
    day_hash = int(hashlib.md5(today.isoformat().encode()).hexdigest(), 16)
    return quotes[day_hash % len(quotes)]


def _count_lines(text: str, font, max_width: int) -> int:
    """Count lines produced by word-wrapping text at max_width (no drawing)."""
    return len(wrap_lines(text, font, max_width))


def draw_info(
    draw: ImageDraw.ImageDraw,
    today: date,
    *,
    region: ComponentRegion | None = None,
    style: ThemeStyle | None = None,
):
    if region is None:
        region = ComponentRegion(L.INFO_X, L.INFO_Y, L.INFO_W, L.INFO_H)
    if style is None:
        style = ThemeStyle()

    x0 = region.x
    y0 = region.y
    w = region.w
    h = region.h
    pad = L.PAD

    # Top border (2px for stronger section separation)
    if style.show_borders:
        hline(draw, y0, x0, x0 + w, fill=style.fg)
        hline(draw, y0 + 1, x0, x0 + w, fill=style.fg)

    # Section label
    label_font = style.label_font()
    info_label = style.component_labels.get("info", "QUOTE OF THE DAY")
    draw.text((x0 + pad, y0 + pad), info_label, font=label_font, fill=style.fg)

    quote = _quote_for_today(today)

    # Quote text — adapt font size so long quotes fit without truncation
    text = f'"{quote["text"]}"'
    y = y0 + 28
    max_width = w - pad * 2

    _quote_fn = style.font_quote if style.font_quote is not None else style.font_regular
    quote_font = _quote_fn(14)
    if _count_lines(text, quote_font, max_width) > 3:
        quote_font = _quote_fn(12)
        max_lines = 4
    else:
        max_lines = 3

    used_h = draw_text_wrapped(
        draw, (x0 + pad, y), text, quote_font,
        max_width, max_lines=max_lines, line_spacing=3, fill=style.fg,
    )

    # Attribution
    _author_fn = style.font_quote_author if style.font_quote_author is not None else style.font_regular
    author_font = _author_fn(12)
    attr_y = y + used_h + 6
    if attr_y + 16 < y0 + h:
        draw.text((x0 + pad, attr_y), f'— {quote["author"]}', font=author_font, fill=style.fg)
