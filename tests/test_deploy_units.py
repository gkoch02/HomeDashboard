"""Static checks on the systemd units in deploy/.

The renderer runs on a board with no RTC, so a run right after boot can see
the last shutdown time (#301). It waits for NTP inside the service, bounded,
rather than through ``time-sync.target``: with ``systemd-time-wait-sync``
enabled that target waits forever offline, and ``OnCalendar=`` timers order
themselves after it implicitly — so an offline Pi would never render at all,
where it used to keep showing cached data.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "deploy" / "dashboard.service").read_text()


def _values(key: str) -> list[str]:
    return re.findall(rf"^{key}=(.*)$", SERVICE, re.M)


def test_renderer_waits_for_time_sync_with_a_bound():
    waits = [v for v in _values("ExecStartPre") if "systemd-time-wait-sync" in v]
    assert len(waits) == 1
    assert waits[0].startswith("-"), "a timeout or missing helper must not fail the run"
    assert re.search(r"\btimeout \d+\b", waits[0]), "the wait must be bounded"


def test_renderer_is_not_gated_on_time_sync_target():
    ordering = " ".join(_values("After") + _values("Wants") + _values("Requires"))
    assert "time-sync.target" not in ordering


def test_pi_enable_does_not_enable_the_unbounded_wait():
    makefile = (ROOT / "Makefile").read_text()
    recipe = re.search(r"^pi-enable:.*?(?=^\S)", makefile, re.M | re.S)
    assert recipe and "systemd-time-wait-sync" not in recipe.group(0)
