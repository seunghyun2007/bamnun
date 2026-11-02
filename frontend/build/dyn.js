/* Vanilla versions of the three interactive canvas screens. Each init gets the screen's root element. */
const DYN = {
  Night(root) {
    const names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const days = [true, true, true, true, true, false, false];
    const P = {
      day: { label: 'Day', range: '6 AM–2 PM', a: 6, b: 14, start: '6:00 AM', end: '2:00 PM', hard: 'Your hardest stretch is right after lunch, around 1 to 2 PM.' },
      eve: { label: 'Evening', range: '2–10 PM', a: 14, b: 22, start: '2:00 PM', end: '10:00 PM', hard: 'Your hardest stretch is the start, around 2 to 3 PM.' },
      night: { label: 'Night', range: '10 PM–6 AM', a: 22, b: 6, start: '10:00 PM', end: '6:00 AM', hard: 'Your hardest stretch is 3 to 5 AM. Ollie will plan a break before it.' },
      custom: { label: 'Custom', range: 'Set times', a: 20, b: 4, start: '8:00 PM', end: '4:00 AM', hard: 'Your hardest stretch is 2 to 4 AM. Ollie will plan a break before it.' }
    };
    let shift = 'night';
    const $ = (s) => root.querySelector(s);
    function draw() {
      $('#nDays').innerHTML = names.map((n, i) => `<button type="button" data-d="${i}" aria-pressed="${days[i]}" aria-label="${n}" style="width:42px;height:42px;border-radius:50%;border:2px solid ${days[i] ? '#C4B5FD' : 'transparent'};background:${days[i] ? '#C4B5FD' : 'rgba(255,255,255,.07)'};color:${days[i] ? '#241A26' : '#B3A6B4'};font-weight:700;font-size:15px;padding:0;transition:all .2s">${n[0]}</button>`).join('');
      $('#nPresets').innerHTML = Object.keys(P).map((k) => `<button type="button" data-p="${k}" aria-pressed="${shift === k}" style="padding:10px 4px;border-radius:14px;text-align:center;border:2px solid ${shift === k ? '#C4B5FD' : 'transparent'};background:${shift === k ? 'rgba(196,181,253,.16)' : 'rgba(255,255,255,.07)'};transition:all .2s"><b style="display:block;font-size:14px">${P[k].label}</b><span style="display:block;font-size:11px;color:#B3A6B4;margin-top:2px;white-space:nowrap">${P[k].range}</span></button>`).join('');
      const c = P[shift];
      $('#nStart').textContent = c.start; $('#nEnd').textContent = c.end; $('#nHard').textContent = c.hard;
      const seg = (a, b) => `<div style="position:absolute;top:5px;bottom:5px;border-radius:5px;background:#C4B5FD;left:${a / 24 * 100}%;width:${(b - a) / 24 * 100}%;transition:all .4s"></div>`;
      $('#nSegs').innerHTML = c.a < c.b ? seg(c.a, c.b) : seg(c.a, 24) + seg(0, c.b);
    }
    root.addEventListener('click', (e) => {
      const d = e.target.closest('[data-d]'); if (d) { days[+d.dataset.d] = !days[+d.dataset.d]; draw(); }
      const p = e.target.closest('[data-p]'); if (p) { shift = p.dataset.p; draw(); }
    });
    draw();
  },
  Ladder(root) {
    root.querySelectorAll('[data-tog]').forEach((b) => {
      const paint = () => { const on = b.getAttribute('aria-checked') === 'true'; b.style.background = on ? '#C4B5FD' : 'rgba(255,255,255,.11)'; b.firstElementChild.style.transform = 'translateX(' + (on ? 20 : 0) + 'px)'; };
      b.addEventListener('click', () => { b.setAttribute('aria-checked', String(b.getAttribute('aria-checked') !== 'true')); paint(); });
      paint();
    });
  },
  Voice(root) {
    const eye = (l, t) => `<div class="ol-eye" style="left:${l}%;top:${t}%"><div class="ol-lid"></div></div>`;
    const C = [
      { name: 'Calm guide', desc: 'Soft voice, gentle nudges', line: 'Easy now. There’s a rest stop in 12 km.', src: IMG.idle, anim: 'a-breathe', eyes: eye(27.08, 32.58) + eye(54.2, 32.6) },
      { name: 'Straight talker', desc: 'Short and direct', line: 'Your eyes are closing. Pull over.', src: IMG.driving, anim: 'a-drive', eyes: eye(27.65, 38.91) + eye(53.35, 38.71) },
      { name: 'Cheerleader', desc: 'Upbeat, keeps you going', line: 'You’ve got this! Coffee break in 10?', src: IMG.celebrate, anim: 'a-jump', eyes: '', jump: true },
      { name: 'Road buddy', desc: 'Chatty, like a co-driver', line: 'Long night, huh? Let’s stretch at the next stop.', src: IMG.hello, anim: 'a-wave', eyes: '' }
    ];
    let pick = 2;
    const $ = (s) => root.querySelector(s);
    function draw(first) {
      const c = C[pick];
      $('#vAv').src = c.src;
      const say = $('#vSay'); say.textContent = c.line;
      if (!first) { say.classList.remove('vc-say'); void say.offsetWidth; say.classList.add('vc-say'); }
      $('#vCards').innerHTML = C.map((o, i) => `<button type="button" data-c="${i}" aria-pressed="${i === pick}" style="position:relative;border-radius:22px;padding:14px 10px;display:flex;flex-direction:column;align-items:center;gap:6px;border:2px solid ${i === pick ? '#C4B5FD' : 'transparent'};background:${i === pick ? 'rgba(196,181,253,.16)' : 'rgba(255,255,255,.07)'};transition:all .2s">
        ${i === pick ? '<span style="position:absolute;top:10px;right:10px;width:22px;height:22px;border-radius:50%;background:#C4B5FD;display:grid;place-items:center"><svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#241A26" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg></span>' : ''}
        <div class="olw" style="width:96px;font-size:9.6px"><div class="ol-shadow${o.jump ? ' s-jump' : ''}"></div><div class="ol-loop ${o.anim}"><img src="${o.src}" alt="">${o.eyes}</div></div>
        <b style="font-size:15px">${o.name}</b><small style="color:#B3A6B4;font-size:12.5px;text-align:center">${o.desc}</small></button>`).join('');
    }
    root.addEventListener('click', (e) => { const b = e.target.closest('[data-c]'); if (b) { pick = +b.dataset.c; draw(); } });
    draw(true);
  },
  Pair(root) {
    const w = root.firstElementChild, $ = (s) => root.querySelector(s);
    const T = $('#pTitle'), S = $('#pSub'), alive = () => root.isConnected;
    const set = (a, b) => { T.style.opacity = 0; S.style.opacity = 0; setTimeout(() => { T.textContent = a; S.textContent = b; T.style.opacity = 1; S.style.opacity = 1; }, 230); };
    w.classList.add('searching');
    T.textContent = 'Looking for your Bamnun'; S.textContent = 'Keep your phone close to the device.';
    SFX.play('ping');
    const iv = setInterval(() => alive() ? SFX.play('ping') : clearInterval(iv), 1200);
    setTimeout(() => { if (!alive()) return; set('Found Bamnun · 3F2A', 'Connecting…'); SFX.play('found'); }, 2900);
    setTimeout(() => {
      clearInterval(iv); if (!alive()) return;
      [...$('#pChecks').children].forEach((c, i) => { c.style.transitionDelay = (0.35 + i * 0.12) + 's'; setTimeout(() => alive() && SFX.play('tick'), 700 + i * 120); });
      w.classList.remove('searching');
      set('Bamnun is connected', 'All six parts check out.');
      SFX.play('success');
    }, 4400);
  },
  Settings(root) {
    const paintTog = (b) => { const on = b.getAttribute('aria-checked') === 'true'; b.style.background = on ? '#C4B5FD' : 'rgba(255,255,255,.16)'; b.firstElementChild.style.transform = 'translateX(' + (on ? 20 : 0) + 'px)'; };
    const paintSeg = (attr, val) => root.querySelectorAll('[data-' + attr + ']').forEach((b) => { const on = b.dataset[attr] === val; b.setAttribute('aria-pressed', String(on)); b.style.background = on ? '#F4EFE6' : 'transparent'; b.style.color = on ? '#241A26' : '#B3A6B4'; });
    paintSeg('lang', BN_LANG());
    let sens = 'normal'; try { sens = localStorage.getItem('bn-sens') || 'normal'; } catch (e) {}
    paintSeg('sens', sens);
    root.querySelectorAll('[data-tog]').forEach((b) => {
      if (b.dataset.tog === 'sound') b.setAttribute('aria-checked', String(SFX.enabled()));
      paintTog(b);
      b.addEventListener('click', () => {
        const on = b.getAttribute('aria-checked') !== 'true';
        if (b.dataset.tog === 'sound') { if (!on) SFX.play('off'); SFX.set(on); }
        b.setAttribute('aria-checked', String(on)); paintTog(b);
      });
    });
    root.addEventListener('click', (e) => { const b = e.target.closest('[data-sens]'); if (b) { paintSeg('sens', b.dataset.sens); try { localStorage.setItem('bn-sens', b.dataset.sens); } catch (er) {} } });
  }
};
