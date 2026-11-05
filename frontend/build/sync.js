/* Cloud sync: the phone carries data between the Pi and Supabase.

   The Pi has no internet in the truck, so it stays the source of truth while
   driving. The phone does the carrying:

     Pi  --(hotspot Wi-Fi)-->  phone outbox  --(any internet, later)-->  Supabase

   - On every connect to the Pi (and when a trip ends) the phone copies each
     finished trip, with its events, into an outbox kept in localStorage.
   - Whenever it can reach Supabase it uploads the outbox. A trip's key is
     (user, device_uid, device_trip_id) and every write is an upsert on that
     key, so sending a trip twice updates the same row: no duplicates, and
     nothing is lost if the upload fails half way.
   - The profile and settings are uploaded after each change, and downloaded
     at sign-in, so a new phone gets them back (and passes them to the Pi).
   - Trips and Insights read from Supabase when signed in, so history
     survives a new phone, with the Pi (and the outbox) filling in whatever
     hasn't been uploaded yet.

   Video never comes here: the Pi never sends it to the phone's storage. */
(function () {
  "use strict";
  const A = () => window.BN_ACCOUNT, API = () => window.BN_API;
  const read = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v && typeof v === "object" ? v : d; } catch (e) { return d; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  const iso = (s) => (s == null ? null : new Date(s * 1000).toISOString());
  const secs = (t) => (t == null ? null : Date.parse(t) / 1000);
  const MAX_EVENTS = 500;

  let flushing = null, profileTimer = null, cloudCache = null;
  let status = { state: "idle", at: null, error: null };   // for Settings

  const uid = () => { const u = A() && A().user(); return u ? u.id : null; };
  // Everything kept per user, so a second account on the phone never
  // uploads the first one's trips. "Start over" leaves these alone.
  const box = (u) => read("bn-sync-out-" + u, { trips: {}, events: {}, devices: {}, profile: false });
  const saveBox = (u, b) => write("bn-sync-out-" + u, b);
  const done = (u) => read("bn-sync-done-" + u, {});
  const saveDone = (u, d) => write("bn-sync-done-" + u, d);
  function setStatus(state, error) { status = { state, at: Date.now(), error: error || null }; if (API()) API().emit({ type: "sync", status }); }

  // -- profile -------------------------------------------------------------- //
  function profileRow(extra) {
    const p = API().profile(), s = API().settings(), u = A().user();
    return Object.assign({
      user_id: u.id, email: u.email, name: (p.name || "").slice(0, 20), owl_name: "Ollie",
      vehicle: p.vehicle, work: p.work, voice_lang: p.voice_lang || null, app_lang: window.BN_LANG ? BN_LANG() : p.app_lang || "en",
      settings: s,
    }, extra || {});
  }
  function profileChanged() {
    const u = uid(); if (!u) return;
    const b = box(u); b.profile = true; saveBox(u, b);
    clearTimeout(profileTimer); profileTimer = setTimeout(flush, 1500);
  }
  function markOnboarded() {
    try { localStorage.setItem("bn-onboarded", "1"); } catch (e) {}
    const u = uid(); if (!u) return;
    const b = box(u); b.profile = true; b.onboarded = true; saveBox(u, b);
    flush();
  }
  const onboarded = () => { try { return localStorage.getItem("bn-onboarded") === "1"; } catch (e) { return false; } };

  // Just signed in: a returning driver gets their saved profile back (and the
  // Pi gets it on the next connect); a new one starts setup. Returns the
  // screen to go to.
  // ``keepPhone``: signing in from Settings on a phone that's already set
  // up, so its answers become the account's. Otherwise (from Welcome) a new
  // account always goes through setup, whatever this phone or the Pi knew.
  async function afterSignIn(setLang, opts) {
    opts = opts || {};
    const u = A().user();
    const rows = await A().rest("GET", "profiles?select=*&user_id=eq." + encodeURIComponent(u.id));
    const row = rows && rows[0];
    if (row && row.onboarded) {
      const patch = { name: row.name || "", vehicle: row.vehicle };
      if (row.work && Object.keys(row.work).length) patch.work = row.work;
      if (row.voice_lang) patch.voice_lang = row.voice_lang;
      if (row.app_lang) { patch.app_lang = row.app_lang; if (setLang) setLang(row.app_lang); }
      API().saveProfile(patch);
      if (row.settings && Object.keys(row.settings).length) API().saveSettings(row.settings);
      try { localStorage.setItem("bn-onboarded", "1"); } catch (e) {}
      const b = box(u.id); b.profile = false; saveBox(u.id, b);
      flush();
      return "Home";
    }
    if (opts.keepPhone) {
      await A().rest("POST", "profiles?on_conflict=user_id", profileRow({ onboarded: true }), "resolution=merge-duplicates,return=minimal");
      try { localStorage.setItem("bn-onboarded", "1"); } catch (e) {}
      flush();
      return "Settings";
    }
    // New account (or setup never finished): setup from the start, with the
    // name field empty. The empty name also goes to the Pi, so its old
    // driver's name doesn't come back on the next connect.
    try { localStorage.removeItem("bn-onboarded"); } catch (e) {}
    API().saveProfile({ name: "" });
    await A().rest("POST", "profiles?on_conflict=user_id", profileRow({ onboarded: false }), "resolution=merge-duplicates,return=minimal");
    const b = box(u.id); b.profile = false; saveBox(u.id, b);
    flush();
    return "Meet";
  }

  // -- Pi -> outbox ----------------------------------------------------------- //
  function deviceUid(h) { return h && (h.device_id || (h.device ? "host-" + h.device : null)); }

  function tripRow(u, dev, t) {
    const s = t.summary || {}, r = t.route || null;
    const byStage = [0, 0, 0, 0];
    for (const e of s.episodes || []) { const k = Math.min(4, Math.max(1, +e.max_stage || 1)); byStage[k - 1]++; }
    const num = (v) => (v == null || isNaN(+v) ? null : +v);
    return {
      user_id: u, device_uid: dev, device_trip_id: t.id,
      started_at: iso(t.started_at), ended_at: iso(t.ended_at), tz_min: t.tz_min || 0,
      start_place: (r && r.from) || null,
      end_place: (r && r.to) || null,
      distance_km: r && (r.distance_km != null ? num(r.distance_km) : r.distance_m != null ? Math.round(r.distance_m / 100) / 10 : null),
      route: r ? Object.assign({}, r, { path: undefined, cum: undefined }) : null,
      duration_s: num(s.duration_s), drive_s: num(s.drive_s), calm_s: num(s.calm_s), alert_free: num(s.alert_free),
      alerts: s.alerts || 0, alerts_by_stage: byStage, max_stage: s.max_stage || 0, microsleeps: s.microsleeps || 0,
      longest_calm_s: num(s.longest_calm_s), breaks: s.breaks || 0, break_s: num(s.break_s), co2_max: num(s.co2_max),
      emergencies: s.emergencies || 0, summary: s,
    };
  }
  function eventRows(u, dev, t) {
    const seen = new Set(), out = [];
    for (const e of (t.events || []).slice(-MAX_EVENTS)) {
      const at = iso(e.at), k = at + "|" + e.kind;
      if (!at || seen.has(k)) continue;   // one upsert can't touch a row twice
      seen.add(k);
      const data = Object.assign({}, e); delete data.at; delete data.kind;
      out.push({ user_id: u, device_uid: dev, device_trip_id: t.id, at, kind: e.kind,
        stage: e.stage == null ? null : +e.stage, reason: e.reason || e.why || e.kind,
        lat: e.lat == null ? null : +e.lat, lng: e.lng == null ? null : +e.lng, data });
    }
    return out;
  }

  let collecting = false;
  async function collect() {
    const u = uid();
    if (!u || collecting || API().demo || !API().online()) return;
    const h = API().health(), dev = deviceUid(h);
    if (!dev) return;
    collecting = true;
    try {
      const b = box(u), d = done(u);
      b.devices[dev] = { user_id: u, device_uid: dev, name: h.device || null, version: h.version || null, last_seen: new Date().toISOString() };
      saveBox(u, b);
      const list = await API().get("/api/trips?limit=500");
      for (const t of list || []) {
        if (t.open || t.ended_at == null) continue;          // still driving: next time
        const key = dev + ":" + t.id;
        if ((d[key] != null && Math.abs(d[key] - t.ended_at) < 0.01) || b.trips[key]) continue;  // already sent, or waiting
        let full;
        try { full = await API().get("/api/trips/" + t.id); } catch (e) { break; }
        const nb = box(u);
        nb.trips[key] = tripRow(u, dev, full);
        nb.events[key] = eventRows(u, dev, full);
        saveBox(u, nb);
      }
    } catch (e) { /* the Pi went away; the rest next time */ }
    finally { collecting = false; }
    flush();
  }

  // -- outbox -> Supabase ------------------------------------------------------ //
  async function flush() {
    if (flushing) return flushing;
    const u = uid();
    if (!u) return;
    flushing = (async () => {
      const b = box(u);
      const nTrips = Object.keys(b.trips).length;
      if (!b.profile && !nTrips && !Object.keys(b.devices).length) return;
      setStatus("syncing");
      try {
        const devs = Object.values(b.devices);
        if (devs.length) await A().rest("POST", "devices?on_conflict=user_id,device_uid", devs, "resolution=merge-duplicates,return=minimal");
        let nb = box(u); for (const k of devs.map((x) => x.device_uid)) delete nb.devices[k]; saveBox(u, nb);

        if (b.profile) {
          await A().rest("POST", "profiles?on_conflict=user_id", profileRow(b.onboarded ? { onboarded: true } : {}), "resolution=merge-duplicates,return=minimal");
          nb = box(u); nb.profile = false; delete nb.onboarded; saveBox(u, nb);
        }

        // Trips in small batches; each batch's events after its trips (the
        // events point at their trip).
        const keys = Object.keys(b.trips);
        for (let i = 0; i < keys.length; i += 20) {
          const part = keys.slice(i, i + 20);
          await A().rest("POST", "trips?on_conflict=user_id,device_uid,device_trip_id", part.map((k) => b.trips[k]), "resolution=merge-duplicates,return=minimal");
          const ev = [].concat(...part.map((k) => b.events[k] || []));
          for (let j = 0; j < ev.length; j += 500)
            await A().rest("POST", "alert_events?on_conflict=user_id,device_uid,device_trip_id,at,kind", ev.slice(j, j + 500), "resolution=merge-duplicates,return=minimal");
          nb = box(u); const d = done(u);
          for (const k of part) { d[k] = secs(b.trips[k].ended_at); delete nb.trips[k]; delete nb.events[k]; }
          saveBox(u, nb); saveDone(u, d);
        }
        cloudCache = null;
        setStatus("done");
      } catch (e) {
        // Offline: everything is still in the outbox for next time.
        setStatus(e.offline || e.name === "AbortError" || e instanceof TypeError ? "offline" : "error", e.message);
      }
    })().finally(() => { flushing = null; });
    return flushing;
  }

  // -- reading: cloud + outbox + Pi ------------------------------------------- //
  function fromCloud(r) {
    return { id: r.device_uid + ":" + r.device_trip_id, started_at: secs(r.started_at), ended_at: secs(r.ended_at),
      tz_min: r.tz_min || 0, open: false, summary: r.summary || {}, route: r.route, cloud: true };
  }
  async function cloudTrips() {
    if (cloudCache && Date.now() - cloudCache.at < 30000) return cloudCache.list;
    const rows = await A().rest("GET", "trips?select=device_uid,device_trip_id,started_at,ended_at,tz_min,summary,route&order=started_at.desc&limit=1000");
    const list = (rows || []).map(fromCloud);
    cloudCache = { at: Date.now(), list };
    return list;
  }
  function outboxTrips(u) {
    return Object.values(box(u).trips).map((r) => Object.assign(fromCloud(r), { cloud: false }));
  }

  // Trips, newest first: the cloud's, plus anything not uploaded yet, plus
  // what the Pi has now (the freshest, including a trip still going).
  // null when there's nothing to show from anywhere.
  async function trips(limit) {
    const u = uid();
    if (API().demo || !u) return API().get("/api/trips?limit=" + limit);
    const [pi, cloud] = await Promise.all([
      API().online() ? API().get("/api/trips?limit=" + Math.max(limit, 50)).catch(() => null) : Promise.resolve(null),
      cloudTrips().catch(() => null),
    ]);
    const queued = outboxTrips(u);
    if (pi == null && cloud == null && !queued.length) return null;
    const dev = deviceUid(API().health()), all = new Map();
    for (const t of cloud || []) all.set(t.id, t);
    for (const t of queued) all.set(t.id, t);
    for (const t of pi || []) all.set(dev ? dev + ":" + t.id : "pi:" + t.id, Object.assign({}, t, { id: dev ? dev + ":" + t.id : "pi:" + t.id }));
    return [...all.values()].sort((a, b) => b.started_at - a.started_at).slice(0, limit);
  }

  // Insights: from the cloud when signed in (all phones' history), else the Pi.
  async function insights(range, tzMin) {
    const u = uid();
    const pi = () => API().get("/api/insights?range=" + range + "&tz=" + tzMin);
    if (API().demo || !u) return pi();
    let cloud;
    try { cloud = await cloudTrips(); } catch (e) { return pi(); }
    const all = new Map();
    for (const t of cloud) all.set(t.id, t);
    for (const t of outboxTrips(u)) all.set(t.id, t);
    return compute([...all.values()], range, tzMin, Date.now() / 1000);
  }

  // The same maths as src/bamnun/trips.py insights(), for trips from the cloud.
  const RANGES = { week: 7, month: 30, all: null };
  function compute(list, range, tz, now) {
    const days = range in RANGES ? RANGES[range] : 7;
    const since = days == null ? null : now - days * 86400;
    const trips = list.filter((t) => since == null || t.started_at >= since);
    const prev = days == null ? [] : list.filter((t) => t.started_at >= since - days * 86400 && t.started_at < since);
    const day = (ts) => { const d = new Date((ts + tz * 60) * 1000); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); };
    const hour = (ts) => new Date((ts + tz * 60) * 1000).getUTCHours();
    const sum = (ts, k) => ts.reduce((a, t) => a + ((t.summary || {})[k] || 0), 0);
    const share = (ts) => { const dr = sum(ts, "drive_s"); return dr > 0 ? Math.round(sum(ts, "calm_s") / dr * 10000) / 10000 : null; };
    const episodes = [].concat(...trips.map((t) => (t.summary || {}).episodes || []));
    const hours = Array(24).fill(0);
    for (const e of episodes) hours[hour(e.at)]++;
    const woke = [0, 0, 0, 0];
    for (const e of episodes) { const s = parseInt(e.max_stage || 1, 10); if (s >= 1 && s <= 4) woke[s - 1]++; }
    const DAY = 86400000, today = day(now), per = [];
    const isoDate = (ms) => new Date(ms).toISOString().slice(0, 10);
    if (days === 7) {
      for (let i = 6; i >= 0; i--) {
        const d = today - i * DAY;
        per.push({ date: isoDate(d), weekday: (new Date(d).getUTCDay() + 6) % 7,
          alerts: episodes.filter((e) => day(e.at) === d).length, drove: trips.some((t) => day(t.started_at) === d) });
      }
    } else {
      let weeks = 5;
      if (days == null) { const first = Math.min(now, ...trips.map((t) => t.started_at)); weeks = Math.max(1, Math.min(12, Math.floor((now - first) / (7 * 86400)) + 1)); }
      for (let i = weeks - 1; i >= 0; i--) {
        const end = today - 7 * i * DAY, start = end - 6 * DAY;
        per.push({ date: isoDate(start), alerts: episodes.filter((e) => day(e.at) >= start && day(e.at) <= end).length,
          drove: trips.some((t) => day(t.started_at) >= start && day(t.started_at) <= end) });
      }
    }
    let peak = null;
    if (hours.some(Boolean)) { peak = 0; for (let h = 1; h < 24; h++) if (hours[h] > hours[peak]) peak = h; }
    return {
      range, trips: trips.length, drive_s: Math.round(sum(trips, "drive_s") * 10) / 10, alerts: episodes.length,
      alert_free: share(trips), alert_free_prev: share(prev),
      longest_calm_s: Math.max(0, ...trips.map((t) => (t.summary || {}).longest_calm_s || 0)),
      per, hours, peak_hour: peak, woke_by: woke, first_step_enough: woke[0],
      microsleeps: sum(trips, "microsleeps"), breaks: sum(trips, "breaks"),
    };
  }

  // -- sign out ------------------------------------------------------------- //
  // The outbox stays (under the user's ID), so trips not uploaded yet go up
  // the next time that driver signs in. The phone's copy of the profile is
  // cleared, so the next person starts fresh.
  async function signOut() {
    try { await flush(); } catch (e) {}
    try { await A().signOut(); } catch (e) {}
    try { Object.keys(localStorage).filter((k) => k.startsWith("bn-") && !k.startsWith("bn-sync-") && !["bn-lang", "bn-pi", "bn-sound"].includes(k)).forEach((k) => localStorage.removeItem(k)); } catch (e) {}
    cloudCache = null;
  }

  // Deletes the account and all its cloud rows (supabase/schema.sql,
  // delete_my_account), then everything about it on this phone, including
  // trips still waiting to upload. Trips on the Pi itself stay.
  async function deleteAccount() {
    const u = uid();
    if (!u) return;
    await A().rest("POST", "rpc/delete_my_account", {});
    try { ["bn-sync-out-" + u, "bn-sync-done-" + u].forEach((k) => localStorage.removeItem(k)); } catch (e) {}
    await signOut();
  }

  // When to try: on start, when the network comes back, when the app comes
  // to the front, once a minute, and when a trip ends on the Pi.
  function start() {
    if (!A() || !API()) return;
    addEventListener("online", () => flush());
    document.addEventListener("visibilitychange", () => { if (!document.hidden) flush(); });
    setInterval(() => flush(), 60000);
    API().on("trip", (m) => { if (m.event === "ended") setTimeout(collect, 3000); });
    A().on((u) => { cloudCache = null; if (u) flush(); });
    setTimeout(flush, 1500);
  }

  window.BN_SYNC = {
    status: () => status, pending() { const u = uid(); if (!u) return 0; return Object.keys(box(u).trips).length; },
    profileChanged, markOnboarded, onboarded, afterSignIn, collect, flush, trips, insights, signOut, deleteAccount, compute,
  };
  start();
})();
