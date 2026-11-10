// Real screens of the phone app, from the live website, for the video.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'ko-KR' });
  const p = await ctx.newPage();
  await p.goto('https://seunghyun2007.github.io/bamnun/');
  await p.evaluate(() => { localStorage.clear(); localStorage.setItem('bn-lang', 'ko'); localStorage.setItem('bn-tour-site', '1'); });
  await p.goto('https://seunghyun2007.github.io/bamnun/?r=' + Date.now());
  await p.waitForTimeout(9000);                       // the demo drive gets going
  await p.screenshot({ path: 'assets/app_home.png' });
  await p.evaluate(() => BN_GO('Trips', { instant: true })); await p.waitForTimeout(1200);
  await p.evaluate(() => { const c = [...document.querySelectorAll('[data-trip]')].find(x => /서울/.test(x.textContent)) || document.querySelectorAll('[data-trip]')[0]; c.click(); });
  await p.waitForTimeout(800);
  await p.evaluate(() => { const c = document.querySelector('[data-trip][aria-expanded="true"]'); c.scrollIntoView({ block: 'start' }); });
  await p.waitForTimeout(600);
  await p.screenshot({ path: 'assets/app_trip.png' });
  await p.evaluate(() => BN_GO('Insights', { instant: true })); await p.waitForTimeout(1500);
  await p.screenshot({ path: 'assets/app_insights.png' });
  await p.evaluate(() => BN_GO('Stages', { instant: true })); await p.waitForTimeout(1500);
  await p.screenshot({ path: 'assets/app_stages.png' });
  await b.close();
})();
