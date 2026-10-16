"use strict";
// OneVoice Sender UI. Talks to the Python controller through pywebview's js_api.
// Opened in a normal browser as index.html?demo, it runs an animated preview with
// sample data so the design can be checked without audio hardware.

const $ = (id) => document.getElementById(id);
const STATE_TEXT = {
  stopped: ["Not streaming", "Ready", "Choose your input, then start streaming."],
  connecting: ["Connecting…", "Connecting", "Reaching the caption server…"],
  standby: ["Connected · standby", "Standby", "Connected. Captions start automatically at service time."],
  live: ["LIVE", "Live", "Sending audio to live captions."],
  retry_wait: ["Reconnecting", "Reconnecting", "Connection lost. Retrying automatically…"],
  revoked: ["Revoked", "Sender revoked", "Create a new token in the admin dashboard."],
};

let api = null;
let state = null;
let streaming = false;
let testing = false;
let peak = { db: -120, until: 0 };
let clipUntil = 0;
let toastTimer = null;

function toast(message, isError = false) {
  const t = $("toast");
  t.textContent = message;
  t.className = isError ? "toast error" : "toast";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 4200);
}

async function call(method, ...args) {
  try {
    return await api[method](...args);
  } catch (e) {
    const msg = (e && (e.message || e.toString())) || "Something went wrong";
    toast(msg.replace(/^.*UserError:\s*/, ""), true);
    throw e;
  }
}

// ---------------------------------------------------------------- dropdowns
// Native <select> popups don't open reliably in the translucent macOS webview, so each
// <select> stays as the hidden data model and gets an HTML dropdown on top.
function enhanceSelect(sel) {
  const wrap = document.createElement("div");
  wrap.className = "dropdown";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dropdown-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  if (sel.getAttribute("aria-labelledby")) btn.setAttribute("aria-labelledby", sel.getAttribute("aria-labelledby"));
  const list = document.createElement("ul");
  list.className = "dropdown-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  sel.hidden = true;
  sel.after(wrap);
  wrap.append(btn, list);

  const label = () => {
    const o = sel.options[sel.selectedIndex];
    btn.textContent = o ? o.text : "";
    btn.disabled = sel.disabled || sel.options.length === 0;
  };
  const close = () => {
    list.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  };
  const choose = (value) => {
    if (sel.value !== value) {
      sel.value = value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    label();
    close();
    btn.focus();
  };
  const open = () => {
    list.replaceChildren();
    for (const o of sel.options) {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.tabIndex = -1;
      li.textContent = o.text;
      li.dataset.value = o.value;
      li.setAttribute("aria-selected", String(o.value === sel.value));
      if (!o.value) li.classList.add("placeholder");
      li.addEventListener("click", () => choose(o.value));
      list.append(li);
    }
    list.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    (list.querySelector('[aria-selected="true"]') || list.firstElementChild)?.focus();
  };
  btn.addEventListener("click", () => (list.hidden ? open() : close()));
  btn.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      open();
    }
  });
  list.addEventListener("keydown", (e) => {
    const items = [...list.children];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") items[Math.min(i + 1, items.length - 1)]?.focus();
    else if (e.key === "ArrowUp") items[Math.max(i - 1, 0)]?.focus();
    else if (e.key === "Enter" || e.key === " ") { if (i >= 0) choose(items[i].dataset.value); }
    else if (e.key === "Escape" || e.key === "Tab") { close(); if (e.key === "Escape") btn.focus(); return; }
    else return;
    e.preventDefault();
  });
  document.addEventListener("pointerdown", (e) => { if (!wrap.contains(e.target)) close(); });
  new MutationObserver(label).observe(sel, { childList: true });
  sel.refreshLabel = label;
  label();
}

// ---------------------------------------------------------------- settings form
function fillDevices(devices, selectedKey) {
  const sel = $("device");
  sel.replaceChildren();
  const empty = new Option(devices.length ? "Select an input…" : "No input devices found", "");
  sel.add(empty);
  for (const d of devices) {
    const opt = new Option(`${d.name}  ·  ${d.hostapi}  ·  ${d.channels} ch`, d.key);
    sel.add(opt);
  }
  sel.value = devices.some((d) => d.key === selectedKey) ? selectedKey : "";
  sel.refreshLabel?.();
  fillChannels();
}

function fillChannels(selected) {
  const dev = state.devices.find((d) => d.key === $("device").value);
  const sel = $("channel");
  const current = selected ?? Number(sel.value || state.config.channel || 1);
  sel.replaceChildren();
  const n = dev ? dev.channels : 1;
  for (let i = 1; i <= n; i++) sel.add(new Option(`Channel ${i}`, String(i)));
  sel.value = String(Math.min(Math.max(1, current), n));
  sel.refreshLabel?.();
}

function setRate(rate) {
  for (const b of $("rates").querySelectorAll("button")) b.setAttribute("aria-checked", String(Number(b.dataset.rate) === Number(rate)));
}

function currentRate() {
  const b = $("rates").querySelector('button[aria-checked="true"]');
  return b ? Number(b.dataset.rate) : 16000;
}

function headerRow(name = "", saved = false) {
  const row = document.createElement("div");
  row.className = "header-row";
  const n = Object.assign(document.createElement("input"), { type: "text", placeholder: "Header name", value: name });
  const v = Object.assign(document.createElement("input"), { type: "password", placeholder: saved ? "•••• saved (leave blank to keep)" : "Value" });
  const del = Object.assign(document.createElement("button"), { type: "button", className: "icon-btn", ariaLabel: "Remove header" });
  del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  del.addEventListener("click", () => row.remove());
  row.append(n, v, del);
  $("headers").append(row);
}

function collectHeaders() {
  const out = {};
  for (const row of $("headers").querySelectorAll(".header-row")) {
    const [n, v] = row.querySelectorAll("input");
    if (n.value.trim()) out[n.value.trim()] = v.value;
  }
  return out;
}

function setTokenBadge(has) {
  const b = $("tokenBadge");
  b.textContent = has ? "Token saved" : "No token";
  b.classList.toggle("ok", has);
}

async function updateUrlWarning() {
  const url = $("serverUrl").value.trim();
  const hint = url ? await api.url_warning(url) : null;
  $("urlWarn").hidden = !hint;
  $("urlWarn").textContent = hint ? hint.text : "";
  $("urlWarn").classList.toggle("warn", !!(hint && hint.warn));
}

function settingsPayload() {
  return {
    server_url: $("serverUrl").value.trim(),
    token: $("token").value.trim(),
    device_key: $("device").value,
    channel: Number($("channel").value || 1),
    sample_rate: currentRate(),
    gain_db: Number($("gain").value),
    auto_start_stream: $("autoStart").checked,
    headers: collectHeaders(),
  };
}

async function save(quiet = false) {
  const r = await call("save_settings", settingsPayload());
  $("token").value = "";
  setTokenBadge(r.has_token);
  $("headers").replaceChildren();
  for (const name of r.header_names) headerRow(name, true);
  if (!quiet) {
    $("savedNote").hidden = false;
    setTimeout(() => ($("savedNote").hidden = true), 2000);
  }
}

// ---------------------------------------------------------------- live status
function fmtDuration(since, now) {
  if (!since) return "—";
  let s = Math.max(0, Math.floor(now - since));
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(s).padStart(2, "0")}s`;
}

function applyStatus(p) {
  const st = p.status;
  streaming = st.streaming;
  testing = st.testing;
  const key = STATE_TEXT[st.state] ? st.state : "stopped";
  const [pill, title, detail] = STATE_TEXT[key];
  $("statePill").dataset.state = key;
  $("orb").dataset.state = key;
  $("stateText").textContent = pill;
  $("heroTitle").textContent = title;
  let d = detail;
  if (key === "retry_wait" && st.retry_at) d = `Connection lost. Retrying in ${Math.max(0, Math.round(st.retry_at - p.now))} s…`;
  $("heroDetail").textContent = d;

  const btn = $("streamBtn");
  btn.textContent = streaming ? "Stop streaming" : "Start streaming";
  btn.classList.toggle("stop", streaming);
  $("testBtn").textContent = testing ? "Stop test" : "Test input";
  $("testBtn").disabled = streaming;
  for (const el of document.querySelectorAll("#settingsForm input, #settingsForm select, #settingsForm button")) {
    if (el.id === "gain") continue;
    el.disabled = streaming;
  }
  $("lockedNote").hidden = !streaming;

  $("statCampus").textContent = st.campus || "—";
  $("statSince").textContent = fmtDuration(st.connected_since, p.now);
  $("statSent").textContent = st.bytes_sent ? `${(st.bytes_sent / 1e6).toFixed(1)} MB` : "—";
  $("statReconnects").textContent = String(st.reconnects ?? 0);

  const alert = $("alert");
  const msg = st.last_error || st.warning;
  alert.hidden = !msg;
  alert.className = st.last_error ? "alert" : "alert warn";
  alert.textContent = msg || "";

  // level meter
  const now = performance.now();
  const lv = p.levels;
  const pos = (db) => Math.max(0, Math.min(100, ((db + 60) / 60) * 100));
  if (lv) {
    $("meterFill").style.clipPath = `inset(0 ${100 - pos(lv.rms)}% 0 0 round 999px)`;
    if (lv.peak >= peak.db || now > peak.until) peak = { db: lv.peak, until: now + 1500 };
    if (lv.clipped) clipUntil = now + 2000;
    $("levelText").textContent = `${lv.rms.toFixed(1)} dBFS`;
    $("levelHint").textContent =
      lv.peak <= -119 ? "Digital silence: check the Dante subscription / input channel." : lv.rms < -45 ? "Very quiet: raise the gain or check the channel." : "Aim for −30 to −12 dBFS while someone speaks.";
  } else if (!p.capturing) {
    $("meterFill").style.clipPath = "inset(0 100% 0 0 round 999px)";
    $("levelText").textContent = "— dBFS";
    peak = { db: -120, until: 0 };
  }
  $("meterPeak").style.left = `calc(${pos(peak.db)}% - 2px)`;
  $("meterPeak").style.opacity = p.capturing && peak.db > -60 ? "1" : "0";
  $("clip").classList.toggle("on", now < clipUntil);

  if (p.log && p.log.length) {
    const el = $("log");
    el.textContent = (el.textContent + p.log.join("\n") + "\n").split("\n").slice(-400).join("\n");
    el.scrollTop = el.scrollHeight;
  }
}

async function pollLoop() {
  try {
    applyStatus(await api.poll());
  } catch {
    /* window closing */
  }
  setTimeout(pollLoop, 100);
}

// ---------------------------------------------------------------- wiring
async function init() {
  state = await api.initial_state();
  enhanceSelect($("device"));
  enhanceSelect($("channel"));
  document.body.classList.toggle("vibrant", !!state.vibrant);
  $("version").textContent = `Version ${state.app.version} · live audio for captions`;
  const c = state.config;
  $("serverUrl").value = c.server_url || "";
  setTokenBadge(state.has_token);
  fillDevices(state.devices, c.device_key);
  fillChannels(c.channel);
  setRate(c.sample_rate);
  $("gain").value = String(c.gain_db);
  $("gainText").textContent = `${Number(c.gain_db).toFixed(1)} dB`;
  $("autoStart").checked = !!c.auto_start_stream;
  $("launchAtLogin").checked = !!c.launch_at_login;
  $("launchAtLogin").disabled = !state.autostart_supported;
  if (state.web) {
    // Raspberry Pi: streaming runs on the Pi from boot; this page only sets it up.
    $("launchAtLoginRow").hidden = true;
    $("autoStartText").textContent = "Start streaming whenever the Pi starts";
    $("tokenNote").textContent = "Stored on the Pi, readable only by OneVoice Sender.";
    $("signOut").hidden = false;
    $("signOut").addEventListener("click", async () => {
      await fetch("/logout", { method: "POST", headers: { "X-OneVoice": "1", "Content-Type": "application/json" }, body: "{}" });
      location.href = "/login";
    });
  }
  for (const name of c.header_names) headerRow(name, true);
  await updateUrlWarning();

  $("device").addEventListener("change", () => fillChannels(1));
  $("refreshDevices").addEventListener("click", async () => {
    state.devices = await call("refresh_devices");
    fillDevices(state.devices, $("device").value);
  });
  $("rates").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) setRate(b.dataset.rate);
  });
  $("gain").addEventListener("input", () => {
    $("gainText").textContent = `${Number($("gain").value).toFixed(1)} dB`;
    api.set_gain(Number($("gain").value));
  });
  $("serverUrl").addEventListener("change", updateUrlWarning);
  $("showToken").addEventListener("click", () => {
    const t = $("token");
    t.type = t.type === "password" ? "text" : "password";
  });
  $("addHeader").addEventListener("click", () => headerRow());
  $("launchAtLogin").addEventListener("change", async (e) => {
    try {
      e.target.checked = await call("set_launch_at_login", e.target.checked);
    } catch {
      e.target.checked = !e.target.checked;
    }
  });
  $("settingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    await save();
  });
  $("testBtn").addEventListener("click", async () => {
    await save(true);
    await call("toggle_test");
  });
  $("streamBtn").addEventListener("click", async () => {
    if (streaming) await call("stop_streaming");
    else {
      await save(true);
      await call("start_streaming");
    }
  });

  pollLoop();
  if (state.should_autostart) setTimeout(() => call("start_streaming").catch(() => {}), 800);
}

// ---------------------------------------------------------------- Raspberry Pi (web interface)
// Same methods as the desktop js_api, as POST /api/<method> to the Pi.
function httpApi() {
  return new Proxy({}, {
    get: (_t, method) => async (...args) => {
      const res = await fetch(`/api/${String(method)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-OneVoice": "1" },
        body: JSON.stringify({ args }),
      });
      if (res.status === 401) {
        location.href = "/login";
        throw new Error("Signed out");
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
      return data.result;
    },
  });
}

// ---------------------------------------------------------------- preview mode (plain browser)
function demoApi() {
  const t0 = Date.now() / 1000 - 1520;
  let live = true;
  return {
    initial_state: async () => ({
      app: { name: "OneVoice Sender", version: "1.4.0" },
      devices: [
        { key: "Core Audio::Dante Virtual Soundcard", name: "Dante Virtual Soundcard", hostapi: "Core Audio", channels: 16, rate: 48000 },
        { key: "Core Audio::MacBook Pro Microphone", name: "MacBook Pro Microphone", hostapi: "Core Audio", channels: 1, rate: 48000 },
      ],
      config: { server_url: "captions.example.org", device_key: "Core Audio::Dante Virtual Soundcard", channel: 3, sample_rate: 16000, gain_db: 2, auto_start_stream: true, launch_at_login: true, header_names: [] },
      has_token: true,
      autostart_supported: true,
      should_autostart: false,
    }),
    poll: async () => {
      const now = Date.now() / 1000;
      const wobble = Math.sin(now * 3.1) * 7 + Math.sin(now * 7.3) * 4;
      return {
        status: live
          ? { state: "live", streaming: true, testing: false, campus: "downtown", connected_since: t0, bytes_sent: 48.6e6, reconnects: 1 }
          : { state: "stopped", streaming: false, testing: false },
        levels: live ? { rms: -21 + wobble, peak: -11 + wobble / 2, clipped: false } : null,
        capturing: live,
        log: [],
        now,
      };
    },
    save_settings: async () => ({ has_token: true, header_names: [] }),
    refresh_devices: async () => [],
    url_warning: async () => null,
    set_gain: async () => {},
    set_launch_at_login: async (v) => v,
    toggle_test: async () => true,
    start_streaming: async () => { live = true; },
    stop_streaming: async () => { live = false; },
  };
}

// The preview only runs when asked for (index.html?demo). The desktop app can take
// several seconds to attach its API, so never fall back to sample data on a timer.
function start(withApi) {
  if (api) return;
  api = withApi;
  init();
}
if (new URLSearchParams(location.search).has("demo")) start(demoApi());
else if (document.querySelector('meta[name="onevoice-backend"][content="http"]')) start(httpApi());
else if (window.pywebview && window.pywebview.api && window.pywebview.api.initial_state) start(window.pywebview.api);
else window.addEventListener("pywebviewready", () => start(window.pywebview.api));
