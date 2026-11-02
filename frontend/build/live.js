/* Live data from the Bamnun device, painted into [data-live] elements.
   One WebSocket to the Pi's /ws (docs/SPEC.md, section 1). Only numbers
   arrive here; camera video never leaves the device. */
(function () {
  "use strict";
  const T = (s, v) => window.BN_T(s, v);
  // Ladder stage names, as the Wake-up ladder screen calls them.
  const STAGES = ["", "Blue light", "Mint mist", "Chime and voice", "Rising alarm"];
  const STAGE_COLOURS = ["#F8C4A4", "#A99BF0", "#F5B5C8", "#C4B5FD", "#F48FB1"];
  const CO2_PROMPT = 1500;
  let ws = null, last = null, conn = "connecting", retry = 0;
  // Demo: a simulated driver inside the page, so the live screens can be seen
  // with nothing installed. Only ever on request (?demo, or opening the file
  // directly), and labelled on screen: a real app that has lost its Pi must
  // never show made-up numbers.
  const DEMO = new URLSearchParams(location.search).has("demo") || location.protocol === "file:";

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
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone }));
      paint();
    };
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch (er) { return; }
      if (m.type === "snapshot") last = m;
      else if (m.type === "alert" && last) last = Object.assign({}, last, { stage: m.stage, stage_name: m.stage_name });
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

  function eyesBadge(s, v) {
    if (v === "offline" || v === "connecting" || v === "nocam") return [dash, "rgba(255,255,255,.16)", "#F4EFE6"];
    if (s.calibrating) return [T("Calibrating"), "#C4B5FD", "#241A26"];
    if (!s.face) return [T("No face"), "rgba(255,255,255,.16)", "#F4EFE6"];
    if (s.eye_closed) return [T("Eyes closed"), "#F48FB1", "#241A26"];
    return [T("Eyes open"), "#F8C4A4", "#241A26"];
  }

  function paint() {
    const s = last, v = view(s), live = v !== "offline" && v !== "connecting" && v !== "nocam";

    // Connection chip (Home) and pill (Camera).
    text("conn", DEMO ? T("Demo · simulated driver")
      : T(conn === "open" ? "Bamnun connected" : conn === "connecting" ? "Connecting…" : "Not connected"));
    css("conn-dot", "background", conn === "open" ? "#7BD88F" : conn === "connecting" ? "#FFB547" : "#B3A6B4");
    text("live", T(DEMO ? "Demo" : live ? "Live" : "Offline"));
    css("live-dot", "background", live ? "#F48FB1" : "#B3A6B4");

    // "Right now" card.
    const [title, note] = v === "alert" ? [STAGES[s.stage] || "Rising alarm", "Ollie is waking you up."] : STATUS[v];
    text("status", T(title));
    text("status-note", T(note));
    css("status", "color", v === "alert" ? STAGE_COLOURS[s.stage] || STAGE_COLOURS[4]
      : live ? "#F8C4A4" : "#B3A6B4");
    const kss = live && s.calibrated && !s.calibrating ? Math.round(s.kss) : null;
    text("kss", kss == null ? dash : String(kss));
    attr("kss-ring", "stroke-dasharray", (kss == null ? 0 : 207 * kss / 9).toFixed(1) + " 277");
    text("perclos", live ? pct(s.perclos) : dash);
    text("blinks", live && s.blink_rate != null ? String(Math.round(s.blink_rate)) : dash);
    if (s && live) {
      const m = Math.floor(s.trip_s / 60);
      text("trip", Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"));
    } else text("trip", dash);

    // Eyes badge, on both screens.
    const [eyes, bg, fg] = eyesBadge(s, v);
    text("eyes", eyes); css("eyes", "background", bg); css("eyes", "color", fg);

    // Cab air.
    const ppm = live ? s.co2_ppm : null;
    text("co2", ppm == null ? dash : String(Math.round(ppm)));
    css("co2-bar", "width", ppm == null ? "0%" : Math.min(100, ppm / CO2_PROMPT * 100).toFixed(0) + "%");
    css("co2-bar", "background", ppm != null && ppm >= CO2_PROMPT ? "#F48FB1" : "#F5B5C8");
    text("co2-note", ppm == null ? T("Sensor offline")
      : T(ppm < 1000 ? "Fresh" : ppm < CO2_PROMPT ? "Getting stale" : "Open a window") + " · " +
        T("window prompt at {n}", { n: CO2_PROMPT }));

    // Wake-up steps: the current stage stands out in its own colour.
    for (const el of document.querySelectorAll("[data-live-stage]")) {
      const n = +el.dataset.liveStage, on = live && s.stage === n;
      el.style.background = on ? STAGE_COLOURS[n] + "55" : "rgba(255,255,255,.11)";
      el.style.color = on ? "#F4EFE6" : "#B3A6B4";
      el.style.boxShadow = on ? "0 0 0 2px " + STAGE_COLOURS[n] : "none";
    }

    // Ollie looks the part: sleepy while the ladder runs, alarmed at the top.
    if (typeof IMG !== "undefined") {   // a top-level const in the same page script, not on window
      const stage = live ? s.stage : 0;
      const img = stage >= 4 || (live && s.microsleep) ? IMG.wake : stage >= 1 ? IMG.sleepy : IMG.idle;
      for (const el of all("owl")) if (el.getAttribute("src") !== img) el.setAttribute("src", img);
      css("owl-eye", "display", img === IMG.idle ? "" : "none");
    }

    // Camera screen video, straight from the device, only while this screen
    // is open: leaving the screen removes the <img>, which ends the stream,
    // and the Pi stops encoding. The drawing below stays as the fallback for
    // the demo, the simulated device, or a stream that fails.
    for (const img of all("video")) {
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
      css("face-drawing", "visibility", showing ? "hidden" : "visible");
    }

    // Camera screen: the drawn eyes follow the measured openness.
    const eo = live ? s.eye_open : null;
    attr("pupil", "ry", eo == null ? 8 : Math.max(0.8, Math.min(10, 8 * eo)).toFixed(1));
    attr("pupil", "opacity", eo == null ? 0.35 : 1);
    attr("glint", "opacity", eo != null && eo > 0.45 ? 0.9 : 0);
    attr("eye-box", "stroke", eo == null ? "rgba(255,255,255,.25)" : s.eye_closed ? "#F48FB1" : "#A99BF0");
    text("fps", live ? T("Infrared") + " · " + Math.round(s.fps) + " fps" : T("Infrared") + " · " + dash);
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

  window.BN_LIVE = { paint, state: () => last, demo: DEMO };
  if (DEMO) demo(); else connect();
})();
