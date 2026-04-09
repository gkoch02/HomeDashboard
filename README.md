# Home Dashboard

Home Dashboard is a low-maintenance eInk wall display for family logistics on a Raspberry Pi. It shows calendar events, weather, birthdays, quotes, and optional diagnostics on supported Waveshare and Inky displays, with graceful fallback behavior for unattended use.

![Default theme preview](output/theme_default.png)

## Start Here

For a first install on a Raspberry Pi:

```bash
git clone https://github.com/gkoch02/Dashboard-v4.git ~/home-dashboard
cd ~/home-dashboard
make pi-install
make configure
make dry
make pi-enable
make pi-status
```

If SPI was enabled for the first time during `make pi-install`, reboot once before your first live hardware refresh:

```bash
sudo reboot
```

## Choose Your Path

| If you want to... | Read this |
|---|---|
| Install on a Pi and get the first render working | [Setup Guide](docs/setup.md) |
| Choose between ICS and Google service-account calendar setup | [Setup Guide](docs/setup.md#ics-feed-no-gcp-required) |
| Enable the optional browser control panel | [Web UI](docs/web-ui.md) |
| Pick or schedule themes | [Themes](docs/themes.md) |
| See the full `config.yaml` reference | [Configuration Reference](docs/configuration.md) |
| Preview themes or regenerate gallery images | [Color Theme Previews](docs/color-theme-previews.md) |
| Upgrade from an older install | [Upgrading from v3](docs/upgrading-from-v3.md) |
| Develop locally without hardware | [Development](docs/development.md) |
| Contribute code or docs | [Contributing](CONTRIBUTING.md) |

## What You Get

- Weekly calendar via Google Calendar API or private ICS feed
- Current weather, forecast, and optional PurpleAir air quality
- Birthdays from a file, calendar events, or Google Contacts
- 21 built-in themes plus scheduled and random rotation modes
- Optional Web UI for status, config editing, and manual refresh
- Per-source caching, circuit breakers, stale-data indicators, and quiet hours

## Documentation Map

### Operator docs

- [Setup Guide](docs/setup.md) for install, Pi setup, calendar setup, and recovery
- [Web UI](docs/web-ui.md) for browser access, auth, and service setup
- [Configuration Reference](docs/configuration.md) for every `config.yaml` field
- [Themes](docs/themes.md) for the live theme catalog and scheduling behavior
- [FAQ](docs/faq.md) for common operational questions

### Contributor docs

- [Development](docs/development.md) for commands, local workflow, and repo layout
- [Architecture](docs/architecture.md) for internals and design decisions
- [Contributing](CONTRIBUTING.md) for contribution-specific guidance

## Quick Checks

After setup, these are the main operator commands:

```bash
make check      # validate config/config.yaml
make dry        # render output/latest.png with dummy data
make pi-status  # inspect timer/service status on the Pi
make pi-logs    # tail renderer logs
```

If something looks off, go to [docs/setup.md](docs/setup.md#troubleshooting-and-recovery) and [docs/faq.md](docs/faq.md).
