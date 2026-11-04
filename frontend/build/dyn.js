/* The interactive screens. Each init gets the screen's root element and a
   context ({go, forward, setLang, rerender}). Everything the driver chooses
   goes through BN_API (api.js): saved on the phone at once, and on the
   device as soon as it's reachable. Every string shown goes through BN_T or
   is an exact key in ko.json, so it follows the app language. */
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const T = (s, v) => BN_T(s, v);
const API = () => window.BN_API;
const GLASS = 'background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.09);-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)';
const HEAD_FONT = "font-family:'Bricolage Grotesque',Arial,sans-serif;font-stretch:80%;font-weight:800";
const TICK = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#241A26" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
const CROSS = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#241A26" stroke-width="2.8" stroke-linecap="round" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>';
const SPEAKER = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';

const VEHICLES = { long_haul: 'Long-haul truck', delivery: 'Delivery truck', bus: 'Bus or coach', taxi: 'Taxi or van', car: 'My own car' };
const MOUNT_CM = { long_haul: [50, 70], delivery: [50, 70], bus: [50, 70], taxi: [40, 60], car: [40, 60] };
const SHIFTS = { day: ['06:00', '14:00'], eve: ['14:00', '22:00'], night: ['22:00', '06:00'] };
const SHIFT_NAMES = { day: 'Day shift', eve: 'Evening shift', night: 'Night shift', custom: 'Custom hours', variable: 'Hours change weekly' };
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const locale = () => (BN_LANG() === 'ko' ? 'ko-KR' : 'en-US');
function clock(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return new Date(2000, 0, 1, h, m).toLocaleTimeString(locale(), { hour: 'numeric', minute: '2-digit' });
}
function hourLabel(h) { return new Date(2000, 0, 1, h).toLocaleTimeString(locale(), { hour: 'numeric' }); }
function shiftOf(work) {
  if (!work) return 'night';
  if (work.variable) return 'variable';
  for (const k in SHIFTS) if (SHIFTS[k][0] === work.start && SHIFTS[k][1] === work.end) return k;
  return 'custom';
}
function dur(s) {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? T('{h}h {m}m', { h, m: String(m).padStart(2, '0') }) : T('{m} min', { m });
}
function when(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
  const diff = Math.round((day(now) - day(d)) / 86400000);
  const t = d.toLocaleTimeString(locale(), { hour: 'numeric', minute: '2-digit' });
  const label = diff === 0 ? T('Today') : diff === 1 ? T('Yesterday') : diff < 7 ? T(WEEKDAYS[(d.getDay() + 6) % 7])
    : d.toLocaleDateString(locale(), { month: 'short', day: 'numeric' });
  return label + ' · ' + t;
}
function tripTitle(trip) {
  if (trip.route && trip.route.from && trip.route.to) return T('{a} to {b}', { a: T(trip.route.from), b: T(trip.route.to) });
  const h = new Date(trip.started_at * 1000).getHours();
  return T(h >= 21 || h < 5 ? 'Night drive' : h < 12 ? 'Morning drive' : h < 17 ? 'Afternoon drive' : 'Evening drive');
}
const alertsText = (n) => (n === 0 ? T('No alerts') : n === 1 ? T('1 alert') : T('{n} alerts', { n }));
const breaksText = (n) => (n === 0 ? T('No breaks') : n === 1 ? T('1 break') : T('{n} breaks', { n }));
function paintSwitch(b, on) {
  b.setAttribute('aria-checked', String(on));
  b.style.background = on ? '#C4B5FD' : 'rgba(255,255,255,.16)';
  b.firstElementChild.style.transform = 'translateX(' + (on ? 20 : 0) + 'px)';
}
function paintSeg(root, attr, val) {
  root.querySelectorAll('[data-' + attr + ']').forEach((b) => {
    const on = b.dataset[attr] === val;
    b.setAttribute('aria-pressed', String(on));
    b.style.background = on ? '#F4EFE6' : 'transparent';
    b.style.color = on ? '#241A26' : '#B3A6B4';
  });
}
// Ollie's line as a speech bubble next to the owl, for a few seconds.
function bubble(el, text) {
  if (!el) return;
  el.textContent = text;
  el.style.opacity = 1;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.opacity = 0; }, Math.max(2600, text.length * 75));
}
function emptyCard(title, sub, img) {
  return `<section style="${GLASS};border-radius:22px;padding:22px 18px;display:flex;gap:14px;align-items:center">
    <img src="${img || IMG.sleepy}" alt="" style="width:64px;flex-shrink:0">
    <div><b style="display:block;font-size:16px">${esc(T(title))}</b><span style="display:block;margin-top:4px;font-size:13.5px;color:#B3A6B4;line-height:1.4">${esc(T(sub))}</span></div></section>`;
}

const DYN = {
  Name(root, ctx) {
    const inp = root.querySelector('#inName'), next = root.querySelector('#nameNext');
    inp.value = API().profile().name || '';
    const clean = () => inp.value.trim().slice(0, 20);
    const paint = () => { const ok = !!clean(); next.setAttribute('aria-disabled', String(!ok)); next.style.opacity = ok ? 1 : 0.4; inp.style.borderColor = ok ? '#C4B5FD' : 'rgba(255,255,255,.18)'; };
    inp.addEventListener('input', paint);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && clean()) next.click(); });
    next.addEventListener('click', (e) => {
      if (!clean()) { e.preventDefault(); e.stopPropagation(); inp.focus(); SFX.play('off'); return; }
      API().saveProfile({ name: clean() });
    });
    paint();
    setTimeout(() => { if (root.isConnected && !clean()) inp.focus({ preventScroll: true }); }, 400);
  },

  Vehicle(root) {
    let pick = API().profile().vehicle || 'long_haul';
    const btns = root.querySelectorAll('[data-veh]');
    function paint() {
      btns.forEach((b) => {
        const on = b.dataset.veh === pick, mark = b.lastElementChild;
        b.setAttribute('aria-pressed', String(on));
        b.style.background = on ? 'rgba(196,181,253,.16)' : 'rgba(255,255,255,.07)';
        b.style.borderColor = on ? '#C4B5FD' : 'transparent';
        mark.style.background = on ? '#C4B5FD' : 'rgba(255,255,255,.11)';
        mark.style.display = 'grid'; mark.style.placeItems = 'center';
        mark.innerHTML = on ? TICK.replace(/12/g, '14') : '';
      });
    }
    root.addEventListener('click', (e) => { const b = e.target.closest('[data-veh]'); if (b) { pick = b.dataset.veh; paint(); } });
    root.querySelector('#vehNext').addEventListener('click', () => API().saveProfile({ vehicle: pick }));
    paint();
  },

  Night(root) {
    const w = API().profile().work || {};
    const days = (w.days && w.days.length === 7 ? w.days : [true, true, true, true, true, false, false]).slice();
    let start = w.start || '22:00', end = w.end || '06:00';
    const P = { day: 'Day', eve: 'Evening', night: 'Night', custom: 'Custom' };
    const range = (k) => (k === 'custom' ? T('Set times') : clock(SHIFTS[k][0]).replace(':00', '') + '–' + clock(SHIFTS[k][1]).replace(':00', ''));
    const $ = (s) => root.querySelector(s);
    const shift = () => shiftOf({ start, end });
    function draw() {
      const sh = shift();
      $('#nDays').innerHTML = WEEKDAYS.map((n, i) => `<button type="button" data-d="${i}" aria-pressed="${days[i]}" aria-label="${esc(T(n))}" style="width:42px;height:42px;border-radius:50%;border:2px solid ${days[i] ? '#C4B5FD' : 'transparent'};background:${days[i] ? '#C4B5FD' : 'rgba(255,255,255,.07)'};color:${days[i] ? '#241A26' : '#B3A6B4'};font-weight:700;font-size:15px;padding:0;transition:all .2s">${esc(T(n).slice(0, BN_LANG() === 'ko' ? 1 : 1))}</button>`).join('');
      $('#nPresets').innerHTML = Object.keys(P).map((k) => `<button type="button" data-p="${k}" aria-pressed="${sh === k}" style="padding:10px 4px;border-radius:14px;text-align:center;border:2px solid ${sh === k ? '#C4B5FD' : 'transparent'};background:${sh === k ? 'rgba(196,181,253,.16)' : 'rgba(255,255,255,.07)'};transition:all .2s"><b style="display:block;font-size:14px">${esc(T(P[k]))}</b><span style="display:block;font-size:11px;color:#B3A6B4;margin-top:2px;white-space:nowrap">${esc(range(k))}</span></button>`).join('');
      $('#nStart').textContent = clock(start); $('#nEnd').textContent = clock(end);
      const ok = days.some(Boolean), next = $('#nNext');
      next.style.opacity = ok ? 1 : 0.4; next.setAttribute('aria-disabled', String(!ok));
    }
    // The time picker: a native one, over the time it changes.
    const picker = document.createElement('input');
    picker.type = 'time'; picker.style.cssText = 'position:absolute;opacity:0;pointer-events:none;width:1px;height:1px';
    root.firstElementChild.appendChild(picker);
    let editing = null;
    picker.addEventListener('change', () => { if (!picker.value) return; if (editing === 'start') start = picker.value; else end = picker.value; draw(); });
    root.addEventListener('click', (e) => {
      const d = e.target.closest('[data-d]'); if (d) { days[+d.dataset.d] = !days[+d.dataset.d]; draw(); }
      const p = e.target.closest('[data-p]');
      if (p) { if (p.dataset.p !== 'custom') { [start, end] = SHIFTS[p.dataset.p]; draw(); } else { editing = 'start'; picker.value = start; open(); } }
      const t = e.target.closest('[data-time]'); if (t) { editing = t.dataset.time; picker.value = editing === 'start' ? start : end; open(); }
    });
    function open() { try { picker.showPicker(); } catch (er) { picker.style.pointerEvents = 'auto'; picker.focus(); picker.click(); } }
    $('#nNext').addEventListener('click', (e) => {
      if (!days.some(Boolean)) { e.preventDefault(); e.stopPropagation(); SFX.play('off'); return; }
      API().saveProfile({ work: { days, start, end, variable: false } });
    });
    $('#nVar').addEventListener('click', () => { if (days.some(Boolean)) API().saveProfile({ work: { days, variable: true } }); });
    draw();
  },

  Ladder(root) {
    const s = API().settings();
    root.querySelectorAll('[data-tog]').forEach((b) => {
      const key = b.dataset.tog;
      const on = () => b.getAttribute('aria-checked') === 'true';
      const paint = () => { b.style.background = on() ? '#C4B5FD' : 'rgba(255,255,255,.11)'; b.firstElementChild.style.transform = 'translateX(' + (on() ? 20 : 0) + 'px)'; };
      b.setAttribute('aria-checked', String(s.ladder[key] !== false));
      b.addEventListener('click', () => { b.setAttribute('aria-checked', String(!on())); paint(); API().saveSettings({ ladder: { [key]: on() } }); });
      paint();
    });
  },

  Permissions(root) {
    // Section 7. In a browser, location and notifications are real prompts;
    // they need https or the app, so a page from the device over plain http
    // says so instead of pretending. Bluetooth is only for finding the device
    // in the app; a browser already reached it over Wi-Fi.
    const secure = window.isSecureContext || !!window.Capacitor;
    const btn = (k) => root.querySelector('[data-perm="' + k + '"]');
    function set(k, state) {
      const b = btn(k);
      const look = { allowed: ['Allowed', '#F8C4A4', '#241A26'], ask: ['Allow', '#F4EFE6', '#241A26'], denied: ['Blocked', 'rgba(244,143,177,.3)', '#F4EFE6'],
        app: ['In the app', 'rgba(255,255,255,.11)', '#B3A6B4'], na: ['Not needed', 'rgba(255,255,255,.11)', '#B3A6B4'] }[state];
      b.textContent = T(look[0]); b.style.background = look[1]; b.style.color = look[2]; b.style.whiteSpace = 'nowrap';
      b.dataset.state = state;
    }
    async function check() {
      set('bt', window.Capacitor ? 'app' : 'na');
      if (!secure) { set('loc', 'app'); set('notif', 'app'); return; }
      try {
        const q = navigator.permissions && await navigator.permissions.query({ name: 'geolocation' });
        set('loc', !q ? 'ask' : q.state === 'granted' ? 'allowed' : q.state === 'denied' ? 'denied' : 'ask');
      } catch (e) { set('loc', 'ask'); }
      if (!('Notification' in window)) set('notif', 'app');
      else set('notif', Notification.permission === 'granted' ? 'allowed' : Notification.permission === 'denied' ? 'denied' : 'ask');
    }
    root.addEventListener('click', (e) => {
      const b = e.target.closest('[data-perm]'); if (!b || b.dataset.state !== 'ask') return;
      if (b.dataset.perm === 'loc') navigator.geolocation.getCurrentPosition(() => set('loc', 'allowed'), () => check());
      if (b.dataset.perm === 'notif') Notification.requestPermission().then(check);
    });
    document.addEventListener('visibilitychange', () => { if (root.isConnected && !document.hidden) check(); });
    check();
  },

  Contact(root) {
    const e0 = API().settings().emergency || {};
    const nm = root.querySelector('#ecName'), ph = root.querySelector('#ecPhone'), err = root.querySelector('#ecErr');
    nm.value = e0.contact_name || ''; ph.value = e0.contact_phone || '';
    const digits = () => ph.value.replace(/[^\d]/g, '');
    const valid = () => !ph.value.trim() || (digits().length >= 9 && digits().length <= 15);
    ph.addEventListener('input', () => { err.textContent = ''; ph.style.borderColor = 'transparent'; });
    root.querySelector('#ecNext').addEventListener('click', (e) => {
      if (!valid()) { e.preventDefault(); e.stopPropagation(); err.textContent = T('That number looks too short.'); ph.style.borderColor = '#F49AC1'; SFX.play('off'); return; }
      const plus = ph.value.trim().startsWith('+') ? '+' : '';
      API().saveSettings({ emergency: { contact_name: nm.value.trim(), contact_phone: digits() ? plus + digits() : '' } });
    });
  },

  Pair(root) {
    // Section 7: the six checks show the device's real part status.
    const w = root.firstElementChild, $ = (s) => root.querySelector(s);
    const Tt = $('#pTitle'), S = $('#pSub'), alive = () => root.isConnected, next = $('#pNext');
    const PARTS = ['camera', 'ir_light', 'blue_light', 'mist', 'speakers', 'co2'];
    const FIX = { camera: 'Check the camera cable.', ir_light: 'Check the infrared LED.', blue_light: 'Check the blue light wiring.', mist: 'Check the mister and its water.', speakers: 'Check the speaker cable.', co2: 'Check the CO₂ sensor cable.' };
    const set = (a, b) => { Tt.style.opacity = 0; S.style.opacity = 0; setTimeout(() => { Tt.textContent = a; S.textContent = b; Tt.style.opacity = 1; S.style.opacity = 1; }, 230); };
    let done = false, tries = 0;
    const t0 = Date.now();
    w.classList.add('searching');
    Tt.textContent = T('Looking for your Bamnun'); S.textContent = T('Keep your phone close to the device.');
    SFX.play('ping');
    const iv = setInterval(() => (alive() && !done ? SFX.play('ping') : clearInterval(iv)), 1200);
    async function attempt() {
      if (!alive() || done) return;
      tries++;
      let h = null;
      try { h = await API().get('/api/health'); } catch (e) {}
      if (!alive() || done) return;
      if (!h) {
        if (Date.now() - t0 > 20000) return fail();
        return setTimeout(attempt, 1500);
      }
      done = true; clearInterval(iv);
      $('#pName').textContent = API().demo ? T('Bamnun · demo') : 'Bamnun · ' + h.device;
      $('#pModel').textContent = T(h.simulated ? 'Simulated device · no camera' : 'Raspberry Pi 5 · NoIR camera');
      set(T('Found your Bamnun'), T('Connecting…'));
      SFX.play('found');
      setTimeout(() => {
        if (!alive()) return;
        let bad = 0, sim = 0;
        [...$('#pChecks').children].forEach((c, i) => {
          const st = (h.parts || {})[PARTS[i]] || 'missing', dot = c.firstElementChild;
          const good = st === 'ok' || st === 'simulated';
          if (!good) bad++; if (st === 'simulated') sim++;
          dot.style.background = good ? '#F8C4A4' : '#F48FB1';
          dot.innerHTML = good ? TICK : CROSS;
          c.title = good ? '' : T(FIX[PARTS[i]]);
          c.style.transitionDelay = (0.35 + i * 0.12) + 's';
          setTimeout(() => alive() && SFX.play('tick'), 700 + i * 120);
        });
        w.classList.remove('searching');
        if (bad) set(T('Bamnun is connected'), T('{n} parts need a look. Tap one to see the fix.', { n: bad }));
        else set(T('Bamnun is connected'), sim === 6 ? T('Simulated device: every part is a stand-in.') : T('All six parts check out.'));
        SFX.play('success');
        API().onConnect();
      }, 900);
    }
    function fail() {
      clearInterval(iv); done = true;
      set(T("Can't find Bamnun"), T('Is it switched on? Is this phone on the Bamnun Wi-Fi, within 3 m?'));
      next.innerHTML = esc(T('Try again'));
      next.style.opacity = 1; next.style.pointerEvents = 'auto';
      next.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); DYN.Pair(root); }, { once: true });
    }
    $('#pChecks').addEventListener('click', (e) => { const c = e.target.closest('#pChecks>div'); if (c && c.title) S.textContent = c.title; });
    setTimeout(attempt, 1600);
  },

  Voice(root) {
    // Section 6: which language Ollie speaks, heard on the device speaker.
    const L = API().lines;
    let pick = API().profile().voice_lang || BN_LANG();
    const say = root.querySelector('#vSay'), note = root.querySelector('#vNote');
    const CARDS = [{ lang: 'ko', name: '한국어', sample: L.sample[1] }, { lang: 'en', name: 'English', sample: L.sample[0] }];
    function draw(glow) {
      root.querySelector('#vCards').innerHTML = CARDS.map((c) => `<button type="button" data-vl="${c.lang}" aria-pressed="${pick === c.lang}" class="vc-card${glow === c.lang ? ' vc-glow' : ''}" style="background:${pick === c.lang ? 'rgba(196,181,253,.16)' : 'rgba(255,255,255,.07)'};border-color:${pick === c.lang ? '#C4B5FD' : 'transparent'}">
        ${pick === c.lang ? '<span style="position:absolute;top:10px;right:10px;width:22px;height:22px;border-radius:50%;background:#C4B5FD;display:grid;place-items:center">' + TICK + '</span>' : ''}
        <b data-lang-keep style="${HEAD_FONT};font-size:26px;margin-top:6px">${c.name}</b>
        <small data-lang-keep style="color:#B3A6B4;font-size:13px;text-align:center;line-height:1.35;min-height:36px">“${esc(c.sample)}”</small>
        <span data-play="${c.lang}" role="button" aria-label="${esc(T('Play'))}" style="display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border-radius:99px;background:rgba(255,255,255,.11);font-size:13px;font-weight:700">${SPEAKER}${esc(T('Play'))}</span></button>`).join('');
    }
    let glowT = null;
    API().on('say', (m) => {
      if (m.line !== 'greet' && m.line !== 'sample') return;
      bubble(say, m.text);
      draw(m.lang); clearTimeout(glowT); glowT = setTimeout(() => root.isConnected && draw(), Math.max(2400, m.text.length * 70));
      if (m.result === 'simulated') note.textContent = T("Ollie's recordings aren't on this Bamnun yet, so the words show here.");
    }, root);
    function greet() { API().say('greet', 'ko'); setTimeout(() => root.isConnected && API().say('greet', 'en'), 3000); }
    root.addEventListener('click', (e) => {
      const b = e.target.closest('[data-vl]');
      if (b) { pick = b.dataset.vl; API().saveProfile({ voice_lang: pick }); draw(pick); API().say('sample', pick); }
    });
    root.querySelector('#vBoth').addEventListener('click', greet);
    root.querySelector('#vNext').addEventListener('click', () => API().saveProfile({ voice_lang: pick }));
    if (!API().online()) note.textContent = T('Connect your Bamnun to hear Ollie.');
    draw();
    setTimeout(() => root.isConnected && API().online() && greet(), 700);
  },

  Calibrate(root, ctx) {
    // Section 8: the guided calibration and device test, run by the device.
    const $ = (s) => root.querySelector(s);
    const STEPS = [
      ['position', 'Get in position'], ['look', 'Look ahead'], ['close', 'Close your eyes'],
      ['speaker', 'Speaker'], ['chime', 'Wake-up chime'], ['light', 'Blue light'], ['mist', 'Mint mist']];
    const TEXT = {
      position: ['Get in position', "Sit like you're driving and look at the camera."],
      look: ['Look straight ahead', 'Blink normally. Ollie is learning your eyes.'],
      close: ['Close your eyes', 'Close them now… and open.'],
      speaker: ['Can you hear Ollie?', 'The voice comes from your Bamnun.'],
      chime: ['Did you hear the chime?', "That's the step 3 wake-up chime."],
      light: ['See the blue light?', 'It glows at the edge of your view for 3 seconds.'],
      mist: ['Smell the mint?', 'A short puff of peppermint mist.'],
    };
    const FAIL = {
      position: ["Ollie can't see you", 'Check the camera faces you and nothing blocks it.'],
      look: ["Ollie couldn't learn your eyes", 'Sit still, face the camera, and check the light. Then try again.'],
      close: ["Ollie didn't see your eyes close", 'Close them fully for a second when asked. Then try again.'],
    };
    let st = { active: false, step: null, results: {} }, finished = false;
    const go = $('#cGo'), later = $('#cLater'), owl = $('#cOwl');
    const mount = MOUNT_CM[API().profile().vehicle] || [50, 70];
    $('#cHint').textContent = T('Mount the camera {a}–{b} cm from your face, facing you.', { a: mount[0], b: mount[1] });

    function list() {
      const idx = STEPS.findIndex((s) => s[0] === st.step);
      $('#cList').innerHTML = STEPS.map(([k, label], i) => {
        const r = st.results[k], now = st.active && k === st.step;
        const dot = r === 'ok' ? `<span class="cal-dot" style="background:#7BD88F">${TICK}</span>`
          : r === 'fail' ? `<span class="cal-dot" style="background:#F48FB1">${CROSS}</span>`
          : `<span class="cal-dot" style="color:${now ? '#241A26' : '#B3A6B4'}">${i + 1}</span>`;
        return `<div class="cal-row${now ? ' cal-now' : ''}" style="${now || r ? 'color:#F4EFE6' : ''};${i > 2 && idx < 3 && !r ? 'opacity:.6' : ''}">${dot}${esc(T(label))}</div>`;
      }).join('');
    }
    function ring(p) { $('#cRing').setAttribute('stroke-dasharray', (490 * Math.max(0, Math.min(1, p))).toFixed(0) + ' 490'); }
    function head(a, b) { $('#cTitle').textContent = T(a); $('#cSub').textContent = T(b); }
    function paint(m) {
      const ask = st.active && ['speaker', 'chime', 'light', 'mist'].includes(st.step);
      $('#cAsk').style.display = ask ? 'flex' : 'none';
      const count = $('#cCount');
      if (st.active) {
        const [a, b] = TEXT[st.step] || ['', ''];
        head(a, st.message === 'no_face' ? "Ollie can't see you. Check the camera faces you." : st.message === 'retry' ? "Let's try that once more. Look straight ahead." : b);
        const i = STEPS.findIndex((s) => s[0] === st.step);
        if (st.step === 'look' && st.progress != null) {
          ring(st.progress); count.style.opacity = 1;
          count.textContent = T('{n} s', { n: Math.max(0, Math.ceil(12 * (1 - st.progress))) });
        } else { ring((i + 0.5) / STEPS.length); count.style.opacity = 0; }
        owl.src = st.step === 'close' ? IMG.sleepy : IMG.thinking;
        go.style.display = 'none';
        later.textContent = T('Cancel');
      } else {
        count.style.opacity = 0;
        go.style.display = '';
        later.textContent = T('Do this later');
        later.style.visibility = finished && st.message === 'done' ? 'hidden' : '';
        if (finished && st.failed) {
          const [a, b] = FAIL[st.failed] || ['Something went wrong', 'Try again.'];
          head(a, b); owl.src = IMG.wake; go.textContent = T('Try again');
        } else if (finished && st.message === 'done') {
          const parts = ['speaker', 'chime', 'light', 'mist'], ok = parts.filter((k) => st.results[k] === 'ok').length;
          head('Ollie knows your eyes', ok === 4 ? 'Every part works. You’re ready to drive.' : T('{n} of 4 parts need a look. Ollie still watches your eyes.', { n: 4 - ok }));
          owl.src = IMG.celebrate; ring(1); go.textContent = T('Next');
          if (!m || m.message === 'done') SFX.play('success');
        } else if (!API().online()) {
          head('Let Ollie learn your eyes', 'Connect your Bamnun first.'); go.textContent = T('Start'); go.style.opacity = 0.5;
        } else {
          head('Let Ollie learn your eyes', 'About a minute. Sit in your driving position, then tap Start.'); go.textContent = T('Start'); go.style.opacity = 1;
        }
      }
      list();
    }
    API().on('calibration', (m) => {
      const was = st.step;
      st = m;
      if (!m.active && (m.message === 'done' || m.failed)) finished = true;
      if (!m.active && m.message === 'cancelled') finished = false;
      if (m.step !== was && m.active) SFX.play('tick');
      paint(m);
    }, root);
    API().on('say', (m) => { if (String(m.line).startsWith('cal_')) bubble($('#cSay'), m.text); }, root);
    go.addEventListener('click', () => {
      if (finished && st.message === 'done') return ctx.forward('Plan');
      if (!API().online()) { SFX.play('off'); return; }
      finished = false; st = { active: true, step: 'position', results: {} }; paint();
      API().post('/api/calibration/start').catch(() => { st = { active: false, results: {} }; paint(); });
    });
    later.addEventListener('click', (e) => {
      if (st.active) { e.preventDefault(); e.stopPropagation(); API().post('/api/calibration/cancel').catch(() => {}); st = { active: false, results: {} }; finished = false; paint(); }
    });
    root.addEventListener('click', (e) => {
      const b = e.target.closest('[data-ans]');
      if (b && st.active) API().post('/api/calibration/answer', { step: st.step, ok: b.dataset.ans === 'yes' }).catch(() => {});
    });
    API().on('health', () => root.isConnected && !st.active && paint(), root);
    paint();
    // Joining a calibration already running (the app reopened mid-way).
    if (!API().demo) API().get('/api/calibration').then((m) => { if (m && m.active && root.isConnected) { st = m; paint(); } }).catch(() => {});
  },

  Home(root) {
    const p = API().profile(), h = new Date().getHours();
    const hello = h >= 5 && h < 12 ? 'Good morning,' : h >= 12 && h < 17 ? 'Good afternoon,' : h >= 17 && h < 22 ? 'Good evening,' : 'Good night,';
    root.querySelector('#hHello').innerHTML = esc(T(hello)) + '<br>' + esc(BN_NAME());
    root.querySelector('#hShift').textContent = T(SHIFT_NAMES[shiftOf(p.work)]);
    const card = root.querySelector('#hTrip');
    async function load() {
      let trips = null;
      try { trips = await API().get('/api/trips?limit=1'); } catch (e) {}
      if (!root.isConnected) return;
      const t = trips && trips[0];
      if (!t) {
        card.innerHTML = emptyCard(trips ? 'No trips yet' : 'Trips appear here', trips ? 'Drive with Bamnun and Ollie keeps count.' : 'Connect your Bamnun to see your trips.', IMG.driving);
        card.style.background = 'none'; card.style.border = '0';
        return;
      }
      const s = t.summary || {};
      card.innerHTML = `<div style="display:flex;gap:12px;align-items:center;padding:16px 16px 6px">
          <span style="position:relative;width:42px;height:42px;flex-shrink:0;border-radius:12px;background:rgba(255,255,255,.11);overflow:hidden"><img src="${IMG.driving}" alt="" style="position:absolute;width:64px;left:-11px;top:-6px"></span>
          <div style="flex-grow:1"><b style="display:block;font-size:15px">${esc(tripTitle(t))}</b><span style="font-size:12.5px;color:#B3A6B4">${esc(when(t.started_at))}</span></div>
          ${t.open ? `<span style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#241A26;background:#F48FB1;padding:4px 8px;border-radius:99px">${esc(T('Now'))}</span>` : API().demo ? `<span style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#B3A6B4;background:rgba(255,255,255,.11);padding:4px 8px;border-radius:99px">${esc(T('Demo'))}</span>` : ''}
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;padding:12px 16px 16px">
          ${[['Time', dur(s.duration_s)], ['Alert-free', s.alert_free == null ? '–' : Math.round(s.alert_free * 100) + '%'], ['Alerts', s.alerts || 0], ['Breaks', s.breaks || 0]].map(([k, v]) => `<div><span style="display:block;font-size:12px;color:#B3A6B4">${esc(T(k))}</span><b style="font-size:17px;white-space:nowrap">${esc(v)}</b></div>`).join('')}
        </div>`;
    }
    API().on('trip', load, root);
    load();
  },

  Trips(root) {
    let range = 'week', all = null, openId = null;
    const $ = (s) => root.querySelector(s);
    $('#tBadge').hidden = !API().demo;
    function draw() {
      paintSeg(root, 'r', range);
      if (!all) { $('#tList').innerHTML = emptyCard('Trips appear here', 'Connect your Bamnun to see your trips.', IMG.driving); return; }
      const since = range === 'all' ? 0 : Date.now() / 1000 - (range === 'week' ? 7 : 30) * 86400;
      const list = all.filter((t) => t.started_at >= since);
      $('#tN').textContent = list.length;
      $('#tTime').textContent = dur(list.reduce((a, t) => a + (t.summary.drive_s || 0), 0));
      $('#tAlerts').textContent = list.reduce((a, t) => a + (t.summary.alerts || 0), 0);
      if (!list.length) { $('#tList').innerHTML = emptyCard(all.length ? 'No trips in this range' : 'No trips yet', 'Drive with Bamnun and Ollie keeps count.', IMG.driving); return; }
      $('#tList').innerHTML = list.map((t) => {
        const s = t.summary || {}, open = openId === t.id, n = s.alerts || 0;
        const detail = open ? `<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:12px 16px 16px;border-top:1px solid rgba(255,255,255,.08)">
            ${[['Alert-free', s.alert_free == null ? '–' : Math.round(s.alert_free * 100) + '%'], ['Longest alert-free', dur(s.longest_calm_s)], ['Highest step', s.max_stage ? T(['', 'Blue light', 'Mint mist', 'Chime and voice', 'Rising alarm'][s.max_stage]) : T('None')], ['Microsleeps', s.microsleeps || 0], ['Break time', dur(s.break_s)], ['Distance', t.route && t.route.distance_km ? t.route.distance_km + ' km' : '–']].map(([k, v]) => `<div><span style="display:block;font-size:12px;color:#B3A6B4">${esc(T(k))}</span><b style="font-size:15px">${esc(v)}</b></div>`).join('')}</div>` : '';
        return `<section data-trip="${t.id}" role="button" aria-expanded="${open}" style="${GLASS};border-radius:22px;overflow:hidden;cursor:pointer">
          <div style="padding:14px 16px">
            <div style="display:flex;justify-content:space-between;align-items:center"><span style="font-size:12.5px;color:#B3A6B4">${esc(when(t.started_at))}</span>${t.open ? `<span style="font-size:11px;font-weight:700;color:#241A26;background:#F48FB1;padding:3px 8px;border-radius:99px">${esc(T('Now'))}</span>` : ''}</div>
            <h2 style="margin:2px 0 0;${HEAD_FONT};font-size:21px">${esc(tripTitle(t))}</h2>
            <div style="display:flex;gap:16px;margin-top:8px;font-size:14px;flex-wrap:wrap"><span><b>${esc(dur(s.duration_s))}</b></span><span style="color:${n ? '#C4B5FD' : '#F8C4A4'}"><b>${esc(alertsText(n))}</b></span><span style="color:#B3A6B4">${esc(breaksText(s.breaks || 0))}</span></div>
          </div>${detail}</section>`;
      }).join('');
    }
    root.addEventListener('click', (e) => {
      const r = e.target.closest('[data-r]'); if (r) { range = r.dataset.r; draw(); return; }
      const c = e.target.closest('[data-trip]'); if (c) { openId = openId === +c.dataset.trip ? null : +c.dataset.trip; draw(); }
    });
    async function load() { try { all = await API().get('/api/trips?limit=500'); } catch (e) {} if (root.isConnected) draw(); }
    API().on('trip', load, root);
    draw(); load();
  },

  Insights(root) {
    let range = 'week';
    const $ = (s) => root.querySelector(s);
    $('#iBadge').hidden = !API().demo;
    const card = (inner) => `<section style="${GLASS};border-radius:22px;padding:16px">${inner}</section>`;
    const h2 = (t, right) => `<div style="display:flex;justify-content:space-between;align-items:baseline"><h2 style="margin:0;${HEAD_FONT};font-size:20px">${esc(T(t))}</h2>${right ? `<span style="font-size:13px;color:#B3A6B4">${esc(right)}</span>` : ''}</div>`;
    const note = (t) => `<p style="margin:10px 0 0;font-size:13.5px;color:#B3A6B4;line-height:1.4">${esc(t)}</p>`;
    function draw(d) {
      paintSeg(root, 'r', range);
      if (!d) { $('#iBody').innerHTML = emptyCard('Insights appear here', 'Connect your Bamnun to see your patterns.', IMG.thinking); return; }
      if (!d.trips) { $('#iBody').innerHTML = emptyCard('Nothing to show yet', 'After a few drives, Ollie shows when you get tired and what wakes you.', IMG.thinking); return; }
      const out = [];
      // 1. Alert driving.
      const pct = d.alert_free == null ? null : Math.round(d.alert_free * 100), prev = d.alert_free_prev == null ? null : Math.round(d.alert_free_prev * 100);
      const period = T(range === 'week' ? 'last week' : 'last month');
      const cmp = prev == null ? '' : pct > prev ? T('Up from {p}% {when}.', { p: prev, when: period }) : pct < prev ? T('Down from {p}% {when}.', { p: prev, when: period }) : T('Same as {when}.', { when: period });
      out.push(card(`<div style="display:flex;gap:16px;align-items:center">
        <div style="position:relative;width:96px;height:96px;flex-shrink:0"><svg viewBox="0 0 96 96" width="96" height="96" style="transform:rotate(-90deg)"><circle cx="48" cy="48" r="40" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="10"/><circle cx="48" cy="48" r="40" fill="none" stroke="#F8C4A4" stroke-width="10" stroke-linecap="round" stroke-dasharray="${(251 * (pct || 0) / 100).toFixed(0)} 251"/></svg>
          <b style="position:absolute;inset:0;display:grid;place-items:center;${HEAD_FONT};font-size:26px">${pct == null ? '–' : pct + '%'}</b></div>
        <div><h2 style="margin:0;${HEAD_FONT};font-size:20px">${esc(T('Alert driving'))}</h2><p style="margin:6px 0 0;font-size:13.5px;color:#B3A6B4;line-height:1.4">${esc(T('Share of driving time with no drowsiness signs.'))} ${esc(cmp)}</p></div></div>`));
      // 2. Alerts per night (or per week).
      const per = d.per || [], max = Math.max(1, ...per.map((x) => x.alerts));
      const bars = per.map((x, i) => {
        const hgt = x.alerts ? 14 + 70 * x.alerts / max : 4;
        const label = range === 'week' ? T(WEEKDAYS[x.weekday]).slice(0, BN_LANG() === 'ko' ? 1 : 3) : T('W{n}', { n: i + 1 });
        return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px"><span style="font-size:12px;font-weight:700;color:${x.alerts ? '#F4EFE6' : 'transparent'}">${x.alerts}</span><div style="width:70%;height:${hgt}px;border-radius:7px;background:${x.alerts ? 'linear-gradient(#C4B5FD,#F9A8D4)' : x.drove ? 'rgba(248,196,164,.55)' : 'rgba(255,255,255,.1)'}"></div><span style="font-size:11.5px;color:#B3A6B4">${esc(label)}</span></div>`;
      }).join('');
      const off = (API().profile().work || {}).days ? WEEKDAYS.filter((n, i) => !API().profile().work.days[i]).map((n) => T(n)) : [];
      out.push(card(h2(range === 'week' ? 'Alerts per night' : 'Alerts per week', T('{n} total', { n: d.alerts })) +
        `<div style="display:flex;align-items:flex-end;height:118px;margin-top:12px">${bars}</div>` +
        (range === 'week' && off.length ? note(T('Off days in your work week: {days}.', { days: off.join(', ') })) : '')));
      // 3. When you got tired.
      if (d.alerts) {
        const hmax = Math.max(1, ...d.hours);
        const hb = d.hours.map((n, hr) => `<span title="${esc(hourLabel(hr))}" style="flex:1;height:${n ? 10 + 60 * n / hmax : 3}px;border-radius:3px;background:${hr === d.peak_hour ? '#F48FB1' : n ? '#C4B5FD' : 'rgba(255,255,255,.1)'}"></span>`).join('');
        out.push(card(h2('When you got tired') + `<div role="img" aria-label="${esc(T('Alerts by hour of the day'))}" style="display:flex;align-items:flex-end;gap:2px;height:76px;margin-top:14px">${hb}</div>
          <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px;color:#B3A6B4"><span>${esc(hourLabel(0))}</span><span>${esc(hourLabel(6))}</span><span>${esc(hourLabel(12))}</span><span>${esc(hourLabel(18))}</span><span>${esc(hourLabel(0))}</span></div>` +
          note(T('Most tired hour: {a} to {b}', { a: hourLabel(d.peak_hour), b: hourLabel((d.peak_hour + 1) % 24) }))));
        // 4. What woke you up.
        const names = ['Blue light', 'Mint mist', 'Voice', 'Alarm'], colours = ['#A99BF0', '#F5B5C8', '#C4B5FD', '#F48FB1'];
        const wmax = Math.max(1, ...d.woke_by);
        out.push(card(h2('What woke you up') + `<div style="display:flex;flex-direction:column;gap:10px;margin-top:12px">${d.woke_by.map((n, i) => `<div style="display:flex;align-items:center;gap:10px"><span style="width:84px;font-size:13.5px;color:#B3A6B4">${esc(T(names[i]))}</span><div style="flex:1;height:10px;border-radius:6px;background:rgba(255,255,255,.08);overflow:hidden"><div style="width:${100 * n / wmax}%;height:100%;border-radius:6px;background:${colours[i]}"></div></div><b style="width:22px;text-align:right">${n}</b></div>`).join('')}</div>` +
          note(T('The first step was enough {a} out of {b} times.', { a: d.first_step_enough, b: d.alerts }))));
      } else out.push(card(h2('No alerts') + note(T('Ollie never had to wake you in this range. Keep it up.'))));
      $('#iBody').innerHTML = out.join('');
    }
    async function load() {
      paintSeg(root, 'r', range);
      let d = null;
      try { d = await API().get('/api/insights?range=' + range + '&tz=' + (-new Date().getTimezoneOffset())); } catch (e) {}
      if (root.isConnected) draw(d);
    }
    root.addEventListener('click', (e) => { const r = e.target.closest('[data-r]'); if (r) { range = r.dataset.r; load(); } });
    draw(null); load();
  },

  Settings(root, ctx) {
    const $ = (s) => root.querySelector(s);
    const BREAKS = [0, 60, 90, 120, 180];
    const breakText = (m) => (m ? T('Every {h} h', { h: m / 60 }) : T('Off'));
    function paint() {
      const p = API().profile(), s = API().settings(), h = API().health();
      $('#sProf').textContent = T(VEHICLES[p.vehicle] || 'Long-haul truck') + ' · ' + T(SHIFT_NAMES[shiftOf(p.work)]);
      paintSeg(root, 'lang', BN_LANG());
      paintSeg(root, 'vlang', p.voice_lang || BN_LANG());
      paintSeg(root, 'sens', s.sensitivity);
      $('#sBreak').textContent = breakText(s.break_every_min);
      const tog = { sound: SFX.enabled(), voice: s.ladder.voice !== false, co2: s.co2_alert, call: s.emergency.call_services, demo: s.emergency.demo };
      root.querySelectorAll('[data-tog]').forEach((b) => paintSwitch(b, !!tog[b.dataset.tog]));
      const e = s.emergency;
      $('#sContact').textContent = e.contact_phone ? (e.contact_name ? e.contact_name + ' · ' : '') + e.contact_phone : T('Not set');
      $('#sDev').textContent = API().demo ? T('Bamnun · demo') : h ? 'Bamnun · ' + h.device : 'Bamnun';
      $('#sDevSub').textContent = API().demo ? T('Simulated driver, in this page') : API().online() ? T(h && h.simulated ? 'Connected · simulated device' : 'Connected · Raspberry Pi 5') : T('Not connected');
      if (h && h.version) $('#sVer').textContent = 'v' + h.version;
    }
    root.addEventListener('click', (e) => {
      const b = e.target.closest('button,[data-go]'); if (!b) return;
      if (b.dataset.lang) setTimeout(() => API().saveProfile({ app_lang: BN_LANG() }), 0);
      if (b.dataset.vlang) { API().saveProfile({ voice_lang: b.dataset.vlang }); API().say('sample', b.dataset.vlang); }
      if (b.dataset.sens) API().saveSettings({ sensitivity: b.dataset.sens });
      if (b.id === 'sBreak') { const cur = API().settings().break_every_min; API().saveSettings({ break_every_min: BREAKS[(BREAKS.indexOf(cur) + 1) % BREAKS.length] }); }
      if (b.id === 'sTryEm') { window.BN_EMERGENCY && BN_EMERGENCY.show({ practice: true }); return; }
      if (b.id === 'sReset') {
        if (!confirm(T('Start over? This clears your name and choices on this phone. Your trips stay on the device.'))) { e.preventDefault(); e.stopPropagation(); return; }
        try { Object.keys(localStorage).filter((k) => k.startsWith('bn-') && k !== 'bn-lang' && k !== 'bn-pi').forEach((k) => localStorage.removeItem(k)); } catch (er) {}
        setTimeout(() => location.reload(), 50);
        return;
      }
      const k = b.dataset.tog; if (!k) return;
      const on = b.getAttribute('aria-checked') !== 'true';
      if (k === 'sound') { if (!on) SFX.play('off'); SFX.set(on); }
      if (k === 'voice') API().saveSettings({ ladder: { voice: on } });
      if (k === 'co2') API().saveSettings({ co2_alert: on });
      if (k === 'demo') API().saveSettings({ emergency: { demo: on } });
      if (k === 'call') {
        if (on && !confirm(T("If you don't respond and your contact has been tried, Ollie opens your phone's dialer with no number filled in. Nothing is called until you tap Call. Turn on?")))
          return;
        API().saveSettings({ emergency: { call_services: on } });
      }
      setTimeout(paint, 0);
    });
    API().on('profile_changed', () => root.isConnected && paint(), root);
    API().on('settings_changed', () => root.isConnected && paint(), root);
    API().on('health', () => root.isConnected && paint(), root);
    paint();
  },
};
