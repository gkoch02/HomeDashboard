← [README](../README.md)

# Theme Previews

How to regenerate the per-theme preview PNGs that are embedded in
[Themes](themes.md). Both the standard (Waveshare 1-bit) and Inky color
(Spectra 6) variants live under `output/`.

- [Overview](#overview)
- [Standard preview set](#standard-preview-set)
- [Inky color preview set](#inky-color-preview-set)
- [Diagonal split previews](#diagonal-split-previews)
- [Output files](#output-files)
- [Notes and limitations](#notes-and-limitations)

---

## Overview

Theme previews are just dry-run renders written to PNG files in `output/`. They are useful for:

- comparing layouts across themes without hardware
- reviewing typography and spacing after theme edits
- checking how a theme maps to the Inky Impression Spectra 6 palette
- generating updated screenshots for docs, PRs, or local review

For a normal black-and-white preview, use your usual display config or the default config.
For an Inky color preview, render with `display.provider: inky` and
`display.model: impression_7_3_2025` so the final image goes through the Inky palette mapping.

---

## Standard preview set

If you have a project venv, the built-in batch target is:

```bash
make previews
```

That renders the standard preview PNGs:

```text
output/theme_<theme>.png
```

Example single-theme dry run:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme fuzzyclock
cp output/latest.png output/theme_fuzzyclock.png
```

If you do not have `venv/` yet, you can run the same command with another Python environment as
long as the project dependencies are installed:

```bash
python3 -m src.main --config config/config.example.yaml --dry-run --dummy --theme fuzzyclock
```

---

## Inky color preview set

To generate Inky-specific color previews, render against a config that sets:

```yaml
display:
  provider: inky
  model: impression_7_3_2025
```

You can do that by editing your local `config/config.yaml`, or by using a temporary config file.

Example single-theme Inky preview:

```bash
python3 -m src.main \
  --config /path/to/inky-config.yaml \
  --dry-run \
  --dummy \
  --theme fuzzyclock

cp output/latest.png output/theme_fuzzyclock_inky.png
```

Example full batch for all concrete themes:

```bash
for theme in air_quality astronomy countdown default diags fantasy fuzzyclock fuzzyclock_invert \
             message minimalist monthly moonphase moonphase_invert old_fashioned photo qotd \
             qotd_invert scorecard sunrise terminal tides timeline today weather year_pulse; do
  if [ "$theme" = "message" ]; then
    python3 -m src.main --config /path/to/inky-config.yaml --dry-run --dummy \
      --theme "$theme" --message "Preview Message"
  else
    python3 -m src.main --config /path/to/inky-config.yaml --dry-run --dummy \
      --theme "$theme"
  fi
  cp output/latest.png "output/theme_${theme}_inky.png"
done
```

This is the most accurate way to review:

- per-theme key accents assigned for Inky
- semantic accent roles such as AQI or alert colors
- final Spectra 6 palette mapping after quantization

---

## Diagonal split previews

[Themes](themes.md) embeds one image per theme rather than two, by combining each
Waveshare and Inky pair into a single PNG split along the anti-diagonal — top-left
triangle is the Waveshare render, bottom-right triangle is the Inky render. After
regenerating both `theme_<theme>.png` and `theme_<theme>_inky.png`, rebuild the
combined images with:

```bash
make previews-split
```

That walks `output/`, pairs every `theme_<name>.png` with its `theme_<name>_inky.png`
sibling, and writes `output/theme_<name>_split.png`. The script depends only on
Pillow, so it runs against any Python environment with the project deps installed:

```bash
python3 scripts/build_split_previews.py
```

---

## Output files

Standard preview set:

- `output/theme_<theme>.png`

Inky color preview set:

- `output/theme_<theme>_inky.png`

Combined diagonal split previews (used by [Themes](themes.md)):

- `output/theme_<theme>_split.png`

Latest dry run from the last command:

- `output/latest.png`

Timestamped dry runs are also written automatically:

- `output/dashboard_<timestamp>.png`

---

## Notes and limitations

- `make previews` currently targets the normal dry-run path only. It does not generate a separate
  Inky batch on its own.
- The `message` theme requires `--message TEXT` during preview generation.
- The `countdown` theme renders an empty "No countdowns configured" placeholder when
  `countdown.events` is empty — configure at least one upcoming date in the active
  config for a meaningful preview.
- The `astronomy` theme uses `weather.latitude` / `weather.longitude` for twilight math;
  the preview degrades gracefully without them (OWM sunrise/sunset only, no twilight).
- The `photo` theme will still render in dry-run mode even if no custom photo path is configured,
  but the result depends on the active config.
- Inky previews are still PNG files on your computer. They are not a perfect simulation of the
  physical panel, but they do reflect the dashboard's final limited-palette render path.

For the theme catalog and embedded previews, see [Themes](themes.md). For general
dev commands and the Makefile, see [Development](development.md).
