"""Theme system for the eInk dashboard.

A theme is composed of two objects:
- ``ThemeStyle``: visual properties (fg/bg colors, inversion flags, fonts, spacing).
- ``ThemeLayout``: structural layout (canvas size, per-component bounding boxes,
  component draw order).

Together they are wrapped in a ``Theme`` dataclass.

Usage::

    from src.render.theme import load_theme
    theme = load_theme("default")
    image = render_dashboard(data, config, theme=theme)

Adding a new theme requires only two steps:
1. Create ``src/render/themes/<name>.py`` with a ``<name>_theme() -> Theme`` factory.
2. Register the name in ``load_theme()`` below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont

FontCallable = Callable[[int], "ImageFont.FreeTypeFont"]


@dataclass
class ComponentRegion:
    """Bounding box for a single component on the canvas."""
    x: int
    y: int
    w: int
    h: int
    visible: bool = True


@dataclass
class ThemeLayout:
    """Full canvas structure: size, per-component bounding boxes, and draw order."""
    canvas_w: int = 800
    canvas_h: int = 480
    header: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 40)
    )
    week_view: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 40, 800, 320)
    )
    weather: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 360, 300, 120)
    )
    birthdays: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(300, 360, 250, 120)
    )
    info: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(550, 360, 250, 120)
    )
    today_view: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 60, 800, 280, visible=False)
    )
    # Used by the ``qotd`` theme for the full-canvas centered quote area.
    # Hidden by default so existing themes are not affected.
    qotd: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 400, visible=False)
    )
    # Used by the ``weather`` theme for the full-screen weather display.
    # Hidden by default so existing themes are not affected.
    weather_full: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``fuzzyclock`` theme for the full-canvas clock face area.
    # Hidden by default so existing themes are not affected.
    fuzzyclock: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 400, visible=False)
    )
    # Used by the ``diags`` theme for the full-canvas diagnostics readout.
    # Hidden by default so existing themes are not affected.
    diags: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    # Used by the ``air_quality`` theme for the full-screen air quality display.
    # Hidden by default so existing themes are not affected.
    air_quality_full: ComponentRegion = field(
        default_factory=lambda: ComponentRegion(0, 0, 800, 480, visible=False)
    )
    draw_order: list[str] = field(
        default_factory=lambda: ["header", "week_view", "weather", "birthdays", "info"]
    )
    # Optional overlay function called after all components are drawn.
    # Signature: (draw, layout, style) -> None.  Use for theme-specific decorations
    # such as ornamental borders that must render on top of all components.
    overlay_fn: "Callable[[ImageDraw.ImageDraw, ThemeLayout, ThemeStyle], None] | None" = field(
        default=None, repr=False
    )


@dataclass
class ThemeStyle:
    """Visual style: fg/bg colors, inversion policy, font callables, spacing density.

    Font callables default to Plus Jakarta Sans (the bundled default fonts)
    when left as ``None``, via ``__post_init__``.
    """
    # 1-bit color values: 0 = BLACK, 1 = WHITE
    fg: int = 0
    bg: int = 1

    # Which regions use inverted color (fg fill + bg text)
    invert_header: bool = True
    invert_today_col: bool = True
    invert_allday_bars: bool = True

    # Font callables — each takes a size (int) and returns a FreeTypeFont.
    # None triggers automatic default-font assignment in __post_init__.
    font_regular: FontCallable | None = None
    font_medium: FontCallable | None = None
    font_semibold: FontCallable | None = None
    font_bold: FontCallable | None = None
    # Optional overrides for specific large display elements in the week view.
    # Falls back to font_bold when None.
    font_date_number: FontCallable | None = None  # large today date numeral
    font_month_title: FontCallable | None = None  # large month name band
    font_title: FontCallable | None = None  # dashboard title + day column headers
    font_section_label: FontCallable | None = None  # WEATHER / BIRTHDAYS / QUOTE OF THE DAY
    font_quote: FontCallable | None = None   # quote body text
    font_quote_author: FontCallable | None = None  # quote attribution line

    # Event spacing multiplier (applied in _fonts_for_tier)
    spacing_scale: float = 1.0

    # Section label style ("WEATHER", "BIRTHDAYS", "QUOTE OF THE DAY")
    label_font_size: int = 12
    label_font_weight: str = "bold"  # "bold" | "semibold" | "regular"

    # Optional overrides for component section labels.
    # Keys: "weather", "birthdays", "info".  Missing keys fall back to defaults.
    component_labels: dict[str, str] = field(default_factory=dict)

    # When False, all structural border lines and separators are suppressed.
    # Useful for borderless themes like minimalist.
    show_borders: bool = True

    def __post_init__(self) -> None:
        """Fill in default fonts from fonts.py when callables were not provided."""
        if any(
            f is None
            for f in [self.font_regular, self.font_medium, self.font_semibold, self.font_bold]
        ):
            from src.render import fonts
            if self.font_regular is None:
                self.font_regular = fonts.regular
            if self.font_medium is None:
                self.font_medium = fonts.medium
            if self.font_semibold is None:
                self.font_semibold = fonts.semibold
            if self.font_bold is None:
                self.font_bold = fonts.bold

    def label_font(self) -> "ImageFont.FreeTypeFont":
        """Return the appropriate font for section labels based on label_font_weight."""
        if self.font_section_label is not None:
            return self.font_section_label(self.label_font_size)  # type: ignore[misc]
        fn = {
            "bold": self.font_bold,
            "semibold": self.font_semibold,
            "regular": self.font_regular,
        }.get(self.label_font_weight, self.font_bold)
        return fn(self.label_font_size)  # type: ignore[misc]


@dataclass
class Theme:
    """A complete theme: visual style + structural layout."""
    name: str
    style: ThemeStyle
    layout: ThemeLayout


# ---------------------------------------------------------------------------
# Built-in theme names
# ---------------------------------------------------------------------------

AVAILABLE_THEMES: frozenset[str] = frozenset(
    {
        "default", "terminal", "minimalist", "old_fashioned", "today",
        "fantasy", "qotd", "qotd_invert", "weather", "fuzzyclock", "fuzzyclock_invert",
        "diags", "air_quality", "random",
    }
)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def default_layout() -> ThemeLayout:
    """Build a ThemeLayout that exactly matches the layout.py constants."""
    from src.render import layout as L
    return ThemeLayout(
        canvas_w=L.WIDTH,
        canvas_h=L.HEIGHT,
        header=ComponentRegion(0, L.HEADER_Y, L.WIDTH, L.HEADER_H),
        week_view=ComponentRegion(L.WEEK_X, L.WEEK_Y, L.WEEK_W, L.WEEK_H),
        weather=ComponentRegion(L.WEATHER_X, L.WEATHER_Y, L.WEATHER_W, L.WEATHER_H),
        birthdays=ComponentRegion(L.BIRTHDAY_X, L.BIRTHDAY_Y, L.BIRTHDAY_W, L.BIRTHDAY_H),
        info=ComponentRegion(L.INFO_X, L.INFO_Y, L.INFO_W, L.INFO_H),
    )


def default_theme() -> Theme:
    """Return the default theme: identical to the pre-theme rendering."""
    return Theme(
        name="default",
        style=ThemeStyle(),  # __post_init__ fills in default fonts
        layout=default_layout(),
    )


def load_theme(name: str) -> Theme:
    """Return a Theme for the given name.

    Raises ``ValueError`` for unknown names.

    Note: ``"random"`` is not handled here — it must be resolved to a concrete
    theme name via ``src.render.random_theme.pick_random_theme`` before calling
    this function (see ``main.py``).
    """
    if name == "default":
        return default_theme()
    if name == "terminal":
        from src.render.themes.terminal import terminal_theme
        return terminal_theme()
    if name == "minimalist":
        from src.render.themes.minimalist import minimalist_theme
        return minimalist_theme()
    if name == "old_fashioned":
        from src.render.themes.old_fashioned import old_fashioned_theme
        return old_fashioned_theme()
    if name == "today":
        from src.render.themes.today import today_theme
        return today_theme()
    if name == "fantasy":
        from src.render.themes.fantasy import fantasy_theme
        return fantasy_theme()
    if name == "qotd":
        from src.render.themes.qotd import qotd_theme
        return qotd_theme()
    if name == "qotd_invert":
        from src.render.themes.qotd_invert import qotd_invert_theme
        return qotd_invert_theme()
    if name == "weather":
        from src.render.themes.weather import weather_theme
        return weather_theme()
    if name == "fuzzyclock":
        from src.render.themes.fuzzyclock import fuzzyclock_theme
        return fuzzyclock_theme()
    if name == "fuzzyclock_invert":
        from src.render.themes.fuzzyclock_invert import fuzzyclock_invert_theme
        return fuzzyclock_invert_theme()
    if name == "diags":
        from src.render.themes.diags import diags_theme
        return diags_theme()
    if name == "air_quality":
        from src.render.themes.air_quality import air_quality_theme
        return air_quality_theme()
    raise ValueError(
        f"Unknown theme: {name!r}. Available: {', '.join(sorted(AVAILABLE_THEMES))}"
    )
