"""Built-in dashboard themes.

Importing this package triggers registration of every built-in theme into
``src.render.themes.registry`` as a side effect. ``src.render.theme`` calls
``import src.render.themes`` lazily inside :func:`load_theme` and friends so
the registrations happen before any consumer reads the registry.
"""

from __future__ import annotations

# Side-effect imports populate the theme registry. Order is not significant.
from src.render.themes import agenda as _agenda  # noqa: F401
from src.render.themes import air_quality as _air_quality  # noqa: F401
from src.render.themes import astronomy as _astronomy  # noqa: F401
from src.render.themes import countdown as _countdown  # noqa: F401
from src.render.themes import diags as _diags  # noqa: F401
from src.render.themes import fantasy as _fantasy  # noqa: F401
from src.render.themes import fuzzyclock as _fuzzyclock  # noqa: F401
from src.render.themes import fuzzyclock_invert as _fuzzyclock_invert  # noqa: F401
from src.render.themes import light_cycle as _light_cycle  # noqa: F401
from src.render.themes import message as _message  # noqa: F401
from src.render.themes import minimalist as _minimalist  # noqa: F401
from src.render.themes import monthly as _monthly  # noqa: F401
from src.render.themes import moonphase as _moonphase  # noqa: F401
from src.render.themes import moonphase_invert as _moonphase_invert  # noqa: F401
from src.render.themes import old_fashioned as _old_fashioned  # noqa: F401
from src.render.themes import photo as _photo  # noqa: F401
from src.render.themes import qotd as _qotd  # noqa: F401
from src.render.themes import qotd_invert as _qotd_invert  # noqa: F401
from src.render.themes import scorecard as _scorecard  # noqa: F401
from src.render.themes import sunrise as _sunrise  # noqa: F401
from src.render.themes import terminal as _terminal  # noqa: F401
from src.render.themes import tides as _tides  # noqa: F401
from src.render.themes import timeline as _timeline  # noqa: F401
from src.render.themes import today as _today  # noqa: F401
from src.render.themes import weather as _weather  # noqa: F401
from src.render.themes import year_pulse as _year_pulse  # noqa: F401
