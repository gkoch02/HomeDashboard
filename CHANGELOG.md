# Changelog

All notable changes to Home Dashboard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [4.2.1] - 2026-04-04

### (Patch version bump for minor fixes)

## [4.2] - Unreleased

### Added
- 

## [4.1.3] - 2026-04-04

### Fixed
- **KeyError in data pipeline**: Resolved a race condition where `source_staleness`
  dictionary access could raise `KeyError` when a fetch failed and cached data was
  expired. The four duplicate `_resolve_*` methods have been consolidated into a
  single `_resolve_source()` method with safe `.get()` access throughout.
- **EPD sleep exception masking**: The `finally` block in `WaveshareDisplay.show()`
  now catches exceptions from `epd.sleep()` to avoid masking the original error.
- **Timezone resolution safety**: `resolve_tz("local")` now falls back to UTC with
  a warning if the system timezone cannot be determined.

### Added
- **NYC coordinate warning**: Config validation now warns when weather coordinates
  are still set to the example defaults (New York City).
- **API key format validation**: Config validation checks that the OpenWeatherMap
  API key matches the expected 32-character hex format.
- **Circuit breaker startup logging**: Non-closed breaker states are now logged at
  startup so users can see why a source might be skipped.
- **PurpleAir debug logging**: Malformed API responses now emit debug-level log
  messages with payload structure details.
- **Systemd restart limits**: `dashboard.service` now includes `StartLimitBurst`
  and `StartLimitIntervalSec` to prevent infinite restart loops on hardware failure.
- **SPI detection in Makefile**: `make pi-install` now detects whether SPI was
  already enabled and gives clear reboot guidance accordingly.
- **Auto-derived theme registry**: `AVAILABLE_THEMES` is now derived from
  `_THEME_REGISTRY`, eliminating the risk of the two lists drifting out of sync.
- **Documentation**: Added prerequisites, first-run checklist, reliability
  explanation, and troubleshooting table to README. Added `docs/faq.md` and
  `CHANGELOG.md`.

## [4.1.1]

### Added
- Moonphase theme (`moonphase`, `moonphase_invert`) -- full-canvas moon phase
  display with illumination percentage and daily quote
- PurpleAir air quality integration (`air_quality` theme and weather theme AQI card)
- ICS calendar feed support (`google.ical_url`) -- no GCP project required
- Quote rotation control (`cache.quote_refresh`: daily, twice_daily, hourly)
- Per-panel staleness indicators (! badge on weather and birthday panels)
- Host system diagnostics theme (`diags`)
- Additional Waveshare display models (epd9in7, epd13in3k)

### Changed
- Theme schedule (`theme_schedule`) for time-of-day theme switching
- Hourly random theme rotation (`random_hourly`)
- Configurable circuit breaker and cache TTL per source

## [4.0.0]

### Added
- Complete rewrite from v3 with dataclass-first architecture
- 16 built-in themes with random rotation
- Per-source caching, circuit breaking, and staleness tracking
- Concurrent data fetching via ThreadPoolExecutor
- Waveshare multi-model support with auto-scaling
- Systemd timer-based scheduling (replaces cron)
- Interactive configuration wizard (`make configure`)
- Comprehensive config validation (`make check`)
