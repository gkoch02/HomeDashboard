"""The YAML writer embedded in deploy/configure.sh.

`make configure` collects values interactively and then hands them to a Python
heredoc that edits config/config.yaml in place. The writer used to look for a
live `purpleair:` section that the template deliberately ships commented out,
so the PurpleAir key was silently dropped and `sensor_id` was appended as a
stray top-level key while the wizard reported success (#265). These tests run
the extracted heredoc as a subprocess against a copy of the template.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "configure.sh"
EXAMPLE = ROOT / "config" / "config.example.yaml"


def _writer_source() -> str:
    text = SCRIPT.read_text()
    match = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF\n", text, re.DOTALL)
    assert match, "configure.sh no longer embeds a PYEOF heredoc"
    return match.group(1)


@pytest.fixture
def writer(tmp_path):
    path = tmp_path / "writer.py"
    path.write_text(_writer_source())
    return path


def _run(writer: Path, config: Path, *, pa_key: str = "", pa_sensor: str = ""):
    args = [
        sys.executable,
        str(writer),
        str(config),
        "inky",
        "impression_7_3_2025",
        "OWMKEY",
        "47.6",
        "-122.3",
        "metric",
        "America/Los_Angeles",
        "cal@group.calendar.google.com",
        pa_key,
        pa_sensor,
    ]
    return subprocess.run(args, capture_output=True, text=True)


def _purpleair_block(text: str) -> str:
    match = re.search(r"(?ms)^purpleair:\n(.*?)(?=^\S|\Z)", text)
    return match.group(1) if match else ""


def test_purpleair_values_land_in_a_live_section(writer, tmp_path):
    cfg = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE, cfg)

    result = _run(writer, cfg, pa_key="PAKEY", pa_sensor="99999")

    assert result.returncode == 0, result.stderr
    text = cfg.read_text()
    block = _purpleair_block(text)
    assert re.search(r'^\s+api_key: "PAKEY"$', block, re.MULTILINE)
    assert re.search(r"^\s+sensor_id: 99999$", block, re.MULTILINE)
    assert not re.search(r"^sensor_id:", text, re.MULTILINE), "stray top-level key"

    from src.config import load_config

    loaded = load_config(str(cfg))
    assert (loaded.purpleair.api_key, loaded.purpleair.sensor_id) == ("PAKEY", 99999)
    assert loaded.weather.api_key == "OWMKEY"
    assert loaded.weather.units == "metric"
    assert (loaded.display.provider, loaded.display.model) == ("inky", "impression_7_3_2025")
    assert loaded.timezone == "America/Los_Angeles"
    assert loaded.google.calendar_id == "cal@group.calendar.google.com"


def test_skipping_purpleair_leaves_the_section_off(writer, tmp_path):
    cfg = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE, cfg)

    result = _run(writer, cfg)

    assert result.returncode == 0, result.stderr
    text = cfg.read_text()
    assert not re.search(r"^purpleair:", text, re.MULTILINE)
    assert not re.search(r"^sensor_id:", text, re.MULTILINE)


def test_rerun_updates_an_already_live_section(writer, tmp_path):
    cfg = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE, cfg)
    assert _run(writer, cfg, pa_key="OLD", pa_sensor="1").returncode == 0

    result = _run(writer, cfg, pa_key="NEW", pa_sensor="2")

    assert result.returncode == 0, result.stderr
    text = cfg.read_text()
    assert text.count("purpleair:") == 1
    block = _purpleair_block(text)
    assert 'api_key: "NEW"' in block
    assert "sensor_id: 2" in block
    assert "OLD" not in text


def test_missing_section_is_appended_as_a_real_block(writer, tmp_path):
    cfg = tmp_path / "config.yaml"
    text = EXAMPLE.read_text()
    lines = [line for line in text.splitlines(keepends=True) if "purpleair" not in line.lower()]
    text = "".join(lines)
    assert not re.search(r"(?im)^#?\s*purpleair:", text)
    cfg.write_text(text)

    result = _run(writer, cfg, pa_key="PAKEY", pa_sensor="7")

    assert result.returncode == 0, result.stderr
    block = _purpleair_block(cfg.read_text())
    assert 'api_key: "PAKEY"' in block
    assert "sensor_id: 7" in block


def test_missing_target_key_fails_loudly_and_leaves_the_file_alone(writer, tmp_path):
    cfg = tmp_path / "config.yaml"
    original = "display:\n  provider: x\n"
    cfg.write_text(original)

    result = _run(writer, cfg)

    assert result.returncode != 0
    assert "could not find 'model:' under 'display:'" in result.stderr
    assert cfg.read_text() == original
