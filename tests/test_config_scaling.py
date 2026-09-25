"""``display.scaling`` through the parser, the validator and the schema."""

from __future__ import annotations

from src.config import Config, DisplayConfig, load_config, validate_config
from src.config_schema import editable_field_paths, to_json


def test_default_is_auto():
    assert DisplayConfig().scaling == "auto"


def test_parsed_from_yaml(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('display:\n  provider: "waveshare"\n  scaling: "fit"\n')
    assert load_config(str(p)).display.scaling == "fit"


def test_unknown_mode_is_an_error():
    errors, _ = validate_config(Config(display=DisplayConfig(scaling="squash")))
    assert any(e.field == "display.scaling" for e in errors)


def test_known_modes_pass():
    for mode in ("auto", "stretch", "fit"):
        errors, _ = validate_config(Config(display=DisplayConfig(scaling=mode)))
        assert not any(e.field == "display.scaling" for e in errors), mode


def test_web_editable_with_choices():
    assert editable_field_paths()["display.scaling"] == ("display", "scaling")
    schema = to_json(values={})
    field = next(
        f
        for section in schema["sections"]
        for f in section["fields"]
        if f["path"] == "display.scaling"
    )
    assert field["type"] == "enum"
    assert field["choices"] == ["auto", "stretch", "fit"]
