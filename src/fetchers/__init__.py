"""Built-in data fetchers.

Importing this package triggers registration of every built-in fetcher into
``src.fetchers.registry`` as a side effect. Code that only uses
``save_source`` / ``load_cached_source`` from ``src.fetchers.cache`` will
still see a fully-populated registry because importing the submodule runs
this ``__init__`` first.
"""

from __future__ import annotations

# Side-effect imports populate the fetcher registry. Order is not significant.
from src.fetchers import calendar as _calendar  # noqa: F401
from src.fetchers import purpleair as _purpleair  # noqa: F401
from src.fetchers import weather as _weather  # noqa: F401
