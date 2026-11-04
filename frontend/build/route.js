/* Route (docs/SPEC.md, section 9): Kakao map, place search, directions, and
   the highway rest areas along the way, with Ollie's pick of where to stop.

   The map and the search use the Kakao JS SDK on the phone, with the JS key
   (public, locked to registered web addresses). Directions come from Kakao
   Mobility through the device (GET /api/route), so the secret REST key never
   ships in the app. "Set route" starts the trip on the device and saves the
   route with it. */
DYN.Route = function (root, ctx) {
  const $ = (s) => root.querySelector(s);
  const msg = $('#rMapMsg'), list = $('#rList'), head = $('#rListHead'), sum = $('#rSum'), setBtn = $('#rSet');
  const fromIn = $('#rtFrom'), toIn = $('#rtTo');
  const SEOUL = { lat: 37.5665, lng: 126.978 };
  let map = null, places = null, K = null, searching = false;
  let origin = null, dest = null, result = null, stops = [], pick = null, field = 'to';
  let overlays = [], line = null, searchT = null, seq = 0;
  const alive = () => root.isConnected;

  function say(html) { msg.style.display = 'grid'; msg.innerHTML = html; }
  function recent() { try { return JSON.parse(localStorage.getItem('bn-recent') || '[]'); } catch (e) { return []; } }
  function remember(p) { const r = recent().filter((x) => x.name !== p.name); r.unshift(p); try { localStorage.setItem('bn-recent', JSON.stringify(r.slice(0, 5))); } catch (e) {} }
  const km = (m) => (m >= 10000 ? Math.round(m / 1000) : (m / 1000).toFixed(1)) + ' km';
  function hav(a, b) {
    const R = 6371000, r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const at = (secondsFromNow) => new Date(Date.now() + secondsFromNow * 1000).toLocaleTimeString(locale(), { hour: 'numeric', minute: '2-digit' });

  // -- the SDK ------------------------------------------------------------ //
  function loadSdk(key) {
    if (window.kakao && window.kakao.maps && window.kakao.maps.services) return Promise.resolve();
    if (!window._bnKakao) {
      window._bnKakao = new Promise((res, rej) => {
        const s = document.createElement('script');
        s.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=' + encodeURIComponent(key) + '&libraries=services&autoload=false';
        s.onload = () => { try { kakao.maps.load(res); } catch (e) { rej(e); } };
        s.onerror = () => rej(new Error('load'));
        document.head.appendChild(s);
        setTimeout(() => rej(new Error('timeout')), 12000);
      }).catch((e) => { window._bnKakao = null; throw e; });
    }
    return window._bnKakao;
  }
  async function init() {
    say(esc(T('Loading the map…')));
    let key = window.BN_KAKAO_JS || null;
    if (!key) { try { key = (await API().get('/api/config')).kakao_js_key; } catch (e) {} }
    if (!alive()) return;
    if (!key) {
      say(`<div><b style="display:block;color:#F4EFE6;font-size:15px">${esc(T('The map needs a Kakao key'))}</b><span style="display:block;margin-top:6px">${esc(T('Add KAKAO_JS_KEY and KAKAO_REST_KEY to frontend/.env on the device, then restart it.'))}</span></div>`);
      return;
    }
    try { await loadSdk(key); } catch (e) {
      if (alive()) say(`<div><b style="display:block;color:#F4EFE6;font-size:15px">${esc(T("Kakao Maps didn't load"))}</b><span style="display:block;margin-top:6px">${esc(T('Check the internet connection, and that this address is registered for the key in Kakao Developers: {addr}', { addr: location.origin }))}</span></div>`);
      return;
    }
    if (!alive()) return;
    K = kakao.maps;
    map = new K.Map($('#rMap'), { center: new K.LatLng(SEOUL.lat, SEOUL.lng), level: 9 });
    places = new K.services.Places();
    msg.style.display = 'none';
    locate();
  }
  function locate() {
    fromIn.placeholder = T('Finding where you are…');
    if (!navigator.geolocation || !window.isSecureContext) return noLocation();
    navigator.geolocation.getCurrentPosition((p) => {
      if (!alive()) return;
      setOrigin({ lat: p.coords.latitude, lng: p.coords.longitude, name: T('Current location'), here: true });
    }, noLocation, { timeout: 8000, maximumAge: 60000, enableHighAccuracy: false });
  }
  function noLocation() {
    if (!alive()) return;
    fromIn.placeholder = T('Type your starting point');
    if (!origin) { field = 'from'; fromIn.focus(); }
  }
  function setOrigin(p) {
    origin = p; fromIn.value = p.name;
    if (map) map.setCenter(new K.LatLng(p.lat, p.lng));
    drawPins();
    if (dest) route(); else showRecent();
  }

  // -- search ------------------------------------------------------------- //
  function showRecent() {
    const r = recent();
    head.textContent = r.length ? T('Recent') : '';
    list.style.display = r.length ? '' : 'none';
    list.innerHTML = r.map((p, i) => row(p.name, p.address || '', '', 'recent', i)).join('');
  }
  function row(name, sub, right, kind, i) {
    return `<button type="button" class="rt-row" data-${kind}="${i}"><span style="width:34px;height:34px;flex-shrink:0;border-radius:11px;background:rgba(255,255,255,.11);display:grid;place-items:center"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#C4B5FD" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg></span>
      <span style="flex-grow:1;min-width:0"><b style="display:block;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(name)}</b><span style="display:block;font-size:12.5px;color:#B3A6B4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(sub)}</span></span>
      <span style="font-size:13px;color:#B3A6B4;white-space:nowrap">${esc(right)}</span></button>`;
  }
  let found = [];
  function search(q) {
    if (!places) return;
    const my = ++seq;
    const opts = origin ? { location: new K.LatLng(origin.lat, origin.lng), sort: K.services.SortBy.ACCURACY } : {};
    places.keywordSearch(q, (data, status) => {
      if (!alive() || my !== seq) return;
      found = status === K.services.Status.OK ? data : [];
      head.textContent = found.length ? T('Places') : '';
      list.style.display = '';
      list.innerHTML = found.length ? found.slice(0, 8).map((p, i) => row(p.place_name, p.road_address_name || p.address_name, p.distance ? km(+p.distance) : '', 'place', i)).join('')
        : `<div style="padding:14px;color:#B3A6B4;font-size:14px">${esc(status === K.services.Status.ZERO_RESULT ? T('Nothing found. Try another name.') : T("Search isn't working right now."))}</div>`;
    }, opts);
  }
  function onType(e) {
    field = e.target === fromIn ? 'from' : 'to';
    const q = e.target.value.trim();
    clearTimeout(searchT);
    if (!q) { if (field === 'to') showRecent(); return; }
    searchT = setTimeout(() => search(q), 280);
  }
  fromIn.addEventListener('input', onType); toIn.addEventListener('input', onType);
  fromIn.addEventListener('focus', () => { field = 'from'; if (origin && origin.here) fromIn.select(); });
  toIn.addEventListener('focus', () => { field = 'to'; if (!toIn.value.trim()) showRecent(); });
  root.addEventListener('click', (e) => {
    const p = e.target.closest('[data-place]'), r = e.target.closest('[data-recent]'), st = e.target.closest('[data-stop]');
    if (p || r) {
      const f = p ? found[+p.dataset.place] : recent()[+r.dataset.recent];
      const place = p ? { lat: +f.y, lng: +f.x, name: f.place_name, address: f.road_address_name || f.address_name } : f;
      list.style.display = 'none'; head.textContent = '';
      if (field === 'from') setOrigin(place);
      else { dest = place; toIn.value = place.name; toIn.blur(); remember(place); route(); }
    }
    if (st && map) { const s = stops[+st.dataset.stop]; map.panTo(new K.LatLng(s.lat, s.lng)); map.setLevel(6); }
  });

  // -- the route ------------------------------------------------------------ //
  function clearMap() { overlays.forEach((o) => o.setMap(null)); overlays = []; if (line) { line.setMap(null); line = null; } }
  function pin(p, label, cls) {
    const o = new K.CustomOverlay({ position: new K.LatLng(p.lat, p.lng), content: `<div class="rt-pin ${cls || ''}">${esc(label)}</div>`, yAnchor: 1.2 });
    o.setMap(map); overlays.push(o);
  }
  function drawPins() {
    if (!map) return;
    clearMap();
    if (origin) pin(origin, T('Start'), '');
    if (dest) pin(dest, dest.name, 'pick');
    if (result) {
      line = new K.Polyline({ path: result.path.map(([x, y]) => new K.LatLng(y, x)), strokeWeight: 6, strokeColor: '#8B5CF6', strokeOpacity: 0.9 });
      line.setMap(map);
      stops.forEach((s) => pin(s, (s === pick ? '🦉 ' : '') + s.short, s === pick ? 'pick' : ''));
    }
  }
  async function route() {
    if (!origin || !dest) return;
    result = null; stops = []; pick = null; searching = true; paintSet();
    sum.innerHTML = `<p style="margin:14px 6px;color:#B3A6B4;font-size:14px">${esc(T('Finding the route…'))}</p>`;
    let r;
    try {
      const v = API().profile().vehicle || 'car';
      r = await API().get(`/api/route?origin=${origin.lng},${origin.lat}&destination=${dest.lng},${dest.lat}&vehicle=${v}`);
    } catch (e) {
      if (!alive()) return;
      sum.innerHTML = `<p style="margin:14px 6px;color:#F49AC1;font-size:14px;line-height:1.4">${esc(T("Couldn't get directions."))} ${esc(e.message || '')}</p>`;
      return;
    }
    if (!alive() || !r || !r.path) return;
    result = r;
    const pts = r.path.map(([x, y]) => ({ lat: y, lng: x }));
    if (map) { const b = new K.LatLngBounds(); pts.forEach((p) => b.extend(new K.LatLng(p.lat, p.lng))); map.setBounds(b, 30, 30, 30, 30); }
    drawPins(); paintSummary(); paintSet();
    findStops(pts);
  }

  // Highway rest areas (휴게소) along the line: search around points every
  // 20 km, keep the ones within 1.5 km of the route, in order along it.
  function findStops(pts) {
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + hav(pts[i - 1], pts[i]));
    const total = cum[cum.length - 1], probes = [];
    for (let d = 15000; d < total - 5000; d += 20000) probes.push(pts[cum.findIndex((c) => c >= d)]);
    const seen = new Map(), my = seq;
    let left = probes.length;
    if (!left) { searching = false; return paintSummary(); }
    probes.forEach((pr, k) => setTimeout(() => {
      if (!alive()) return;
      places.keywordSearch('휴게소', (data, status) => {
        if (!alive()) return;
        if (status === K.services.Status.OK) for (const p of data) {
          if (!/휴게소/.test(p.place_name) || /주유소|충전소|약국|식당|편의점|정류장/.test(p.place_name)) continue;
          const q = { lat: +p.y, lng: +p.x };
          let best = Infinity, bi = 0;
          for (let i = 0; i < pts.length; i += 2) { const d = hav(q, pts[i]); if (d < best) { best = d; bi = i; } }
          if (best > 1500) continue;
          const base = p.place_name.replace(/\s*\(.*\)\s*$/, '');
          const prev = seen.get(base);
          if (!prev || best < prev.off) seen.set(base, { lat: q.lat, lng: q.lng, name: p.place_name, short: base.replace(/휴게소$/, ''), off: best, along: cum[bi], id: p.id });
        }
        if (--left === 0) {
          searching = false;
          stops = [...seen.values()].sort((a, b) => a.along - b.along);
          stops.forEach((s) => { s.eta_s = result.duration_s * s.along / total; });
          choose(); drawPins(); paintSummary();
        }
      }, { location: new K.LatLng(pr.lat, pr.lng), radius: 4000 });
    }, k * 120));
  }

  // Ollie's pick (section 9): the last rest area before the break is due
  // and before the driver's tired window, whichever comes first.
  function tiredWindowIn() {
    const w = API().profile().work || {}, now = new Date();
    const sh = shiftOf(w);
    const startH = sh === 'day' ? 13 : sh === 'eve' ? 14 : 2;           // post-lunch dip, or the 2-5 AM trough
    const t = new Date(now); t.setHours(startH, 0, 0, 0);
    if (t <= now) t.setDate(t.getDate() + 1);
    return (t - now) / 1000;
  }
  let reason = '';
  function choose() {
    const every = (API().settings().break_every_min || 120) * 60, tired = tiredWindowIn();
    const deadline = Math.min(every, tired);
    const before = stops.filter((s) => s.eta_s <= deadline && s.eta_s >= 20 * 60);
    pick = before.length ? before[before.length - 1] : stops[0] || null;
    if (!pick) return;
    reason = tired < every && pick.eta_s <= tired ? T('Stop here at {t}, before your tired window.', { t: at(pick.eta_s) })
      : pick.eta_s <= every ? T('Stop here at {t}, {d} into the drive.', { t: at(pick.eta_s), d: dur(pick.eta_s) })
      : T('The first rest area, at {t}. Your break is due before it.', { t: at(pick.eta_s) });
  }

  function paintSummary() {
    if (!result) return;
    const v = API().profile().vehicle, truck = ['long_haul', 'delivery', 'bus'].includes(v);
    const cell = (k, val) => `<div><span style="display:block;font-size:12px;color:#B3A6B4">${esc(T(k))}</span><b style="font-size:18px;white-space:nowrap">${esc(val)}</b></div>`;
    let html = `<section style="margin-top:12px;border-radius:22px;${GLASS};padding:14px 16px">
      <h2 style="margin:0;${HEAD_FONT};font-size:21px">${esc(T('{a} to {b}', { a: origin.name, b: dest.name }))}</h2>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:10px">${cell('Distance', km(result.distance_m))}${cell('Time', dur(result.duration_s))}${cell('Arrive', at(result.duration_s))}</div>
      ${result.toll_won ? `<p style="margin:8px 0 0;font-size:13px;color:#B3A6B4">${esc(T('Tolls about {n} won', { n: result.toll_won.toLocaleString() }))}</p>` : ''}
      ${truck ? `<p style="margin:6px 0 0;font-size:12.5px;color:#B3A6B4;line-height:1.4">${esc(T("Kakao's car route. Truck height and weight limits aren't checked."))}</p>` : ''}
    </section>`;
    html += `<p style="margin:16px 6px 8px;font-size:12.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#B3A6B4">${esc(T('Rest areas on the way'))}</p>`;
    if (!stops.length) html += `<section style="border-radius:20px;${GLASS};padding:14px;color:#B3A6B4;font-size:14px">${esc(T(left0() ? 'Looking for rest areas…' : 'No highway rest areas on this route.'))}</section>`;
    else html += `<section style="border-radius:20px;${GLASS};overflow:hidden">${stops.map((s, i) => `<button type="button" class="rt-row" data-stop="${i}" style="${s === pick ? 'background:rgba(196,181,253,.14)' : ''}">
        ${s === pick ? `<img src="${IMG.cup}" alt="" style="width:34px;flex-shrink:0">` : `<span style="width:34px;text-align:center;font-weight:800;color:#B3A6B4">${i + 1}</span>`}
        <span style="flex-grow:1;min-width:0"><b style="display:block;font-size:15px">${esc(s.name)}</b><span style="display:block;font-size:12.5px;color:${s === pick ? '#C4B5FD' : '#B3A6B4'}">${esc(s === pick ? reason : T('{km} · around {t}', { km: km(s.along), t: at(s.eta_s) }))}</span></span></button>`).join('')}</section>`;
    sum.innerHTML = html;
  }
  const left0 = () => searching && !stops.length && result;
  function paintSet() { setBtn.disabled = !result; setBtn.style.opacity = result ? 1 : 0.4; }

  setBtn.addEventListener('click', async () => {
    if (!result) return;
    const route = { from: origin.name, to: dest.name, to_lat: dest.lat, to_lng: dest.lng,
      distance_km: Math.round(result.distance_m / 100) / 10, duration_s: result.duration_s,
      eta: Date.now() / 1000 + result.duration_s,
      stop: pick ? { name: pick.name, km: Math.round(pick.along / 1000), eta_s: Math.round(pick.eta_s) } : null };
    setBtn.disabled = true;
    try {
      await API().post('/api/trips/start');
      await API().put('/api/trips/current/route', route);
    } catch (e) {}
    SFX.play('start');
    ctx.forward('Home');
  });

  paintSet();
  init();
};
