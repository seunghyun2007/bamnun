/* Maps (docs/SPEC.md, section 9): plan a route, then drive it.

   Route  full-screen Kakao map. From / To on top, search as you type, or
          tap the pin button and drag the map under the pin to the exact
          spot. The bottom sheet shows the route, the rest areas on the way
          and Ollie's stop. "Set route" starts the trip on the device.
   Home   a live card while a route is set: a small map, km and time left.
   Drive  the card opened up: the map follows the phone's position along the
          route, with what's left, the arrival time and the next stop.

   The map and place search use the Kakao JS SDK on the phone with the JS key
   (public, locked to registered web addresses). Directions come from Kakao
   Mobility through the device (GET /api/route), so the REST key stays there. */

// -- shared ----------------------------------------------------------------- //
const KMAP = {
  K: null,
  async load() {
    if (window.kakao && kakao.maps && kakao.maps.services) return (KMAP.K = kakao.maps);
    let key = window.BN_KAKAO_JS || null;
    if (!key) { try { key = (await API().get('/api/config')).kakao_js_key; } catch (e) {} }
    if (!key) throw new Error('nokey');
    if (!window._bnKakao) {
      window._bnKakao = new Promise((res, rej) => {
        const s = document.createElement('script');
        s.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=' + encodeURIComponent(key) + '&libraries=services&autoload=false';
        s.onload = () => { try { kakao.maps.load(res); } catch (e) { rej(e); } };
        s.onerror = () => rej(new Error('load'));
        document.head.appendChild(s);
        setTimeout(() => rej(new Error('load')), 12000);
      }).catch((e) => { window._bnKakao = null; throw e; });
    }
    await window._bnKakao;
    return (KMAP.K = kakao.maps);
  },
  failText(e) {
    return e && e.message === 'nokey'
      ? `<div><b style="display:block;color:#F2EEE8;font-size:15px">${esc(T('The map needs a Kakao key'))}</b><span style="display:block;margin-top:6px">${esc(T('Add KAKAO_JS_KEY and KAKAO_REST_KEY to frontend/.env on the device, then restart it.'))}</span></div>`
      : `<div><b style="display:block;color:#F2EEE8;font-size:15px">${esc(T("Kakao Maps didn't load"))}</b><span style="display:block;margin-top:6px">${esc(T('Check the internet connection, and that this address is registered for the key in Kakao Developers: {addr}', { addr: location.origin }))}</span></div>`;
  },
  ll: (p) => new KMAP.K.LatLng(p.lat, p.lng),
  pin(map, p, label, cls) {
    const o = new KMAP.K.CustomOverlay({ position: KMAP.ll(p), content: `<div class="mp-pin ${cls || ''}">${esc(label)}</div>`, yAnchor: 1.2 });
    o.setMap(map); return o;
  },
  line(map, path, color, weight) {
    const l = new KMAP.K.Polyline({ path: path.map(KMAP.ll), strokeWeight: weight || 6, strokeColor: color || '#E8D7AE', strokeOpacity: 0.92 });
    l.setMap(map); return l;
  },
  fit(map, pts, pad) { const b = new KMAP.K.LatLngBounds(); pts.forEach((p) => b.extend(KMAP.ll(p))); map.setBounds(b, pad || 40, pad || 40, pad || 40, pad || 40); },
};
function hav(a, b) {
  const R = 6371000, r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
const kmText = (m) => (m >= 10000 ? Math.round(m / 1000) : (m / 1000).toFixed(1)) + ' km';
const clockIn = (s) => new Date(Date.now() + s * 1000).toLocaleTimeString(locale(), { hour: 'numeric', minute: '2-digit' });

// -- the active drive: the route that was set, and where the phone is ------ //
const BN_DRIVE = (function () {
  let route = null, pos = null, watch = null;
  const subs = new Set();
  try { route = JSON.parse(localStorage.getItem('bn-drive') || 'null'); } catch (e) {}
  function cum(path) { const c = [0]; for (let i = 1; i < path.length; i++) c.push(c[i - 1] + hav(path[i - 1], path[i])); return c; }
  if (route) route.cum = cum(route.path);
  function save() { try { localStorage.setItem('bn-drive', JSON.stringify(route ? Object.assign({}, route, { cum: undefined }) : null)); } catch (e) {} }
  function emit() { subs.forEach((f) => { try { f(); } catch (e) { console.error(e); } }); }
  // Where we are along the route: the nearest point of the line.
  function progress() {
    if (!route) return null;
    const total = route.cum[route.cum.length - 1];
    if (!pos) return { left_m: total, left_s: route.duration_s, along: 0, off_m: null, total };
    let best = Infinity, bi = 0;
    for (let i = 0; i < route.path.length; i++) { const d = hav(pos, route.path[i]); if (d < best) { best = d; bi = i; } }
    const along = route.cum[bi], left = Math.max(0, total - along);
    return { left_m: left, left_s: route.duration_s * left / total, along, off_m: best, total, idx: bi };
  }
  function nextStop(p) {
    if (!route || !route.stops) return null;
    const along = p ? p.along : 0;
    return route.stops.find((s) => s.along > along + 300) || null;
  }
  function start() {
    if (watch != null || !navigator.geolocation || !window.isSecureContext) return;
    watch = navigator.geolocation.watchPosition((p) => {
      pos = { lat: p.coords.latitude, lng: p.coords.longitude, acc: p.coords.accuracy, at: Date.now() };
      emit();
    }, () => emit(), { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 });
  }
  return {
    get: () => route, pos: () => pos, progress, nextStop, start,
    set(r) { route = r; if (route) route.cum = cum(route.path); save(); start(); emit(); },
    clear() { route = null; save(); emit(); },
    on(fn, root) { subs.add(fn); if (root) { const iv = setInterval(() => { if (!root.isConnected) { subs.delete(fn); clearInterval(iv); } }, 1000); } },
  };
})();
if (BN_DRIVE.get()) BN_DRIVE.start();

// -- Route ------------------------------------------------------------------ //
DYN.Route = function (root, ctx) {
  const $ = (s) => root.querySelector(s);
  const msg = $('#rMapMsg'), list = $('#rList'), sum = $('#rSum'), cross = $('#rCross');
  const fromIn = $('#rtFrom'), toIn = $('#rtTo');
  let map = null, places = null, geocoder = null, K = null;
  let origin = null, dest = null, result = null, stops = [], pick = null, field = 'to';
  let pickMode = null, pickPlace = null, overlays = [], line = null, searchT = null, seq = 0, searching = false, showStops = false, reason = '';
  const alive = () => root.isConnected;
  const recent = () => { try { return JSON.parse(localStorage.getItem('bn-recent') || '[]'); } catch (e) { return []; } };
  function remember(p) { const r = recent().filter((x) => x.name !== p.name); r.unshift(p); try { localStorage.setItem('bn-recent', JSON.stringify(r.slice(0, 5))); } catch (e) {} }
  function placeList() { const top = $('#rTop'); list.style.top = (top.offsetTop + top.offsetHeight + 8) + 'px'; }

  async function init() {
    try { K = await KMAP.load(); } catch (e) { if (alive()) msg.innerHTML = KMAP.failText(e); return; }
    if (!alive()) return;
    const here = BN_DRIVE.pos();
    map = new K.Map($('#rMap'), { center: KMAP.ll(here || { lat: 37.5665, lng: 126.978 }), level: here ? 5 : 8 });
    places = new K.services.Places(); geocoder = new K.services.Geocoder();
    msg.style.display = 'none';
    setTimeout(() => alive() && map.relayout(), 450);
    K.event.addListener(map, 'dragstart', () => { if (pickMode) cross.classList.add('lift'); });
    K.event.addListener(map, 'dragend', () => cross.classList.remove('lift'));
    K.event.addListener(map, 'idle', () => { if (pickMode) lookup(); });
    K.event.addListener(map, 'click', (e) => { if (pickMode) map.panTo(e.latLng); });
    locate();
    paintSheet();
  }
  function locate(center) {
    fromIn.placeholder = T('Finding where you are…');
    if (!navigator.geolocation || !window.isSecureContext) return noLocation();
    navigator.geolocation.getCurrentPosition((p) => {
      if (!alive()) return;
      const here = { lat: p.coords.latitude, lng: p.coords.longitude, name: T('Current location'), here: true };
      if (center && map) { map.setCenter(KMAP.ll(here)); map.setLevel(4); }
      if (!origin || origin.here) setOrigin(here);
    }, noLocation, { timeout: 8000, maximumAge: 60000 });
  }
  function noLocation() { if (alive()) fromIn.placeholder = T('Type your starting point'); }
  function setOrigin(p) { origin = p; fromIn.value = p.name; drawPins(); if (dest) route(); else if (map && !dest) { map.setCenter(KMAP.ll(p)); } }
  function setDest(p) { dest = p; toIn.value = p.name; remember(p); route(); }

  // -- search -------------------------------------------------------------- //
  const row = (name, sub, right, kind, i) => `<button type="button" class="mp-row" data-${kind}="${i}"><span style="color:#E8D7AE;flex-shrink:0">📍</span><span style="flex:1;min-width:0"><b>${esc(name)}</b><span style="display:block;font-size:12.5px;color:#9A93A0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(sub)}</span></span><span style="font-size:13px;color:#9A93A0;white-space:nowrap">${esc(right)}</span></button>`;
  function showRecent() {
    const r = recent();
    if (!r.length) { list.hidden = true; return; }
    placeList(); list.hidden = false;
    list.innerHTML = `<p style="margin:10px 14px 4px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#9A93A0">${esc(T('Recent'))}</p>` + r.map((p, i) => row(p.name, p.address || '', '', 'recent', i)).join('');
  }
  let found = [];
  function search(q) {
    if (!places) return;
    const my = ++seq, near = origin || BN_DRIVE.pos();
    places.keywordSearch(q, (data, status) => {
      if (!alive() || my !== seq) return;
      found = status === K.services.Status.OK ? data : [];
      placeList(); list.hidden = false;
      list.innerHTML = found.length ? found.slice(0, 8).map((p, i) => row(p.place_name, p.road_address_name || p.address_name, p.distance ? kmText(+p.distance) : '', 'place', i)).join('')
        : `<div style="padding:14px;color:#9A93A0;font-size:14px">${esc(T(status === K.services.Status.ZERO_RESULT ? 'Nothing found. Try another name.' : "Search isn't working right now."))}</div>`;
    }, near ? { location: KMAP.ll(near), sort: K.services.SortBy.ACCURACY } : {});
  }
  function onType(e) {
    field = e.target === fromIn ? 'from' : 'to';
    if (pickMode) endPick();
    const q = e.target.value.trim();
    clearTimeout(searchT);
    if (!q) { if (field === 'to') showRecent(); else list.hidden = true; return; }
    searchT = setTimeout(() => search(q), 280);
  }
  fromIn.addEventListener('input', onType); toIn.addEventListener('input', onType);
  fromIn.addEventListener('focus', () => { field = 'from'; if (origin && origin.here) fromIn.select(); });
  toIn.addEventListener('focus', () => { field = 'to'; if (!toIn.value.trim()) showRecent(); });

  // -- pick on the map: drag the map under the pin ------------------------- //
  function startPick(which) {
    if (!map) return;
    list.hidden = true; fromIn.blur(); toIn.blur();
    pickMode = which; pickPlace = null;
    root.querySelectorAll('[data-pickon]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.pickon === which)));
    cross.style.display = 'block';
    const at = which === 'to' ? dest : origin;
    if (at) map.setCenter(KMAP.ll(at));
    if (map.getLevel() > 6) map.setLevel(5);
    lookup(); paintSheet();
  }
  function endPick() {
    pickMode = null; cross.style.display = 'none';
    root.querySelectorAll('[data-pickon]').forEach((b) => b.setAttribute('aria-pressed', 'false'));
    paintSheet();
  }
  let lookT = null;
  function lookup() {
    clearTimeout(lookT);
    const c = map.getCenter(), p = { lat: c.getLat(), lng: c.getLng() };
    pickPlace = { lat: p.lat, lng: p.lng, name: T('Pinned spot'), address: '' };
    paintSheet();
    lookT = setTimeout(() => geocoder.coord2Address(p.lng, p.lat, (res, status) => {
      if (!alive() || !pickMode || status !== K.services.Status.OK || !res[0]) return;
      const r = res[0], road = r.road_address, addr = r.address;
      const name = road && road.building_name ? road.building_name : (road ? road.address_name : addr.address_name);
      pickPlace = { lat: p.lat, lng: p.lng, name, address: road ? addr.address_name : '' };
      paintSheet();
    }), 250);
  }

  root.addEventListener('click', (e) => {
    const pb = e.target.closest('[data-pickon]');
    if (pb) { pickMode === pb.dataset.pickon ? endPick() : startPick(pb.dataset.pickon); return; }
    const p = e.target.closest('[data-place]'), r = e.target.closest('[data-recent]');
    if (p || r) {
      const f = p ? found[+p.dataset.place] : recent()[+r.dataset.recent];
      const place = p ? { lat: +f.y, lng: +f.x, name: f.place_name, address: f.road_address_name || f.address_name } : f;
      list.hidden = true; fromIn.blur(); toIn.blur();
      field === 'from' ? setOrigin(place) : setDest(place);
      return;
    }
    if (e.target.closest('#rPickOk') && pickPlace) { const pl = pickPlace, which = pickMode; endPick(); which === 'from' ? setOrigin(pl) : setDest(pl); return; }
    if (e.target.closest('#rPickNo')) { endPick(); return; }
    if (e.target.closest('#rStopsTog')) { showStops = !showStops; paintSheet(); return; }
    const st = e.target.closest('[data-stop]');
    if (st && map) { const s = stops[+st.dataset.stop]; map.panTo(KMAP.ll(s)); map.setLevel(6); return; }
    if (e.target.closest('#rSet')) setRoute();
  });
  $('#rLocate').addEventListener('click', () => locate(true));
  $('#rMap').addEventListener('pointerdown', () => { list.hidden = true; });

  // -- route ---------------------------------------------------------------- //
  function drawPins() {
    if (!map) return;
    overlays.forEach((o) => o.setMap(null)); overlays = [];
    if (line) { line.setMap(null); line = null; }
    if (result) line = KMAP.line(map, result.path.map(([x, y]) => ({ lat: y, lng: x })));
    if (origin) overlays.push(KMAP.pin(map, origin, T('Start')));
    if (dest) overlays.push(KMAP.pin(map, dest, dest.name, 'pick'));
    stops.forEach((s) => overlays.push(KMAP.pin(map, s, (s === pick ? '☕ ' : '') + s.short, s === pick ? 'pick' : '')));
  }
  async function route() {
    if (!origin || !dest) { drawPins(); paintSheet(); return; }
    result = null; stops = []; pick = null; searching = true; showStops = false;
    paintSheet('finding');
    let r;
    try {
      r = await API().get(`/api/route?origin=${origin.lng},${origin.lat}&destination=${dest.lng},${dest.lat}&vehicle=${API().profile().vehicle || 'car'}`);
    } catch (e) { if (alive()) paintSheet('error', e.message); return; }
    if (!alive() || !r || !r.path) return;
    result = r;
    const pts = r.path.map(([x, y]) => ({ lat: y, lng: x }));
    if (map) { map.relayout(); KMAP.fit(map, pts, 60); }
    drawPins(); paintSheet();
    findStops(pts);
  }
  // Highway rest areas along the line (see the commit history for why each
  // filter is there): Kakao's 고속도로휴게소 category, within 1.5 km of the
  // route, and of each direction pair the one on the right of the road.
  function findStops(pts) {
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + hav(pts[i - 1], pts[i]));
    const total = cum[cum.length - 1], probes = [];
    for (let d = 15000; d < total - 5000; d += 20000) probes.push(pts[cum.findIndex((c) => c >= d)]);
    const seen = new Map(), my = result;
    let left = probes.length;
    const done = () => {
      searching = false;
      stops = [...seen.values()].sort((a, b) => a.along - b.along);
      stops.forEach((s) => { s.eta_s = result.duration_s * s.along / total; });
      choose(); drawPins(); paintSheet();
    };
    if (!left) return done();
    probes.forEach((pr, k) => setTimeout(() => {
      if (!alive() || result !== my) return;
      places.keywordSearch('고속도로휴게소', (data, status) => {
        if (!alive() || result !== my) return;
        if (status === K.services.Status.OK) for (const p of data) {
          if (!/고속도로휴게소$/.test(p.category_name || '')) continue;
          const q = { lat: +p.y, lng: +p.x };
          let best = Infinity, bi = 0;
          for (let i = 0; i < pts.length; i++) { const d = hav(q, pts[i]); if (d < best) { best = d; bi = i; } }
          if (best > 1500) continue;
          const a0 = pts[Math.max(0, bi - 1)], a1 = pts[Math.min(pts.length - 1, bi + 1)];
          const right = (a1.lng - a0.lng) * (q.lat - a0.lat) - (a1.lat - a0.lat) * (q.lng - a0.lng) < 0 || /양방향/.test(p.place_name);
          if (!right && /방향/.test(p.place_name)) continue;
          const base = p.place_name.replace(/(?:\s+|\s*\()[가-힣·]+방향\)?\s*$/, '').trim();
          const prev = seen.get(base);
          if (!prev || best < prev.off) seen.set(base, { lat: q.lat, lng: q.lng, name: p.place_name, short: base.replace(/휴게소$/, ''), off: best, along: cum[bi] });
        }
        if (--left === 0) done();
      }, { location: KMAP.ll(pr), radius: 4000 });
    }, k * 120));
  }
  // Ollie's pick: the last rest area before the break is due and before the
  // tired window, whichever comes first.
  function choose() {
    const every = (API().settings().break_every_min || 120) * 60;
    const sh = shiftOf(API().profile().work), now = new Date(), t = new Date(now);
    t.setHours(sh === 'day' ? 13 : sh === 'eve' ? 14 : 2, 0, 0, 0); if (t <= now) t.setDate(t.getDate() + 1);
    const tired = (t - now) / 1000, deadline = Math.min(every, tired);
    const before = stops.filter((s) => s.eta_s <= deadline && s.eta_s >= 20 * 60);
    pick = before.length ? before[before.length - 1] : stops[0] || null;
    if (!pick) return;
    reason = tired < every && pick.eta_s <= tired ? T('Stop here at {t}, before your tired window.', { t: clockIn(pick.eta_s) })
      : pick.eta_s <= every ? T('Stop here at {t}, {d} into the drive.', { t: clockIn(pick.eta_s), d: dur(pick.eta_s) })
      : T('The first rest area, at {t}. Your break is due before it.', { t: clockIn(pick.eta_s) });
  }

  // -- the bottom sheet ----------------------------------------------------- //
  function paintSheet(state, detail) {
    const fab = $('#rLocate');
    if (pickMode) {
      const p = pickPlace;
      sum.innerHTML = `<p style="margin:0;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#9A93A0">${esc(T(pickMode === 'to' ? 'Move the map to your destination' : 'Move the map to your start'))}</p>
        <b style="display:block;margin-top:6px;font-size:18px">${esc(p ? p.name : '…')}</b><span style="display:block;font-size:13px;color:#9A93A0;min-height:18px">${esc(p && p.address || '')}</span>
        <div style="display:flex;gap:8px;margin-top:12px"><button type="button" id="rPickNo" class="mp-cta" style="flex:0 0 auto;width:auto;padding:16px 20px;background:rgba(255,255,255,.12);color:#F2EEE8">${esc(T('Cancel'))}</button>
        <button type="button" id="rPickOk" class="mp-cta" ${p ? '' : 'disabled'}>${esc(T(pickMode === 'to' ? 'Set destination here' : 'Start from here'))}</button></div>`;
    } else if (state === 'finding') {
      sum.innerHTML = `<p style="margin:4px 0 8px;color:#9A93A0;font-size:15px">${esc(T('Finding the route…'))}</p>`;
    } else if (state === 'error') {
      sum.innerHTML = `<p style="margin:4px 0 8px;color:#9A93A0;font-size:14.5px;line-height:1.4">${esc(T("Couldn't get directions."))} ${esc(detail || '')}</p>`;
    } else if (!result) {
      sum.innerHTML = `<p style="margin:2px 0 6px;font-size:15px;font-weight:700">${esc(T('Where are you going?'))}</p><p style="margin:0;font-size:13.5px;color:#9A93A0;line-height:1.4">${esc(T('Search above, or tap the pin and move the map to the exact spot.'))}</p>`;
    } else {
      const v = API().profile().vehicle, truck = ['long_haul', 'delivery', 'bus'].includes(v);
      const cell = (k, val) => `<div><span style="display:block;font-size:12px;color:#9A93A0">${esc(T(k))}</span><b style="font-size:21px;font-family:Pretendard,system-ui,sans-serif;font-weight:700;white-space:nowrap">${esc(val)}</b></div>`;
      sum.innerHTML = `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px">${cell('Distance', kmText(result.distance_m))}${cell('Time', dur(result.duration_s))}${cell('Arrive', clockIn(result.duration_s))}</div>
        ${result.toll_won || truck ? `<p style="margin:6px 0 0;font-size:12.5px;color:#9A93A0;line-height:1.4">${result.toll_won ? esc(T('Tolls about {n} won', { n: result.toll_won.toLocaleString() })) + (truck ? ' · ' : '') : ''}${truck ? esc(T("Kakao's car route. Truck height and weight limits aren't checked.")) : ''}</p>` : ''}
        <div style="margin-top:12px;display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:16px;background:rgba(232,215,174,.14)">
          <img src="${IMG.cup}" alt="" style="width:36px;flex-shrink:0">
          <span style="flex:1;min-width:0">${pick ? `<b style="display:block;font-size:14.5px">${esc(pick.name)}</b><span style="font-size:12.5px;color:#E8D7AE">${esc(reason)}</span>`
            : `<span style="font-size:13.5px;color:#9A93A0">${esc(T(searching ? 'Looking for rest areas…' : 'No highway rest areas on this route.'))}</span>`}</span>
          ${stops.length ? `<button type="button" id="rStopsTog" style="border:0;background:rgba(255,255,255,.1);border-radius:99px;padding:7px 10px;font-size:12.5px;font-weight:700;white-space:nowrap">${esc(T(showStops ? 'Hide' : '{n} stops', { n: stops.length }))}</button>` : ''}
        </div>
        ${showStops ? `<div style="margin-top:8px;border-radius:16px;background:rgba(255,255,255,.05);overflow:hidden">${stops.map((s, i) => `<button type="button" class="mp-row" data-stop="${i}" style="${s === pick ? 'background:rgba(232,215,174,.12)' : ''}"><span style="width:22px;text-align:center;font-weight:700;color:#9A93A0">${i + 1}</span><span style="flex:1;min-width:0"><b style="font-size:14.5px">${esc(s.name)}</b><span style="display:block;font-size:12.5px;color:#9A93A0">${esc(T('{km} · around {t}', { km: kmText(s.along), t: clockIn(s.eta_s) }))}</span></span></button>`).join('')}</div>` : ''}
        <button type="button" id="rSet" class="mp-cta" style="margin-top:12px">${esc(T('Set route'))}</button>`;
    }
    requestAnimationFrame(() => { if (alive()) fab.style.bottom = ($('#rSheet').offsetHeight + 12) + 'px'; });
  }

  async function setRoute() {
    if (!result) return;
    const total = result.distance_m;
    const drive = { from: origin.name, to: dest.name, dest: { lat: dest.lat, lng: dest.lng }, origin: { lat: origin.lat, lng: origin.lng },
      path: result.path.map(([x, y]) => ({ lat: y, lng: x })), distance_m: total, duration_s: result.duration_s, toll_won: result.toll_won,
      stops: stops.map((s) => ({ name: s.name, short: s.short, lat: s.lat, lng: s.lng, along: s.along, pick: s === pick })), set_at: Date.now() };
    BN_DRIVE.set(drive);
    try {
      await API().post('/api/trips/start');
      await API().put('/api/trips/current/route', { from: drive.from, to: drive.to, to_lat: dest.lat, to_lng: dest.lng,
        distance_km: Math.round(total / 100) / 10, duration_s: result.duration_s, eta: Date.now() / 1000 + result.duration_s,
        stop: pick ? { name: pick.name, km: Math.round(pick.along / 1000), eta_s: Math.round(pick.eta_s) } : null });
    } catch (e) {}
    SFX.play('start');
    ctx.forward('Home');
  }

  // Coming back to a route that's already set: show it.
  const cur = BN_DRIVE.get();
  if (cur) { origin = { lat: cur.origin.lat, lng: cur.origin.lng, name: cur.from }; dest = { lat: cur.dest.lat, lng: cur.dest.lng, name: cur.to }; fromIn.value = cur.from; toIn.value = cur.to; }
  init().then(() => { if (cur && alive()) route(); });
};

// -- Home: the live card ----------------------------------------------------- //
function driveCard(root) {
  const card = root.querySelector('#hDrive');
  if (!card) return;
  let map = null, me = null, built = false;
  async function paint() {
    const r = BN_DRIVE.get();
    card.hidden = !r;
    if (!r) return;
    const p = BN_DRIVE.progress(), next = BN_DRIVE.nextStop(p), pos = BN_DRIVE.pos();
    if (!built) {
      built = true;
      card.innerHTML = `<div id="hdMap" style="height:150px;pointer-events:none;background:#15131A"></div>
        <div style="padding:12px 14px 14px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><span style="display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:#F2B66D"><i style="width:8px;height:8px;border-radius:50%;background:#F2B66D;animation:livePulse 1.4s infinite"></i>${esc(T('Live'))}</span><span style="font-size:12.5px;color:#E8D7AE;font-weight:700">${esc(T('Open map'))} ›</span></div>
          <b id="hdTo" style="display:block;margin-top:4px;font-family:Pretendard,system-ui,sans-serif;font-weight:700;font-size:21px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"></b>
          <span id="hdLeft" style="display:block;font-size:14px;margin-top:2px"></span>
          <span id="hdNext" style="display:block;font-size:12.5px;color:#9A93A0;margin-top:4px"></span>
        </div>`;
      KMAP.load().then((K) => {
        if (!card.isConnected) return;
        map = new K.Map(card.querySelector('#hdMap'), { center: KMAP.ll(r.dest), level: 10, draggable: false, scrollwheel: false, disableDoubleClickZoom: true });
        KMAP.line(map, r.path, '#E8D7AE', 5);
        KMAP.pin(map, r.dest, r.to, 'pick');
        KMAP.fit(map, r.path, 20);
        paint();
      }).catch(() => { const m = card.querySelector('#hdMap'); if (m) m.style.display = 'none'; });
    }
    card.querySelector('#hdTo').textContent = T('To {to}', { to: r.to });
    card.querySelector('#hdLeft').textContent = T('{km} left · arrive {t}', { km: kmText(p.left_m), t: clockIn(p.left_s) }) + (pos ? '' : ' · ' + T('waiting for GPS'));
    card.querySelector('#hdNext').textContent = next ? T('Next rest area: {name} in {km}', { name: next.name, km: kmText(next.along - p.along) }) : '';
    if (map && pos) {
      if (!me) me = new KMAP.K.CustomOverlay({ position: KMAP.ll(pos), content: '<div class="mp-me"></div>', zIndex: 5 });
      me.setPosition(KMAP.ll(pos)); me.setMap(map);
    }
  }
  card.addEventListener('click', () => BN_FORWARD('Drive'));
  BN_DRIVE.on(paint, root);
  paint();
}
const _home = DYN.Home;
DYN.Home = function (root, ctx) { _home(root, ctx); driveCard(root); };

// -- Drive: the card opened up ---------------------------------------------- //
DYN.Drive = function (root, ctx) {
  const $ = (s) => root.querySelector(s);
  const r = BN_DRIVE.get();
  if (!r) { setTimeout(() => ctx.go('Route'), 0); return; }
  let map = null, me = null, done = null, follow = true, last = '';
  $('#dFrom').textContent = T('{a} to', { a: r.from });
  $('#dTo').textContent = r.to;
  async function init() {
    let K;
    try { K = await KMAP.load(); } catch (e) { if (root.isConnected) $('#dMapMsg').innerHTML = KMAP.failText(e); return; }
    if (!root.isConnected) return;
    map = new K.Map($('#dMap'), { center: KMAP.ll(BN_DRIVE.pos() || r.origin), level: 6 });
    $('#dMapMsg').style.display = 'none';
    setTimeout(() => root.isConnected && map.relayout(), 450);
    KMAP.line(map, r.path);
    KMAP.pin(map, r.dest, r.to, 'pick');
    r.stops.forEach((s) => KMAP.pin(map, s, (s.pick ? '☕ ' : '') + s.short, s.pick ? 'pick' : ''));
    K.event.addListener(map, 'dragstart', () => { follow = false; paintFollow(); });
    if (!BN_DRIVE.pos()) KMAP.fit(map, r.path, 50);
    paint();
  }
  function paintFollow() { $('#dFollow').style.color = follow ? '#4C8DFF' : '#F2EEE8'; }
  function paint() {
    const p = BN_DRIVE.progress(), pos = BN_DRIVE.pos(), next = BN_DRIVE.nextStop(p);
    $('#dLeft').textContent = kmText(p.left_m);
    $('#dTime').textContent = dur(p.left_s);
    $('#dEta').textContent = clockIn(p.left_s);
    const fresh = pos && Date.now() - pos.at < 30000;
    $('#dDot').style.background = fresh ? '#E8D7AE' : '#9A93A0';
    $('#dLiveTxt').textContent = T(fresh ? 'Live' : 'GPS');
    $('#dNext').innerHTML = next ? `<div style="display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:16px;background:${next.pick ? 'rgba(232,215,174,.14)' : 'rgba(255,255,255,.06)'}">
        <img src="${IMG.cup}" alt="" style="width:34px;flex-shrink:0"><span style="flex:1;min-width:0"><span style="display:block;font-size:12px;color:#9A93A0">${esc(T(next.pick ? "Ollie's stop" : 'Next rest area'))}</span><b style="display:block;font-size:15px">${esc(next.name)}</b></span>
        <b style="white-space:nowrap">${esc(kmText(next.along - p.along))}</b></div>` : '';
    const off = p.off_m != null && p.off_m > 400;
    $('#dNote').textContent = !pos ? T('Waiting for your location…') : off ? T("You're off the route.") : p.left_m < 300 ? T("You've arrived.") : '';
    $('#dReroute').hidden = !off;
    if (map && pos) {
      if (!me) { me = new KMAP.K.CustomOverlay({ position: KMAP.ll(pos), content: '<div class="mp-me"></div>', zIndex: 5 }); me.setMap(map); }
      me.setPosition(KMAP.ll(pos));
      if (done) done.setMap(null);
      if (p.idx > 0) done = KMAP.line(map, r.path.slice(0, p.idx + 1), '#9A93A0', 6);
      // Follow every new fix (they come about once a second); skip repeats.
      const key = pos.lat.toFixed(5) + ',' + pos.lng.toFixed(5);
      if (follow && key !== last) { last = key; map.setCenter(KMAP.ll(pos)); }
    }
  }
  $('#dFollow').addEventListener('click', () => { follow = true; paintFollow(); const pos = BN_DRIVE.pos(); if (map && pos) { map.setLevel(5); map.panTo(KMAP.ll(pos)); } });
  $('#dEnd').addEventListener('click', async () => {
    if (!confirm(T('End this trip?'))) return;
    BN_DRIVE.clear();
    try { await API().post('/api/trips/end'); } catch (e) {}
    ctx.forward('Home');
  });
  $('#dReroute').addEventListener('click', async () => {
    const pos = BN_DRIVE.pos(); if (!pos) return;
    $('#dNote').textContent = T('Finding the route…');
    try {
      const res = await API().get(`/api/route?origin=${pos.lng},${pos.lat}&destination=${r.dest.lng},${r.dest.lat}&vehicle=${API().profile().vehicle || 'car'}`);
      BN_DRIVE.set(Object.assign({}, r, { path: res.path.map(([x, y]) => ({ lat: y, lng: x })), distance_m: res.distance_m, duration_s: res.duration_s, origin: pos }));
      ctx.go('Drive', { instant: true });
    } catch (e) { $('#dNote').textContent = T("Couldn't get directions.") + ' ' + (e.message || ''); }
  });
  BN_DRIVE.on(paint, root);
  BN_DRIVE.start();
  paintFollow(); paint(); init();
};

// A trip the device ended (empty seat for a long time) ends the drive too.
setTimeout(() => window.BN_API && BN_API.on('trip', (m) => { if (m.event === 'ended' && BN_DRIVE.get()) BN_DRIVE.clear(); }), 0);
