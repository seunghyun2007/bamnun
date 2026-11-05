/* Things that appear over any screen: the emergency countdown (SPEC.md,
   section 9b), and short notes for Ollie's lines, break reminders and trips.

   Safety rule for this build: nothing here ever dials 119, 112 or any real
   emergency number. The "dialer" step opens the phone's dialer with NO number
   filled in, and only if the driver turned it on; the driver must still type
   a number and tap Call. Demo mode (on by default) sends nothing at all. */
(function () {
  "use strict";
  const T = (s, v) => BN_T(s, v);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const phone = document.getElementById("phone");
  const COUNTDOWN_S = 30;
  // Deliberately empty: the dialer opens with no number in it (see above).
  const DIALER_NUMBER = "";

  // -- siren: loud, on the phone, while the countdown runs --------------- //
  let actx = null, siren = null;
  function sirenOn() {
    try {
      const A = window.AudioContext || window.webkitAudioContext; if (!A) return;
      actx = actx || new A(); if (actx.state === "suspended") actx.resume();
      const o = actx.createOscillator(), g = actx.createGain(), lfo = actx.createOscillator(), lg = actx.createGain();
      o.type = "square"; o.frequency.value = 880; lfo.frequency.value = 2.2; lg.gain.value = 260;
      lfo.connect(lg).connect(o.frequency); g.gain.value = 0.18; o.connect(g).connect(actx.destination);
      o.start(); lfo.start(); siren = [o, lfo];
    } catch (e) {}
    try { navigator.vibrate && navigator.vibrate([600, 300, 600, 300, 600]); } catch (e) {}
  }
  function sirenOff() { if (siren) { siren.forEach((n) => { try { n.stop(); } catch (e) {} }); siren = null; } try { navigator.vibrate && navigator.vibrate(0); } catch (e) {} }

  // -- the emergency overlay ------------------------------------------- //
  let open = null;
  function where() {
    return new Promise((res) => {
      if (!navigator.geolocation || !window.isSecureContext) return res(null);
      navigator.geolocation.getCurrentPosition((p) => res(p.coords), () => res(null), { timeout: 5000, maximumAge: 60000 });
    });
  }
  function message(name, coords) {
    const link = coords ? "https://maps.google.com/?q=" + coords.latitude.toFixed(5) + "," + coords.longitude.toFixed(5) : T("location unavailable");
    const time = new Date().toLocaleTimeString(BN_LANG() === "ko" ? "ko-KR" : "en-US", { hour: "numeric", minute: "2-digit" });
    return T("Bamnun detected that {name} may have fallen asleep at the wheel and isn't responding. Location: {link}. Time: {time}.", { name, link, time });
  }

  function show(ev) {
    ev = ev || {};
    if (open) return;
    const s = BN_API.settings().emergency || {}, practice = !!ev.practice;
    const demo = practice || ev.demo !== false && s.demo !== false;
    const contact = s.contact_name || s.contact_phone || "";
    const name = BN_NAME();
    const el = document.createElement("div");
    el.setAttribute("role", "alertdialog"); el.setAttribute("aria-live", "assertive");
    el.style.cssText = "position:absolute;inset:0;z-index:60;display:flex;flex-direction:column;align-items:center;padding:64px 24px 40px;text-align:center;color:#F4EFE6;font-family:Figtree,Arial,sans-serif;background:radial-gradient(120% 60% at 50% 0%,rgba(244,143,177,.55),rgba(244,143,177,0) 70%),#2A1018;animation:scIn .3s ease both";
    el.innerHTML = `
      ${demo ? `<span style="font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;background:rgba(255,255,255,.16);padding:5px 10px;border-radius:99px">${esc(T(practice ? "Practice" : "Demo"))}</span>` : ""}
      <img src="${IMG.wake}" alt="" style="width:130px;margin-top:14px">
      <h1 style="margin:10px 0 0;font-family:'Bricolage Grotesque',Arial,sans-serif;font-weight:800;font-stretch:75%;font-size:46px;line-height:1">${esc(T("Are you OK?"))}</h1>
      <p data-em="sub" style="margin:12px 0 0;font-size:16.5px;line-height:1.4;max-width:30ch"></p>
      <div style="position:relative;width:132px;height:132px;margin-top:22px">
        <svg viewBox="0 0 132 132" width="132" height="132" style="transform:rotate(-90deg)"><circle cx="66" cy="66" r="58" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="10"/><circle data-em="ring" cx="66" cy="66" r="58" fill="none" stroke="#F48FB1" stroke-width="10" stroke-linecap="round" stroke-dasharray="364 364" style="transition:stroke-dasharray 1s linear"/></svg>
        <b data-em="n" style="position:absolute;inset:0;display:grid;place-items:center;font-family:'Bricolage Grotesque',Arial,sans-serif;font-size:48px;font-weight:800"></b>
      </div>
      <div data-em="log" style="margin-top:16px;width:100%;display:flex;flex-direction:column;gap:8px"></div>
      <div style="margin-top:auto;width:100%;display:flex;flex-direction:column;gap:10px">
        <button type="button" data-em="ok" style="width:100%;padding:22px;border:0;border-radius:24px;background:#7BD88F;color:#241A26;font-weight:800;font-size:22px;box-shadow:0 12px 30px rgba(0,0,0,.45)">${esc(T("I'm OK"))}</button>
        <button type="button" data-em="now" style="padding:12px;border:0;background:transparent;color:#F4EFE6;font-weight:700;font-size:15px;text-decoration:underline">${esc(T(contact ? "Contact now" : "Close"))}</button>
      </div>`;
    phone.appendChild(el);
    const $ = (k) => el.querySelector('[data-em="' + k + '"]');
    let left = COUNTDOWN_S, phase = "contact", timer = null;
    const log = (txt, tone) => { const d = document.createElement("div"); d.style.cssText = "padding:10px 12px;border-radius:14px;font-size:13.5px;line-height:1.4;text-align:left;background:" + (tone === "demo" ? "rgba(255,255,255,.12)" : "rgba(123,216,143,.22)"); d.textContent = txt; $("log").appendChild(d); };
    function paint() {
      $("n").textContent = left;
      $("ring").setAttribute("stroke-dasharray", (364 * left / COUNTDOWN_S).toFixed(0) + " 364");
      $("sub").textContent = phase === "contact"
        ? (contact ? T("Contacting {contact} in {n} s", { contact, n: left }) : T("No emergency contact is set. Add one in Settings."))
        : T("Opening the dialer in {n} s. No number is filled in.", { n: left });
    }
    async function contactNow() {
      clearInterval(timer);
      const coords = await where();
      const text = message(name, coords);
      if (demo || !s.contact_phone) {
        log(T("Demo: nothing was sent. Would text {who}:", { who: contact || T("your contact") }) + " “" + text + "”", "demo");
        log(T("Demo: would then call {who}.", { who: contact || T("your contact") }), "demo");
      } else {
        // Both need a tap on iOS; on Android the SMS app opens with the text in.
        location.href = "sms:" + encodeURIComponent(s.contact_phone) + "?body=" + encodeURIComponent(text);
        log(T("Message ready for {who}. Tap Send.", { who: contact }));
        setTimeout(() => { location.href = "tel:" + encodeURIComponent(s.contact_phone); }, 4000);
        report("contacted");
      }
      if (s.call_services) { phase = "dialer"; left = COUNTDOWN_S; paint(); timer = setInterval(tick, 1000); }
      else { sirenOff(); $("n").textContent = "✓"; $("sub").textContent = T("Done. Tap I'm OK when you're safe."); }
    }
    function dialer() {
      clearInterval(timer); sirenOff();
      if (demo) log(T("Demo: would open the dialer, with no number filled in."), "demo");
      else { location.href = "tel:" + DIALER_NUMBER; report("called"); log(T("Dialer opened. Nothing is called until you tap Call.")); }
      $("n").textContent = "✓"; $("sub").textContent = T("Done. Tap I'm OK when you're safe.");
    }
    function tick() { left--; paint(); if (left <= 0) (phase === "contact" ? contactNow : dialer)(); }
    function report(outcome) { if (!practice && ev.id != null && !BN_API.demo) BN_API.post("/api/emergency/" + ev.id, { outcome }).catch(() => {}); }
    function close(outcome) { clearInterval(timer); sirenOff(); report(outcome); el.remove(); open = null; }
    $("ok").addEventListener("click", () => close("ok"));
    $("now").addEventListener("click", () => { if (!contact) return close("dismissed"); left = 0; contactNow(); });
    open = el; paint(); sirenOn();
    timer = setInterval(tick, 1000);
  }

  // -- notes over the screen -------------------------------------------- //
  let toastEl = null;
  function toast(text, img) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.style.cssText = "position:absolute;left:14px;right:14px;top:14px;z-index:55;display:flex;gap:10px;align-items:center;padding:10px 14px;border-radius:18px;background:#F4EFE6;color:#241A26;font-weight:700;font-size:14px;line-height:1.3;box-shadow:0 12px 30px rgba(0,0,0,.5);transition:transform .35s cubic-bezier(.22,1,.36,1),opacity .3s;transform:translateY(-120%);opacity:0;pointer-events:none";
      phone.appendChild(toastEl);
    }
    toastEl.innerHTML = `<img src="${img || IMG.hello}" alt="" style="width:34px;flex-shrink:0"><span>${esc(text)}</span>`;
    requestAnimationFrame(() => { toastEl.style.transform = "none"; toastEl.style.opacity = 1; });
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => { toastEl.style.transform = "translateY(-120%)"; toastEl.style.opacity = 0; }, Math.max(3200, text.length * 70));
  }
  function notify(title, body) {
    try { if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification(title, { body, icon: IMG.wake }); } catch (e) {}
  }
  const screen = () => (location.hash || "").slice(1);
  BN_API.on("say", (m) => {
    // The Voice and Calibrate screens show these beside Ollie already.
    if (["Voice", "Calibrate"].includes(screen()) || /^(greet|sample|cal_)/.test(m.line)) return;
    toast(T("Ollie") + ": " + m.text, IMG.hello);
  });
  BN_API.on("reminder", () => { toast(T("Time for a break. Ollie will be here when you're back."), IMG.cup); notify(T("Ollie"), T("Time for a break.")); });
  BN_API.on("alert", (m) => {
    if (m.stage >= 3) notify(T("Ollie"), T(m.stage >= 4 ? "Wake up! Pull over now." : "Your eyes are closing. Let's find a place to rest."));
    else if (m.stage >= 1 && m.stage > (m.previous || 0)) notify(T("Ollie"), T(m.stage === 1 ? "A little light to keep you fresh" : "A breath of mint"));
  });
  BN_API.on("trip", (m) => { if (m.event === "ended") toast(T("Trip saved. See it in Trips."), IMG.celebrate); });
  // The device knew the driver's name before this phone did: show it.
  BN_API.on("name_changed", () => { const s = screen(); if (["Home", "Settings", "Plan"].includes(s)) BN_GO(s, { instant: true, keepScroll: true }); });
  // Nobody is driving during setup, so a device emergency waits for the app
  // screens. Settings' practice run calls show() directly and isn't affected.
  const DRIVING = ["Home", "Camera", "Trips", "Insights", "Settings", "Route", "Drive"];
  BN_API.on("emergency", (m) => {
    if (!DRIVING.includes(screen())) return;
    show(m); notify(T("Ollie"), T("Are you OK?"));
  });

  window.BN_EMERGENCY = { show };
})();
