"""Static checks on the systemd units in deploy/.

The renderer runs on a board with no RTC; ordering it after
``time-sync.target`` keeps the first tick after boot from reading a stale
clock (#301), and the target is only a real barrier when
``systemd-time-wait-sync`` is enabled, which ``make pi-enable`` does.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _unit_values(text: str, key: str) -> set[str]:
    return {v for line in re.findall(rf"^{key}=(.*)$", text, re.M) for v in line.split()}


def test_renderer_waits_for_time_sync():
    unit = (ROOT / "deploy" / "dashboard.service").read_text()
    assert "time-sync.target" in _unit_values(unit, "After")
    assert "time-sync.target" in _unit_values(unit, "Wants")


def test_pi_enable_turns_on_time_wait_sync():
    makefile = (ROOT / "Makefile").read_text()
    recipe = re.search(r"^pi-enable:.*?(?=^\S)", makefile, re.M | re.S)
    assert recipe and "systemd-time-wait-sync" in recipe.group(0)
