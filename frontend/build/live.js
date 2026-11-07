/* Live data from the Bamnun device, painted into [data-live] elements.
   One WebSocket to the Pi's /ws (docs/SPEC.md, section 1). Only numbers
   arrive here; camera video never leaves the device. */
(function () {
  "use strict";
  const T = (s, v) => window.BN_T(s, v);
  // Ladder stage names, as the Wake-up ladder screen calls them.
  const STAGES = ["", "Blue light", "Mint mist", "Chime and voice", "Rising alarm"];
  // Cream while all is well; amber only while Ollie is really waking you.
  const STAGE_COLOURS = ["#E8D7AE", "#F2B66D", "#F2B66D", "#F2B66D", "#F2B66D"];
  const CO2_PROMPT = 1500;
  // The driver's state in one word, decided on the device (SPEC.md, 13), and
  // its colour on the app's lavender -> pink scale.
  const LABEL = {
    alert: ["Alert", "#F2EEE8"], a_bit: ["A bit tired", "#E8D7AE"], drowsy: ["Drowsy", "#F2B66D"],
    very: ["Very drowsy", "#F2B66D"], eyes_closed: ["Eyes closed", "#F2B66D"], head_drop: ["Head dropping", "#F2B66D"],
    away: ["Looking away", "#F2B66D"], no_face: ["No face", "#9A93A0"],
  };
  // The drowsiness signals (SPEC.md, 15), on the driver's own scale.
  const SIGNALS = {
    heavy_lids: ["Heavy eyelids", (v) => Math.round(v * 100) + "%"],
    perclos: ["Eyes shut, last min", (v) => (v * 100).toFixed(1) + "%"],
    blink_duration: ["Blink length", (v) => (v ? v.toFixed(2) + " s" : "–")],
    long_blinks: ["Long blinks / min", (v) => v.toFixed(1)],
    lid_speed: ["Lid reopening (x normal)", (v) => (v ? v.toFixed(1) + "×" : "–")],
    nods: ["Head nods, last 2 min", (v) => Math.round(v)],
    microsleep: ["Microsleeps, last min", (v) => Math.round(v)],
    yawn: ["Yawns / h", (v) => Math.round(v)],
    blink_rate: ["Blink rate (x normal)", (v) => (v ? v.toFixed(1) + "×" : "–")],
  };
  const UNRELIABLE = { smile: "smiling", talk: "talking", yawn: "yawning", expression: "expression",
    lighting: "light changing", edge: "face at the edge", small_face: "face too far", looking_down: "looking down",
    pose: "head turned", off_road: "looking away", disagree: "glare" };

  let ws = null, last = null, conn = "connecting", retry = 0;
  // Demo: a simulated driver inside the page, so the live screens can be seen
  // with nothing installed. Only ever on request (?demo, or opening the file
  // directly, or the public website on GitHub Pages, which has no Pi behind
  // it), and labelled on screen: a real app that has lost its Pi must never
  // show made-up numbers.
  const WEBSITE = /\.github\.io$/i.test(location.hostname);
  const DEMO = new URLSearchParams(location.search).has("demo") || location.protocol === "file:" || WEBSITE;

  // Which device to talk to. A page served by the Pi talks back to the Pi;
  // the Capacitor app or a file uses ?pi=host:port, remembered, or the
  // hotspot's default address.
  function piAddress() {
    const q = new URLSearchParams(location.search).get("pi");
    if (q) { try { localStorage.setItem("bn-pi", q); } catch (e) {} return q; }
    if (/^https?:$/.test(location.protocol) && !window.Capacitor && location.host) return location.host;
    try { const s = localStorage.getItem("bn-pi"); if (s) return s; } catch (e) {}
    return "10.42.0.1:8000";
  }

  const secure = () => location.protocol === "https:";

  function connect() {
    conn = "connecting"; paint();
    try {
      ws = new WebSocket((secure() ? "wss://" : "ws://") + piAddress() + "/ws");
    } catch (e) { return later(); }
    ws.onopen = () => {
      retry = 0; conn = "open";
      // The Pi has no reliable clock, so the phone tells it the time.
      ws.send(JSON.stringify({ type: "hello", time: Date.now(), lang: window.BN_LANG(),
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        tz_min: -new Date().getTimezoneOffset() }));
      paint();
      if (window.BN_API) BN_API.onConnect();
    };
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch (er) { return; }
      if (m.type === "snapshot") last = m;
      else if (m.type === "alert" && last) last = Object.assign({}, last, { stage: m.stage, stage_name: m.stage_name });
      if (m.type !== "snapshot" && window.BN_API) BN_API.emit(m);
      paint();
    };
    ws.onclose = () => { conn = "closed"; paint(); later(); };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }
  function later() { setTimeout(connect, Math.min(5000, 500 * 2 ** retry++)); }

  // A 2½-minute drive on repeat: calibration, normal driving, an empty seat,
  // a glance away, then drowsiness climbing the whole ladder. The shape, not
  // the detector, is simulated; tools/sim_server.py runs the real pipeline.
  function demo() {
    const CYCLE = 150, t0 = performance.now();
    let blinkUntil = 0, nextBlink = 2, lastBlink = 0.18, perclos = 0.012;
    conn = "open";
    setInterval(() => {
      const t = ((performance.now() - t0) / 1000) % CYCLE;
      const drowsy = Math.max(0, (t - 55) / 80);                    // 0 → 1 from 55 s
      const stage = t < 75 ? 0 : t < 92 ? 1 : t < 108 ? 2 : t < 122 ? 3 : t < 132 ? 4 : 0;
      const face = !(t > 24 && t < 30);
      if (t < 1) { blinkUntil = 0; nextBlink = 2; }
      if (t >= nextBlink) {
        lastBlink = 0.15 + 0.25 * drowsy + Math.random() * 0.05;
        blinkUntil = t + (stage === 4 ? 1.2 : lastBlink);
        nextBlink = blinkUntil + Math.max(0.8, 4 - 2.5 * drowsy + Math.random() * 2);
      }
      const closed = face && t < blinkUntil;
      perclos += ((0.012 + 0.2 * drowsy) - perclos) * 0.02;
      const yaw = t > 40 && t < 44 ? 38 : Math.sin(t / 3) * 3;
      last = {
        type: "snapshot", demo: true, face, stale: false,
        calibrating: t < 6, cal_progress: t < 6 ? t / 6 : null, calibrated: t >= 6,
        eye_open: face && t >= 6 ? (closed ? 0.18 : 1 - 0.25 * drowsy + Math.sin(t * 3) * 0.02) : null,
        eye_closed: face && t >= 6 ? closed : null,
        blink_rate: face && t >= 6 ? 15 + 12 * drowsy : null,
        perclos: face && t >= 6 ? perclos : null,
        last_blink_s: lastBlink, microsleep: stage === 4 && closed,
        stage, stage_name: ["none", "light", "scent", "chime", "emergency"][stage],
        kss: 1 + 7 * Math.min(1, drowsy), distracted: yaw > 25, off_road: face ? yaw > 25 : null,
        yaw: face ? yaw : null, co2_ppm: 620 + 9 * t, co2_age_s: 2, trip_s: 1800 + t, fps: 30,
        drowsiness: face && t >= 6 ? Math.round(100 * Math.min(0.95, drowsy * 0.9)) : null,
        label: !face ? "no_face" : t < 6 ? "alert" : stage === 4 && closed ? "eyes_closed" : yaw > 25 ? "away"
          : ["alert", "a_bit", "drowsy", "very", "very"][stage],
      };
      paint();
    }, 200);
  }

  // -- painting ----------------------------------------------------------- //
  const all = (k) => document.querySelectorAll('[data-live="' + k + '"]');
  function text(k, v) { for (const el of all(k)) if (el.textContent !== v) el.textContent = v; }
  function css(k, prop, v) { for (const el of all(k)) if (el.style[prop] !== v) el.style[prop] = v; }
  function attr(k, a, v) { for (const el of all(k)) if (el.getAttribute(a) !== String(v)) el.setAttribute(a, v); }
  const dash = "–";
  const pct = (x) => x == null ? dash : (x * 100).toFixed(1) + "%";

  function view(s) {
    if (conn !== "open" || !s) return conn === "connecting" && !s ? "connecting" : "offline";
    if (s.stale) return "nocam";
    if (s.calibrating) return "calibrating";
    if (s.stage > 0) return "alert";
    if (!s.face) return "nodriver";
    if (s.distracted || s.off_road) return "away";
    return "watching";
  }

  const STATUS = {
    connecting: ["Connecting…", "Looking for your Bamnun."],
    offline: ["Offline", "Can't reach your Bamnun."],
    nocam: ["No camera", "Bamnun isn't sending camera data."],
    calibrating: ["Calibrating", "Look straight ahead and blink normally."],
    nodriver: ["No driver", "Sit in the driver's seat so Ollie can see you."],
    away: ["Eyes off road", "Look back at the road."],
    watching: ["Watching", "Ollie is watching your eyes."],
  };

  function chip(s, v) {
    if (v === "offline" || v === "connecting" || v === "nocam") return [T("Not connected"), "rgba(255,255,255,.16)", "#F2EEE8"];
    if (s.calibrating) return [T("Calibrating"), "#E8D7AE", "#15131A"];
    const [text, colour] = LABEL[s.label] || LABEL[s.face ? "alert" : "no_face"];
    return [T(text), colour, "#15131A"];
  }

  // The Home tile shows the video cropped around the face: scale so the face
  // (with some room) fills the tile, centre it, and never show past an edge.
  function cropTo(img, box) {
    const tile = img.parentElement, tw = tile.clientWidth, th = tile.clientHeight;
    const vw = img.naturalWidth, vh = img.naturalHeight;
    if (!tw || !vw) return;
    const cover = Math.max(tw / vw, th / vh);
    let k = cover, cx = 0.5, cy = 0.5;
    if (box) {
      cx = box[0] + box[2] / 2; cy = box[1] + box[3] / 2;
      k = Math.max(cover, Math.min(tw / (box[2] * vw * 1.9), th / (box[3] * vh * 1.6)));
    }
    let x = tw / 2 - cx * vw * k, y = th / 2 - cy * vh * k;
    x = Math.min(0, Math.max(tw - vw * k, x)); y = Math.min(0, Math.max(th - vh * k, y));
    const tf = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) scale(${k.toFixed(4)})`;
    if (Math.abs((img._k || 0) - k) > 0.02 || Math.abs((img._x || 0) - x) > 4 || Math.abs((img._y || 0) - y) > 4) {
      img.style.transform = tf; img._k = k; img._x = x; img._y = y;
    }
  }

  function signalRows(s) {
    const sig = s.signals || {};
    return Object.keys(SIGNALS).map((k) => {
      const [name, fmt] = SIGNALS[k], [val, part] = sig[k] || [0, 0];
      return `<div style="display:grid;grid-template-columns:1fr auto 74px;gap:10px;align-items:center;font-size:13px">
        <span style="color:#9A93A0">${T(name)}</span><b>${fmt(val || 0)}</b>
        <span style="position:relative;height:8px;border-radius:6px;background:rgba(255,255,255,.08);overflow:hidden"><i style="position:absolute;left:0;top:0;bottom:0;width:${Math.min(100, (part || 0) / 30 * 100).toFixed(0)}%;background:#E8D7AE;border-radius:6px"></i></span></div>`;
    }).join("") + (s.unreliable ? `<p style="margin:4px 0 0;font-size:12.5px;color:#F2B66D">${T("Eyes not scored right now: {why}", { why: T(UNRELIABLE[s.unreliable] || s.unreliable) })}</p>` : "")
      + `<p style="margin:4px 0 0;font-size:11.5px;color:#9A93A0">${T("Bars: each signal's share of the score, in points.")}</p>`;
  }

  function paint() {
    const s = last, v = view(s), live = v !== "offline" && v !== "connecting" && v !== "nocam";

    // Connection chip (Home) and pill (Camera).
    text("conn", DEMO ? T("Demo · simulated driver")
      : T(conn === "open" ? "Bamnun connected" : conn === "connecting" ? "Connecting…" : "Not connected"));
    css("conn-dot", "background", conn === "open" ? "#E8D7AE" : conn === "connecting" ? "#F2B66D" : "#9A93A0");
    text("live", T(DEMO ? "Demo" : live ? "Live" : "Offline"));
    css("live-dot", "background", live ? "#F2B66D" : "#9A93A0");

    // "Right now" card.
    // Watching: the one word is how the driver is right now.
    const AWAKE = { alert: "Awake", a_bit: "A bit tired", drowsy: "Drowsy", very: "Very drowsy" };
    const [title, note] = v === "alert" ? [STAGES[s.stage] || "Rising alarm", "Ollie is waking you up."]
      : v === "watching" && AWAKE[s.label] ? [AWAKE[s.label], STATUS.watching[1]] : STATUS[v];
    text("status", T(title));
    text("status-note", T(note));
    css("status", "color", v === "alert" ? STAGE_COLOURS[s.stage] || STAGE_COLOURS[4]
      : live ? "#E8D7AE" : "#9A93A0");
    const kss = live && s.calibrated && !s.calibrating ? Math.round(s.kss) : null;
    text("kss", kss == null ? dash : String(kss));
    attr("kss-ring", "stroke-dasharray", (kss == null ? 0 : 207 * kss / 9).toFixed(1) + " 277");
    css("kss-bar", "width", (kss == null ? 0 : 100 * kss / 9).toFixed(0) + "%");
    // Next rest: the break reminder's own rhythm (Settings, every N min).
    const every = ((window.BN_API && BN_API.settings && BN_API.settings()) || {}).break_every_min || 120;
    if (s && live && s.trip_s != null) {
      const left = Math.max(0, Math.ceil((every * 60 - (s.trip_s % (every * 60))) / 60));
      text("next-rest", left >= 60 ? T("{h}h {m}m", { h: Math.floor(left / 60), m: String(left % 60).padStart(2, "0") }) : T("{m} min", { m: left }));
    } else text("next-rest", dash);
    text("perclos", live ? pct(s.perclos) : dash);
    text("blinks", live && s.blink_rate != null ? String(Math.round(s.blink_rate)) : dash);
    if (s && live) {
      const m = Math.floor(s.trip_s / 60);
      text("trip", Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"));
    } else text("trip", dash);

    // The state chip, on both screens: the device's own label.
    const [label, bg, fg] = chip(s, v);
    text("state-chip", label); css("state-chip", "background", bg); css("state-chip", "color", fg);
    text("cam-off-text", T(conn === "connecting" && !s ? "Connecting…" : v === "nocam" ? "No camera"
      : live && !s.video ? "No camera picture" : "Not connected"));

    // Drowsiness score and its breakdown (Camera screen).
    const score = live && s.drowsiness != null ? s.drowsiness : null;
    text("score", score == null ? dash : String(score));
    css("score-bar", "width", (score || 0) + "%");
    text("score-label", score == null ? dash : T((LABEL[s.label] || LABEL.alert)[0]));
    text("score-stage", !live ? dash : s.stage ? T("Wake-up step {n}: {name}", { n: s.stage, name: T(STAGES[s.stage]) }) : T("No wake-up step running"));
    for (const el of all("signals")) if (!el.hidden && live && s.signals) el.innerHTML = signalRows(s);
    // Time-of-day risk: shown on its own, never part of the camera score.
    const risk = live && s.time_risk ? s.time_risk.level : null;
    text("time-risk", risk ? T({ low: "Low", medium: "Medium", high: "High" }[risk]) : dash);
    css("time-risk", "color", risk === "high" ? "#F2B66D" : risk === "medium" ? "#F2B66D" : "#9A93A0");

    // Cab air.
    const ppm = live ? s.co2_ppm : null;
    text("co2", ppm == null ? dash : String(Math.round(ppm)));
    css("co2-bar", "width", ppm == null ? "0%" : Math.min(100, ppm / CO2_PROMPT * 100).toFixed(0) + "%");
    css("co2-bar", "background", ppm != null && ppm >= CO2_PROMPT ? "#F2B66D" : "#9A93A0");
    text("co2-note", ppm == null ? T("Sensor offline")
      : T(ppm < 1000 ? "Fresh" : ppm < CO2_PROMPT ? "Getting stale" : "Open a window") + " · " +
        T("window prompt at {n}", { n: CO2_PROMPT }));

    // Wake-up steps: the current stage stands out in its own colour.
    for (const el of document.querySelectorAll("[data-live-stage]")) {
      const n = +el.dataset.liveStage, on = live && s.stage === n;
      el.style.background = on ? STAGE_COLOURS[n] + "55" : "rgba(255,255,255,.11)";
      el.style.color = on ? "#F2EEE8" : "#9A93A0";
      el.style.boxShadow = on ? "0 0 0 2px " + STAGE_COLOURS[n] : "none";
    }

    // Ollie looks the part: sleepy while the ladder runs, alarmed at the top.
    if (typeof IMG !== "undefined") {   // a top-level const in the same page script, not on window
      const stage = live ? s.stage : 0;
      const img = stage >= 4 || (live && s.microsleep) ? IMG.wake : stage >= 1 ? IMG.sleepy : IMG.idle;
      for (const el of all("owl")) if (el.getAttribute("src") !== img) el.setAttribute("src", img);
      css("owl-eye", "display", img === IMG.idle ? "" : "none");
    }

    // Video straight from the device, only while a screen with it is open:
    // leaving the screen removes the <img>, which ends the stream, and the
    // device stops encoding. Not connected shows a plain grey box instead.
    for (const img of [...all("video"), ...all("video-thumb")]) {
      const want = live && s.video && !DEMO && !img.dataset.failed;
      if (want && !img.getAttribute("src")) {
        img.onerror = () => { img.dataset.failed = "1"; img.removeAttribute("src"); paint(); };
        img.onload = () => paint();
        img.src = (secure() ? "https://" : "http://") + piAddress() + "/video";
      } else if (!want && img.getAttribute("src")) {
        img.removeAttribute("src");
      }
      const showing = want && img.naturalWidth > 0;
      img.style.display = showing ? "block" : "none";
      const box = img.parentElement;
      if (img.dataset.live === "video-thumb") {
        img.style.width = img.naturalWidth + "px"; img.style.height = img.naturalHeight + "px";
        if (showing) cropTo(img, s.face_box);
      } else if (s && s.video_size && box) {
        box.style.aspectRatio = s.video_size[0] + "/" + s.video_size[1];
      }
      // visibility, not display: the boxes keep their own centred layout.
      for (const off of box ? box.querySelectorAll('[data-live="cam-off"]') : []) off.style.visibility = showing ? "hidden" : "visible";
      // Offline, the box says so itself: no chip, no frame rate.
      for (const c of box ? box.querySelectorAll('[data-live="state-chip"],[data-live="fps"]') : []) c.style.visibility = live ? "visible" : "hidden";
    }

    text("fps", live ? Math.round(s.fps) + " fps" : dash);
    text("last-blink", live && s.last_blink_s != null ? s.last_blink_s.toFixed(2) + " s" : dash);
    if (!live || !s.face) {
      text("road", T("No face in view")); text("road-note", dash);
    } else {
      const off = !!(s.off_road || s.distracted);
      text("road", T(off ? "Looking away" : "Looking at the road"));
      const zone = T(off ? "outside the safe zone" : "inside the safe zone");
      text("road-note", s.yaw == null ? zone : Math.abs(s.yaw) < 1 ? T("Head straight · {zone}", { zone })
        : T("Head {n}° {dir} · {zone}", { n: Math.abs(Math.round(s.yaw)), dir: T(s.yaw < 0 ? "left" : "right"), zone }));
    }
  }

  window.BN_LIVE = { paint, state: () => last, demo: DEMO, address: piAddress, reconnect: () => { if (DEMO) return; try { ws && ws.close(); } catch (e) {} },
    connected: () => conn === "open" && !DEMO,
    // Point the app at another device (Settings, or a found device).
    use: (addr) => { try { localStorage.setItem("bn-pi", addr); } catch (e) {} if (ws) try { ws.close(); } catch (e) {} } };
  if (DEMO) demo(); else connect();
})();
