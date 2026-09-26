#!/usr/bin/env bash
# Interactive configuration wizard for Home Dashboard.
# Run via: make configure
# Safe to re-run — existing values are shown as defaults.

set -euo pipefail

CONFIG="config/config.yaml"

if [ ! -f "$CONFIG" ]; then
  cp config/config.example.yaml "$CONFIG"
fi

# ---------------------------------------------------------------------------
# Helper: read current value from config, strip quotes
# ---------------------------------------------------------------------------
current() {
  local key="$1"
  grep -m1 "^\s*${key}:" "$CONFIG" 2>/dev/null \
    | sed 's/.*:\s*//' | tr -d '"' | xargs || true
}

# Read a value scoped to a YAML section (e.g. current_in purpleair api_key)
current_in() {
  local section="$1" key="$2"
  awk -v sec="$section" -v k="$key" '
    /^[^ #]/ { in_sec = ($0 ~ "^"sec":") }
    in_sec && $0 ~ "^[ \t]+"k":" {
      sub(/.*:[ \t]*/, ""); gsub(/"/, ""); print; exit
    }
  ' "$CONFIG" 2>/dev/null | xargs || true
}

prompt() {
  local label="$1" default="$2" varname="$3"
  if [ -n "$default" ]; then
    read -rp "  ${label} [${default}]: " val
    val="${val:-$default}"
  else
    read -rp "  ${label}: " val
  fi
  eval "$varname=\$val"
}

echo ""
echo "======================================"
echo "  Home Dashboard — Configuration"
echo "======================================"
echo ""
echo "Press Enter to keep the current value shown in [brackets]."
echo ""

# --- Display provider/model ---
echo "--- Display ---"
echo "  Providers: waveshare, inky"
echo "  Waveshare models: epd7in5 epd7in5_V2 epd7in5b_V2 epd7in5_HD epd13in3k epd10in85g"
echo "  Inky models: impression_7_3_2025"
prompt "Display provider" "$(current provider)" DISPLAY_PROVIDER
prompt "Display model" "$(current model)" DISPLAY_MODEL
echo ""

# --- Weather ---
echo "--- Weather (openweathermap.org — free API key) ---"
prompt "OpenWeatherMap API key" "$(current api_key)" WEATHER_KEY
prompt "Latitude" "$(current latitude)" LAT
prompt "Longitude" "$(current longitude)" LON
prompt "Units (imperial/metric)" "$(current units)" UNITS
echo ""

# --- Timezone ---
echo "--- Timezone ---"
echo "  Use an IANA name (e.g. America/New_York) or \"local\" for system clock."
prompt "Timezone" "$(current timezone)" TIMEZONE
echo ""

# --- Calendar source ---
# Default to whichever source the config already uses (CalDAV > ICS > Google,
# the same precedence the fetcher applies).
if [ -n "$(current_in google caldav_url)" ]; then
  CAL_DEFAULT="caldav"
elif [ -n "$(current_in google ical_url)" ]; then
  CAL_DEFAULT="ics"
else
  CAL_DEFAULT="google"
fi
echo "--- Calendar ---"
echo "  ics    — a calendar's secret iCal address; no Google Cloud project needed"
echo "           (recommended for most setups)"
echo "  caldav — Nextcloud / Radicale / iCloud / Fastmail / any CalDAV server"
echo "  google — Google Calendar API with a service account"
echo "  See docs/setup.md for each option."
CAL_SOURCE=""
while :; do
  prompt "Calendar source (ics/caldav/google)" "$CAL_DEFAULT" CAL_SOURCE
  case "$CAL_SOURCE" in
    ics|caldav|google) break ;;
    *) echo "  Please answer ics, caldav or google." ;;
  esac
done
CALENDAR_ID="" ICAL_URL="" CALDAV_URL="" CALDAV_USER="" CALDAV_PW_FILE="" CALDAV_CAL_URL=""
case "$CAL_SOURCE" in
  google)
    echo "  Calendar ID looks like: abc123@group.calendar.google.com"
    prompt "Calendar ID" "$(current_in google calendar_id)" CALENDAR_ID
    ;;
  ics)
    echo "  Google Calendar: Settings → [calendar] → \"Secret address in iCal format\"."
    prompt "ICS feed URL" "$(current_in google ical_url)" ICAL_URL
    ;;
  caldav)
    prompt "CalDAV URL" "$(current_in google caldav_url)" CALDAV_URL
    prompt "CalDAV username" "$(current_in google caldav_username)" CALDAV_USER
    pw_default="$(current_in google caldav_password_file)"
    prompt "CalDAV password file" "${pw_default:-credentials/caldav_password.txt}" CALDAV_PW_FILE
    # The specific-calendar URL wins over discovery, so one left from another
    # server would keep the fetch pointed there. Offer the current one only
    # when the server is unchanged; "-" clears it.
    cal_default=""
    if [ "$CALDAV_URL" = "$(current_in google caldav_url)" ]; then
      cal_default="$(current_in google caldav_calendar_url)"
    fi
    echo "  Specific calendar URL is optional — leave empty (or \"-\") to use the first calendar."
    prompt "CalDAV calendar URL" "$cal_default" CALDAV_CAL_URL
    [ "$CALDAV_CAL_URL" = "-" ] && CALDAV_CAL_URL=""
    ;;
esac
echo ""

# --- PurpleAir (optional) ---
echo "--- PurpleAir AQI (optional — press Enter to skip) ---"
echo "  Free API key at develop.purpleair.com"
echo "  Find sensor ID at map.purpleair.com (click sensor → check URL)"
prompt "PurpleAir API key" "$(current_in purpleair api_key)" PA_KEY
prompt "PurpleAir sensor ID" "$(current_in purpleair sensor_id)" PA_SENSOR
echo ""

# ---------------------------------------------------------------------------
# Write values into config.yaml using Python for reliable YAML editing
# ---------------------------------------------------------------------------
venv/bin/python - "$CONFIG" "$DISPLAY_PROVIDER" "$DISPLAY_MODEL" "$WEATHER_KEY" "$LAT" "$LON" "$UNITS" "$TIMEZONE" "$CALENDAR_ID" "$PA_KEY" "$PA_SENSOR" \
  "$CAL_SOURCE" "$ICAL_URL" "$CALDAV_URL" "$CALDAV_USER" "$CALDAV_PW_FILE" "$CALDAV_CAL_URL" <<'PYEOF'
import re
import sys

config_path = sys.argv[1]
display_provider = sys.argv[2]
display_model = sys.argv[3]
weather_key = sys.argv[4]
lat = sys.argv[5]
lon = sys.argv[6]
units = sys.argv[7]
tz = sys.argv[8]
calendar_id = sys.argv[9]
pa_key = sys.argv[10]
pa_sensor = sys.argv[11]
# Calendar source and its settings. Optional so the writer still runs with the
# eleven arguments older callers pass: that is the Google API path.
extra = sys.argv[12:18] + [""] * (6 - len(sys.argv[12:18]))
cal_source = extra[0] or "google"
ical_url, caldav_url, caldav_user, caldav_pw_file, caldav_cal_url = extra[1:]

with open(config_path) as f:
    text = f.read()


class ConfigWriteError(SystemExit):
    """A target key could not be located: refuse rather than append a stray one.

    set_scalar used to append `key: value` at the end of the file when the key
    was missing, which for a section-scoped key like purpleair.sensor_id
    produced a top-level key the parser ignores while the wizard reported
    success (#265).
    """

    def __init__(self, message):
        super().__init__("  ERROR: {} — config/config.yaml was NOT modified.".format(message))


def q(v):
    """Quote strings, leave numbers bare."""
    try:
        float(v)
        return v
    except (ValueError, TypeError):
        return '"{}"'.format(v.replace("\\", "\\\\").replace('"', '\\"')) if v else '""'


def set_scalar(text, key, value):
    """Replace the first `key: <anything>` in the file, or fail loudly."""
    pattern = r"(?m)^(\s*{key}:\s*).*$".format(key=re.escape(key))
    new_text, n = re.subn(pattern, lambda m: m.group(1) + value, text, count=1)
    if n == 0:
        raise ConfigWriteError("could not find '{}:' in the config".format(key))
    return new_text


def section_span(lines, section):
    """Return (start, end) line indices of an uncommented top-level section."""
    start = None
    for i, line in enumerate(lines):
        if start is None:
            if line.strip() == section + ":" and not line.startswith((" ", "\t")):
                start = i
        elif line.strip() and not line.startswith((" ", "\t", "#")):
            return start, i
    return (start, len(lines)) if start is not None else None


def set_in_section(text, section, key, value):
    """Replace `key:` inside the top-level `section:` block, or fail loudly."""
    lines = text.splitlines(keepends=True)
    span = section_span(lines, section)
    if span is None:
        raise ConfigWriteError("could not find the '{}:' section".format(section))
    for i in range(*span):
        if re.match(r"^\s+{}:".format(re.escape(key)), lines[i]):
            lines[i] = re.sub(r"({}:\s*).*".format(re.escape(key)), lambda m: m.group(1) + value, lines[i], count=1)
            return "".join(lines)
    raise ConfigWriteError("could not find '{}:' under '{}:'".format(key, section))


def ensure_section(text, section, defaults):
    """Make `section:` a live block.

    The template ships optional sections commented out (`# purpleair:` and its
    `#   key:` lines) so a placeholder key can't trip the circuit breaker on
    every run. If the block is present but commented, strip the comment
    prefix from it; if it is missing altogether, append a fresh block from
    *defaults*. Either way the section's keys can then be set normally.
    """
    lines = text.splitlines(keepends=True)
    if section_span(lines, section) is not None:
        return text
    header = re.compile(r"^#\s*{}:\s*(#.*)?$".format(re.escape(section)))
    for i, line in enumerate(lines):
        if header.match(line):
            lines[i] = section + ":\n"
            j = i + 1
            while j < len(lines) and re.match(r"^#(\s+\S|\s*$)", lines[j]):
                body = re.sub(r"^#\s?", "", lines[j], count=1)
                # A doubled comment (`#   # Get a free key…`) stays a comment.
                lines[j] = body if body.strip() else "\n"
                j += 1
            return "".join(lines)
    block = section + ":\n" + "".join("  {}: {}\n".format(k, v) for k, v in defaults)
    return text.rstrip("\n") + "\n\n" + block


def enable_in_section(text, section, key, value):
    """Set `key:` in `section:`, uncommenting the template's `# key:` line if needed.

    The template ships the ICS and CalDAV keys commented out under `google:`;
    a live key is replaced, a commented one is brought to life in place, and a
    missing one is added at the end of the section.
    """
    lines = text.splitlines(keepends=True)
    span = section_span(lines, section)
    if span is None:
        raise ConfigWriteError("could not find the '{}:' section".format(section))
    live = re.compile(r"^(\s+){}:".format(re.escape(key)))
    commented = re.compile(r"^(\s*)#\s*{}:".format(re.escape(key)))
    for i in range(*span):
        if live.match(lines[i]):
            return set_in_section(text, section, key, value)
    for i in range(*span):
        m = commented.match(lines[i])
        if m:
            lines[i] = "{}{}: {}\n".format(m.group(1) or "  ", key, value)
            return "".join(lines)
    end = span[1]
    while end > span[0] + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, "  {}: {}\n".format(key, value))
    return "".join(lines)


def disable_in_section(text, section, key):
    """Comment out a live `key:` in `section:` so a lower-precedence source wins."""
    lines = text.splitlines(keepends=True)
    span = section_span(lines, section)
    if span is None:
        return text
    live = re.compile(r"^(\s+)({}:.*)$".format(re.escape(key)), re.S)
    for i in range(*span):
        m = live.match(lines[i])
        if m:
            lines[i] = "{}# {}".format(m.group(1), m.group(2))
    return "".join(lines)


text = set_in_section(text, "display", "provider", q(display_provider))
text = set_in_section(text, "display", "model", q(display_model))
text = set_in_section(text, "weather", "api_key", q(weather_key))
text = set_in_section(text, "weather", "latitude", lat)
text = set_in_section(text, "weather", "longitude", lon)
text = set_in_section(text, "weather", "units", q(units))
text = set_scalar(text, "timezone", q(tz))

# Calendar source. The fetcher takes CalDAV over ICS over the Google API, so
# choosing a lower-precedence source has to switch the higher ones off, or a
# previous answer would keep winning.
if cal_source == "caldav":
    text = enable_in_section(text, "google", "caldav_url", q(caldav_url))
    text = enable_in_section(text, "google", "caldav_username", q(caldav_user))
    text = enable_in_section(text, "google", "caldav_password_file", q(caldav_pw_file))
    # fetch_from_caldav() uses this ahead of discovery: an empty answer must
    # switch off a URL left from a previous server, not leave it in force.
    if caldav_cal_url:
        text = enable_in_section(text, "google", "caldav_calendar_url", q(caldav_cal_url))
    else:
        text = disable_in_section(text, "google", "caldav_calendar_url")
elif cal_source == "ics":
    for key in ("caldav_url", "caldav_username", "caldav_password_file", "caldav_calendar_url"):
        text = disable_in_section(text, "google", key)
    text = enable_in_section(text, "google", "ical_url", q(ical_url))
else:
    for key in (
        "caldav_url",
        "caldav_username",
        "caldav_password_file",
        "caldav_calendar_url",
        "ical_url",
    ):
        text = disable_in_section(text, "google", key)
    text = set_in_section(text, "google", "calendar_id", q(calendar_id))

# PurpleAir — only written when a value was given; the section stays off otherwise.
# Both keys are always written once the section is live: uncommenting the
# template block and then replacing only the supplied value left the other
# placeholder ("YOUR_PURPLEAIR_API_KEY" or sensor 12345) in force, and both are
# truthy, so the source fetched with a bogus key every run.
if pa_key or pa_sensor:
    text = ensure_section(
        text, "purpleair", [("api_key", q(pa_key)), ("sensor_id", pa_sensor or "0")]
    )
    text = set_in_section(text, "purpleair", "api_key", q(pa_key))
    text = set_in_section(text, "purpleair", "sensor_id", pa_sensor or "0")
    if not (pa_key and pa_sensor):
        print(
            "  NOTE: PurpleAir needs both an API key and a sensor ID; the source stays "
            "off until the missing one is set in config/config.yaml."
        )

with open(config_path, "w") as f:
    f.write(text)

print("  config/config.yaml updated.")
PYEOF

if [ "$CAL_SOURCE" = "google" ]; then
  echo ""
  echo "--- Google service account credentials ---"
  echo ""
  echo "  The service account JSON must be downloaded manually from Google Cloud Console."
  echo "  See docs/setup.md > Google Calendar Setup for step-by-step instructions."
  echo ""
  echo "  Expected path: credentials/service_account.json"
  echo ""
  if [ -f "credentials/service_account.json" ]; then
    echo "  ✓ credentials/service_account.json already present."
  else
    read -rp "  Press Enter when the file is in place (or Ctrl-C to do it later)..." _
    if [ -f "credentials/service_account.json" ]; then
      echo "  ✓ Found credentials/service_account.json"
    else
      echo "  WARNING: credentials/service_account.json not found."
      echo "  Calendar data will not load until it is added."
    fi
  fi
elif [ "$CAL_SOURCE" = "caldav" ] && [ ! -f "$CALDAV_PW_FILE" ]; then
  echo ""
  echo "  NOTE: $CALDAV_PW_FILE does not exist yet. Put the account password in it"
  echo "  (one line, chmod 600) — see docs/setup.md > CalDAV, Step 2."
fi

echo ""
echo "==> Validating configuration..."
make check && echo "" && echo "Configuration looks good. Run 'make dry' to preview the dashboard."
