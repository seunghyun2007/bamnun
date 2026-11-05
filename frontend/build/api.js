/* The device API (docs/SPEC.md, section 1), for the screens.

   BN_API.profile() / settings()     the cached copy, instantly (the Pi is the
                                     master; the phone keeps a copy so screens
                                     load with no device in reach)
   BN_API.saveProfile(patch)         saved on the phone at once, sent to the
   BN_API.saveSettings(patch)        Pi now or on the next connect
   BN_API.get / post / put(path)     REST on the device
   BN_API.on(type, fn)               device events from /ws: say, calibration,
                                     test_result, trip, reminder, emergency
   BN_API.online()                   connected to a real device

   In the demo (the file opened from disk, or ?demo) there is no device, so a
   small stand-in answers instead: it keeps settings on the phone, plays the
   calibration with a pretend driver, and shows sample trips, all labelled
   as a demo on screen. */
(function () {
  "use strict";
  const DEMO = window.BN_LIVE ? BN_LIVE.demo : true;
  const PROFILE = { name: "", vehicle: "long_haul", work: { days: [true, true, true, true, true, false, false], start: "22:00", end: "06:00", variable: false }, voice_lang: null, app_lang: "en", owl_name: "Ollie" };
  const SETTINGS = { ladder: { mint: true, voice: true }, sensitivity: "normal", volume: "high", break_every_min: 120, break_len_min: 15, co2_alert: true, emergency: { contact_name: "", contact_phone: "", call_services: false, demo: true } };
  const subs = {};

  const load = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); if (v && typeof v === "object") return merge(d, v); } catch (e) {} return JSON.parse(JSON.stringify(d)); };
  const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  function merge(base, patch) {
    const out = JSON.parse(JSON.stringify(base));
    for (const k in patch) {
      if (out[k] && typeof out[k] === "object" && !Array.isArray(out[k]) && patch[k] && typeof patch[k] === "object" && !Array.isArray(patch[k])) out[k] = merge(out[k], patch[k]);
      else out[k] = patch[k];
    }
    return out;
  }

  let profile = load("bn-profile", PROFILE), settings = load("bn-settings", SETTINGS);
  // The name used to live on its own; keep it.
  try { const n = localStorage.getItem("bn-name"); if (n && !profile.name) profile.name = n; } catch (e) {}
  let pending = { profile: load("bn-pending-profile", {}), settings: load("bn-pending-settings", {}) };
  let health = null;

  function base() {
    const host = window.BN_LIVE && BN_LIVE.address ? BN_LIVE.address() : location.host;
    return (location.protocol === "https:" ? "https://" : "http://") + host;
  }
  async function req(method, path, body) {
    if (DEMO) return fake(method, path, body);
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 6000);
    try {
      const r = await fetch(base() + path, { method, signal: ctl.signal,
        headers: body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body) });
      if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (e) {} throw new Error(typeof d === "string" && d ? d : method + " " + path + " " + r.status); }
      return r.status === 204 ? null : r.json();
    } finally { clearTimeout(timer); }
  }

  function emit(m) {
    for (const fn of (subs[m.type] || []).slice()) { try { fn(m); } catch (e) { console.error(e); } }
    for (const fn of (subs["*"] || []).slice()) { try { fn(m); } catch (e) { console.error(e); } }
  }
  // A screen's handler goes away with the screen: ``root`` is its element.
  function on(type, fn, root) {
    (subs[type] = subs[type] || []).push(fn);
    const off = () => { subs[type] = (subs[type] || []).filter((f) => f !== fn); };
    if (root) { const iv = setInterval(() => { if (!root.isConnected) { off(); clearInterval(iv); } }, 1000); }
    return off;
  }

  async function flush() {
    for (const kind of ["profile", "settings"]) {
      const p = pending[kind];
      if (!Object.keys(p).length) continue;
      try {
        const saved = await req("PUT", "/api/" + kind, p);
        pending[kind] = {}; store("bn-pending-" + kind, {});
        apply(kind, saved);
      } catch (e) { return; }
    }
  }
  function apply(kind, saved) {
    if (!saved) return;
    if (kind === "profile") { const vl = profile.voice_lang, oldName = profile.name; profile = merge(PROFILE, saved); if (profile.name !== oldName) { try { localStorage.setItem("bn-name", profile.name); } catch (e) {} setTimeout(() => emit({ type: "name_changed" }), 0); } if (saved.voice_lang && vl === null && !pending.profile.voice_lang) profile.voice_lang = saved.voice_lang; store("bn-profile", profile); }
    else { settings = merge(SETTINGS, saved); store("bn-settings", settings); }
    emit({ type: kind + "_changed" });
    // The Pi's copy is the master; the cloud keeps a copy of it.
    if (window.BN_SYNC) BN_SYNC.profileChanged();
  }
  function save(kind, patch) {
    if (kind === "profile") { profile = merge(profile, patch); store("bn-profile", profile); if ("name" in patch) { try { localStorage.setItem("bn-name", patch.name); } catch (e) {} } }
    else { settings = merge(settings, patch); store("bn-settings", settings); }
    pending[kind] = merge(pending[kind], patch); store("bn-pending-" + kind, pending[kind]);
    flush();
    if (window.BN_SYNC) BN_SYNC.profileChanged();
  }

  // Called by live.js on every (re)connect: send what changed offline, then
  // take the device's copy, which is the master.
  async function onConnect() {
    await flush();
    try {
      health = await req("GET", "/api/health");
      if (!Object.keys(pending.profile).length) apply("profile", await req("GET", "/api/profile"));
      if (!Object.keys(pending.settings).length) apply("settings", await req("GET", "/api/settings"));
      emit({ type: "health", health });
    } catch (e) {}
    // Copy finished trips into the cloud outbox (signed in only).
    if (window.BN_SYNC) BN_SYNC.collect();
  }

  // -- the demo stand-in ------------------------------------------------- //
  const LINES = {
    greet: ["Hi! I'm Ollie. Which language should I speak?", "안녕하세요! 저는 올리예요. 어떤 언어로 말할까요?"],
    sample: ["I'll keep watch while you drive.", "운전하는 동안 제가 지켜볼게요."],
    cal_position: ["Sit like you're driving and look at me.", "운전할 때처럼 앉아서 저를 봐주세요."],
    cal_look: ["Look straight ahead and blink normally.", "정면을 보며 평소처럼 눈을 깜빡이세요."],
    cal_close: ["Now close your eyes… and open.", "이제 눈을 감았다가… 떠주세요."],
    cal_hear: ["Can you hear me?", "제 목소리가 들리세요?"],
    cal_chime: ["That's my wake-up chime.", "이게 깨우는 차임 소리예요."],
    cal_light: ["See the blue light?", "파란 불빛이 보이세요?"],
    cal_mist: ["Mist is coming out now. Smell the mint?", "지금 미스트가 나와요. 민트 향이 나나요?"],
    cal_done: ["All set. I've got your eyes.", "준비 완료. 눈을 잘 익혔어요."],
    emergency_check: ["Are you OK? Say something or tap your phone.", "괜찮으세요? 휴대폰을 눌러주세요."],
  };
  const STEPS = ["position", "look", "close", "speaker", "chime", "light", "mist"];
  const SAY = { position: "cal_position", look: "cal_look", close: "cal_close", speaker: "cal_hear", chime: "cal_chime", light: "cal_light", mist: "cal_mist" };
  const ASK = { speaker: 1, chime: 1, light: 1, mist: 1 };
  let cal = null;
  const later = (fn, ms) => setTimeout(fn, ms);
  function demoSay(line, lang) {
    lang = lang || profile.voice_lang || BN_LANG();
    const t = LINES[line] || [line, line];
    later(() => emit({ type: "say", line, lang, text: lang === "ko" ? t[1] : t[0], result: "simulated" }), 60);
  }
  function calState(extra) {
    return Object.assign({ type: "calibration", active: !!cal && cal.idx < STEPS.length, step: cal && cal.idx < STEPS.length ? STEPS[cal.idx] : null,
      index: cal ? cal.idx : 0, steps: STEPS.concat("done"), results: cal ? cal.results : {}, progress: null, message: "", ask: !!(cal && ASK[STEPS[cal.idx]]) }, extra || {});
  }
  function calEnter(i) {
    if (!cal) return;
    cal.idx = i;
    if (i >= STEPS.length) {
      demoSay("cal_done");
      emit(calState({ active: false, step: null, message: "done", summary: { eye_size: "medium", separation: 0.66, blink_ms: 120, blink_rate: 16,
        wobble: { yaw: 1.5, pitch: 1.2 }, head: { yaw: -6, pitch: 4, roll: 0 }, closed_estimated: false, quality: {} } }));
      cal = null; return;
    }
    const step = STEPS[i], my = cal;
    demoSay(SAY[step]);
    emit(calState());
    if (step === "position") later(() => { if (cal === my) { cal.results.position = "ok"; calEnter(1); } }, 2600);
    if (step === "look") {
      const t0 = Date.now();
      const iv = setInterval(() => {
        if (cal !== my) return clearInterval(iv);
        const p = Math.min(1, (Date.now() - t0) / 12000);
        emit(calState({ progress: p }));
        if (p >= 1) { clearInterval(iv); cal.results.look = "ok"; calEnter(2); }
      }, 400);
    }
    if (step === "close") later(() => { if (cal === my) { cal.results.close = "ok"; calEnter(3); } }, 3200);
  }
  const SAMPLE_PLACES = [["Incheon", "Daejeon"], ["Pyeongtaek", "Busan"], ["Incheon", "Gwangju"], ["Seoul", "Ulsan"], ["Suwon", "Daegu"]];
  function sampleTrips() {
    const now = Date.now() / 1000, out = [];
    for (let i = 0; i < 9; i++) {
      const day = [1, 2, 4, 6, 8, 11, 15, 19, 26][i], dur = 5400 + (i * 2731) % 9000, alerts = [2, 1, 0, 1, 3, 0, 1, 0, 2][i];
      const d = new Date(); d.setDate(d.getDate() - day); d.setHours(21 + (i % 3), (i * 17) % 60, 0, 0);
      const start = d.getTime() / 1000;
      const p = SAMPLE_PLACES[i % SAMPLE_PLACES.length];
      out.push({ id: 100 - i, started_at: start, ended_at: start + dur, open: false, tz_min: -new Date().getTimezoneOffset(),
        summary: { duration_s: dur, drive_s: dur - 900, calm_s: (dur - 900) * (0.86 + 0.012 * i), alerts, breaks: 1 + (i % 2), max_stage: Math.min(4, alerts), microsleeps: alerts > 1 ? 1 : 0, longest_calm_s: 3600 + i * 300 },
        route: { from: p[0], to: p[1], distance_km: Math.round(dur / 3600 * 78) } });
    }
    return out;
  }
  function sampleInsights(range) {
    const trips = sampleTrips().filter((t) => range === "all" || t.started_at > Date.now() / 1000 - (range === "month" ? 30 : 7) * 86400);
    const today = new Date(), per = [];
    for (let i = 6; i >= 0; i--) { const d = new Date(today - i * 86400000); per.push({ date: d.toISOString().slice(0, 10), weekday: (d.getDay() + 6) % 7, alerts: trips.filter((t) => new Date(t.started_at * 1000).toDateString() === d.toDateString()).reduce((a, t) => a + t.summary.alerts, 0), drove: trips.some((t) => new Date(t.started_at * 1000).toDateString() === d.toDateString()) }); }
    const alerts = trips.reduce((a, t) => a + t.summary.alerts, 0);
    const hours = Array(24).fill(0); [3, 3, 4, 2, 3, 5, 1, 4, 3].slice(0, alerts).forEach((h) => hours[h]++);
    return { range, trips: trips.length, alerts, drive_s: trips.reduce((a, t) => a + t.summary.drive_s, 0), alert_free: 0.93, alert_free_prev: 0.89,
      longest_calm_s: 5520, per: range === "week" ? per : weekly(trips), hours, peak_hour: 3, woke_by: [Math.ceil(alerts * 0.6), Math.floor(alerts * 0.3), alerts - Math.ceil(alerts * 0.6) - Math.floor(alerts * 0.3), 0], first_step_enough: Math.ceil(alerts * 0.6), microsleeps: 1, breaks: 9, sample: true };
  }
  function weekly(trips) {
    const out = [], now = Date.now() / 1000;
    for (let i = 4; i >= 0; i--) {
      const ts = trips.filter((t) => t.started_at > now - (i + 1) * 7 * 86400 && t.started_at <= now - i * 7 * 86400);
      out.push({ alerts: ts.reduce((a, t) => a + t.summary.alerts, 0), drove: ts.length > 0 });
    }
    return out;
  }
  async function fake(method, path, body) {
    await new Promise((r) => setTimeout(r, 120));
    if (path === "/api/health") return { device: "bamnun-demo", version: "0.1.0", calibrated: true, simulated: true, parts: { camera: "simulated", ir_light: "simulated", blue_light: "simulated", mist: "simulated", speakers: "simulated", co2: "simulated" }, checks: {} };
    if (path === "/api/profile") return method === "GET" ? profile : merge(profile, body || {});
    if (path === "/api/settings") return method === "GET" ? settings : merge(settings, body || {});
    let m;
    if ((m = path.match(/^\/api\/say\/(\w+)(?:\?lang=(\w+))?/))) { demoSay(m[1], m[2]); return { queued: m[1] }; }
    if ((m = path.match(/^\/api\/test\/(\w+)/))) { later(() => emit({ type: "test_result", part: m[1], result: "simulated" }), 300); return { queued: m[1] }; }
    if (path === "/api/calibration/start") { cal = { idx: 0, results: {} }; calEnter(0); return { queued: "start" }; }
    if (path === "/api/calibration/cancel") { cal = null; emit(calState({ active: false, step: null, message: "cancelled" })); return {}; }
    if (path === "/api/calibration/answer") { if (cal && STEPS[cal.idx] === body.step) { cal.results[body.step] = body.ok ? "ok" : "fail"; const i = cal.idx + 1; later(() => calEnter(i), 200); } return {}; }
    if (path.startsWith("/api/trips/current")) return null;
    if (path.startsWith("/api/trips")) return sampleTrips();
    if (path.startsWith("/api/insights")) return sampleInsights((path.match(/range=(\w+)/) || [0, "week"])[1]);
    return {};
  }

  window.BN_API = {
    demo: DEMO,
    profile: () => profile, settings: () => settings, health: () => health,
    saveProfile: (p) => save("profile", p), saveSettings: (p) => save("settings", p),
    get: (p) => req("GET", p), post: (p, b) => req("POST", p, b === undefined ? {} : b), put: (p, b) => req("PUT", p, b),
    say: (line, lang) => req("POST", "/api/say/" + line + (lang ? "?lang=" + lang : "")).catch(() => null),
    on, emit, onConnect, online: () => DEMO || !!(window.BN_LIVE && BN_LIVE.connected()),
    lines: LINES,
  };
  if (DEMO) setTimeout(() => emit({ type: "health", health: null }), 0);
})();
