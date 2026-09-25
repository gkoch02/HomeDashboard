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

# --- Google Calendar ---
echo "--- Google Calendar ---"
echo "  Calendar ID looks like: abc123@group.calendar.google.com"
echo "  See README > Google Calendar Setup for service account instructions."
prompt "Calendar ID" "$(current calendar_id)" CALENDAR_ID
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
venv/bin/python - "$CONFIG" "$DISPLAY_PROVIDER" "$DISPLAY_MODEL" "$WEATHER_KEY" "$LAT" "$LON" "$UNITS" "$TIMEZONE" "$CALENDAR_ID" "$PA_KEY" "$PA_SENSOR" <<'PYEOF'
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


text = set_in_section(text, "display", "provider", q(display_provider))
text = set_in_section(text, "display", "model", q(display_model))
text = set_in_section(text, "weather", "api_key", q(weather_key))
text = set_in_section(text, "weather", "latitude", lat)
text = set_in_section(text, "weather", "longitude", lon)
text = set_in_section(text, "weather", "units", q(units))
text = set_scalar(text, "timezone", q(tz))
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

echo ""
echo "--- Google service account credentials ---"
echo ""
echo "  The service account JSON must be downloaded manually from Google Cloud Console."
echo "  See README > Google Calendar Setup for step-by-step instructions."
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

echo ""
echo "==> Validating configuration..."
make check && echo "" && echo "Configuration looks good. Run 'make dry' to preview the dashboard."
