# Keeping Home Dashboard running

A guide to running a dashboard panel day to day with nothing but a terminal and a text editor: checking it's healthy, changing its settings, updating, recovering when something breaks, and making small code changes safely.

The rest of the docs (`README.md`, `docs/`) are the full reference. This page only tells you which of it you need, and when.

## What's where

The panel is a Raspberry Pi with a systemd **timer** that starts the renderer every five minutes. Each run fetches what's due, draws the picture, refreshes the panel if the picture changed, and exits. If you've turned on the web UI, a second service runs all the time beside it.

| Thing | Where on the Pi | Touch it? |
|---|---|---|
| The code (a copy of this GitHub repo) | `~/home-dashboard` | Only through `git pull`, or small tweaks (see the last section) |
| Its Python environment | `~/home-dashboard/venv` | Rebuild it if it breaks (see "Things that will break eventually") |
| **Your settings** | `~/home-dashboard/config/config.yaml` | Yes, this is the file you edit |
| Birthdays | `~/home-dashboard/config/birthdays.json` (when `birthdays.source` is `file`) | Yes |
| Web UI settings (port, password) | `~/home-dashboard/config/web.yaml` | Rarely |
| Google calendar key | `~/home-dashboard/credentials/service_account.json` | No; keep a copy (see "Back up") |
| Cache, circuit breakers, sync tokens | `~/home-dashboard/state/` | No. Deleting one file resets that one behaviour (`docs/setup.md`, "Reset cached data") |
| The log, the last picture, health markers | `~/home-dashboard/output/` (`dashboard.log`, `latest.png`, `last_success.txt`, `last_error.txt`) | Read only |
| The service definitions | `/etc/systemd/system/dashboard.service`, `dashboard.timer`, `dashboard-web.service`, `dashboard-trigger.path` | Rarely; `make pi-enable` / `make web-enable` write them |

Everything below starts with logging in to the Pi from your Mac (`ssh pi@<the Pi>`, or the shortcut in your `~/.ssh/config`) and `cd ~/home-dashboard`. If you have more than one panel, each Pi has its own copy of all of this.

## Is it OK?

```bash
make pi-status
```

That shows the timer (`Active: active (waiting)` is good, with the next run under `Trigger:`), the last run of the service, and the last 20 lines of the log. A healthy run ends with `INFO src.app: Done`. `Image unchanged — skipping display refresh` is normal: the panel is only redrawn when the picture changes.

`systemctl status dashboard.service` on its own says `inactive (dead)` between runs. That's expected for a job that runs and exits; `failed` is not.

Quicker, from the Pi or (if the web UI is on and open to your network) from the Mac:

```bash
curl -s http://127.0.0.1:8080/api/health
```

`"healthy":true` with a small `seconds_since_success` (under 300 while it's awake) is good. In quiet hours (23:00–06:00 by default) nothing runs, so the number climbs; that's normal.

To watch it live (Ctrl-C to stop watching; the panel keeps running):

```bash
make pi-logs
```

## Changing settings (no code)

All the everyday choices live in one file. The recipe is always the same:

```bash
cp config/config.yaml config/config.yaml.bak-$(date +%Y%m%d)   # 1. back it up
nano config/config.yaml                                         # 2. edit
make check                                                      # 3. check it
sudo systemctl start dashboard.service                          # 4. run it now (or wait for the next five minutes)
make pi-status                                                  # 5. check it ran
```

Step 3 prints `Config OK — no issues found.`, or a list of errors and warnings, each naming the setting at fault. Fix any **ERRORS** before going on. Read the **WARNINGS** too: one of them is `Unknown theme`, and a misspelled theme name gets past `make check` as a warning but makes every run fail. An unreadable value (a word where a number belongs) is also a warning: that one setting falls back to its default and the rest still work.

A file that isn't valid YAML at all (a missing closing quote, bad indentation) makes `make check` say `Could not read config file … line N`, and every run will fail the same way until it's fixed. Restore your backup if you can't see the problem.

The web UI's settings page edits the same file and keeps its own backups (`config.yaml.bak`, `config.yaml.bak.<time>`), and it checks a change before saving it. Either way works; don't use both at the same moment.

The settings you're most likely to want:

| Setting | What it does | Example |
|---|---|---|
| `theme` | The look. A theme name, `random` (a new one each day) or `random_hourly` | `theme: weather` |
| `random_theme:` `include` / `exclude` | Which themes `random` chooses from | `exclude: [terminal]` |
| `theme_schedule` | Different themes at different times of day | see `config/config.example.yaml` |
| `theme_rules` | Themes chosen by weather, season, weekday and so on | see `docs/configuration.md` |
| `schedule:` `quiet_hours_start`, `quiet_hours_end` | When it stops refreshing for the night (whole hours) | `quiet_hours_start: 23` |
| `title` | The text in the header | `title: "Home"` |
| `filters` | Calendars or keywords to leave off | see `docs/configuration.md` |

Rules for the file: indentation matters (two spaces per level, never tabs), text with special characters goes in "double quotes", and a line starting with `#` is ignored. `config/config.example.yaml` lists every setting with a comment; `docs/configuration.md` explains them. `docs/themes.md` shows every theme.

**To undo**, copy your backup back:

```bash
cp config/config.yaml.bak-YYYYMMDD config/config.yaml
sudo systemctl start dashboard.service
```

## The web UI

If it's set up (`make web-enable`; `docs/web-ui.md`), it's at `http://<the Pi>:8080` from any browser on your network, or through an SSH tunnel if `config/web.yaml` says `host: "127.0.0.1"`:

```bash
ssh -L 8080:127.0.0.1:8080 pi@<the Pi>
```

Then visit <http://127.0.0.1:8080> on the Mac. It shows the last picture, each source's state, the log, a settings editor, and **Refresh now**. The Apple TV companion reads it too.

To check it or restart it: `make web-status`, `sudo systemctl restart dashboard-web.service`.

## Updating

```bash
cd ~/home-dashboard
git pull --ff-only origin main
git diff --stat ORIG_HEAD HEAD -- requirements*.txt constraints/
```

If that last command lists any files, the update changed the libraries the code needs, so install them (this keeps your settings):

```bash
make pi-install
```

Then:

```bash
make check
sudo systemctl start dashboard.service
make pi-status
sudo systemctl restart dashboard-web.service    # only if you use the web UI
```

The renderer starts fresh every five minutes, so it picks up new code by itself; the web UI keeps running, so it needs the restart. If the update changed a file in `deploy/`, also run `make pi-enable` (and `make web-enable`) to reinstall the service definitions. `git pull` refuses to run if you've edited a tracked file; see "Small code changes".

**To go back to the version that worked**, every release has a tag (`v6.1.0`, `v6.2.0`, …; the list is in `CHANGELOG.md` and on the GitHub releases page):

```bash
cd ~/home-dashboard
git fetch --tags origin
git checkout v6.1.0
sudo systemctl start dashboard.service
```

The `fetch --tags` matters: the Pi's copy only follows `main`, so it doesn't have the newest tags until you ask for them. `git checkout main` and `git pull` put you back on the latest.

## When it stops working

| What you see | Try |
|---|---|
| Panel frozen on an old picture | `make pi-status`. If the timer isn't `active`, `sudo systemctl enable --now dashboard.timer`. Otherwise read the last log lines for the reason |
| `failed` right after a settings change | `make check`, then fix the setting or restore your config backup |
| `failed` right after an update | Go back to the previous tag (above) |
| Fails after a Pi system update | See "Things that will break eventually" |
| A `!` on part of the panel, or "Unavailable" | That source's data is old: its service didn't answer, or refused the key. `grep -i -E "error|warn" output/dashboard.log \| tail` names the source. It recovers by itself when the service comes back |
| Calendar empty or wrong | `docs/faq.md`, "Why are my calendar events not showing up?" |
| Blacks look grey, ghosting | `docs/faq.md`, "Display" |
| Want a refresh right now | `sudo systemctl start dashboard.service`, or **Refresh now** in the web UI. Add `--force-full-refresh` to a manual run to flash the panel clean: `venv/bin/python -m src.main --config config/config.yaml --force-full-refresh` |
| Web page won't load | `make web-status`; `sudo systemctl restart dashboard-web.service` |
| Times are an hour off | The Pi's time zone: `timedatectl` shows it, `sudo timedatectl set-timezone America/Los_Angeles` (your zone) fixes it |
| Can't log in to the Pi | Its network address changed; your router's device list shows the new one. Update `~/.ssh/config` on the Mac |
| Pi won't boot at all | Probably the SD card. See "Rebuilding from scratch" |

`output/last_error.txt` holds the last error with its time. It's never cleared, so compare its time with `output/last_success.txt`: if the success is newer, the error is old news. The log nearly always says what's wrong in its last lines; `docs/CODE_TOUR.md`, "Reading a crash", shows how to read a Python error.

## Back up now, while it works

Copy your settings, keys and state onto the Mac, from a Mac terminal:

```bash
mkdir -p ~/Backups/home-dashboard
rsync -a --relative --exclude '*.example.yaml' 'pi@<the Pi>:home-dashboard/./config/' 'pi@<the Pi>:home-dashboard/./credentials/' 'pi@<the Pi>:home-dashboard/./state/' ~/Backups/home-dashboard/
```

That copies `config/` (your settings, their backups, birthdays, web UI settings and any quote file you changed), `credentials/` (the calendar key, which you can't download again from Google without making a new one) and `state/` (the cache and sync tokens, which save the first run after a rebuild from starting cold). It skips the code (including the example config files, which come with it), the logs and old pictures. Run it again whenever you change something. With more than one panel, give each its own folder (`~/Backups/home-dashboard-wide`, say).

## Rebuilding from scratch

For a dead SD card or a new Pi. Allow an hour.

1. Flash Raspberry Pi OS Lite (64-bit) onto a card with Raspberry Pi Imager on the Mac. In its settings, set the username to `pi`, your Wi-Fi, and turn on SSH.
2. Log in, then get the code:

   ```bash
   sudo apt update && sudo apt install -y git make
   git clone https://github.com/gkoch02/HomeDashboard.git ~/home-dashboard
   ```

3. Put your backup back before anything is installed or started, from the Mac:

   ```bash
   rsync -a ~/Backups/home-dashboard/ 'pi@<the Pi>:home-dashboard/'
   ```

4. Install, back on the Pi. Your restored `config/config.yaml` is kept, not replaced by the example:

   ```bash
   cd ~/home-dashboard
   make pi-install
   sudo reboot
   ```

   (The reboot is needed the first time, to turn on the panel's connection.) If `git status` now lists `config/quotes.json` as changed and you never edited the quotes, `git checkout -- config/quotes.json` takes the current version instead of the one from your backup.

5. Log in again, check, and start it:

   ```bash
   cd ~/home-dashboard
   make check
   make dry          # draws a test picture to output/latest.png, with made-up data
   make pi-enable    # installs the timer and starts it
   make web-enable   # only if you use the web UI
   make pi-status
   ```

`docs/setup.md` has the long version, including the display drivers and what each step does.

## Things that will break eventually

Left alone, the Pi will run for years. What breaks it is change:

- **A big Raspberry Pi OS upgrade** (a new Debian version) usually brings a new Python, which strands the Python environment. Symptom: every run fails with `No module named` or `python: not found` in `output/dashboard.log`. Fix: rebuild the environment, then run it:

  ```bash
  cd ~/home-dashboard
  rm -rf venv
  make pi-install
  make web-enable        # only if you use the web UI
  sudo systemctl start dashboard.service
  ```

  Routine `sudo apt update && sudo apt upgrade` is safe; it's the jump between major versions that does this. Simplest of all: don't do major upgrades on an appliance that works.

- **The panel's driver library** (Waveshare's or Pimoroni's) changes now and then. `make pi-install` installs the versions this repo was tested with (the files in `constraints/`), so a reinstall brings back a known-good set. `docs/setup.md`, "Reproducible installs", explains it.

- **The services it depends on** change their rules: OpenWeatherMap keys and plans, Google's calendar access, PurpleAir keys. The panel keeps showing the last good data, marked stale, and the log names the source and the error (`401` means the key was refused).

- **The SD card** wears out. A spare card, or the backup above, makes this a 20-minute job instead of an afternoon.

## Small code changes

Settings cover most wishes. When they don't, [`docs/CODE_TOUR.md`](docs/CODE_TOUR.md) explains how the code fits together, and small edits are within reach without knowing Python well, as long as you keep to one change at a time and keep git's safety net.

**The safety net.** On the Pi, in `~/home-dashboard`:

- `git status` lists files you've changed. `output/latest.png` always shows as changed; that's the current picture overwriting the sample kept in the repo, and it's harmless.
- `git diff` shows exactly what you changed.
- `git checkout -- <file>` throws your change to that file away and puts the original back.

**Trying a change without touching the panel.** On the Mac, in your copy of the repo (after `make setup`):

```bash
venv/bin/python -m src.main --dry-run --dummy --theme weather
open output/latest.png
```

That draws the `weather` theme with made-up data to a picture on the Mac. If the picture looks right, the change works.

**Where common things live:**

| To change | Look in |
|---|---|
| A theme's layout or fonts | `src/render/themes/<theme name>.py`; its notes are at the top of the file and in `docs/themes.md` |
| How one part is drawn (the week, the weather, the header) | `src/render/components/<part>.py` |
| The daily quotes | `config/quotes.json`, or better a copy outside the repo named by `quotes.path` in your config, so updates don't overwrite it |

**Getting it onto the Pi.** The quick way is to make the same edit on the Pi itself (`nano ~/home-dashboard/<file>`); the next run uses it. It stays until the next `git pull`, which will refuse to run while your edit is there: `git diff > ~/my-change.patch` saves it, `git checkout -- <file>` clears it, and after the pull `git apply ~/my-change.patch` puts it back (if the file hasn't changed underneath it).

The lasting way is to commit it in the repo on GitHub (on a branch, then a pull request, since `main` is protected), and `git pull` on the Pi. The tests on GitHub will tell you if the change broke something; one of them compares every theme pixel by pixel, so any change to how a theme looks fails it on purpose until its fingerprints are updated.

**Leave alone:**

- `state/`: the renderer and the web UI both write these files, carefully. Delete one to reset it; don't edit it.
- `/etc/systemd/system/dashboard.service`: its time limit and trigger handling are tuned (the comments in `deploy/dashboard.service` say why). Change it with `sudo systemctl edit dashboard.service` so `make pi-enable` doesn't overwrite your change.
- `constraints/`: the tested library versions, regenerated by a tool, never by hand.
