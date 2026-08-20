"""Shared quote store for the panels that show a daily quote.

Four panels — info, tides, scorecard, moonphase — each used to carry their own
copy of the quotes path, the bundled fallback list, and the stable bucket-hash
selection. The path was hardcoded four times over, which also made it
unconfigurable: a user who customised ``config/quotes.json`` on the Pi had it
overwritten by the next ``make deploy``.

Selection is deliberately unchanged. The bucket key is
``<prefix><date>[-bucket]`` hashed with MD5 and taken modulo the store size, so
the same slot always maps to the same quote and repeats are possible. Each
panel keeps its own *prefix* (``"tides-"``, ``"scorecard-"``, ``"moonphase-"``,
and the empty prefix for the info panel) so two panels on the same plate do not
show the same quote on the same day.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Bundled store. Read at call time rather than captured at import, so tests and
# the ``quotes.path`` config option can both redirect it.
DEFAULT_QUOTES_PATH = Path(__file__).parent.parent.parent / "config" / "quotes.json"

# Used only when the store is missing, unreadable, or empty — an install error
# rather than a normal state. Enough entries that the panels' distinct key
# prefixes still separate them.
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


def bucket_key(
    today: date,
    refresh: str = "daily",
    now: datetime | None = None,
    prefix: str = "",
) -> str:
    """Build the stable selection key for *today* under a refresh cadence.

    *refresh* controls the time bucket:

    - ``"daily"``       — one quote per calendar day (default)
    - ``"twice_daily"`` — flips at noon; ``"am"`` before 12:00, ``"pm"`` after
    - ``"hourly"``      — a new quote each clock hour

    *now* is read only for the two sub-daily cadences and defaults to the
    current local time; it is a parameter so tests can pin it.
    """
    if refresh == "hourly":
        dt = now if now is not None else datetime.now()  # allow-naive-datetime — hour bucket only
        return f"{prefix}{today.isoformat()}T{dt.hour:02d}"
    if refresh == "twice_daily":
        dt = now if now is not None else datetime.now()  # allow-naive-datetime — am/pm bucket only
        period = "am" if dt.hour < 12 else "pm"
        return f"{prefix}{today.isoformat()}-{period}"
    return f"{prefix}{today.isoformat()}"


def _usable(entry: object) -> bool:
    """True when *entry* is a quote the panels can actually draw.

    Panels index ``["text"]`` and ``["author"]`` directly, so a bare string or
    a mapping missing either key raises out of the render — which would make a
    hand-edited quote store the one config mistake that takes down the whole
    dashboard. Both keys must be present and stringy.
    """
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("text"), str)
        and isinstance(entry.get("author"), str)
    )


def load_quotes(path: Path) -> list[dict]:
    """Read the quote store at *path*, falling back to the bundled list.

    A missing file, malformed JSON, a valid-but-empty list, or a list with no
    usable entries all fall back: an empty store would make the modulo in
    :func:`_select` divide by zero, and an unusable entry would raise out of
    whichever panel happened to select it.

    Usable entries are kept even when some of their neighbours are dropped —
    a single typo in a long hand-written store should cost that one quote, not
    the whole file.
    """
    if not path.exists():
        return DEFAULT_QUOTES
    try:
        quotes = json.loads(path.read_text())
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        logger.warning("Could not read quotes from %s: %s", path, exc)
        return DEFAULT_QUOTES
    if not isinstance(quotes, list) or not quotes:
        logger.warning("Quote store at %s is empty or not a list; using defaults", path)
        return DEFAULT_QUOTES

    usable = [entry for entry in quotes if _usable(entry)]
    if not usable:
        logger.warning(
            "Quote store at %s has no usable {text, author} entries; using defaults", path
        )
        return DEFAULT_QUOTES
    if len(usable) != len(quotes):
        logger.warning(
            "Quote store at %s: skipped %d entr%s without a string 'text' and 'author'",
            path,
            len(quotes) - len(usable),
            "y" if len(quotes) - len(usable) == 1 else "ies",
        )
    return usable


@lru_cache(maxsize=128)
def _select(key: str, path_str: str) -> dict:
    """Pick the quote for *key* from the store at *path_str*.

    Cached on both arguments: keying on the bucket alone would serve one
    panel's quote from another store after the path changed under it.
    """
    quotes = load_quotes(Path(path_str))
    day_hash = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return quotes[day_hash % len(quotes)]


def quote_for(
    today: date,
    *,
    refresh: str = "daily",
    now: datetime | None = None,
    prefix: str = "",
    path: str | Path | None = None,
) -> dict:
    """Return this panel's quote for *today*.

    *path* overrides the bundled store (from ``quotes.path`` in config); an
    empty or absent value uses :data:`DEFAULT_QUOTES_PATH`.
    """
    resolved = Path(path) if path else DEFAULT_QUOTES_PATH
    return _select(bucket_key(today, refresh, now, prefix), str(resolved))


def cache_clear() -> None:
    """Flush the selection cache — for tests that swap the store mid-run."""
    _select.cache_clear()
