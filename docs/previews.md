← [README](../README.md)

# Theme Previews

How to regenerate the per-theme preview PNGs embedded in the docs. There are two
independent sets, both under `assets/previews/`: the monochrome Waveshare renders
in [Themes](themes.md), and the Spectra 6 color renders in
[Inky Previews](inky-previews.md).

- [Overview](#overview)
- [Standard preview set](#standard-preview-set)
- [Inky color preview set](#inky-color-preview-set)
- [Output files](#output-files)
- [Notes and limitations](#notes-and-limitations)

---

## Overview

Theme previews are just dry-run renders written to PNG files in `assets/previews/`. They are useful for:

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
assets/previews/theme_<theme>.png
```

The target runs `scripts/build_previews.py`, which enumerates the theme
registry and renders every theme in **one process** — adding a theme needs no
edit to the script or the Makefile. Exclusions, if a theme ever needs one, are
the single `EXCLUDED` set at the top of the script.

The render date is pinned (`2026-04-06`, matching the pixel-snapshot fixture)
so re-running the batch does not churn every committed PNG through a moved
dateline. Useful flags:

```bash
python3 scripts/build_previews.py --theme moonphase --theme qotd   # a subset
python3 scripts/build_previews.py --date 2026-12-21                # another date
python3 scripts/build_previews.py --config config/config.yaml      # your config
python3 scripts/build_previews.py --out-dir /tmp/previews          # elsewhere
```

A theme that fails to render is reported and the batch continues, exiting
non-zero at the end — one broken theme does not cost you the other 36.

Example single-theme dry run:

```bash
venv/bin/python -m src.main --dry-run --dummy --theme fuzzyclock
cp output/latest.png assets/previews/theme_fuzzyclock.png
```

If you do not have `venv/` yet, you can run the same command with another Python environment as
long as the project dependencies are installed:

```bash
python3 -m src.main --config config/config.example.yaml --dry-run --dummy --theme fuzzyclock
```

---

## Inky color preview set

The same script renders the Inky set:

```bash
make previews-inky
# or: python3 scripts/build_previews.py --provider inky
```

That writes `assets/previews/theme_<theme>_inky.png` for every registered
theme, overriding `display.provider` / `display.model` in memory so no config
file needs editing.

To do it by hand instead, render against a config that sets:

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

cp output/latest.png assets/previews/theme_fuzzyclock_inky.png
```

Example full batch for all concrete themes:

```bash
for theme in agenda air_quality almanac astronomy constellation_map countdown day_arc default diags fantasy fuzzyclock \
             fuzzyclock_invert halftone halftone_agenda light_cycle message minimalist monthly moonphase moonphase_invert moonphase_photo \
             naturalist old_fashioned photo postcard qotd qotd_invert scorecard sunrise terminal tides timeline today trends \
             weather weatherglass year_pulse; do
  if [ "$theme" = "message" ]; then
    python3 -m src.main --config /path/to/inky-config.yaml --dry-run --dummy \
      --theme "$theme" --message "Preview Message"
  else
    python3 -m src.main --config /path/to/inky-config.yaml --dry-run --dummy \
      --theme "$theme"
  fi
  cp output/latest.png "assets/previews/theme_${theme}_inky.png"
done
```

This is the most accurate way to review:

- per-theme key accents assigned for Inky
- semantic accent roles such as AQI or alert colors
- final Spectra 6 palette mapping after quantization

---

## Output files

Standard preview set:

- `assets/previews/theme_<theme>.png`

Inky color preview set:

- `assets/previews/theme_<theme>_inky.png`

Latest dry run from the last command:

- `output/latest.png`

Timestamped dry runs are also written automatically:

- `output/dashboard_<timestamp>.png`

---

## Notes and limitations

- `make previews` renders the Waveshare set embedded in [Themes](themes.md);
  `make previews-inky` renders the Inky set embedded in
  [Inky Previews](inky-previews.md). The two sets are independent — a change that
  only affects one backend needs only that batch rerun.
- The `message` and `countdown` themes need extra input to render anything but an
  empty-state placeholder. The script supplies both: a fixed preview message, and a
  pair of sample countdown targets when `countdown.events` is empty in the config.
  Rendering them through `python -m src.main` by hand still needs `--message TEXT`
  and configured `countdown.events`.
- The `astronomy` theme uses `weather.latitude` / `weather.longitude` for twilight math;
  the preview degrades gracefully without them (OWM sunrise/sunset only, no twilight).
- The `photo` theme will still render in dry-run mode even if no custom photo path is configured,
  but the result depends on the active config.
- Inky previews are still PNG files on your computer. They are not a perfect simulation of the
  physical panel, but they do reflect the dashboard's final limited-palette render path.

For the theme catalog and its monochrome previews, see [Themes](themes.md); for
the color catalog, see [Inky Previews](inky-previews.md). For general dev
commands and the Makefile, see [Development](development.md).
