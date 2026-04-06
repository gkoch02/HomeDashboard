/* Dashboard Web UI — vanilla JS, no dependencies */
"use strict";

const STATUS_INTERVAL_MS  = 30_000;  // poll /api/status every 30 s
const IMAGE_INTERVAL_MS   = 60_000;  // refresh dashboard image every 60 s
const LOG_INTERVAL_MS     = 60_000;  // refresh log tail every 60 s

// --------------------------------------------------------------------------
// Utilities
// --------------------------------------------------------------------------

function $(id) { return document.getElementById(id); }

function fmt_age(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes < 1) return "<1 min ago";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  const h = Math.floor(minutes / 60), m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
}

function fmt_seconds(s) {
  if (s === null || s === undefined) return "—";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

function fmt_uptime(s) {
  if (s === null || s === undefined) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function staleness_badge(level) {
  const map = {
    fresh:   ["badge-ok",   "fresh"],
    aging:   ["badge-warn", "aging"],
    stale:   ["badge-bad",  "stale"],
    expired: ["badge-bad",  "expired"],
    unknown: ["badge-unknown", "—"],
  };
  const [cls, label] = map[level] || ["badge-unknown", level || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function breaker_badge(state) {
  const map = {
    closed:    ["badge-ok",   "ok"],
    half_open: ["badge-warn", "half-open"],
    open:      ["badge-bad",  "open"],
  };
  const [cls, label] = map[state] || ["badge-unknown", state || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function bar_class(pct) {
  if (pct >= 90) return "bad";
  if (pct >= 70) return "warn";
  return "";
}

function set_text(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function show_action_msg(msg, ok = true) {
  const el = $("action-msg");
  if (!el) return;
  el.textContent = msg;
  el.className = "action-msg " + (ok ? "action-ok" : "action-err");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.textContent = ""; el.className = "action-msg"; }, 4000);
}

// --------------------------------------------------------------------------
// Status update
// --------------------------------------------------------------------------

function applyStatus(data) {
  // Last run
  set_text("last-run", fmt_seconds(data.seconds_since_run));
  set_text("current-theme", data.current_theme || "—");

  // Quiet hours banner
  const banner = $("quiet-banner");
  if (banner) banner.classList.toggle("visible", !!data.quiet_hours_active);

  // Host metrics
  const h = data.host || {};
  set_text("host-hostname", h.hostname || "—");
  set_text("host-uptime",   fmt_uptime(h.uptime_seconds));
  set_text("host-load",     h.load_1m != null ? h.load_1m.toFixed(2) : "—");
  set_text("host-ip",       h.ip_address || "—");

  if (h.cpu_temp_c != null) {
    set_text("host-temp", `${h.cpu_temp_c.toFixed(1)} °C`);
  }

  if (h.ram_used_mb != null && h.ram_total_mb != null) {
    const pct = Math.round((h.ram_used_mb / h.ram_total_mb) * 100);
    set_text("host-ram", `${Math.round(h.ram_used_mb)} / ${Math.round(h.ram_total_mb)} MB`);
    const bar = $("ram-bar");
    if (bar) { bar.style.width = pct + "%"; bar.className = "bar-fill " + bar_class(pct); }
  }

  if (h.disk_used_gb != null && h.disk_total_gb != null) {
    const pct = Math.round((h.disk_used_gb / h.disk_total_gb) * 100);
    set_text("host-disk", `${h.disk_used_gb.toFixed(1)} / ${h.disk_total_gb.toFixed(1)} GB`);
    const bar = $("disk-bar");
    if (bar) { bar.style.width = pct + "%"; bar.className = "bar-fill " + bar_class(pct); }
  }

  // Sources table — includes Reset/Clear buttons for P2
  const tbody = $("sources-tbody");
  if (tbody && data.sources) {
    tbody.innerHTML = Object.entries(data.sources).map(([name, s]) => `
      <tr>
        <td><strong>${name}</strong></td>
        <td>${breaker_badge(s.breaker_state)}${s.consecutive_failures > 0
          ? ` <span class="text-muted">(${s.consecutive_failures})</span>` : ""}</td>
        <td>${fmt_age(s.cache_age_minutes)}</td>
        <td>${staleness_badge(s.staleness)}</td>
        <td>${s.quota_today ?? "—"}</td>
        <td class="row-actions">
          ${s.breaker_state !== "closed"
            ? `<button class="btn btn-xs" onclick="doResetBreaker('${name}',this)">reset</button>` : ""}
          ${s.cache_age_minutes !== null
            ? `<button class="btn btn-xs" onclick="doClearCache('${name}',this)">clear</button>` : ""}
        </td>
      </tr>
    `).join("");
  }
}

async function refreshStatus() {
  const dot = $("refresh-dot");
  if (dot) dot.classList.add("pulse");
  try {
    const resp = await fetch("/api/status");
    if (!resp.ok) return;
    const data = await resp.json();
    applyStatus(data);
  } catch (_) { /* network error — keep stale UI */ }
  finally {
    if (dot) dot.classList.remove("pulse");
  }
}

// --------------------------------------------------------------------------
// Image refresh
// --------------------------------------------------------------------------

function refreshImage() {
  const img = $("dash-img");
  if (!img) return;
  img.src = "/image/latest?t=" + Date.now();
}

// --------------------------------------------------------------------------
// Log refresh
// --------------------------------------------------------------------------

async function refreshLogs() {
  try {
    const resp = await fetch("/api/logs?lines=100");
    if (!resp.ok) return;
    const data = await resp.json();
    const pre = $("log-output");
    if (pre) pre.textContent = data.lines.join("\n");
  } catch (_) {}
}

// --------------------------------------------------------------------------
// P2 action handlers (status page)
// --------------------------------------------------------------------------

async function doTriggerRefresh(btn) {
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/trigger-refresh", { method: "POST" });
    const data = await resp.json();
    show_action_msg(data.ok ? "Refresh triggered — display will update shortly." : `Error: ${data.error}`, data.ok);
  } catch (_) {
    show_action_msg("Request failed.", false);
  } finally {
    if (btn) setTimeout(() => { btn.disabled = false; }, 3000);
  }
}

async function doResetBreaker(source, btn) {
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/reset-breaker", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const data = await resp.json();
    show_action_msg(data.ok ? `Breaker reset: ${source}` : `Error: ${data.error}`, data.ok);
    if (data.ok) await refreshStatus();
  } catch (_) {
    show_action_msg("Request failed.", false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function doClearCache(source, btn) {
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/clear-cache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const data = await resp.json();
    show_action_msg(data.ok ? `Cache cleared: ${source}` : `Error: ${data.error}`, data.ok);
    if (data.ok) await refreshStatus();
  } catch (_) {
    show_action_msg("Request failed.", false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// --------------------------------------------------------------------------
// P2 Config page
// --------------------------------------------------------------------------

// Parse a textarea value into a trimmed, non-empty string array.
function textarea_to_list(id) {
  const el = $(id);
  if (!el) return [];
  return el.value.split("\n").map(s => s.trim()).filter(Boolean);
}

// Collect all form values and return a flat patch object for POST /api/config.
function collectConfigPatch() {
  const v = (id) => { const el = $(id); return el ? el.value : null; };
  const b = (id) => { const el = $(id); return el ? el.checked : false; };
  const n = (id) => { const val = v(id); return val !== null ? Number(val) : null; };
  const f = (id) => { const val = v(id); return val !== null ? parseFloat(val) : null; };

  const patch = {};

  // Root fields
  if (v("cfg-title")    !== null) patch["title"]     = v("cfg-title");
  if (v("cfg-theme")    !== null) patch["theme"]      = v("cfg-theme");
  if (v("cfg-timezone") !== null) patch["timezone"]   = v("cfg-timezone");
  if (v("cfg-loglevel") !== null) patch["log_level"]  = v("cfg-loglevel");

  // Display
  if ($("cfg-show-weather"))    patch["display.show_weather"]           = b("cfg-show-weather");
  if ($("cfg-show-birthdays"))  patch["display.show_birthdays"]         = b("cfg-show-birthdays");
  if ($("cfg-show-info"))       patch["display.show_info_panel"]        = b("cfg-show-info");
  if ($("cfg-week-days"))       patch["display.week_days"]              = n("cfg-week-days");
  if ($("cfg-partial-refresh")) patch["display.enable_partial_refresh"] = b("cfg-partial-refresh");
  if ($("cfg-max-partials"))    patch["display.max_partials_before_full"] = n("cfg-max-partials");

  // Schedule
  if ($("cfg-qh-start")) patch["schedule.quiet_hours_start"] = n("cfg-qh-start");
  if ($("cfg-qh-end"))   patch["schedule.quiet_hours_end"]   = n("cfg-qh-end");

  // Weather
  if ($("cfg-lat"))   patch["weather.latitude"]  = f("cfg-lat");
  if ($("cfg-lon"))   patch["weather.longitude"] = f("cfg-lon");
  if ($("cfg-units")) patch["weather.units"]     = v("cfg-units");

  // Birthdays
  if ($("cfg-bday-source"))   patch["birthdays.source"]          = v("cfg-bday-source");
  if ($("cfg-bday-lookahead")) patch["birthdays.lookahead_days"] = n("cfg-bday-lookahead");
  if ($("cfg-bday-keyword"))  patch["birthdays.calendar_keyword"] = v("cfg-bday-keyword");

  // Filters
  patch["filters.exclude_calendars"] = textarea_to_list("cfg-excl-calendars");
  patch["filters.exclude_keywords"]  = textarea_to_list("cfg-excl-keywords");
  if ($("cfg-excl-allday")) patch["filters.exclude_all_day"] = b("cfg-excl-allday");

  // Cache
  const cache_fields = [
    ["cfg-wtl",  "cache.weather_ttl_minutes",        n],
    ["cfg-etl",  "cache.events_ttl_minutes",         n],
    ["cfg-btl",  "cache.birthdays_ttl_minutes",      n],
    ["cfg-wfi",  "cache.weather_fetch_interval",     n],
    ["cfg-efi",  "cache.events_fetch_interval",      n],
    ["cfg-bfi",  "cache.birthdays_fetch_interval",   n],
    ["cfg-aqtl", "cache.air_quality_ttl_minutes",    n],
    ["cfg-aqfi", "cache.air_quality_fetch_interval", n],
    ["cfg-mxf",  "cache.max_failures",               n],
    ["cfg-cool", "cache.cooldown_minutes",            n],
    ["cfg-qr",   "cache.quote_refresh",              v],
  ];
  for (const [id, key, coerce] of cache_fields) {
    if ($(id) !== null) { const val = coerce(id); if (val !== null) patch[key] = val; }
  }

  // Random theme
  patch["random_theme.include"] = textarea_to_list("cfg-rt-include");
  patch["random_theme.exclude"] = textarea_to_list("cfg-rt-exclude");

  // Theme schedule — collect rows from the table
  const schedRows = document.querySelectorAll(".schedule-row");
  const schedule = [];
  schedRows.forEach(row => {
    const time  = row.querySelector(".sched-time")?.value?.trim();
    const theme = row.querySelector(".sched-theme")?.value;
    if (time && theme) schedule.push({ time, theme });
  });
  patch["theme_schedule"] = schedule;

  return patch;
}

// Submit config form
async function saveConfig(btn) {
  if (btn) btn.disabled = true;
  const patch = collectConfigPatch();

  const result_el = $("cfg-result");
  if (result_el) result_el.innerHTML = '<span class="text-muted">Saving…</span>';

  try {
    const resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const data = await resp.json();

    if (result_el) {
      if (data.saved) {
        const warn_html = data.warnings.length
          ? `<div class="cfg-warnings">${data.warnings.map(w =>
              `<div>⚠ [${w.field}] ${w.message}${w.hint ? ` — ${w.hint}` : ""}</div>`
            ).join("")}</div>` : "";
        result_el.innerHTML = `<div class="cfg-ok">✓ Saved${warn_html ? " (with warnings)" : ""}</div>${warn_html}`;
      } else {
        const err_html = data.errors.map(e =>
          `<div>✗ [${e.field}] ${e.message}${e.hint ? ` — ${e.hint}` : ""}</div>`
        ).join("");
        const warn_html = data.warnings.map(w =>
          `<div>⚠ [${w.field}] ${w.message}</div>`
        ).join("");
        result_el.innerHTML = `<div class="cfg-errors">${err_html}</div>${warn_html
          ? `<div class="cfg-warnings">${warn_html}</div>` : ""}`;
      }
    }
  } catch (_) {
    if (result_el) result_el.innerHTML = '<div class="cfg-errors">Request failed — check network.</div>';
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Theme grid — clicking a thumbnail updates the hidden input and highlights.
function selectTheme(name) {
  const inp = $("cfg-theme");
  if (inp) inp.value = name;
  document.querySelectorAll(".theme-opt").forEach(el => {
    el.classList.toggle("selected", el.dataset.theme === name);
  });
}

// Theme schedule — add/remove rows
function addScheduleRow(time = "", theme = "") {
  const tbody = $("sched-tbody");
  if (!tbody) return;
  const allThemes = JSON.parse($("all-themes-json")?.textContent || "[]");
  const opts = allThemes.map(t =>
    `<option value="${t}" ${t === theme ? "selected" : ""}>${t}</option>`
  ).join("");
  const tr = document.createElement("tr");
  tr.className = "schedule-row";
  tr.innerHTML = `
    <td><input type="time" class="sched-time" value="${time}" required></td>
    <td><select class="sched-theme">${opts}</select></td>
    <td><button type="button" class="btn btn-xs btn-danger" onclick="this.closest('tr').remove()">✕</button></td>
  `;
  tbody.appendChild(tr);
}

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  refreshStatus();
  refreshLogs();

  setInterval(refreshStatus, STATUS_INTERVAL_MS);
  setInterval(refreshImage,  IMAGE_INTERVAL_MS);
  setInterval(refreshLogs,   LOG_INTERVAL_MS);
});
