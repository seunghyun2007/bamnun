/* Calibrate (docs/SPEC.md, section 15): the live camera with a face guide,
   then one step at a time. Each step is a card with Ollie, one big
   instruction and a progress ring; when it passes the ring turns into a check
   and the card slides away for the next. Hints from the device ("Move
   closer", "Too dark"...) appear on the video. The device test (speaker,
   chime, blue light, mint mist) uses the same cards with Yes / No. The last
   card shows what Ollie learned. */
DYN.Calibrate = function (root, ctx) {
  const $ = (s) => root.querySelector(s);
  const stage = $('#cbStage'), go = $('#cGo'), later = $('#cLater'), hintEl = $('#cbHint');
  const ORDER = ['position', 'look', 'close', 'speaker', 'chime', 'light', 'mist'];
  const ASK = { speaker: 1, chime: 1, light: 1, mist: 1 };
  const TEXT = {
    position: ['Get in position', "Sit like you're driving and look at the camera. Fit your face in the oval.", IMG.thinking],
    look: ['Look straight ahead', 'Blink normally. Ollie is learning your eyes.', IMG.idle],
    close: ['Close your eyes', 'Keep them closed until the ring is full.', IMG.sleepy],
    speaker: ['Can you hear Ollie?', 'The voice comes from your Bamnun.', IMG.hello],
    chime: ['Did you hear the chime?', "That's the step 3 wake-up chime.", IMG.hello],
    light: ['See the blue light?', 'It glows at the edge of your view for 3 seconds.', IMG.hello],
    mist: ['Smell the mint?', 'A short puff of peppermint mist.', IMG.hello],
  };
  const HINTS = { no_face: "Ollie can't see you", closer: 'Move closer', farther: 'Move back a little', dark: 'Too dark',
    bright: 'Too bright', face_camera: 'Face the camera', still: 'Hold still' };
  const FAIL = {
    no_face: "Ollie couldn't see your face", still: 'Your head moved a lot', dark: "It's too dark", bright: 'Too much light',
    separation: "Ollie couldn't tell your eyes apart", tracking: "Ollie couldn't learn your eyes",
  };
  let st = { active: false, step: null, results: {} }, finished = false, card = null, shown = null;

  function dots() {
    const i = ORDER.indexOf(st.step);
    $('#cbDots').innerHTML = ORDER.map((k, j) => `<i class="${finished && st.message === 'done' ? 'done' : j < i ? 'done' : j === i && st.active ? 'now' : ''}"></i>`).join('');
  }
  function ring(p) {
    const r = card && card.querySelector('.cb-ring');
    if (r) r.setAttribute('stroke-dasharray', (226 * Math.max(0, Math.min(1, p || 0))).toFixed(0) + ' 226');
  }
  function newCard(html, key) {
    const old = card;
    const el = document.createElement('section');
    el.className = 'cb-card in';
    el.style.cssText = 'background:#1F1C24;border:1px solid rgba(255,255,255,.09)';
    el.innerHTML = html;
    const swap = () => { if (old) { old.classList.add('out'); setTimeout(() => old.remove(), 400); } stage.appendChild(el); };
    // A step that passed shows its check for a moment before sliding away.
    if (old && shown && st.results[shown] === 'ok') { old.classList.add('ok'); SFX.play('tick'); setTimeout(swap, 550); } else swap();
    card = el; shown = key;
  }
  function stepCard(key) {
    const [title, sub, img] = TEXT[key];
    const ask = ASK[key];
    newCard(`
      <div style="display:flex;gap:14px;align-items:center">
        <img src="${img}" alt="" style="width:76px;flex-shrink:0">
        <div style="flex:1;min-width:0"><h1 style="margin:0;font-family:Pretendard,system-ui,sans-serif;font-weight:700;font-size:30px;line-height:1.02">${esc(T(title))}</h1>
          <p data-sub style="margin:6px 0 0;color:#9A93A0;font-size:14.5px;line-height:1.4">${esc(T(sub))}</p></div>
        ${ask ? '' : `<div class="cb-ringwrap" style="position:relative;width:84px;height:84px;flex-shrink:0">
          <svg viewBox="0 0 84 84" width="84" height="84" style="transform:rotate(-90deg);transition:opacity .3s"><circle cx="42" cy="42" r="36" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="8"/>
            <circle class="cb-ring" cx="42" cy="42" r="36" fill="none" stroke="#E8D7AE" stroke-width="8" stroke-linecap="round" stroke-dasharray="0 226"/></svg>
          <span class="cb-check"><svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#E8D7AE" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></div>`}
      </div>
      <p data-say style="margin:0;min-height:20px;font-size:13.5px;color:#E8D7AE;font-weight:700"></p>
      <p data-why style="margin:0;display:none;padding:10px 12px;border-radius:14px;background:rgba(242,182,109,.18);font-size:14px;line-height:1.4"></p>
      ${ask ? `<div style="display:flex;gap:10px;margin-top:auto"><button type="button" class="cb-ans" data-ans="yes" style="background:#E8D7AE;color:#15131A">${esc(T('Yes'))}</button>
        <button type="button" class="cb-ans" data-ans="no" style="background:rgba(255,255,255,.14);color:#F2EEE8">${esc(T('No'))}</button></div>` : ''}`, key);
  }
  function introCard() {
    const online = API().online();
    newCard(`
      <div style="display:flex;gap:14px;align-items:center"><img src="${IMG.thinking}" alt="" style="width:76px">
        <div><h1 style="margin:0;font-family:Pretendard,system-ui,sans-serif;font-weight:700;font-size:30px;line-height:1.02">${esc(T('Let Ollie learn your eyes'))}</h1>
        <p style="margin:6px 0 0;color:#9A93A0;font-size:14.5px;line-height:1.4">${esc(T(online ? 'About a minute. Ollie learns your normal eyes, blinks and head position, then tests the device.' : 'Connect your Bamnun first.'))}</p></div></div>`, 'intro');
  }
  function summaryCard(s) {
    const size = { small: 'Small', medium: 'Medium', large: 'Large' }[s.eye_size] || 'Medium';
    const parts = ['speaker', 'chime', 'light', 'mist'].filter((k) => st.results[k] === 'ok').length;
    const row = (k, v) => `<div class="cb-row"><span>${esc(T(k))}</span><b>${esc(v)}</b></div>`;
    newCard(`
      <div style="display:flex;gap:12px;align-items:center"><img src="${IMG.celebrate}" alt="" style="width:64px">
        <h1 style="margin:0;font-family:Pretendard,system-ui,sans-serif;font-weight:700;font-size:28px;line-height:1.02">${esc(T('What Ollie learned'))}</h1></div>
      <div style="overflow:auto">
        ${row('Eyes', T(size) + ' · ' + T('closed vs open {n}% apart', { n: Math.round(100 * (s.separation || 0)) }))}
        ${row('Normal blink', T('{ms} ms · {n} a minute', { ms: s.blink_ms, n: Math.round(s.blink_rate) }))}
        ${row('Head position', T('steady within ±{n}°', { n: Math.max(1, Math.round(Math.max(s.wobble.yaw, s.wobble.pitch))) }))}
        ${row('Device', T('{n} of 4 parts work', { n: parts }))}
        ${s.closed_estimated ? `<p style="margin:8px 0 0;font-size:13px;color:#9A93A0">${esc(T('Your closed eyes were estimated. Calibrate again for a better result.'))}</p>` : ''}
      </div>`, 'summary');
  }
  function failCard(code, why) {
    newCard(`
      <div style="display:flex;gap:14px;align-items:center"><img src="${IMG.wake}" alt="" style="width:76px">
        <div><h1 style="margin:0;font-family:Pretendard,system-ui,sans-serif;font-weight:700;font-size:28px;line-height:1.02">${esc(T(FAIL[code] || 'Something went wrong'))}</h1>
        <p style="margin:6px 0 0;color:#9A93A0;font-size:14.5px;line-height:1.4">${esc(T(why || 'Try again.'))}</p></div></div>`, 'fail');
  }

  function paint(m) {
    dots();
    const hint = st.active && st.hint ? T(HINTS[st.hint] || '') : '';
    hintEl.textContent = hint;
    hintEl.classList.toggle('on', !!hint);
    $('#cbOval').setAttribute('stroke', hint ? '#F2B66D' : st.active && ['position', 'look'].includes(st.step) ? '#E8D7AE' : '#E8D7AE');
    if (st.active && st.step && shown !== st.step) stepCard(st.step);
    if (st.active) {
      ring(st.progress != null ? st.progress : 0);
      const why = card && card.querySelector('[data-why]');
      if (why) { why.style.display = st.message === 'retry' && st.reason ? 'block' : 'none'; why.textContent = st.reason ? T(st.reason) : ''; }
      go.style.display = 'none';
      later.textContent = T('Cancel');
      later.style.visibility = '';
    } else {
      go.style.display = '';
      later.textContent = T('Do this later');
      if (finished && st.message === 'done') {
        if (shown !== 'summary' && st.summary) summaryCard(st.summary);
        go.textContent = T('Next');
        later.style.visibility = 'hidden';
      } else if (finished && st.failed) {
        if (shown !== 'fail') failCard(st.message, st.reason);
        go.textContent = T('Try again');
      } else {
        if (!card) introCard();
        go.textContent = T('Start');
        go.style.opacity = API().online() ? 1 : 0.5;
      }
    }
  }
  API().on('calibration', (m) => {
    st = m;
    if (!m.active && (m.message === 'done' || m.failed)) { finished = true; if (m.message === 'done') SFX.play('success'); }
    if (!m.active && m.message === 'cancelled') { finished = false; card = null; shown = null; stage.innerHTML = ''; }
    paint(m);
  }, root);
  API().on('say', (m) => {
    if (!String(m.line).startsWith('cal_') || !card) return;
    const el = card.querySelector('[data-say]');
    if (el) el.textContent = m.text;
  }, root);
  API().on('health', () => root.isConnected && !st.active && !finished && (card = null, stage.innerHTML = '', shown = null, paint()), root);
  go.addEventListener('click', () => {
    if (finished && st.message === 'done') return ctx.forward('Plan');
    if (!API().online()) { SFX.play('off'); return; }
    finished = false; shown = null;
    st = { active: true, step: 'position', results: {} };
    paint();
    API().post('/api/calibration/start').catch(() => { st = { active: false, results: {} }; paint(); });
  });
  later.addEventListener('click', (e) => {
    if (st.active) { e.preventDefault(); e.stopPropagation(); API().post('/api/calibration/cancel').catch(() => {}); }
  });
  root.addEventListener('click', (e) => {
    const b = e.target.closest('[data-ans]');
    if (b && st.active) API().post('/api/calibration/answer', { step: st.step, ok: b.dataset.ans === 'yes' }).catch(() => {});
  });
  paint();
  if (!API().demo) API().get('/api/calibration').then((m) => { if (m && m.active && root.isConnected) { st = m; paint(); } }).catch(() => {});
};
