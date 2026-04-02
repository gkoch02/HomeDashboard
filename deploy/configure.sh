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

# --- Display model ---
echo "--- Display ---"
echo "  Supported models: epd7in5 epd7in5_V2 epd7in5_V3 epd7in5b_V2 epd7in5_HD epd9in7 epd13in3k"
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
venv/bin/python - <<PYEOF
import re, sys

with open("$CONFIG") as f:
    text = f.read()

def set_scalar(text, key, value, section=None):
    """Replace the first occurrence of 'key: <anything>' (optionally under section)."""
    pattern = r'(?m)^(\s*{key}:\s*).*$'.format(key=re.escape(key))
    replacement = r'\g<1>{value}'.format(value=value)
    new_text, n = re.subn(pattern, replacement, text, count=1)
    if n == 0:
        # Append if not found (shouldn't happen with a valid template)
        new_text = text.rstrip() + "\n{key}: {value}\n".format(key=key, value=value)
    return new_text

# Quote strings, leave numbers bare
def q(v):
    try:
        float(v)
        return v
    except (ValueError, TypeError):
        return '"{}"'.format(v) if v else '""'

text = set_scalar(text, "model", q("$DISPLAY_MODEL"))

# Weather section — api_key appears multiple times; target only the weather one
# We look for the first api_key after the 'weather:' header
lines = text.splitlines(keepends=True)
in_weather = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "weather:":
        in_weather = True
    elif in_weather and re.match(r"^\S", line) and not line.startswith(" ") and stripped != "weather:":
        in_weather = False
    if in_weather and re.match(r"^\s+api_key:", line):
        lines[i] = re.sub(r"(api_key:\s*).*", r"\g<1>" + q("$WEATHER_KEY"), line)
        in_weather = False
text = "".join(lines)

text = set_scalar(text, "latitude", "$LAT")
text = set_scalar(text, "longitude", "$LON")
text = set_scalar(text, "units", q("$UNITS"))
text = set_scalar(text, "timezone", q("$TIMEZONE"))
text = set_scalar(text, "calendar_id", q("$CALENDAR_ID"))

# PurpleAir — only write if provided
pa_key = "$PA_KEY"
pa_sensor = "$PA_SENSOR"
if pa_key:
    # api_key under purpleair section
    lines = text.splitlines(keepends=True)
    in_pa = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "purpleair:":
            in_pa = True
        elif in_pa and re.match(r"^\S", line) and stripped != "purpleair:":
            in_pa = False
        if in_pa and re.match(r"^\s+api_key:", line):
            lines[i] = re.sub(r"(api_key:\s*).*", r"\g<1>" + q(pa_key), line)
            in_pa = False
    text = "".join(lines)

if pa_sensor:
    text = set_scalar(text, "sensor_id", pa_sensor)

with open("$CONFIG", "w") as f:
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
