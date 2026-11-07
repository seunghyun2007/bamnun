/* The interactive screens. Each init gets the screen's root element and a
   context ({go, forward, setLang, rerender}). Everything the driver chooses
   goes through BN_API (api.js): saved on the phone at once, and on the
   device as soon as it's reachable. Every string shown goes through BN_T or
   is an exact key in ko.json, so it follows the app language. */
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const T = (s, v) => BN_T(s, v);
const API = () => window.BN_API;
const GLASS = 'background:#1F1C24;border:0';
const HEAD_FONT = "font-family:Pretendard,system-ui,sans-serif;font-weight:700;letter-spacing:-.01em";
const TICK = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#15131A" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
const CROSS = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#15131A" stroke-width="2.8" stroke-linecap="round" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>';
const SPEAKER = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';

const VEHICLES = { long_haul: 'Long-haul truck', delivery: 'Delivery truck', bus: 'Bus or coach', taxi: 'Taxi or van', car: 'My own car' };
const MOUNT_CM = { long_haul: [50, 70], delivery: [50, 70], bus: [50, 70], taxi: [40, 60], car: [40, 60] };
const SHIFTS = { day: ['06:00', '14:00'], eve: ['14:00', '22:00'], night: ['22:00', '06:00'] };
const SHIFT_NAMES = { day: 'Day shift', eve: 'Evening shift', night: 'Night shift', custom: 'Custom hours', variable: 'Hours change weekly' };
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

// Trips from the cloud and the device together when signed in (sync.js).
const SYNC_TRIPS = (n) => (window.BN_SYNC ? BN_SYNC.trips(n) : API().get('/api/trips?limit=' + n));
const ACC = () => window.BN_ACCOUNT;

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
// "새벽 2시 40분, 칠곡휴게소 지나서 두 번 졸았어요": what happened on a trip,
// in one sentence. The numbers under it only support it.
function koClock(d) {
  const h = d.getHours(), m = d.getMinutes();
  const part = h === 0 || h >= 18 ? '밤' : h < 6 ? '새벽' : h < 12 ? '오전' : '오후';
  const h12 = h % 12 || 12;
  return part + ' ' + h12 + '시' + (m ? ' ' + m + '분' : '');
}
function tripSentence(t) {
  const s = t.summary || {}, eps = (s.episodes || []).slice().sort((a, b) => a.at - b.at), ko = BN_LANG() === 'ko';
  const n = eps.length || s.alerts || 0;
  if (!n) return ko ? '한 번도 졸지 않고 끝까지 운전했어요.' : 'No drowsiness the whole way.';
  const count = ko ? (['', '한 번', '두 번', '세 번', '네 번', '다섯 번'][n] || n + '번') : (['', 'once', 'twice'][n] || n + ' times');
  if (!eps.length) return ko ? '이번 운전에서 ' + count + ' 졸았어요.' : 'You got drowsy ' + count + ' on this drive.';
  const first = new Date(eps[0].at * 1000), span = Math.max(1, (t.ended_at || t.started_at + (s.duration_s || 1)) - t.started_at);
  const at = ko ? koClock(first) : first.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  const f = (eps[0].at - t.started_at) / span;
  const passed = ((t.route && t.route.stops) || []).filter((x) => x.f <= f).pop();
  if (passed) return ko ? at + ', ' + passed.name + ' 지나서 ' + count + ' 졸았어요.' : 'At ' + at + ', after ' + passed.name + ', you got drowsy ' + count + '.';
  return ko ? at + '부터 ' + count + ' 졸았어요.' : 'From ' + at + ', you got drowsy ' + count + '.';
}
const alertsText = (n) => (n === 0 ? T('No alerts') : n === 1 ? T('1 alert') : T('{n} alerts', { n }));
const breaksText = (n) => (n === 0 ? T('No breaks') : n === 1 ? T('1 break') : T('{n} breaks', { n }));
function paintSwitch(b, on) {
  b.setAttribute('aria-checked', String(on));
  b.style.background = on ? '#E8D7AE' : '#2E2A33';
  b.firstElementChild.style.transform = 'translateX(' + (on ? 20 : 0) + 'px)';
}
function paintSeg(root, attr, val) {
  root.querySelectorAll('[data-' + attr + ']').forEach((b) => {
    const on = b.dataset[attr] === val;
    b.setAttribute('aria-pressed', String(on));
    b.style.background = on ? '#2E2A33' : 'transparent';
    b.style.color = on ? '#F2EEE8' : '#9A93A0';
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
    <div><b style="display:block;font-size:16px">${esc(T(title))}</b><span style="display:block;margin-top:4px;font-size:13.5px;color:#9A93A0;line-height:1.4">${esc(T(sub))}</span></div></section>`;
}

const DYN = {
  Name(root, ctx) {
    const inp = root.querySelector('#inName'), next = root.querySelector('#nameNext');
    inp.value = API().profile().name || '';
    const clean = () => inp.value.trim().slice(0, 20);
    const paint = () => { const ok = !!clean(); next.setAttribute('aria-disabled', String(!ok)); next.style.opacity = ok ? 1 : 0.4; inp.style.borderColor = ok ? '#E8D7AE' : 'rgba(255,255,255,.18)'; };
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
        b.style.background = on ? 'rgba(232,215,174,.16)' : 'rgba(255,255,255,.07)';
        b.style.borderColor = on ? '#E8D7AE' : 'transparent';
        mark.style.background = on ? '#E8D7AE' : 'rgba(255,255,255,.11)';
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
      $('#nDays').innerHTML = WEEKDAYS.map((n, i) => `<button type="button" data-d="${i}" aria-pressed="${days[i]}" aria-label="${esc(T(n))}" style="width:42px;height:42px;border-radius:50%;border:2px solid ${days[i] ? '#E8D7AE' : 'transparent'};background:${days[i] ? '#E8D7AE' : 'rgba(255,255,255,.07)'};color:${days[i] ? '#15131A' : '#9A93A0'};font-weight:700;font-size:15px;padding:0;transition:all .2s">${esc(T(n).slice(0, BN_LANG() === 'ko' ? 1 : 1))}</button>`).join('');
      $('#nPresets').innerHTML = Object.keys(P).map((k) => `<button type="button" data-p="${k}" aria-pressed="${sh === k}" style="padding:10px 4px;border-radius:14px;text-align:center;border:2px solid ${sh === k ? '#E8D7AE' : 'transparent'};background:${sh === k ? 'rgba(232,215,174,.16)' : 'rgba(255,255,255,.07)'};transition:all .2s"><b style="display:block;font-size:14px">${esc(T(P[k]))}</b><span style="display:block;font-size:11px;color:#9A93A0;margin-top:2px;white-space:nowrap">${esc(range(k))}</span></button>`).join('');
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
      const paint = () => { b.style.background = on() ? '#E8D7AE' : 'rgba(255,255,255,.11)'; b.firstElementChild.style.transform = 'translateX(' + (on() ? 20 : 0) + 'px)'; };
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
      const look = { allowed: ['Allowed', '#E8D7AE', '#15131A'], ask: ['Allow', '#F2EEE8', '#15131A'], denied: ['Blocked', 'rgba(242,182,109,.3)', '#F2EEE8'],
        app: ['In the app', 'rgba(255,255,255,.11)', '#9A93A0'], na: ['Not needed', 'rgba(255,255,255,.11)', '#9A93A0'] }[state];
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
      if (!valid()) { e.preventDefault(); e.stopPropagation(); err.textContent = T('That number looks too short.'); ph.style.borderColor = '#9A93A0'; SFX.play('off'); return; }
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
          dot.style.background = good ? '#E8D7AE' : '#F2B66D';
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
      root.querySelector('#vCards').innerHTML = CARDS.map((c) => `<button type="button" data-vl="${c.lang}" aria-pressed="${pick === c.lang}" class="vc-card${glow === c.lang ? ' vc-glow' : ''}" style="background:${pick === c.lang ? 'rgba(232,215,174,.16)' : 'rgba(255,255,255,.07)'};border-color:${pick === c.lang ? '#E8D7AE' : 'transparent'}">
        ${pick === c.lang ? '<span style="position:absolute;top:10px;right:10px;width:22px;height:22px;border-radius:50%;background:#E8D7AE;display:grid;place-items:center">' + TICK + '</span>' : ''}
        <b data-lang-keep style="${HEAD_FONT};font-size:26px;margin-top:6px">${c.name}</b>
        <small data-lang-keep style="color:#9A93A0;font-size:13px;text-align:center;line-height:1.35;min-height:36px">“${esc(c.sample)}”</small>
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

  Home(root) {
    const p = API().profile(), h = new Date().getHours();
    const hello = h >= 5 && h < 12 ? 'Good morning,' : h >= 12 && h < 17 ? 'Good afternoon,' : h >= 17 && h < 22 ? 'Good evening,' : 'Good night,';
    root.querySelector('#hHello').innerHTML = esc(T(hello)) + '<br>' + esc(BN_NAME());
    // A booth visitor (visit.js): their photo from the booth as the profile.
    const paintVisit = () => {
      if (!root.isConnected) return;
      root.querySelector('#hHello').innerHTML = esc(T(hello)) + '<br>' + esc(BN_NAME());
      const ph = window.BN_VISIT && BN_VISIT.photo();
      let av = root.querySelector('#hAvatar');
      if (ph && !av) {
        av = document.createElement('img');
        av.id = 'hAvatar'; av.alt = '';
        av.style.cssText = 'display:block;width:56px;height:56px;border-radius:50%;object-fit:cover;margin-bottom:12px';
        root.querySelector('#hHello').before(av);
      }
      if (av && ph) av.src = ph;
      load();
    };
    window.addEventListener('bn-visit', paintVisit);
    if (window.BN_VISIT && BN_VISIT.photo()) setTimeout(paintVisit, 0);
    root.querySelector('#hShift').textContent = T(SHIFT_NAMES[shiftOf(p.work)]);
    // Came from Product demo on the Welcome screen: offer the way back.
    let showcase = false; try { showcase = localStorage.getItem('bn-showcase') === '1'; } catch (e) {}
    if (showcase) {
      const pill = 'display:inline-flex;align-items:center;gap:6px;padding:6px 0;font-size:13px;font-weight:500;text-decoration:none;color:#9A93A0';
      const bar = document.createElement('div');
      bar.style.cssText = 'position:absolute;top:12px;left:22px;right:22px;z-index:5;display:flex;justify-content:space-between';
      bar.innerHTML = `<a href="#Welcome" data-go="Welcome" data-back style="${pill}">‹ ${esc(T('Start'))}</a><a href="#Stages" data-go="Stages" style="${pill}">${esc(T('Try the wake-up stages'))} ›</a>`;
      root.querySelector('#hHead').appendChild(bar);
    }
    const card = root.querySelector('#hTrip');
    async function load() {
      let trips = null;
      try { trips = await SYNC_TRIPS(1); } catch (e) {}
      if (!root.isConnected) return;
      const t = trips && trips[0];
      if (!t) {
        card.innerHTML = emptyCard(trips ? 'No trips yet' : 'Trips appear here', trips ? 'Drive with Bamnun and Ollie keeps count.' : 'Connect your Bamnun to see your trips.', IMG.driving);
        card.style.background = 'none'; card.style.border = '0';
        return;
      }
      const s = t.summary || {}, n = s.alerts || 0;
      // One row: where and when, then how long and how it went.
      const tag = t.open ? T('Now') : API().demo ? T('Demo') : '';
      card.innerHTML = `<a href="#Trips" data-go="Trips" style="display:flex;gap:14px;align-items:center;padding:16px 18px;color:inherit;text-decoration:none">
          <div style="flex-grow:1;min-width:0"><b style="display:block;font-size:15.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(tripTitle(t))}</b>
            <span style="display:block;margin-top:3px;font-size:13px;color:#9A93A0">${esc(when(t.started_at))}${tag ? ' · ' + esc(tag) : ''}</span></div>
          <div style="text-align:right;flex-shrink:0"><b style="display:block;font-size:15.5px;font-weight:600">${esc(dur(s.duration_s))}</b>
            <span style="display:block;margin-top:3px;font-size:13px;color:${n ? '#E8D7AE' : '#9A93A0'}">${esc(alertsText(n))}</span></div>
        </a>`;
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
      const nT = list.length, nA = list.reduce((a, t) => a + (t.summary.alerts || 0), 0), dT = esc(dur(list.reduce((a, t) => a + (t.summary.drive_s || 0), 0)));
      const B = (v) => `<b style="color:#F2EEE8;font-weight:600">${v}</b>`;
      $('#tSum').innerHTML = BN_LANG() === 'ko' ? `운행 ${B(nT + '번')} · 운전 ${B(dT)} · 알림 ${B(nA + '번')}`
        : `${B(nT)} ${nT === 1 ? 'trip' : 'trips'} · ${B(dT)} driving · ${B(nA)} ${nA === 1 ? 'alert' : 'alerts'}`;
      if (!list.length) { $('#tList').innerHTML = emptyCard(all.length ? 'No trips in this range' : 'No trips yet', 'Drive with Bamnun and Ollie keeps count.', IMG.driving); return; }
      $('#tList').innerHTML = list.map((t) => {
        const s = t.summary || {}, open = openId === String(t.id), n = s.alerts || 0;
        const stat = ([k, v]) => `<div><span style="display:block;font-size:12.5px;color:#9A93A0">${esc(T(k))}</span><b style="display:block;margin-top:2px;font-size:15px;font-weight:600">${esc(v)}</b></div>`;
        const V = window.BN_VISIT;
        const detail = open ? `<div style="padding:0 18px 18px">
            <p style="margin:2px 0 0;font-size:17px;font-weight:600;line-height:1.45;color:#F2EEE8">${esc(tripSentence(t))}</p>
            ${V ? V.mapSvg(t) + V.curveSvg(t) + V.caughtHtml(t) : ''}
            <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px 10px;margin-top:16px;padding-top:14px;border-top:1px solid #2E2A33">
            ${[['Alert-free', s.alert_free == null ? '–' : Math.round(s.alert_free * 100) + '%'], ['Longest alert-free', dur(s.longest_calm_s)], ['Highest step', s.max_stage ? T(['', 'Blue light', 'Mint mist', 'Chime and voice', 'Rising alarm'][s.max_stage]) : T('None')], ['Microsleeps', s.microsleeps || 0], ['Break time', dur(s.break_s)], ['Distance', t.route && t.route.distance_km ? t.route.distance_km + ' km' : '–']].map(stat).join('')}</div></div>` : '';
        return `<section data-trip="${esc(t.id)}" role="button" aria-expanded="${open}" style="background:#1F1C24;border-radius:20px;overflow:hidden;cursor:pointer">
          <div style="padding:16px 18px">
            <span style="display:block;font-size:13px;color:#9A93A0">${esc(when(t.started_at))}${t.open ? ' · ' + esc(T('Now')) : ''}</span>
            <h2 style="margin:4px 0 0;${HEAD_FONT};font-size:18px">${esc(tripTitle(t))}</h2>
            <div style="margin-top:6px;font-size:14px;color:#9A93A0">${esc(dur(s.duration_s))} · <span style="color:${n ? '#E8D7AE' : '#9A93A0'}">${esc(alertsText(n))}</span> · ${esc(breaksText(s.breaks || 0))}</div>
          </div>${detail}</section>`;
      }).join('');
    }
    root.addEventListener('click', (e) => {
      const r = e.target.closest('[data-r]'); if (r) { range = r.dataset.r; draw(); return; }
      const c = e.target.closest('[data-trip]'); if (c) { openId = openId === c.dataset.trip ? null : c.dataset.trip; draw(); }
    });
    async function load() { try { all = await SYNC_TRIPS(500); } catch (e) {} if (root.isConnected) draw(); }
    API().on('trip', load, root);
    API().on('sync', (m) => m.status.state === 'done' && load(), root);
    window.addEventListener('bn-visit', () => root.isConnected && load());
    draw(); load();
  },

  Insights(root) {
    let range = 'week';
    const $ = (s) => root.querySelector(s);
    $('#iBadge').hidden = !API().demo;
    const card = (inner) => `<section style="background:#1F1C24;border-radius:20px;padding:18px">${inner}</section>`;
    const h2 = (t, right) => `<div style="display:flex;justify-content:space-between;align-items:baseline"><h2 style="margin:0;${HEAD_FONT};font-size:16px">${esc(T(t))}</h2>${right ? `<span style="font-size:13px;color:#9A93A0">${esc(right)}</span>` : ''}</div>`;
    const note = (t) => `<p style="margin:10px 0 0;font-size:13.5px;color:#9A93A0;line-height:1.45">${esc(t)}</p>`;
    const ko = () => BN_LANG() === 'ko';
    const hourName = (h) => (ko() ? koClock(new Date(2000, 0, 1, h)) : hourLabel(h));
    function draw(d) {
      paintSeg(root, 'r', range);
      if (!d) { $('#iBody').innerHTML = emptyCard('Insights appear here', 'Connect your Bamnun to see your patterns.', IMG.thinking); return; }
      if (!d.trips) { $('#iBody').innerHTML = emptyCard('Nothing to show yet', 'After a few drives, Ollie shows when you get tired and what wakes you.', IMG.thinking); return; }
      const out = [];
      const period = ko() ? (range === 'week' ? '이번 주' : '이번 달') : (range === 'week' ? 'this week' : 'this month');
      // 1. The one finding: the riskiest hour, and what to change.
      if (d.alerts && d.peak_hour != null) {
        const k = d.hours[d.peak_hour], ph = d.peak_hour, next = (ph + 1) % 24;
        const head = ko() ? hourName(ph) + '가 가장 위험해요' : hourLabel(ph) + ' is your riskiest hour';
        const sub = ko() ? `${period} 졸음 ${d.alerts}번 중 ${k}번이 ${hourName(ph)}~${hourName(next).replace(/^(새벽|오전|오후|밤) /, '')} 사이였어요. 그 전에 한 번 쉬어 가세요.`
          : `${k} of your ${d.alerts} drowsy moments ${period} came between ${hourLabel(ph)} and ${hourLabel(next)}. Take a break before then.`;
        const hmax = Math.max(1, ...d.hours);
        const hb = d.hours.map((n, hr) => `<span title="${esc(hourLabel(hr))}" style="flex:1;height:${n ? 8 + 62 * n / hmax : 2}px;border-radius:2px;background:${hr === ph ? '#E8D7AE' : n ? '#5C5662' : '#2E2A33'}"></span>`).join('');
        out.push(`<section style="background:#1F1C24;border-radius:20px;padding:22px 20px 18px">
          <span style="display:block;font-size:13px;color:#9A93A0">${esc(T('When you got tired'))}</span>
          <h2 style="margin:8px 0 0;${HEAD_FONT};font-size:26px;line-height:1.25;color:#F2EEE8">${esc(head)}</h2>
          <p style="margin:8px 0 0;font-size:14.5px;color:#9A93A0;line-height:1.5">${esc(sub)}</p>
          <div role="img" aria-label="${esc(T('Alerts by hour of the day'))}" style="display:flex;align-items:flex-end;gap:2px;height:72px;margin-top:20px">${hb}</div>
          <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px;color:#9A93A0"><span>${esc(hourLabel(0))}</span><span>${esc(hourLabel(6))}</span><span>${esc(hourLabel(12))}</span><span>${esc(hourLabel(18))}</span><span>${esc(hourLabel(0))}</span></div></section>`);
      } else {
        out.push(`<section style="background:#1F1C24;border-radius:20px;padding:22px 20px">
          <h2 style="margin:0;${HEAD_FONT};font-size:26px;line-height:1.25">${esc(ko() ? period + '엔 한 번도 졸지 않았어요' : 'No drowsy moments ' + period)}</h2>${note(T('Ollie never had to wake you in this range. Keep it up.'))}</section>`);
      }
      // 2. Alert driving, as a sentence with its number.
      const pct = d.alert_free == null ? null : Math.round(d.alert_free * 100), prev = d.alert_free_prev == null ? null : Math.round(d.alert_free_prev * 100);
      const lastP = T(range === 'week' ? 'last week' : 'last month');
      const cmp = prev == null ? '' : pct > prev ? T('Up from {p}% {when}.', { p: prev, when: lastP }) : pct < prev ? T('Down from {p}% {when}.', { p: prev, when: lastP }) : T('Same as {when}.', { when: lastP });
      out.push(card(`<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px">${h2('Alert driving')}<b style="${HEAD_FONT};font-size:24px">${pct == null ? '–' : pct + '%'}</b></div>
        <div style="height:6px;margin-top:12px;border-radius:3px;background:#2E2A33;overflow:hidden"><div style="width:${pct || 0}%;height:100%;background:#9A93A0"></div></div>` +
        note(T('Share of driving time with no drowsiness signs.') + (cmp ? ' ' + cmp : ''))));
      // 3. Alerts per night (or per week).
      const per = d.per || [], max = Math.max(1, ...per.map((x) => x.alerts));
      const bars = per.map((x, i) => {
        const hgt = x.alerts ? 12 + 60 * x.alerts / max : 3;
        const label = range === 'week' ? T(WEEKDAYS[x.weekday]).slice(0, BN_LANG() === 'ko' ? 1 : 3) : T('W{n}', { n: i + 1 });
        return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px"><span style="font-size:12px;font-weight:600;color:${x.alerts ? '#F2EEE8' : 'transparent'}">${x.alerts}</span><div style="width:60%;height:${hgt}px;border-radius:3px;background:${x.alerts ? '#5C5662' : '#2E2A33'}"></div><span style="font-size:11.5px;color:#9A93A0">${esc(label)}</span></div>`;
      }).join('');
      const off = (API().profile().work || {}).days ? WEEKDAYS.filter((n, i) => !API().profile().work.days[i]).map((n) => T(n)) : [];
      out.push(card(h2(range === 'week' ? 'Alerts per night' : 'Alerts per week', T('{n} total', { n: d.alerts })) +
        `<div style="display:flex;align-items:flex-end;height:104px;margin-top:12px">${bars}</div>` +
        (range === 'week' && off.length ? note(T('Off days in your work week: {days}.', { days: off.join(', ') })) : '')));
      // 4. What woke you up.
      if (d.alerts) {
        const names = ['Blue light', 'Mint mist', 'Voice', 'Alarm'];
        const wmax = Math.max(1, ...d.woke_by);
        out.push(card(h2('What woke you up') + `<div style="display:flex;flex-direction:column;gap:10px;margin-top:14px">${d.woke_by.map((n, i) => `<div style="display:flex;align-items:center;gap:10px"><span style="width:84px;font-size:13.5px;color:#9A93A0">${esc(T(names[i]))}</span><div style="flex:1;height:6px;border-radius:3px;background:#2E2A33;overflow:hidden"><div style="width:${100 * n / wmax}%;height:100%;border-radius:3px;background:#9A93A0"></div></div><b style="width:22px;text-align:right;font-weight:600">${n}</b></div>`).join('')}</div>` +
          note(T('The first step was enough {a} out of {b} times.', { a: d.first_step_enough, b: d.alerts }))));
      }
      $('#iBody').innerHTML = out.join('');
    }
    async function load() {
      paintSeg(root, 'r', range);
      let d = null;
      const tz = -new Date().getTimezoneOffset();
      try { d = window.BN_SYNC ? await BN_SYNC.insights(range, tz) : await API().get('/api/insights?range=' + range + '&tz=' + tz); } catch (e) {}
      if (root.isConnected) draw(d);
    }
    root.addEventListener('click', (e) => { const r = e.target.closest('[data-r]'); if (r) { range = r.dataset.r; load(); } });
    API().on('sync', (m) => m.status.state === 'done' && load(), root);
    window.addEventListener('bn-visit', () => root.isConnected && load());
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
      paintAccount();
    }
    function paintAccount() {
      const u = ACC() && ACC().user(), btn = $('#sAcctBtn');
      if (!btn) return;
      btn.textContent = T('Sign in');
      btn.style.display = u ? 'none' : '';
      // Signed in: Log out and Delete account. Signed out: Start over.
      $('#sAcctActions').style.display = u ? 'flex' : 'none';
      $('#sReset').style.display = u ? 'none' : 'block';
      $('#sAcct').textContent = u ? (u.email || T('Signed in')) : T('Not signed in');
      if (!u) { $('#sAcctSub').textContent = T('Sign in to keep your trips in the cloud'); return; }
      const st = BN_SYNC.status(), n = BN_SYNC.pending();
      $('#sAcctSub').textContent = n ? (n === 1 ? T('1 trip waiting to upload') : T('{n} trips waiting to upload', { n }))
        : st.state === 'syncing' ? T('Syncing…') : st.state === 'offline' ? T('Offline · syncs when you have internet')
        : st.state === 'error' ? T('Sync problem · will try again') : T('Profile and trips synced');
    }
    root.addEventListener('click', (e) => {
      const b = e.target.closest('button,[data-go]'); if (!b) return;
      if (b.dataset.lang) setTimeout(() => API().saveProfile({ app_lang: BN_LANG() }), 0);
      if (b.dataset.vlang) { API().saveProfile({ voice_lang: b.dataset.vlang }); API().say('sample', b.dataset.vlang); }
      if (b.dataset.sens) API().saveSettings({ sensitivity: b.dataset.sens });
      if (b.id === 'sBreak') { const cur = API().settings().break_every_min; API().saveSettings({ break_every_min: BREAKS[(BREAKS.indexOf(cur) + 1) % BREAKS.length] }); }
      if (b.id === 'sTryEm') { window.BN_EMERGENCY && BN_EMERGENCY.show({ practice: true }); return; }
      const restart = () => { try { history.replaceState(null, '', location.pathname + location.search); } catch (er) {} location.reload(); };
      if (b.id === 'sAcctBtn') {
        // Signing in on a phone that's already set up keeps its answers.
        try { localStorage.setItem('bn-acct-from', 'Settings'); } catch (er) {}
        ctx.forward('Account');
        return;
      }
      if (b.id === 'sLogout') {
        if (!confirm(T('Log out? Your trips stay on the device and in your account.'))) return;
        b.disabled = true;
        BN_SYNC.signOut().finally(restart);
        return;
      }
      if (b.id === 'sDelete') {
        if (!confirm(T("Delete your account? Your profile and trip history are deleted from the cloud for good. Trips on the device stay. This can't be undone."))) return;
        b.disabled = true;
        BN_SYNC.deleteAccount().then(restart, (er) => {
          console.error(er);
          b.disabled = false;
          alert(T("Your account wasn't deleted. Check your internet and try again.") + (er && er.message ? ' (' + er.message + ')' : ''));
        });
        return;
      }
      if (b.id === 'sReset') {
        if (!confirm(T('Start over? This clears your name and choices on this phone. Your trips stay on the device.'))) { e.preventDefault(); e.stopPropagation(); return; }
        // Signs out too. Trips not uploaded yet (bn-sync-*) are kept for that account.
        if (ACC() && ACC().user()) ACC().signOut();
        try { Object.keys(localStorage).filter((k) => k.startsWith('bn-') && !k.startsWith('bn-sync-') && k !== 'bn-lang' && k !== 'bn-pi').forEach((k) => localStorage.removeItem(k)); } catch (er) {}
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
    API().on('sync', () => root.isConnected && paintAccount(), root);
    paint();
  },

  Welcome(root) {
    root.querySelectorAll('[data-go="Account"]').forEach((a) => a.addEventListener('click', () => { try { localStorage.removeItem('bn-acct-from'); } catch (e) {} }));
    // Product demo opens Home without setup; remember it so Home offers the
    // way back here.
    root.querySelectorAll('[data-go="Home"],[data-go="Stages"]').forEach((a) => a.addEventListener('click', () => { try { localStorage.setItem('bn-showcase', '1'); } catch (e) {} }));
  },

  // Product control (the booth demo): swipe through the four wake-up stages
  // and play one. With a Bamnun connected it plays on the real device, one
  // phone at a time (the device answers 409 while another stage is playing,
  // and tells every phone what's playing). Otherwise it's a preview here.
  Stages(root) {
    const $ = (q) => root.querySelector(q);
    const track = $('#stTrack'), cards = [...root.querySelectorAll('.st-card')], dots = [...root.querySelectorAll('.st-dot')];
    const play = $('#stPlay'), label = $('#stPlayLabel'), msg = $('#stMsg'), dev = $('#stDev');
    const SOUND = { 1: 'on', 2: 'on', 3: 'chime', 4: 'alarm' };
    let cur = 1, busyUntil = 0, busyStage = 0, mine = false, timer = null;
    const live = () => !API().demo && API().online();
    dev.textContent = T(live() ? 'Bamnun connected' : 'Preview on your phone');
    if (live()) { dev.style.color = '#E8D7AE'; }

    function select(n) {
      if (n === cur && cards[n - 1].classList.contains('on')) return;
      cur = n;
      cards.forEach((c, i) => c.classList.toggle('on', i === n - 1));
      dots.forEach((d, i) => d.classList.toggle('on', i === n - 1));
      label.textContent = T('Play stage {n}', { n });
      SFX.play('tick');
    }
    // A tap on a dot or card scrolls there; the cards passed on the way
    // don't light up.
    let steer = 0, steerUntil = 0;
    const show = (n) => { const c = cards[n - 1]; steer = n; steerUntil = Date.now() + 900; track.scrollTo({ left: c.offsetLeft - (track.clientWidth - c.offsetWidth) / 2, behavior: 'smooth' }); select(n); };
    // The card that's mostly in view is the selected one.
    const seen = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        const n = cards.indexOf(en.target) + 1;
        if (steer && Date.now() < steerUntil) { if (n === steer) steer = 0; continue; }
        steer = 0;
        select(n);
      }
    }, { root: track, threshold: 0.6 });
    cards.forEach((c) => seen.observe(c));
    cards.forEach((c, i) => c.addEventListener('click', () => { if (i + 1 !== cur) show(i + 1); }));
    dots.forEach((d, i) => d.addEventListener('click', () => show(i + 1)));

    function glow(n, s) {
      const c = cards[n - 1];
      c.classList.add('playing');
      setTimeout(() => c.classList.remove('playing'), s * 1000);
    }
    function tick() {
      clearTimeout(timer);
      const left = Math.ceil((busyUntil - Date.now()) / 1000);
      if (left <= 0) { play.disabled = false; msg.textContent = ''; mine = false; return; }
      play.disabled = true;
      msg.textContent = mine ? T('Playing on Bamnun now…') : T('Someone is playing stage {n} on Bamnun. Your turn in {s} s.', { n: busyStage, s: left });
      timer = setTimeout(tick, 250);
    }
    // Every phone hears what the device is playing, so the button waits.
    API().on('showcase', (m) => {
      if (!live()) return;
      busyUntil = Date.now() + (m.hold_s || 4) * 1000; busyStage = m.stage;
      if (!mine) glow(m.stage, m.hold_s || 4);
      tick();
    }, root);

    play.addEventListener('click', async () => {
      const n = cur;
      if (!live()) {
        SFX.play(SOUND[n]); glow(n, n >= 3 ? 3 : 2);
        if (n >= 3) API().say('stage' + n);
        msg.textContent = T('Preview on your phone. At the booth, this plays on the real Bamnun.');
        return;
      }
      play.disabled = true; mine = true;
      try {
        const r = await API().post('/api/showcase/stage/' + n);
        SFX.play(SOUND[n]); glow(n, r.hold_s || 4);
        busyUntil = Math.max(busyUntil, Date.now() + (r.hold_s || 4) * 1000); busyStage = n;
        tick();
      } catch (e) {
        mine = false;
        if (/409/.test(e.message)) { if (busyUntil < Date.now()) busyUntil = Date.now() + 3000; tick(); }
        else { play.disabled = false; msg.textContent = T("Couldn't reach Bamnun. Try again."); }
      }
    });
    select(1);
    requestAnimationFrame(() => show(1));
  },

  // Sign in with Google (account.js), then on through setup or straight home.
  Account(root, ctx) {
    const $ = (q) => root.querySelector(q);
    const btn = $('#aGoogle'), msg = $('#aMsg'), G = $('#aIcon').innerHTML;
    let from = null;
    try { from = localStorage.getItem('bn-acct-from'); } catch (e) {}
    // From Settings the phone is already set up: no "Not now" into setup.
    if (from === 'Settings') { const sk = $('#aSkip'); sk.setAttribute('data-go', 'Settings'); sk.setAttribute('data-back', ''); sk.setAttribute('href', '#Settings'); }
    const say = (t, err) => { msg.textContent = t; msg.style.color = err ? '#9A93A0' : '#9A93A0'; };
    function busy(on, label) {
      btn.disabled = on;
      $('#aLabel').textContent = T(label || 'Continue with Google');
      $('#aIcon').innerHTML = on ? '<span class="ac-spin"></span>' : G;
    }
    async function signedIn() {
      busy(true, 'Loading your profile…'); say('');
      try {
        const to = await BN_SYNC.afterSignIn(ctx.setLang, { keepPhone: from === 'Settings' });
        try { localStorage.removeItem('bn-acct-from'); } catch (e) {}
        if (!root.isConnected) return;
        SFX.play('success');
        ctx.go(to);
      } catch (e) {
        console.error(e);
        if (!root.isConnected) return;
        busy(false, 'Try again');
        say(T("Signed in, but your profile didn't load. Check your internet and try again."), true);
      }
    }
    function failed(e) {
      console.error(e);
      if (!root.isConnected) return;
      busy(false);
      say(e && e.cancelled ? T('Sign-in was cancelled.') : T("Sign-in didn't finish. Please try again.") + (e && e.message ? ' (' + e.message + ')' : ''), !(e && e.cancelled));
    }
    btn.addEventListener('click', () => {
      if (ACC().user()) { signedIn(); return; }
      busy(true, 'Opening Google…'); say('');
      ACC().signIn().then(signedIn, failed);
    });
    if (ACC().pendingReturn()) { busy(true, 'Signing you in…'); ACC().returned().then(signedIn, failed); }
    else if (ACC().user()) signedIn();
    else if (!ACC().ready()) {
      btn.disabled = true;
      say(T(ACC().configured() ? 'Sign-in works in the Bamnun app, or from a page at http://localhost.' : "Sign-in isn't set up in this copy of the app."));
    }
  },
};
