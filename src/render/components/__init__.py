"""Built-in dashboard components.

Importing this package triggers registration of every built-in component
into ``src.render.components.registry`` as a side effect — see
:mod:`src.render.components._builtins`. ``src.render.canvas`` imports the
registry (transitively, via this package) so adapters are populated by
the time :func:`render_dashboard` runs.
"""

from __future__ import annotations

# Side-effect import populates the component registry.
from src.render.components import _builtins as _builtins  # noqa: F401
