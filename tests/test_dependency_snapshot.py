"""The tested dependency snapshot in ``constraints/`` and how it is installed.

``requirements*.txt`` stay minimum-version ranges; ``constraints/py<X.Y>.txt``
records one resolution of them per Raspberry Pi OS release, and
``constraints/waveshare-epd.ref`` the vendor driver commit. These tests hold the
snapshot to the requirements it was resolved from and the Makefile to installing
through it.
"""

import importlib.util
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lock_deps.py"


def _load_lock_module():
    """Import ``scripts/lock_deps.py`` by path — ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("_lock_deps_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lock_deps = _load_lock_module()


def _pins(python: str) -> dict[str, Version]:
    text = lock_deps.snapshot_path(python).read_text()
    pins = {}
    for line in lock_deps.pins(text):
        name, sep, version = line.partition("==")
        assert sep and re.fullmatch(r"[A-Za-z0-9._-]+", name), f"not an exact pin: {line!r}"
        pins[canonicalize_name(name)] = Version(version)
    return pins


def _requirements() -> list[Requirement]:
    reqs = []
    for name in lock_deps.REQUIREMENTS:
        for line in (ROOT / name).read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                reqs.append(Requirement(line))
    return reqs


@pytest.mark.parametrize("python", sorted(lock_deps.TARGETS))
def test_snapshot_pins_every_requirement_within_its_range(python):
    pins = _pins(python)
    for req in _requirements():
        name = canonicalize_name(req.name)
        assert name in pins, f"py{python}.txt does not pin {req.name}"
        assert req.specifier.contains(pins[name], prereleases=True), (
            f"py{python}.txt pins {req.name}=={pins[name]}, outside {req.specifier}"
        )


@pytest.mark.parametrize("python", sorted(lock_deps.TARGETS))
def test_snapshot_records_its_target_and_verification(python):
    text = lock_deps.snapshot_path(python).read_text()
    assert lock_deps.TARGETS[python] in text and f"Python {python}" in text
    assert lock_deps.VERIFIED_RE.search(text)


def test_every_snapshot_file_is_a_target():
    files = {p.name for p in lock_deps.CONSTRAINTS_DIR.glob("py*.txt")}
    assert files == {lock_deps.snapshot_path(py).name for py in lock_deps.TARGETS}


def test_waveshare_ref_is_one_commit():
    text = lock_deps.WAVESHARE_REF_FILE.read_text()
    shas = [line for line in text.splitlines() if lock_deps.SHA_RE.match(line)]
    assert len(shas) == 1
    assert lock_deps.VERIFIED_RE.search(text)


def test_makefile_installs_the_pinned_driver_commit():
    makefile = (ROOT / "Makefile").read_text()
    assert "WAVESHARE_EPD_REF_FILE = constraints/waveshare-epd.ref" in makefile
    assert "fetch -q --depth=1 --filter=blob:none origin $(WAVESHARE_EPD_REF)" in makefile
    # A clone without a ref installs whatever the vendor's default branch is today.
    assert "git clone" not in makefile


def test_makefile_installs_the_g_driver_from_the_same_commit():
    makefile = (ROOT / "Makefile").read_text()
    lib = "E-paper_Separate_Program/10.85inch_e-Paper_G/RaspberryPi/python/lib"
    assert f"WAVESHARE_EPD_G_LIB = {lib}" in makefile
    block = makefile[makefile.index("\ninstall-waveshare-driver:") :]
    block = block[: block.index("\n\n")]
    assert "$(WAVESHARE_EPD_G_LIB)" in block.split("sparse-checkout set", 1)[1].split("fetch")[0]
    assert "scripts/install_epd10in85g.py /tmp/waveshare-epd/$(WAVESHARE_EPD_G_LIB)" in block


def test_pi_install_goes_through_the_snapshot():
    makefile = (ROOT / "Makefile").read_text()
    block = makefile[makefile.index("\npi-install:") : makefile.index("\npi-enable:")]
    assert '_pip-locked REQS="-r requirements.txt -r requirements-pi.txt"' in block
    assert "pip install -r requirements" not in block
    assert 'pip install -c "$$LOCK" $(REQS)' in makefile


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """lock_deps pointed at an empty constraints dir, resolving to fixed pins."""
    monkeypatch.setattr(lock_deps, "CONSTRAINTS_DIR", tmp_path)
    monkeypatch.setattr(lock_deps, "WAVESHARE_REF_FILE", tmp_path / "waveshare-epd.ref")
    resolved = {"lines": ["pillow==12.0.0", "pyyaml==6.0.3"]}
    monkeypatch.setattr(lock_deps, "resolve", lambda python: list(resolved["lines"]))
    return tmp_path, resolved


def test_unchanged_pins_keep_the_recorded_verification(isolated):
    tmp_path, _resolved = isolated
    path = tmp_path / "py3.11.txt"
    assert lock_deps.write_snapshot("3.11") is True
    verified = "# Verified: 2026-10-06 Pi 4, epd7in5_V2 refresh OK"
    path.write_text(path.read_text().replace(lock_deps.PENDING, verified))

    assert lock_deps.write_snapshot("3.11") is False
    assert verified in path.read_text()


def test_changed_pins_reset_verification_to_pending(isolated):
    tmp_path, resolved = isolated
    path = tmp_path / "py3.11.txt"
    lock_deps.write_snapshot("3.11")
    path.write_text(path.read_text().replace(lock_deps.PENDING, "# Verified: yes"))

    resolved["lines"] = ["pillow==12.1.0", "pyyaml==6.0.3"]
    assert lock_deps.write_snapshot("3.11") is True
    text = path.read_text()
    assert lock_deps.PENDING in text and "pillow==12.1.0" in text


def test_waveshare_sha_is_recorded_as_given(isolated):
    tmp_path, _resolved = isolated
    sha = "a" * 40
    assert lock_deps.write_waveshare(sha) == sha
    assert (tmp_path / "waveshare-epd.ref").read_text().splitlines()[-1] == sha


def test_waveshare_verification_survives_only_an_unchanged_commit(isolated):
    tmp_path, _resolved = isolated
    path = tmp_path / "waveshare-epd.ref"
    lock_deps.write_waveshare("a" * 40)
    verified = "# Verified: 2026-10-06 Pi Zero 2 W, epd10in85g refresh OK"
    path.write_text(path.read_text().replace(lock_deps.PENDING, verified))

    lock_deps.write_waveshare("a" * 40)
    assert verified in path.read_text()
    lock_deps.write_waveshare("b" * 40)
    assert lock_deps.PENDING in path.read_text()
