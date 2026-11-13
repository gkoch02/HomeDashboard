# A tour of the code

For anyone opening this repo for the first time. The rest of `docs/` is reference material, written to be looked up; this page is meant to be read once, top to bottom. It leaves you knowing which few files matter, how a weather reading gets from the internet onto the panel, and how to find your way around the rest.

You don't need to know Python well to follow it. Where a piece of Python is quoted, the sentence around it says what it does.

## The big picture

There are two programs in this repo, plus some tools:

1. **The renderer** (`python -m src.main`, starting in `src/main.py`). This is what you see. It doesn't run all the time: a systemd timer starts it every five minutes, it fetches what it needs, draws one picture, sends it to the panel if it changed, and exits.
2. **The web UI** (`python -m src.web`, in `src/web/`), optional. A small web server that runs all the time beside the renderer: a status page, a settings editor, a "Refresh now" button, and the `/api/dashboard` feed the Apple TV companion reads. It never draws to the panel itself; the two programs only share files on disk.
3. **Tools for developers** (`scripts/`, `tools/`, `Makefile`): building the preview images, checking the docs, making releases. The Pi never needs them to run.

If you're trying to understand or change what the panel shows, you only need the first one.

## Words this code uses

Most of what makes the code hard to read from outside is its own vocabulary:

| Word | Means |
|---|---|
| **source** | One kind of data from outside: `events` (calendar), `weather`, `birthdays`, `air_quality` (PurpleAir). Each is handled on its own, so one failing never blocks the others |
| **fetcher** | The code that gets one source, in `src/fetchers/`. Each one registers itself with a `Fetcher(...)` entry saying how to fetch, how to save it in the cache and how long it stays fresh |
| **registry** | A list that things add themselves to when their file is imported: fetchers, themes and components each have one (`registry.py` in their folder). Nothing is wired up by hand |
| **cache** | `state/dashboard_cache.json`: the last good copy of every source. If a fetch fails, the cached copy is drawn instead |
| **staleness** | How old the cached copy is compared to its time-to-live: `FRESH`, `AGING`, `STALE`, `EXPIRED`. Old data gets a small glyph on the panel |
| **circuit breaker** (**breaker**) | After a few failures in a row, a source is left alone for a while (`OPEN`) instead of being retried every five minutes, then tried once (`HALF_OPEN`) |
| **theme** | A complete look: what goes where, in which fonts. One file each in `src/render/themes/` |
| **layout** (`ThemeLayout`) | A theme's arrangement: canvas size, a **region** (a rectangle, `ComponentRegion`) for each part, and the **draw order** |
| **style** (`ThemeStyle`) | A theme's colours, fonts and spacing |
| **component** | The code that draws one part (the week, the weather, the header) inside its region. One file each in `src/render/components/` |
| **adapter** | The small function in `components/_builtins.py` that hands a component the data it needs; the renderer only knows component names |
| **canvas**, **plate** | The picture being drawn, usually 800×480 (1360×480 for the `wide_*` themes). "Plate" is the canvas with its background colour |
| **canvas mode** | `"1"` (pure black and white), `"L"` (greys, for halftones and photos) or `"RGB"` (colour panels) |
| **provider**, **model** | Which panel: `waveshare` or `inky`, and which size of it (`epd7in5_V2`, `epd10in85g`, …) |
| **backend** | `src/display/backend.py`: resizes the picture to the panel and reduces it to the inks the panel has |
| **driver** | `src/display/driver.py`: talks to the panel's hardware library and does the actual refresh |
| **quantize**, **dither** | Turning greys or colours into the few inks the panel has; dithering fakes in-between shades with dots |
| **full / partial refresh** | A full refresh flashes the whole panel and gives the deepest black; a partial one is quicker and quieter, but only some models and themes allow it |
| **quiet hours** | The night window (23:00–06:00 by default) when the renderer exits without doing anything |
| **morning refresh** | The first run after quiet hours always does a full refresh, to clear any ghosting |
| **`theme_rules`**, **`theme_schedule`** | Settings that pick the theme automatically: by weather, time of day, season and so on, or by clock time |
| **dummy data** | Made-up calendar and weather (`src/dummy_data.py`), so you can draw without any accounts or keys |

## Following one weather reading

Say the timer fires at 14:05. Here's the path, with the file and the function at each step. To find a function in a file, search it for `def` and the name, e.g. `def render_dashboard(`.

**1. systemd starts the renderer.** `deploy/dashboard.timer` fires every five minutes and starts `deploy/dashboard.service`, which runs `venv/bin/python -m src.main --config config/config.yaml` in the install folder and appends everything it prints to `output/dashboard.log`.

**2. Read the settings.** `src/main.py`, function `main()`. It reads `config/config.yaml` with `load_config()` (in `src/config.py`), checks it with `validate_config()`, and stops with a report if anything is fatal. Then it hands over to `DashboardApp(cfg, args).run()`.

**3. Decide whether to run at all.** `src/app.py`, method `DashboardApp._run`. It asks `should_skip_refresh()` (in `src/services/run_policy.py`) whether it's quiet hours; if so it logs that and returns, and the program exits. Next, `should_force_full_refresh()` decides whether this is the first run of the morning.

**4. Pick the theme, first guess.** Still in `_run`: `resolve_theme_name()` (in `src/services/theme.py`) works through, in order, a `--theme` option, `theme_rules`, `theme_schedule`, then the `theme:` setting (which may be `random`). It runs once now, before any data is fetched, because the theme decides how many days of calendar to ask for.

**5. Fetch everything.** `src/data_pipeline.py`, method `DataPipeline.fetch`. It reads the cache file once, then for each enabled source:

- if the cached copy is younger than the source's fetch interval (30 minutes for weather), it uses that and doesn't go online;
- if that source's breaker is open, it uses the cache too;
- otherwise it starts the fetch on its own thread, so all sources download at the same time.

It then waits for each one (two minutes at most for all of them together), saves what arrived to the cache, and falls back to the cached copy for any that failed. Weather itself is `fetch_weather()` in `src/fetchers/weather.py`, which calls OpenWeatherMap. The result is one `DashboardData` (defined in `src/data/models.py`), which carries every source plus how stale each one is.

**6. Filter and pick the theme again.** Back in `_run`: `_apply_filters` drops the calendars and keywords you've excluded. If you have `theme_rules`, `resolve_theme_name()` runs a second time, now that it knows the weather, so a rule like "rain → the `weather` theme" can fire. Then `load_theme(theme_name)` (in `src/render/theme.py`) builds the theme.

**7. Draw.** `src/render/canvas.py`, function `render_dashboard`. It:

- makes a blank canvas of the theme's size and mode, in its background colour;
- walks the theme's `draw_order`, and for each name looks up the component and calls it with a `RenderContext` (the data, the region, the style);
- hands the result to the backend.

The core of it is this loop: for each part the theme lists, skip it if it's hidden, otherwise find its adapter and run it.

```python
for name in layout.draw_order:
    ...
    adapter = get_component(name)
    if adapter is not None:
        adapter(ctx)
```

For the weather, the adapter is `_weather` in `src/render/components/_builtins.py`, which calls `draw_weather()` in `src/render/components/weather_panel.py` with the weather data, its region and the theme's style. That's where the icon, temperatures and forecast are drawn.

**8. Fit it to the panel.** `src/display/backend.py`, `build_display_backend(config).resize_and_finalize(...)`. It resizes the picture to the panel's size and reduces it to the panel's inks: pure black and white for most Waveshare panels, four inks for the wide 10.85" one, six for Inky.

**9. Send it, if it changed.** `src/services/output.py`, method `OutputService.publish`. It doesn't touch the panel when the picture is identical to the last one (it compares a fingerprint saved in `output/last_image_hash.txt`), when the theme has already painted this hour, or when the cooldown since the last refresh hasn't passed. Otherwise it calls the driver's `show()` (`WaveshareDisplay` or `InkyDisplay` in `src/display/driver.py`), which drives the hardware. Either way it saves the picture as `output/latest.png` for the web UI.

**10. Done.** `_run` writes `output/last_success.txt` (`write_health_marker`) and logs `Done`, and the program exits until the next tick. If anything above raised an error instead, `output/last_error.txt` says what.

## The files that matter

| File | One line |
|---|---|
| `src/main.py` | Entry point: read and check settings, run the app |
| `src/app.py` | One run from start to finish: quiet hours, theme, fetch, draw, publish |
| `src/config.py` | `config.yaml` → settings objects, with a default for everything |
| `src/config_validation.py` | The checks behind `make check`, and their messages |
| `src/data_pipeline.py` | Fetching every source at once, with cache and breaker fallback |
| `src/fetchers/weather.py`, `calendar.py`, `purpleair.py` | Getting each source from its service |
| `src/fetchers/cache.py`, `circuit_breaker.py` | Keeping the last good copy; backing off a failing source |
| `src/data/models.py` | The shapes of the data: `CalendarEvent`, `WeatherData`, `DashboardData`, … |
| `src/services/theme.py`, `theme_rules.py` | Choosing today's theme |
| `src/render/canvas.py` | Drawing: canvas, components in order, hand-off to the backend |
| `src/render/theme.py` | What a theme is (`Theme`, `ThemeLayout`, `ThemeStyle`), and the default theme |
| `src/render/themes/<name>.py` | One theme |
| `src/render/components/<name>.py` | One part of the picture |
| `src/services/output.py` | Whether to refresh the panel, and doing it |
| `src/display/backend.py`, `driver.py` | Fitting the picture to the panel; driving the panel |
| `config/config.example.yaml` | Every setting, with comments |
| `deploy/dashboard.service`, `dashboard.timer` | How the Pi runs it |

## What you can skip

- **`src/render/themes/` and `src/render/components/`** are most of the code, and each file stands alone. You only ever need the one theme you're looking at and the components it lists in its `draw_order`.
- **`src/web/`**, the optional web UI. It reads the renderer's files and edits `config.yaml`; it doesn't change how the panel is drawn.
- **`tests/`**, the test suite, larger than the code itself. It exists to catch mistakes; ignore it until a test fails.
- **`src/astronomy.py`, `src/render/star_catalog.py`, `moon*.py`, `skyart.py`**: sun, moon and star maths for the sky themes.
- **`scripts/`, `tools/`, `constraints/`, `retired/`**: release, preview and checking tools, pinned library versions, and old themes kept for reference (not loaded).
- **The calendar back-ends** you don't use: `calendar_google.py`, `calendar_ical.py` and `calendar_caldav.py` are three ways to the same list of events.

The layers of checks and tests in this codebase can look alarming: guards that fail the build on a test that asserts nothing, on unused code, on a bare `datetime.now()`. They're there because the code was written mostly by an AI, which rereads everything every time and benefits from tests that catch it drifting. A person can safely read around them.

## Finding things

You'll mostly be searching, not reading. From the repo folder:

```bash
grep -rn "Image unchanged" src/            # where does this log line come from?
grep -rn "def draw_weather" src/           # where is this function defined?
grep -rln "repaint_slot_hours" src/        # which files use this name?
```

`-r` searches every file in the folder, `-n` shows line numbers, `-l` lists just the file names. In VS Code or another editor, "Find in Files" (Cmd-Shift-F) does the same, and Cmd-clicking a function name jumps to where it's defined.

A log line is often the quickest way in: every line in `output/dashboard.log` names the module that wrote it (`src.services.output: Image unchanged …` came from `src/services/output.py`).

## Reading a crash

When something goes wrong, Python prints a **traceback**: the chain of function calls that led to the error. On the Pi it's in `output/dashboard.log`, and the last error is also in `output/last_error.txt`. This one is real, from a config with `theme: nosuchtheme` before an unknown name fell back to `default`, shortened:

```
Traceback (most recent call last):
  File "/home/pi/home-dashboard/src/main.py", line 51, in main
    app.run()
  File "/home/pi/home-dashboard/src/app.py", line 126, in run
    self._run()
  File "/home/pi/home-dashboard/src/app.py", line 230, in _run
    theme = load_theme(theme_name)
  File "/home/pi/home-dashboard/src/render/theme.py", line 547, in load_theme
    raise ValueError(
ValueError: Unknown theme: 'nosuchtheme'. Available: air_quality, almanac, ...
```

Read it **from the bottom up**:

- The last line is the error: a `ValueError` with a message saying the theme name isn't one it knows, and listing the ones it does.
- The lines above it say where: `theme.py`, in the function `load_theme`, called from `_run` in `app.py`.
- Everything higher up is how the program got there; usually you don't need it.

The error types you'll see most:

| Error | Usually means |
|---|---|
| `ValueError` | A value it can't use: a theme or setting name it doesn't know |
| `KeyError: 'x'` | Looked up `x` and it isn't there: a typo in a name |
| `FileNotFoundError` | A path in the config points at a file that doesn't exist (a credentials file, the birthdays file, a photo) |
| `ModuleNotFoundError: No module named 'x'` | The Python environment is missing something; see `MAINTAINING.md` |
| `requests.exceptions.…`, `HTTPError: 401` | A service didn't answer, or refused the key. The renderer falls back to the cache and carries on |
| `PermissionError` | Not allowed to write there, or (for the panel) to use the hardware |
| `SyntaxError` / `IndentationError` | A hand edit broke the Python. Lines in the same block must line up exactly |
| `RunTerminated` | systemd stopped a run that took longer than its time limit |

## Making a change

1. **Find the place** with the tables above, or `grep`.
2. **Change one thing.**
3. **Try it** without the panel, with made-up data:

   ```bash
   venv/bin/python -m src.main --dry-run --dummy --theme weather
   open output/latest.png
   ```

   That runs steps 3–9 above with dummy data, for the `weather` theme, and saves the picture instead of sending it to a panel. Pass `--theme` the one you changed. (`make dry` is the same without `--theme`; both need a `config/config.yaml`, which `make setup` copies from the example.)
4. **Undo** if it's wrong: `git diff` shows what you changed, `git checkout -- <file>` puts the original back.

A dry run overwrites `output/latest.png`, which is also a sample picture kept in the repo; `git checkout -- output/latest.png` puts it back before you commit.

Then run the tests for the area you touched (`venv/bin/pytest tests/test_weather_panel.py --no-cov`, say; most code files have a test file named after them, and `--no-cov` turns off the coverage check, which only makes sense for the whole suite). `make test` runs everything; the test tools come from `venv/bin/pip install -e ".[dev]"`. A failing test says what it expected on its last lines, much like a traceback. Any change to how a theme looks also fails `tests/test_theme_pixel_snapshots.py`, which compares every theme against saved fingerprints; that's expected, and `CLAUDE.md` says how to update them.

`MAINTAINING.md` covers getting a change onto the Pi.

## Where to go next

| To understand | Read |
|---|---|
| Every setting | `docs/configuration.md` |
| The internals in depth: caching, breakers, refresh decisions, the plugin registries | `docs/architecture.md` |
| Adding a fetcher, theme or component; every command and flag | `docs/development.md` |
| Each theme, and the wide ones | `docs/themes.md`, `docs/wide-themes.md` |
| Installing on a Pi, and supported panels | `docs/setup.md` |
| The web UI | `docs/web-ui.md` |
| Common questions | `docs/faq.md` |
