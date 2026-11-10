// Render the film: fill in the narration timings, capture frames in headless Chrome.
//   node render.js stills 3 8 14 ...   -> stills/t_<s>.png
//   node render.js frames              -> frames/f_00001.jpg ... at 30 fps
const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const STARTS = { s01: 1.0, s02: 6.0, s03: 12.0, s04: 18.2, s05: 22.4, s06: 28.8, s07: 33.4, s08: 36.3, s09: 38.4,
                 s10: 40.3, s11: 43.1, s12: 46.0, s13: 50.1, s14: 54.4, s15: 61.6 };
const lines = JSON.parse(fs.readFileSync('script.json')), dur = JSON.parse(fs.readFileSync('audio/durations.json'));
const LINES = lines.map((l) => ({ id: l.id, ko: l.ko, en: l.en, start: STARTS[l.id], dur: dur[l.id] }));
fs.writeFileSync('timeline.json', JSON.stringify(LINES, null, 1));
fs.writeFileSync('built.html', fs.readFileSync('index.html', 'utf8').replace('__LINES__', JSON.stringify(LINES)));
(async () => {
  const [mode, ...ts] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.goto('file://' + path.resolve('built.html'));
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(500);
  if (mode === 'stills') {
    fs.mkdirSync('stills', { recursive: true });
    for (const t of ts) { await p.evaluate((t) => render(+t), t); await p.screenshot({ path: `stills/t_${t}.png` }); }
  } else {
    fs.rmSync('frames', { recursive: true, force: true }); fs.mkdirSync('frames');
    const end = await p.evaluate(() => END), fps = 30, n = Math.round(end * fps);
    for (let i = 0; i < n; i++) {
      await p.evaluate((t) => render(t), i / fps);
      await p.screenshot({ path: `frames/f_${String(i + 1).padStart(5, '0')}.jpg`, type: 'jpeg', quality: 92 });
      if (i % 300 === 0) console.log('frame', i, '/', n);
    }
  }
  await b.close();
})();
