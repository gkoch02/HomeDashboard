/* Dashboard Web UI — vanilla JS, no dependencies */
"use strict";

const STATUS_INTERVAL_MS  = 30_000;  // poll /api/status every 30 s
const IMAGE_INTERVAL_MS   = 60_000;  // refresh dashboard image every 60 s
const LOG_INTERVAL_MS     = 60_000;  // refresh log tail every 60 s

// Module-level state
let _configDirty = false;  // true when config form has unsaved changes
let _statusCache = {};     // latest /api/status response
let _lastLoadedConfig = null;
let _pendingSavePreview = null;

// --------------------------------------------------------------------------
// Utilities
// --------------------------------------------------------------------------

function $(id) { return document.getElementById(id); }

function csrf_headers(extra = {}) {
  const token = document.querySelector('meta[name="csrf-token"]')?.content || "";
  return { ...extra, "X-CSRF-Token": token };
}

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
  if (el && el.textContent !== String(value ?? "")) el.textContent = value;
}

// Only update innerHTML if it has actually changed — avoids unnecessary layout thrash
function set_html(el, html) {
  if (el && el.innerHTML !== html) el.innerHTML = html;
}

function set_image_state(hasImage) {
  const img = $("dash-img");
  const empty = $("image-empty-note");
  if (img) img.style.display = hasImage ? "block" : "none";
  if (empty) empty.hidden = hasImage;
}

function show_action_msg(msg, ok = true) {
  const el = $("action-msg");
  if (!el) return;
  el.textContent = msg;
  el.className = "action-msg " + (ok ? "action-ok" : "action-err");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.textContent = ""; el.className = "action-msg"; }, 5000);
}

function esc_html(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function overall_badge(severity, status) {
  const map = {
    ok: ["badge-ok", "healthy"],
    warn: ["badge-warn", status === "paused" ? "paused" : "attention"],
    bad: ["badge-bad", "needs attention"],
  };
  const [cls, label] = map[severity] || ["badge-unknown", status || "unknown"];
  return { cls, label };
}

// --------------------------------------------------------------------------
// Dirty-state tracking (config page)
// --------------------------------------------------------------------------

function renderBackupList(backups = []) {
  const el = $("cfg-backups");
  if (!el) return;
  if (!backups.length) {
    el.innerHTML = '<div class="text-muted">No backups yet.</div>';
    return;
  }
  el.innerHTML = backups.map(backup =>
    `<div class="backup-item"><strong>${esc_html(backup.name)}</strong><span class="text-muted">${esc_html(backup.modified_at || '')}</span></div>`
  ).join("");
}

function summarizeChanges(current, baseline, prefix = "") {
  const changes = [];
  const keys = new Set([...Object.keys(current || {}), ...Object.keys(baseline || {})]);
  for (const key of keys) {
    const path = prefix ? `${prefix}.${key}` : key;
    const a = current?.[key];
    const b = baseline?.[key];
    if (JSON.stringify(a) === JSON.stringify(b)) continue;
    const bothObjects = a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b);
    if (bothObjects) {
      changes.push(...summarizeChanges(a, b, path));
    } else {
      changes.push({ field: path, before: b, after: a });
    }
  }
  return changes;
}

function getCurrentChangeList() {
  if (!_lastLoadedConfig) return [];
  return summarizeChanges(collectConfigPatch(), {
    title: _lastLoadedConfig.title,
    theme: _lastLoadedConfig.theme,
    timezone: _lastLoadedConfig.timezone,
    log_level: _lastLoadedConfig.log_level,
    display: _lastLoadedConfig.display,
    schedule: _lastLoadedConfig.schedule,
    weather: _lastLoadedConfig.weather,
    birthdays: _lastLoadedConfig.birthdays,
    filters: _lastLoadedConfig.filters,
    cache: _lastLoadedConfig.cache,
    random_theme: _lastLoadedConfig.random_theme,
    theme_schedule: _lastLoadedConfig.theme_schedule,
  });
}

function updateChangeSummary() {
  const el = $("cfg-change-summary");
  if (!el) return;
  if (!_lastLoadedConfig) {
    el.textContent = "Change summary unavailable until the saved config loads.";
    return;
  }
  const changes = getCurrentChangeList();
  if (!changes.length) {
    el.textContent = "No unsaved changes.";
    return;
  }
  el.innerHTML = `<ul class="change-list">${changes.slice(0, 12).map(change =>
    `<li><strong>${esc_html(change.field)}</strong>: ${esc_html(JSON.stringify(change.before))} → ${esc_html(JSON.stringify(change.after))}</li>`
  ).join("")}</ul>${changes.length > 12 ? `<div class="text-muted">+ ${changes.length - 12} more changes</div>` : ""}`;
}

function setDirty(dirty) {
  _configDirty = dirty;
  const badge = $("dirty-badge");
  if (badge) badge.hidden = !dirty;
  // Toggle all discard buttons (top + bottom)
  document.querySelectorAll(".cfg-discard-btn").forEach(el => { el.hidden = !dirty; });
  updateChangeSummary();
  if (!dirty) {
    // Clear any inline field-error highlights
    document.querySelectorAll("[data-field].field-error").forEach(el => {
      el.classList.remove("field-error");
    });
    document.querySelectorAll(".field-inline-err").forEach(el => el.remove());
  }
}

// --------------------------------------------------------------------------
// Status update
// --------------------------------------------------------------------------

function integrationBadge(status) {
  const map = {
    ok: ["issue-ok", "ready"],
    warn: ["issue-warn", "partial"],
    missing: ["issue-bad", "missing"],
  };
  return map[status] || ["issue-warn", status || "unknown"];
}

function formatEventTime(ts) {
  if (!ts) return "unknown time";
  try {
    return new Date(ts).toLocaleString();
  } catch (_) {
    return ts;
  }
}

function buildTroubleshootingItems(data) {
  const items = [];

  if (!data.web_auth_enabled) {
    items.push({ severity: "bad", text: "Auth is disabled. Anyone on your LAN can open this UI." });
  }
  if (data.quiet_hours_active) {
    items.push({ severity: "warn", text: `Quiet hours are active until ${data.quiet_hours_end}:00.` });
  }
  if (data.seconds_since_run === null || data.seconds_since_run === undefined) {
    items.push({ severity: "warn", text: "No successful dashboard run has been recorded yet." });
  } else if (data.seconds_since_run > 7200 && !data.quiet_hours_active) {
    items.push({ severity: "warn", text: "The dashboard may be behind; last successful run was over 2 hours ago." });
  }

  Object.entries(data.sources || {}).forEach(([name, source]) => {
    if (source.breaker_state === "open") {
      items.push({ severity: "bad", text: `${name}: breaker is open — check failures, then reset it.` });
    } else if (source.staleness === "expired") {
      items.push({ severity: "bad", text: `${name}: cached data is expired — run a refresh now.` });
    } else if (source.staleness === "unknown") {
      items.push({ severity: "warn", text: `${name}: no cached data yet — first successful fetch may still be pending.` });
    }
  });

  if (!items.length) {
    items.push({ severity: "ok", text: "Nothing obvious is broken. If the display still looks wrong, check the recent log for render-specific errors." });
  }
  return items.slice(0, 5);
}

function applyStatus(data) {
  _statusCache = data;

  // Last run
  set_text("last-run", fmt_seconds(data.seconds_since_run));
  set_text("current-theme", data.current_theme || "—");
  set_image_state(true);

  // Health summary / banners
  const banner = $("quiet-banner");
  if (banner) banner.classList.toggle("visible", !!data.quiet_hours_active);
  const authBanner = $("auth-banner");
  if (authBanner) authBanner.classList.toggle("visible", !data.web_auth_enabled);

  if (data.overall) {
    const badge = $("overall-badge");
    const title = $("overall-title");
    const detail = $("overall-detail");
    const issues = $("overall-issues");
    const healthCard = $("health-card");
    const summary = overall_badge(data.overall.severity, data.overall.status);
    if (badge) {
      badge.className = `badge ${summary.cls}`;
      badge.textContent = summary.label;
    }
    if (title) title.textContent = data.overall.title || "Dashboard";
    if (detail) detail.textContent = data.overall.detail || "";
    if (healthCard) {
      healthCard.classList.remove("health-ok", "health-warn", "health-bad");
      healthCard.classList.add(
        data.overall.severity === "bad" ? "health-bad" :
        data.overall.severity === "warn" ? "health-warn" : "health-ok"
      );
    }
    if (issues) {
      const issueHtml = (data.overall.issues || []).length
        ? data.overall.issues.map(issue =>
            `<div class="issue-chip issue-${issue.severity || 'warn'}">${issue.kind}: ${issue.message}</div>`
          ).join("")
        : '<div class="issue-chip issue-ok">No immediate issues.</div>';
      set_html(issues, issueHtml);
    }
  }

  // Quiet hours context hint (config page)
  const qhHint = $("qh-status-hint");
  if (qhHint) {
    const active = data.quiet_hours_active;
    const s = data.quiet_hours_start ?? "?";
    const e = data.quiet_hours_end   ?? "?";
    qhHint.textContent = active
      ? `Currently active — display refresh paused until ${e}:00`
      : `Currently inactive — window is ${s}:00 – ${e}:00`;
    qhHint.style.color = active ? "var(--warn)" : "var(--text-muted)";
  }

  // Theme resolution / troubleshooting
  if (data.theme_info) {
    set_text("theme-mode", data.theme_info.mode || "—");
    set_text("theme-effective", data.theme_info.effective_theme || "—");
    set_text("theme-configured", data.theme_info.configured_theme || "—");
    const next = data.theme_info.next_scheduled_change;
    set_text("theme-next", next ? `${next.time} → ${next.theme}` : "none");
    set_text("theme-detail", data.theme_info.detail || "");
  }

  const integrations = $("integration-list");
  if (integrations) {
    const rows = data.integrations || [];
    set_html(integrations, rows.length
      ? rows.map(item => {
          const [cls, label] = integrationBadge(item.status);
          return `<div class="integration-item"><div><strong>${esc_html(item.name)}</strong><div class="text-muted" style="font-size:11px; margin-top:2px;">${esc_html(item.detail || "")}</div></div><span class="issue-chip ${cls}">${esc_html(label)}</span></div>`;
        }).join("")
      : '<div class="text-muted">No integration data.</div>');
  }

  const events = $("recent-events");
  if (events) {
    const rows = data.recent_events || [];
    set_html(events, rows.length
      ? rows.map(item => `<div class="event-item"><div><strong>${esc_html(item.message || item.kind || "event")}</strong><div class="text-muted" style="font-size:11px; margin-top:2px;">${esc_html(formatEventTime(item.timestamp))}</div></div><span class="event-kind">${esc_html(item.kind || "event")}</span></div>`).join("")
      : '<div class="text-muted">No recent events yet.</div>');
  }

  const troubleshoot = $("troubleshoot-list");
  if (troubleshoot) {
    set_html(troubleshoot, buildTroubleshootingItems(data).map(item =>
      `<div class="troubleshoot-item troubleshoot-${item.severity}">${esc_html(item.text)}</div>`
    ).join(""));
  }

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
    if (bar) {
      bar.className = "bar-fill " + bar_class(pct);
      bar.style.width = "0%";
      requestAnimationFrame(() => { bar.style.width = pct + "%"; });
    }
  }

  if (h.disk_used_gb != null && h.disk_total_gb != null) {
    const pct = Math.round((h.disk_used_gb / h.disk_total_gb) * 100);
    set_text("host-disk", `${h.disk_used_gb.toFixed(1)} / ${h.disk_total_gb.toFixed(1)} GB`);
    const bar = $("disk-bar");
    if (bar) {
      bar.className = "bar-fill " + bar_class(pct);
      bar.style.width = "0%";
      requestAnimationFrame(() => { bar.style.width = pct + "%"; });
    }
  }

  // Sources table — includes Reset/Clear buttons for P2
  const tbody = $("sources-tbody");
  if (tbody && data.sources) {
    set_html(tbody, Object.entries(data.sources).map(([name, s]) => `
      <tr>
        <td data-label="Source"><strong>${esc_html(name)}</strong></td>
        <td data-label="Breaker">${breaker_badge(s.breaker_state)}${s.consecutive_failures > 0
          ? ` <span class="text-muted">(${s.consecutive_failures})</span>` : ""}</td>
        <td data-label="Cache Age">${fmt_age(s.cache_age_minutes)}</td>
        <td data-label="Staleness">${staleness_badge(s.staleness)}</td>
        <td data-label="API Calls">${s.quota_today ?? "—"}</td>
        <td data-label="Summary">
          <div><strong>${esc_html(s.summary?.message || "—")}</strong></div>
          <div class="text-muted" style="font-size:11px; margin-top:2px;">${esc_html(s.summary?.detail || "")}</div>
        </td>
        <td data-label="Actions" class="row-actions">
          ${s.breaker_state !== "closed"
            ? `<button class="btn btn-xs" onclick="doResetBreaker('${name}',this)">reset</button>` : ""}
          ${s.cache_age_minutes !== null
            ? `<button class="btn btn-xs" onclick="doClearCache('${name}',this)">clear</button>` : ""}
        </td>
      </tr>
    `).join(""));
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
  // Pre-load into a hidden Image object; only swap src once fully loaded to
  // avoid the brief blank flash that occurs when setting src directly.
  const newSrc = "/image/latest?t=" + Date.now();
  const tmp = new Image();
  tmp.onload = () => { img.src = newSrc; set_image_state(true); };
  tmp.onerror = () => set_image_state(false);
  tmp.src = newSrc;
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
    const wrap = pre?.closest(".log-wrap");
    if (!pre) return;
    const newText = data.lines.join("\n");
    if (pre.textContent === newText) return;  // no change — skip DOM write
    // Preserve scroll: if the user is near the bottom, stay there after update
    const atBottom = wrap && (wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 60);
    pre.textContent = newText;
    if (wrap && atBottom) wrap.scrollTop = wrap.scrollHeight;
  } catch (_) {}
}

// --------------------------------------------------------------------------
// P2 action handlers (status page)
// --------------------------------------------------------------------------

async function doTriggerRefresh(btn) {
  if (_statusCache.quiet_hours_active) {
    const s = _statusCache.quiet_hours_start ?? "?";
    const e = _statusCache.quiet_hours_end   ?? "?";
    if (!confirm(
      `Quiet hours are active (${s}:00 – ${e}:00).\n` +
      `The dashboard will exit immediately when triggered. Proceed anyway?`
    )) return;
  }
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/trigger-refresh", {
      method: "POST",
      headers: csrf_headers(),
    });
    const data = await resp.json();
    show_action_msg(
      data.ok ? "Refresh triggered — waiting for the next render to land." : `Error: ${data.error}`,
      data.ok
    );
    if (data.ok) {
      setTimeout(refreshStatus, 1500);
      setTimeout(refreshLogs, 2000);
    }
  } catch (_) {
    show_action_msg("Request failed.", false);
  } finally {
    if (btn) setTimeout(() => { btn.disabled = false; }, 3000);
  }
}

async function doResetBreaker(source, btn) {
  if (!confirm(
    `Reset circuit breaker for "${source}"?\nThis clears failure state and re-enables fetching.`
  )) return;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/reset-breaker", {
      method: "POST",
      headers: csrf_headers({ "Content-Type": "application/json" }),
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
  if (!confirm(
    `Clear cached data for "${source}"?\nThe next refresh will re-fetch live data.`
  )) return;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/clear-cache", {
      method: "POST",
      headers: csrf_headers({ "Content-Type": "application/json" }),
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
  if ($("cfg-bday-source"))    patch["birthdays.source"]           = v("cfg-bday-source");
  if ($("cfg-bday-lookahead")) patch["birthdays.lookahead_days"]   = n("cfg-bday-lookahead");
  if ($("cfg-bday-keyword"))   patch["birthdays.calendar_keyword"] = v("cfg-bday-keyword");

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

// Populate all config form fields from a GET /api/config response object.
function populateConfigForm(data) {
  const set_val = (id, val) => { const el = $(id); if (el && val != null) el.value = val; };
  const set_chk = (id, val) => { const el = $(id); if (el) el.checked = !!val; };
  const set_ta  = (id, arr) => { const el = $(id); if (el) el.value = (arr || []).join("\n"); };

  _lastLoadedConfig = data;
  set_val("cfg-title",    data.title);
  set_val("cfg-timezone", data.timezone);
  set_val("cfg-loglevel", data.log_level);

  const d = data.display || {};
  set_chk("cfg-show-weather",    d.show_weather);
  set_chk("cfg-show-birthdays",  d.show_birthdays);
  set_chk("cfg-show-info",       d.show_info_panel);
  set_val("cfg-week-days",       d.week_days);
  set_chk("cfg-partial-refresh", d.enable_partial_refresh);
  set_val("cfg-max-partials",    d.max_partials_before_full);

  const s = data.schedule || {};
  set_val("cfg-qh-start", s.quiet_hours_start);
  set_val("cfg-qh-end",   s.quiet_hours_end);

  const w = data.weather || {};
  set_val("cfg-lat",   w.latitude);
  set_val("cfg-lon",   w.longitude);
  set_val("cfg-units", w.units);

  const bday = data.birthdays || {};
  set_val("cfg-bday-source",    bday.source);
  set_val("cfg-bday-lookahead", bday.lookahead_days);
  set_val("cfg-bday-keyword",   bday.calendar_keyword);

  const flt = data.filters || {};
  set_chk("cfg-excl-allday",    flt.exclude_all_day);
  set_ta("cfg-excl-calendars",  flt.exclude_calendars);
  set_ta("cfg-excl-keywords",   flt.exclude_keywords);

  const c = data.cache || {};
  set_val("cfg-wtl",  c.weather_ttl_minutes);
  set_val("cfg-wfi",  c.weather_fetch_interval);
  set_val("cfg-etl",  c.events_ttl_minutes);
  set_val("cfg-efi",  c.events_fetch_interval);
  set_val("cfg-btl",  c.birthdays_ttl_minutes);
  set_val("cfg-bfi",  c.birthdays_fetch_interval);
  set_val("cfg-aqtl", c.air_quality_ttl_minutes);
  set_val("cfg-aqfi", c.air_quality_fetch_interval);
  set_val("cfg-mxf",  c.max_failures);
  set_val("cfg-cool", c.cooldown_minutes);
  set_val("cfg-qr",   c.quote_refresh);

  const rt = data.random_theme || {};
  set_ta("cfg-rt-include", rt.include);
  set_ta("cfg-rt-exclude", rt.exclude);

  // Rebuild schedule table rows
  const tbody = $("sched-tbody");
  if (tbody) {
    tbody.innerHTML = "";
    (data.theme_schedule || []).forEach(e => addScheduleRow(e.time, e.theme));
  }

  // Sync theme dropdown and grid
  if (data.theme) {
    const inp = $("cfg-theme");
    if (inp) inp.value = data.theme;
    if (typeof syncThemeGrid === "function") syncThemeGrid(data.theme);
  }
  renderBackupList(data.backups || []);
  updateChangeSummary();
}

// Discard unsaved config changes by reloading form from the server.
async function discardConfig() {
  if (_configDirty && !confirm("Discard all unsaved changes?")) return;
  try {
    const resp = await fetch("/api/config");
    if (!resp.ok) throw new Error("fetch failed");
    const data = await resp.json();
    populateConfigForm(data);
    setDirty(false);
    const result_el = $("cfg-result");
    if (result_el) {
      result_el.innerHTML = '<span class="text-muted">Reverted to last saved values.</span>';
      setTimeout(() => { if (result_el) result_el.innerHTML = ""; }, 3000);
    }
  } catch (_) {
    const result_el = $("cfg-result");
    if (result_el) result_el.innerHTML =
      '<div class="cfg-errors">Could not load saved config — check network.</div>';
  }
}

function openSavePreview(opts = {}) {
  const dialog = $("save-preview-dialog");
  const body = $("save-preview-body");
  const confirmBtn = $("save-preview-confirm");
  if (!dialog || !body || !confirmBtn) {
    saveConfig(opts.triggerButton || null, opts);
    return;
  }

  const changes = getCurrentChangeList();
  if (!changes.length) {
    const result_el = $("cfg-result");
    if (result_el) result_el.innerHTML = '<span class="text-muted">No changes to save.</span>';
    return;
  }

  body.innerHTML = `
    <div class="save-preview-meta">${opts.refreshAfterSave ? 'Save + Refresh' : 'Save'} will apply <strong>${changes.length}</strong> change${changes.length === 1 ? '' : 's'}.</div>
    <ul class="save-preview-list">
      ${changes.map(change => `
        <li>
          <div class="save-preview-field">${esc_html(change.field)}</div>
          <div class="save-preview-values">
            <div><span class="text-muted">Before:</span> <code>${esc_html(JSON.stringify(change.before))}</code></div>
            <div><span class="text-muted">After:</span> <code>${esc_html(JSON.stringify(change.after))}</code></div>
          </div>
        </li>
      `).join("")}
    </ul>
  `;

  _pendingSavePreview = opts;
  confirmBtn.textContent = opts.refreshAfterSave ? "Confirm save + refresh" : "Confirm save";
  confirmBtn.onclick = async () => {
    closeSavePreview();
    await saveConfig(opts.triggerButton || null, opts);
  };
  dialog.showModal();
}

function closeSavePreview() {
  const dialog = $("save-preview-dialog");
  if (dialog?.open) dialog.close();
  _pendingSavePreview = null;
}

// Submit config form
async function saveConfig(btn, opts = {}) {
  if (btn) btn.disabled = true;
  const patch = collectConfigPatch();

  // Client-side: check for duplicate times in theme schedule before sending.
  const times = (patch.theme_schedule || []).map(e => e.time);
  const dupes = times.filter((t, i) => times.indexOf(t) !== i);
  if (dupes.length) {
    const result_el = $("cfg-result");
    if (result_el) result_el.innerHTML =
      `<div class="cfg-errors">✗ Duplicate schedule times: ${[...new Set(dupes)].join(", ")}</div>`;
    if (btn) btn.disabled = false;
    return;
  }

  const result_el = $("cfg-result");
  if (result_el) result_el.innerHTML = '<span class="text-muted">Saving…</span>';

  // Clear previous inline error highlights
  document.querySelectorAll("[data-field].field-error").forEach(el => {
    el.classList.remove("field-error");
  });
  document.querySelectorAll(".field-inline-err").forEach(el => el.remove());

  try {
    const resp = await fetch("/api/config", {
      method: "POST",
      headers: csrf_headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(patch),
    });
    const data = await resp.json();

    if (result_el) {
      if (data.saved) {
        setDirty(false);
        const warn_html = data.warnings.length
          ? `<div class="cfg-warnings">${data.warnings.map(w =>
              `<div>⚠ [${w.field}] ${w.message}${w.hint ? ` — ${w.hint}` : ""}</div>`
            ).join("")}</div>` : "";
        result_el.innerHTML =
          `<div class="cfg-ok">✓ Saved${warn_html ? " (with warnings)" : ""}</div>${warn_html}`;
        _lastLoadedConfig = await (await fetch("/api/config")).json();
        renderBackupList(data.backups || _lastLoadedConfig.backups || []);
        updateChangeSummary();
        if (opts.refreshAfterSave) {
          const refreshResp = await fetch("/api/trigger-refresh", {
            method: "POST",
            headers: csrf_headers(),
          });
          const refreshData = await refreshResp.json();
          result_el.innerHTML += refreshData.ok
            ? '<div class="cfg-ok" style="margin-top:.35rem;">↻ Refresh requested.</div>'
            : `<div class="cfg-warnings" style="margin-top:.35rem;">Refresh could not be requested: ${refreshData.error || 'unknown error'}</div>`;
        }
      } else {
        // Highlight individual fields that have errors
        data.errors.forEach(e => {
          const el = document.querySelector(`[data-field="${e.field}"]`);
          if (el) {
            el.classList.add("field-error");
            const msg = document.createElement("div");
            msg.className = "field-inline-err";
            msg.textContent = e.message + (e.hint ? ` — ${e.hint}` : "");
            el.closest(".field-input-wrap")?.appendChild(msg);
          }
        });
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
    if (result_el) result_el.innerHTML =
      '<div class="cfg-errors">Request failed — check network.</div>';
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveAndRefresh(btn) {
  await saveConfig(btn, { refreshAfterSave: true });
}

async function restoreLatestBackup(btn) {
  if (!confirm("Restore the most recent config backup? This will overwrite the current config file.")) return;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/config/restore-latest", {
      method: "POST",
      headers: csrf_headers(),
    });
    const data = await resp.json();
    const result_el = $("cfg-result");
    if (data.restored) {
      const refreshed = await (await fetch("/api/config")).json();
      populateConfigForm(refreshed);
      setDirty(false);
      if (result_el) result_el.innerHTML = `<div class="cfg-ok">✓ ${esc_html(data.message)}</div>`;
    } else if (result_el) {
      result_el.innerHTML = `<div class="cfg-errors">${esc_html(data.message || 'Could not restore backup.')}</div>`;
    }
  } catch (_) {
    const result_el = $("cfg-result");
    if (result_el) result_el.innerHTML = '<div class="cfg-errors">Request failed while restoring backup.</div>';
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Theme grid — clicking a thumbnail updates the hidden input and highlights.
function selectTheme(name) {
  const inp = $("cfg-theme");
  if (inp) {
    inp.value = name;
    setDirty(true);
  }
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
    <td data-label="Time"><input type="time" class="sched-time" value="${time}" required></td>
    <td data-label="Theme"><select class="sched-theme">${opts}</select></td>
    <td data-label=""><button type="button" class="btn btn-xs btn-danger" onclick="this.closest('tr').remove()">✕</button></td>
  `;
  tbody.appendChild(tr);
}

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const savePreview = $("save-preview-dialog");
  if (savePreview) {
    savePreview.addEventListener("click", e => { if (e.target === savePreview) closeSavePreview(); });
  }

  // Hamburger menu toggle (mobile nav)
  const hamburger = $("nav-hamburger");
  const navLinks  = $("nav-links");
  const mainNav   = $("main-nav");
  if (hamburger && navLinks) {
    hamburger.addEventListener("click", e => {
      e.stopPropagation();
      const open = navLinks.classList.toggle("open");
      hamburger.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", e => {
      if (mainNav && !mainNav.contains(e.target)) {
        navLinks.classList.remove("open");
        hamburger.setAttribute("aria-expanded", "false");
      }
    });
    // Close on link click (navigation)
    navLinks.querySelectorAll("a").forEach(a => {
      a.addEventListener("click", () => {
        navLinks.classList.remove("open");
        hamburger.setAttribute("aria-expanded", "false");
      });
    });
  }

  refreshStatus();
  refreshLogs();

  setInterval(refreshStatus, STATUS_INTERVAL_MS);
  setInterval(refreshImage,  IMAGE_INTERVAL_MS);
  setInterval(refreshLogs,   LOG_INTERVAL_MS);

  // Dirty tracking: attach delegated listeners on the config form card.
  if ($("cfg-result") !== null) {
    // Fetch the saved config to initialise _lastLoadedConfig so that
    // getCurrentChangeList() can diff form values against the baseline.
    // The form is already populated server-side, so we don't re-render it.
    fetch("/api/config")
      .then(r => r.json())
      .then(data => { _lastLoadedConfig = data; updateChangeSummary(); })
      .catch(() => {});

    const card = document.querySelector(".card");
    if (card) {
      card.addEventListener("input",  () => setDirty(true));
      card.addEventListener("change", () => setDirty(true));
    }
  }

  // Warn before leaving the page with unsaved config changes.
  window.addEventListener("beforeunload", e => {
    if (_configDirty) { e.preventDefault(); e.returnValue = ""; }
  });
});
