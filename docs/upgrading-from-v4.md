← [README](../README.md)

# Upgrading from v4

v5 is a near-drop-in upgrade for users — every v4 `config.yaml` parses unchanged, and
state files migrate transparently on first read. This guide walks through what changes
in practice and the few config-level decisions you'll want to make.

The headline v5 changes:

- **Plugin registries** for fetchers, themes, and components — internal refactor; no user-visible behaviour change.
- **CalDAV calendar source** alongside Google API and ICS feeds (Nextcloud / Radicale / Apple iCloud / Fastmail / etc.).
- **Content-hash + cooldown refresh throttle** replaces the v4 Inky-specific hourly throttle. Fuzzyclock is no longer special-cased.
- **Schema-driven web editor + live theme preview** (`/api/config/schema`, `/api/preview`).
- **Config schema versioning** (`schema_version: 5`) plus an in-memory migration runner.
- **`DisplayBackend` ABC** — internal cleanup; no user-visible behaviour change.
- **Aware-datetime CI guard** — internal; contributor-facing only.

Pick the path that matches your setup:

- **Option A** — you run the dashboard directly on the Pi (most common)
- **Option B** — you develop on a separate machine and deploy to the Pi via `make deploy`

---

## Option A: Upgrade directly on the Pi

SSH into your Pi. Your v4 installation is likely in `~/home-dashboard`.

### 1. Pull the v5 release

```bash
# On the Pi
cd ~/home-dashboard
git fetch --all
git checkout v5.0.0
```

### 2. Update Python dependencies

v5 adds `caldav>=1.5` to core dependencies and bumps a few minimum versions.

```bash
# On the Pi
venv/bin/pip install -e .
```

(If you're running on a Pi with hardware drivers, also re-run
`make install-display-drivers` to pick up any wheel updates.)

### 3. Validate the config

```bash
make check
```

You should see a clean run. v5 errors and warnings to look out for:

- **Removed validation noise**: the v4-only "Inky hourly throttle active" reminder is gone — the new throttle is silent unless you've configured a non-default cooldown.
- **CalDAV warnings** only fire when `caldav_url` is configured (not before).

### 4. Restart the timer

```bash
sudo systemctl daemon-reload
sudo systemctl restart dashboard.timer
```

### 5. (Optional) Restart the web UI

If you have the web UI installed:

```bash
sudo systemctl restart dashboard-web.service
```

The web editor now serves a schema-driven form layout and a live theme preview button.

---

## Option B: Upgrade on dev machine + redeploy

```bash
# On your dev machine
git checkout main
git pull
git checkout v5.0.0
venv/bin/pip install -e ".[dev,web]"
make test                         # confirm green
make deploy PI_USER=... PI_HOST=...
ssh <pi> "sudo systemctl daemon-reload && sudo systemctl restart dashboard.timer dashboard-web.service"
```

---

## What changes for users

### `display.min_refresh_interval_seconds` (new)

The v4 Inky hourly throttle was a hard-coded 3600s window with a fuzzyclock allowlist.
v5 replaces it with a per-display cooldown setting plus the existing content-hash
short-circuit:

| Provider | Default cooldown | What it means |
|---|---|---|
| `inky` | 60s | Rapid-fire identical-content rendering won't write to the panel; novel content can refresh up to once a minute. |
| `waveshare` | 0s | No cooldown by default. Set a non-zero value to add one. |

If you preferred the v4 "exactly once an hour" Inky cap, restore it explicitly:

```yaml
display:
  min_refresh_interval_seconds: 3600
```

`fuzzyclock` and `fuzzyclock_invert` no longer get special treatment in the throttle —
they don't need it. The image-hash check already short-circuits identical-content
refreshes for any theme.

### State file rename

`state/inky_refresh_state.json` → `state/refresh_throttle_state.json`. v5 reads the v4
file once on first run after upgrade, rewrites it under the new name, and deletes the
old. No action required.

### CalDAV (new optional source)

If you've been running a CalDAV server (Nextcloud / Radicale / Apple iCloud / Fastmail
/ Synology / etc.) and want the dashboard to read from it directly, see
[Setup → CalDAV](setup.md#caldav-nextcloud--radicale--icloud--etc) for the four config
fields and the password-file pattern.

CalDAV takes precedence over both Google API and ICS feeds when configured — leaving
your v4 settings around does not block the CalDAV path.

### Config schema versioning

v5 stamps `schema_version: 5` into in-memory configs at parse time. v4 configs (no
`schema_version` field) are upgraded transparently — no rewrite of your `config.yaml`
on disk and no data loss. Future schema changes will use the same runner with
versioned `.bak-v<N>` backups when they need to mutate the file directly.

### Web UI editor

The config editor still serves the `/config` HTML page identically — but it now also
exposes the v5 JSON APIs:

- `GET /api/config/schema` — declarative form metadata for custom UIs
- `POST /api/preview` — render any registered theme to PNG against dummy data

See [Web UI → v5 JSON APIs](web-ui.md#v5-json-apis-for-advanced--custom-uis) for
details.

---

## What changes for contributors

These don't affect end users, but if you've forked the dashboard or maintain a custom
theme/fetcher you'll see them:

### Plugin registries

| v4 recipe | v5 recipe |
|---|---|
| Add a fetcher across `fetchers/`, `data_pipeline.py`, `cache.py`, `data/models.py`, `config.py` | One new file in `fetchers/` plus a `register_fetcher(...)` block |
| Add a theme across `themes/`, `theme.py` (`_THEME_REGISTRY`), `canvas.py` (`_INKY_THEME_KEY_COLORS`) | One new file in `themes/` plus a `register_theme(name, factory, inky_palette=...)` block |
| Add a component across `components/`, `theme.py` (`ThemeLayout`), `canvas.py` dispatch dict | One new file in `components/` plus a `@register_component(name)` decorator |

See [Development → Adding a fetcher / theme / component](development.md#adding-a-fetcher--theme--component) for the full recipes.

### Per-theme Inky palette

The `_INKY_THEME_KEY_COLORS` dict that v4 carried in `canvas.py` is gone. The
`(primary, secondary)` Spectra-6 palette pair for each theme is now passed to
`register_theme(...)` and lives next to the theme module. Theme `ThemeStyle` may also
override it via the new `inky_palette` field.

Palette index constants (`INKY_BLACK`, `INKY_WHITE`, `INKY_YELLOW`, `INKY_RED`,
`INKY_BLUE`, `INKY_GREEN`) are exported from `src.render.theme` so theme modules can
import them without a circular dependency on `canvas`.

### `DisplayBackend` ABC

`canvas.render_dashboard` no longer branches on `config.provider`. Resize + finalize
is delegated to `build_display_backend(config).resize_and_finalize(...)` from
`src/display/backend.py`. Adding a new display family is a single new backend
subclass plus a `build_display_backend` branch.

### Aware-datetime discipline

`tools/check_naive_datetime.py` is a new CI guard that fails on bare `datetime.now()`
or `datetime.utcnow()` outside `src/_time.py`. Contributors should reach for
`now_utc()`, `now_local(tz)`, or `to_aware()` from `src/_time.py`. Lines that genuinely
want naive local wall-clock time carry an `# allow-naive-datetime` trailing comment.

### `EDITABLE_FIELD_PATHS` is schema-derived

The hand-rolled allowlist in `src/web/config_editor.py` is now derived from
`src.config_schema.editable_field_paths()`. Adding a new editable field is a single
`FieldSpec` entry in `src/config_schema.py`, not a dict edit in two places.

---

## Rollback

If something breaks and you need to roll back to v4:

```bash
cd ~/home-dashboard
git checkout v4.3.1                 # or whichever v4 tag you came from
venv/bin/pip install -e .
sudo systemctl restart dashboard.timer dashboard-web.service
```

The state files v5 wrote (`refresh_throttle_state.json`) are ignored by v4 — you can
safely leave them in place. v4 will recreate `inky_refresh_state.json` on its first
hardware write.

---

## Troubleshooting

### "Inky writes more often than I want"

Set an explicit `display.min_refresh_interval_seconds` to a higher value. The v4-equivalent
hourly behaviour is `3600`.

### "I can't find my Inky throttle state file"

It's been renamed to `state/refresh_throttle_state.json`. The v4 file is removed once
the migration runs (which happens automatically on the first `make dry` or scheduled
run after upgrade). To force a clean reset, delete the new file — the next render will
recreate it.

### "Web UI form looks the same as v4"

That's expected — the `/config` HTML template still serves the same fields it did in
v4. The v5 schema layer is currently used for the editable-field allowlist and the
new `/api/config/schema` JSON endpoint. A schema-rendered HTML form is a follow-up.

### "make check warns that caldav_url and ical_url are both set"

CalDAV takes precedence. If the warning bothers you, comment out the `ical_url` line.
If you want the dashboard to fall through to ICS when CalDAV is unreachable, that's
not currently supported — the dispatcher picks one backend up front.
