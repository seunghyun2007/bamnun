// Render the v2 film in headless Chrome. Run `python3 make_timeline.py` first.
//   node render.js stills 3 8 14 ...   -> stills/t_<s>.png
//   node render.js sheet 3 8 14 ...    -> stills + check/sheet_v2.jpg (a contact sheet)
//   node render.js frames              -> frames/f_00001.jpg ... at 30 fps
//   node render.js review              -> review/r_<s>.jpg, one frame every 0.5 s (for the critique loop)
const fs = require('fs'), path = require('path'), { execSync } = require('child_process');
const { chromium } = require('playwright');
const TL = JSON.parse(fs.readFileSync('timeline.json', 'utf8'));
fs.writeFileSync('built.html', fs.readFileSync('index.html', 'utf8').replace('__TIMELINE__', JSON.stringify(TL)));
(async () => {
  const [mode, ...ts] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  p.on('pageerror', (e) => { console.error('PAGE ERROR', e.message); process.exitCode = 1; });
  await p.goto('file://' + path.resolve('built.html'));
  await p.evaluate(() => document.fonts.ready);
  await p.evaluate(() => Promise.all([...document.images].map((i) => i.decode().catch(() => {}))));
  await p.waitForTimeout(400);
  const shot = async (t, file, opt = {}) => { await p.evaluate((t) => render(+t), t); await p.screenshot({ path: file, ...opt }); };
  if (mode === 'stills' || mode === 'sheet') {
    fs.mkdirSync('stills', { recursive: true }); fs.mkdirSync('check', { recursive: true });
    const files = [];
    for (const t of ts) { const f = `stills/t_${t}.png`; await shot(t, f); files.push(f); }
    if (mode === 'sheet') {
      const cols = 4, rows = Math.ceil(files.length / cols);
      const ins = files.map((f) => `-i ${f}`).join(' ');
      const sc = files.map((_, i) => `[${i}]scale=960:540[s${i}]`).join(';');
      const lay = files.map((_, i) => `${(i % cols) * 960}_${Math.floor(i / cols) * 540}`).join('|');
      execSync(`ffmpeg -loglevel error -y ${ins} -filter_complex "${sc};${files.map((_, i) => `[s${i}]`).join('')}xstack=inputs=${files.length}:layout=${lay}:fill=black" -q:v 3 check/sheet_v2.jpg`);
      console.log('check/sheet_v2.jpg', cols, 'x', rows);
    }
  } else if (mode === 'review') {
    fs.rmSync('review', { recursive: true, force: true }); fs.mkdirSync('review');
    for (let t = 0; t < TL.end; t += 0.5) await shot(t, `review/r_${t.toFixed(1).padStart(4, '0')}.jpg`, { type: 'jpeg', quality: 80 });
  } else {
    // `frames` renders everything; `frames 52 56` re-renders only that stretch (seconds) into the existing folder
    const n = Math.round(TL.end * TL.fps), i0 = ts.length ? Math.floor(ts[0] * TL.fps) : 0, i1 = ts.length ? Math.min(n, Math.ceil(ts[1] * TL.fps)) : n;
    if (!ts.length) { fs.rmSync('frames', { recursive: true, force: true }); fs.mkdirSync('frames'); }
    for (let i = i0; i < i1; i++) {
      await shot(i / TL.fps, `frames/f_${String(i + 1).padStart(5, '0')}.jpg`, { type: 'jpeg', quality: 93 });
      if (i % 300 === 0) console.log('frame', i, '/', n);
    }
  }
  await b.close();
})();
