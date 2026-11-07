/* Booth visitors (2026 exhibition, until 24 Nov).

   The website opened from a visitor's own QR code (?v=<code>) loads their
   booth drive and photo from Supabase (supabase/booth_visits.sql,
   get_visit), and shows it as the newest trip of a believable history:
   about 35 night drives over two months on real Korean expressway routes
   (routes_kr.json, fetched once from OSRM), the same history every time for
   the same code. Without a code the history is the same kind, with Ollie
   as the picture. A short guided tour walks a visitor through their data
   once.

   window.BN_VISIT: trips(), visit(), name(), photo(), state(), mapSvg(t),
   curveSvg(t), tour() */
(function () {
  "use strict";
  const ROUTES = /*__ROUTES__*/[];
  // Real expressway rest areas along each route, in driving order.
  const STOPS = [
    ["안성휴게소", "금강휴게소", "추풍령휴게소", "칠곡휴게소"],
    ["안성휴게소", "천안삼거리휴게소"],
    ["서산휴게소", "홍성휴게소", "고창고인돌휴게소"],
    ["용인휴게소", "문막휴게소", "평창휴게소"],
    ["경주휴게소", "칠곡휴게소", "추풍령휴게소", "안성휴게소"],
    ["청도새마을휴게소"],
    ["안성휴게소", "추풍령휴게소", "칠곡휴게소"],
    ["정안알밤휴게소", "함평천지휴게소"],
    ["화성휴게소", "행담도휴게소", "군산휴게소"],
    ["와촌휴게소", "칠곡휴게소", "추풍령휴게소"],
  ];
  const STOPS_EN = { "안성휴게소": "Anseong", "금강휴게소": "Geumgang", "추풍령휴게소": "Chupungnyeong", "칠곡휴게소": "Chilgok",
    "천안삼거리휴게소": "Cheonan Samgeori", "서산휴게소": "Seosan", "홍성휴게소": "Hongseong", "고창고인돌휴게소": "Gochang Goindol",
    "용인휴게소": "Yongin", "문막휴게소": "Munmak", "평창휴게소": "Pyeongchang", "경주휴게소": "Gyeongju", "청도새마을휴게소": "Cheongdo",
    "정안알밤휴게소": "Jeongan", "함평천지휴게소": "Hampyeong", "화성휴게소": "Hwaseong", "행담도휴게소": "Haengdamdo",
    "군산휴게소": "Gunsan", "와촌휴게소": "Wachon" };
  const ko = () => (window.BN_LANG ? BN_LANG() : "en") === "ko";
  const W = (k, e) => (ko() ? k : e);

  const code = (new URLSearchParams(location.search).get("v") || "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 10);
  let visit = null, state = code ? "loading" : "none";     // loading | ok | expired | none

  // -- a seeded history ---------------------------------------------------- //
  function rng(seed) {
    let h = 2166136261;
    for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
    return () => { h += 0x6D2B79F5; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function trace(r, start, drive, eps) {
    const out = [], n = 60;
    for (let i = 0; i <= n; i++) {
      const s = drive * i / n, hr = new Date((start + s) * 1000).getHours();
      let v = 0.12 + (hr >= 2 && hr < 5 ? 0.18 : hr < 2 ? 0.1 : 0.03) + 0.06 * (s / drive) + (r() - 0.5) * 0.06;
      for (const e of eps) { const d = Math.abs(start + s - e.at); if (d < 600) v = Math.max(v, 0.55 + 0.1 * e.max_stage - d / 1500); }
      out.push([Math.round(s), Math.round(Math.min(0.98, Math.max(0.02, v)) * 1000) / 1000]);
    }
    return out;
  }
  let cache = null;
  function history() {
    const key = (code || "bamnun") + (ko() ? "k" : "e");
    if (cache && cache.key === key) return cache.list;
    const r = rng(code || "bamnun"), out = [];
    let day = 61, id = 500;
    while (true) {
      day -= 1 + Math.floor(r() * 2.3);
      if (day < 1) break;
      const ri = Math.floor(r() * ROUTES.length), R = ROUTES[ri], back = r() < 0.5;
      const d = new Date(); d.setDate(d.getDate() - day); d.setHours(20 + Math.floor(r() * 4), Math.floor(r() * 60), 0, 0);
      const start = d.getTime() / 1000;
      const drive = R.min * 60 * (1.05 + r() * 0.25);
      const nb = R.min > 150 ? 1 + Math.floor(r() * 2) : Math.floor(r() * 2);
      const break_s = nb * (900 + r() * 900), dur = drive + break_s;
      const eps = [];
      for (let t = start + 1800; t < start + dur - 600; t += 1200 + r() * 1200) {
        const hr = new Date(t * 1000).getHours(), p = hr >= 2 && hr < 5 ? 0.22 : hr < 2 ? 0.12 : 0.05;
        if (r() < p) eps.push({ at: Math.round(t), max_stage: r() < 0.55 ? 1 : r() < 0.6 ? 2 : r() < 0.7 ? 3 : 4 });
      }
      const alert_s = eps.length * (180 + r() * 240);
      // Rest stops spread along the route, each where it really is (its
      // place in the route's list), in driving order.
      const all = STOPS[ri] || [], k = Math.min(all.length, Math.max(nb, 1));
      let stops = [...Array(k)].map((_, j) => { const i = Math.floor((j + 0.5) * all.length / k); return { name: all[i], f: (i + 1) / (all.length + 1) }; });
      if (back) stops = stops.reverse().map((x) => ({ name: x.name, f: 1 - x.f }));
      const path = back ? R.path.slice().reverse() : R.path;
      out.push({
        id: id--, started_at: start, ended_at: start + dur, open: false, tz_min: -new Date().getTimezoneOffset(),
        summary: { duration_s: Math.round(dur), drive_s: Math.round(drive), calm_s: Math.round(drive - alert_s),
          alert_free: Math.round((drive - alert_s) / drive * 1e4) / 1e4, alerts: eps.length,
          max_stage: Math.max(0, ...eps.map((e) => e.max_stage)), microsleeps: eps.some((e) => e.max_stage === 4) ? 1 : 0,
          breaks: nb, break_s: Math.round(break_s), longest_calm_s: Math.round(Math.min(drive - alert_s, 3000 + r() * 6000)), episodes: eps },
        route: { from: back ? W(R.to, R.to_en) : W(R.from, R.from_en), to: back ? W(R.from, R.from_en) : W(R.to, R.to_en),
          distance_km: R.km, path, stops: stops.map((x) => ({ name: W(x.name, STOPS_EN[x.name] + " rest area"), f: x.f })) },
        trace: trace(r, start, drive, eps),
      });
    }
    out.sort((a, b) => b.started_at - a.started_at);
    cache = { key, list: out };
    return out;
  }
  function boothTrip() {
    if (!visit || !visit.trip) return null;
    const t = visit.trip;
    return Object.assign({}, t, { id: 9999, open: false, tz_min: -new Date().getTimezoneOffset(), caught: visit.caught || null,
      route: { from: W("밤눈 체험 부스", "Bamnun booth"), to: W("창보고 전시회", "Exhibition"), booth: true } });
  }
  function trips() { const b = boothTrip(); return b ? [b].concat(history()) : history(); }

  // -- pictures ------------------------------------------------------------ //
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function mapSvg(t) {
    const p = t.route && t.route.path;
    if (!p || p.length < 2) return "";
    const lat0 = p.reduce((a, q) => a + q[0], 0) / p.length, k = Math.cos(lat0 * Math.PI / 180);
    const xs = p.map((q) => q[1] * k), ys = p.map((q) => -q[0]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const Wd = 300, Hd = 170, pad = 22, s = Math.min((Wd - 2 * pad) / Math.max(1e-6, x1 - x0), (Hd - 2 * pad) / Math.max(1e-6, y1 - y0));
    const ox = (Wd - (x1 - x0) * s) / 2, oy = (Hd - (y1 - y0) * s) / 2;
    const P = (i) => [(ox + (xs[i] - x0) * s).toFixed(1), (oy + (ys[i] - y0) * s).toFixed(1)];
    const d = p.map((_, i) => (i ? "L" : "M") + P(i).join(",")).join("");
    const stops = t.route.stops || [];
    const dots = stops.map((x) => { const [cx, cy] = P(Math.round(x.f * (p.length - 1))); return `<circle cx="${cx}" cy="${cy}" r="4.5" fill="#E8D7AE" stroke="#24212A" stroke-width="2"/>`; }).join("");
    const [ax, ay] = P(0), [bx, by] = P(p.length - 1);
    return `<div style="margin-top:14px"><svg viewBox="0 0 ${Wd} ${Hd}" width="100%" style="display:block;border-radius:14px;background:#24212A">
      <path d="${d}" fill="none" stroke="#E8D7AE" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${dots}
      <circle cx="${ax}" cy="${ay}" r="6" fill="#F2EEE8"/><circle cx="${bx}" cy="${by}" r="6" fill="#24212A" stroke="#F2EEE8" stroke-width="2.5"/>
      <text x="${ax}" y="${+ay - 10}" fill="#F2EEE8" font-size="12" font-weight="600" text-anchor="middle">${esc(t.route.from)}</text>
      <text x="${bx}" y="${+by - 10}" fill="#F2EEE8" font-size="12" font-weight="600" text-anchor="middle">${esc(t.route.to)}</text></svg>
      ${stops.length ? `<p style="margin:8px 0 0;font-size:12.5px;color:#9A93A0">${esc(W("쉬어 간 곳: ", "Stops: "))}${esc(stops.map((x) => x.name).join(" · "))}</p>` : ""}</div>`;
  }
  function curveSvg(t) {
    const tr = t.trace;
    if (!tr || tr.length < 2) return "";
    const Wd = 300, Hd = 110, end = tr[tr.length - 1][0] || 1;
    const X = (s) => (8 + (Wd - 16) * s / end).toFixed(1), Y = (v) => (Hd - 14 - (Hd - 26) * v).toFixed(1);
    const line = tr.map((q, i) => (i ? "L" : "M") + X(q[0]) + "," + Y(q[1])).join("");
    const marks = ((t.summary || {}).episodes || []).map((e) => { const s = e.at - t.started_at; return s >= 0 && s <= end ? `<line x1="${X(s)}" x2="${X(s)}" y1="10" y2="${Hd - 14}" stroke="#F2B66D" stroke-dasharray="3 3"/><circle cx="${X(s)}" cy="10" r="4" fill="#F2B66D"/>` : ""; }).join("");
    return `<div style="margin-top:14px"><span style="font-size:12.5px;color:#9A93A0">${esc(W("졸음 정도", "How sleepy"))}</span>
      <svg viewBox="0 0 ${Wd} ${Hd}" width="100%" style="display:block;margin-top:6px;border-radius:14px;background:#24212A">
      <line x1="8" x2="${Wd - 8}" y1="${Y(0.5)}" y2="${Y(0.5)}" stroke="#2E2A33" stroke-dasharray="4 4"/>${marks}
      <path d="${line} L${X(end)},${Hd - 14} L8,${Hd - 14} Z" fill="rgba(232,215,174,.10)"/>
      <path d="${line}" fill="none" stroke="#E8D7AE" stroke-width="2.5" stroke-linejoin="round"/></svg></div>`;
  }
  function caughtHtml(t) {
    if (!t.caught) return "";
    return `<div style="margin-top:12px;display:flex;gap:12px;align-items:center"><img src="${t.caught}" alt="" style="width:96px;height:96px;object-fit:cover;border-radius:14px;flex-shrink:0">
      <div><b style="font-size:15px">${esc(W("여기서 졸았어요 😴", "Caught you dozing 😴"))}</b><p style="margin:4px 0 0;font-size:13px;color:#9A93A0;line-height:1.4">${esc(W("밤눈이 이 순간 처음으로 깨웠어요.", "The moment Bamnun first woke you."))}</p></div></div>`;
  }

  // -- the guided tour (once per visit) ------------------------------------- //
  const STEPS = [
    { go: "Home", sel: "#hAvatar", ko: ["이건 당신이에요", "방금 부스에서 찍은 사진이 프로필이 됐어요."], en: ["This is you", "Your photo from the booth is your profile."] },
    { go: "Home", sel: "#hTrip", ko: ["방금 운전한 기록", "부스에서 운전한 기록이 맨 위에 있어요."], en: ["Your drive, just now", "Your booth drive is at the top."] },
    { go: "Trips", open: true, sel: "[data-trip='9999']", ko: ["운전 자세히 보기", "졸음 그래프와 밤눈이 깨운 순간이에요."], en: ["Your drive in detail", "How sleepy you got, and when Bamnun woke you."] },
    { go: "Trips", sel: "#tList", ko: ["두 달 동안의 기록", "실제 고속도로 경로로 달린 밤 운전 기록이에요."], en: ["Two months of drives", "Night drives on real Korean expressways."] },
    { go: "Insights", sel: "#iBody > section", ko: ["올리가 찾은 패턴", "언제 졸리는지, 무엇이 깨웠는지 알려줘요."], en: ["Patterns Ollie found", "When you get sleepy, and what wakes you."] },
    { go: "Home", sel: "a[href='#Stages']", alt: () => [...document.querySelectorAll("section")].find((x) => x.isConnected && x.offsetParent && /Wake-up steps|깨우기 단계/.test((x.querySelector("b") || {}).textContent || "")), ko: ["깨우기 단계 미리 듣기", "네 단계를 휴대폰에서 들어 보세요. 이제 자유롭게 둘러보세요!"], en: ["Try the wake-up stages", "Hear the four stages here. Now look around!"] },
  ];
  function tour() {
    let i = 0, box = null;
    const end = () => { if (box) box.remove(); box = null; try { localStorage.setItem("bn-tour-" + code, "1"); } catch (e) {} };
    function show() {
      if (i >= STEPS.length) return end();
      const st = STEPS[i];
      if (window.BN_GO) BN_GO(st.go, { instant: true });
      setTimeout(() => {
        if (st.open) { const c = document.querySelector("[data-trip='9999']"); if (c && c.getAttribute("aria-expanded") !== "true") c.click(); }
        setTimeout(() => {
          const el = document.querySelector(st.sel) || (st.alt && st.alt());
          if (!el) { i++; return show(); }
          el.scrollIntoView({ block: "center" });
          setTimeout(() => place(el, st), 250);
        }, 250);
      }, 350);
    }
    function place(el, st) {
      if (!box) {
        box = document.createElement("div");
        box.style.cssText = "position:fixed;inset:0;z-index:9999;";
        box.addEventListener("click", (e) => { if (e.target.dataset.skip) return end(); i++; show(); });
        document.body.appendChild(box);
      }
      const r = el.getBoundingClientRect(), pad = 8, [h, p] = st[ko() ? "ko" : "en"];
      const below = r.bottom + 190 < innerHeight;
      box.innerHTML = `<div style="position:fixed;left:${r.left - pad}px;top:${r.top - pad}px;width:${r.width + 2 * pad}px;height:${r.height + 2 * pad}px;border-radius:18px;box-shadow:0 0 0 9999px rgba(10,6,12,.72);outline:3px solid #F2EEE8;transition:all .25s"></div>
        <div style="position:fixed;left:16px;right:16px;${below ? `top:${r.bottom + pad + 14}px` : `bottom:${innerHeight - r.top + pad + 14}px`};background:#F2EEE8;color:#15131A;border-radius:20px;padding:16px 18px;font-family:Pretendard,system-ui,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.4)">
          <span style="font-size:12px;color:#9A93A0">${i + 1} / ${STEPS.length}</span>
          <h3 style="margin:4px 0 0;font-size:20px;font-weight:700">${esc(h)}</h3>
          <p style="margin:6px 0 12px;font-size:14.5px;line-height:1.45">${esc(p)}</p>
          <div style="display:flex;justify-content:space-between;align-items:center"><button data-skip="1" style="background:none;border:0;color:#9A93A0;font-size:14px;padding:6px 0">${esc(W("건너뛰기", "Skip"))}</button>
          <span style="background:#15131A;color:#F2EEE8;font-weight:700;font-size:14px;padding:9px 16px;border-radius:99px">${esc(i === STEPS.length - 1 ? W("시작하기", "Done") : W("다음", "Next"))} ›</span></div></div>`;
    }
    show();
  }

  // -- loading ------------------------------------------------------------- //
  function toast(text) {
    const d = document.createElement("div");
    d.textContent = text;
    d.style.cssText = "position:fixed;left:16px;right:16px;top:16px;z-index:9998;background:#F2EEE8;color:#15131A;border-radius:16px;padding:14px 16px;font:600 14.5px Pretendard,system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.35)";
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 5000);
  }
  async function load() {
    const cfg = window.BN_SUPABASE;
    if (!code || !cfg) { state = "none"; return; }
    try {
      const r = await fetch(cfg.url + "/rest/v1/rpc/get_visit", { method: "POST",
        headers: { apikey: cfg.key, Authorization: "Bearer " + cfg.key, "Content-Type": "application/json" },
        body: JSON.stringify({ c: code }) });
      const v = r.ok ? await r.json() : null;
      if (v && v.trip) { visit = v; state = "ok"; } else state = "expired";
    } catch (e) { state = "expired"; }
    cache = null;
    window.dispatchEvent(new Event("bn-visit"));
    if (state === "expired") toast(W("이 체험 기록은 만료됐어요. 기본 데모를 보여 드릴게요.", "This booth drive has expired. Here's the demo instead."));
    if (state === "ok") {
      let done = false; try { done = localStorage.getItem("bn-tour-" + code) === "1"; } catch (e) {}
      if (!done) setTimeout(tour, 1600);
    }
  }

  window.BN_VISIT = {
    trips, state: () => state, visit: () => visit, mapSvg, curveSvg, caughtHtml, tour,
    name: () => (visit ? W("체험 운전자 #" + visit.number, "Test driver #" + visit.number) : null),
    photo: () => (visit && visit.photo) || null,
  };
  if (/\.github\.io$/i.test(location.hostname) || new URLSearchParams(location.search).has("demo")) setTimeout(load, 0);
})();
