/* The driver's account: Google sign-in through Supabase.

   BN_ACCOUNT.ready()            Supabase is set up in this build
   BN_ACCOUNT.user()             { id, email, name } or null
   BN_ACCOUNT.signIn()           opens Google; resolves when signed in
   BN_ACCOUNT.signOut()          forgets the session on this phone
   BN_ACCOUNT.token()            a fresh access token, or null (offline / out)
   BN_ACCOUNT.rest(method, path, body, prefer)   the database, as this user
   BN_ACCOUNT.on(fn)             called with the user (or null) on change

   Sign-in uses Supabase's PKCE flow in the phone's own browser, not in the
   app's WebView (Google refuses sign-in inside WebViews):
     - the Capacitor app opens the system browser (@capacitor/browser) and
       Supabase sends it back to kr.bamnun.app://auth-callback?code=...,
       which @capacitor/app hands us as appUrlOpen;
     - a plain browser goes to Google and comes back to this same page with
       ?code=... in the address.
   Then the code and our secret verifier are swapped for a session.

   The URL and the public anon (publishable) key come from frontend/.env at
   build time (window.BN_SUPABASE). The service role key never comes here.
   Talking to Supabase is plain fetch, so the build stays Python-only. */
(function () {
  "use strict";
  const CFG = window.BN_SUPABASE || null;
  const KEY = "bn-session", PKCE = "bn-pkce";
  const REDIRECT_APP = "kr.bamnun.app://auth-callback";
  const subs = [];
  let session = read(KEY), refreshing = null, waiting = null;

  function read(k) { try { const v = JSON.parse(localStorage.getItem(k)); return v && typeof v === "object" ? v : null; } catch (e) { return null; } }
  function write(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  const native = () => !!(window.Capacitor && Capacitor.isNativePlatform && Capacitor.isNativePlatform());
  function plugin(name) {
    const C = window.Capacitor;
    if (!C) return null;
    return (C.Plugins && C.Plugins[name]) || (C.registerPlugin ? C.registerPlugin(name) : null);
  }
  // Where Supabase sends the browser back to. A page from disk can't be
  // returned to, so sign-in there isn't offered.
  function redirectTo() {
    if (native()) return REDIRECT_APP;
    if (/^https?:$/.test(location.protocol)) return location.origin + location.pathname;
    return null;
  }

  function setSession(s) {
    session = s;
    write(KEY, s);
    const u = user();
    for (const fn of subs.slice()) { try { fn(u); } catch (e) { console.error(e); } }
  }
  function user() {
    if (!session || !session.user) return null;
    const u = session.user, m = u.user_metadata || {};
    return { id: u.id, email: u.email || m.email || "", name: m.full_name || m.name || "" };
  }

  // -- PKCE ---------------------------------------------------------------- //
  function b64url(bytes) {
    let s = ""; for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  async function pkce() {
    const verifier = b64url(crypto.getRandomValues(new Uint8Array(48)));
    // SHA-256 needs a secure context (https, localhost, the Capacitor app).
    if (window.crypto && crypto.subtle && window.isSecureContext) {
      const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
      return { verifier, challenge: b64url(new Uint8Array(hash)), method: "s256" };
    }
    return { verifier, challenge: verifier, method: "plain" };
  }

  async function auth(path, body, token) {
    const r = await fetch(CFG.url + "/auth/v1/" + path, {
      method: "POST",
      headers: Object.assign({ apikey: CFG.key, "Content-Type": "application/json" }, token ? { Authorization: "Bearer " + token } : {}),
      body: JSON.stringify(body || {}),
    });
    let d = null; try { d = await r.json(); } catch (e) {}
    if (!r.ok) { const err = new Error((d && (d.error_description || d.msg || d.message || d.error)) || "Sign-in failed (" + r.status + ")"); err.status = r.status; throw err; }
    return d;
  }
  function keep(d) {
    const exp = d.expires_at || Math.floor(Date.now() / 1000) + (d.expires_in || 3600);
    setSession({ access_token: d.access_token, refresh_token: d.refresh_token, expires_at: exp, user: d.user || (session && session.user) });
  }

  // The code from Supabase's redirect, for the session.
  async function finish(url) {
    const q = new URL(url).searchParams;
    const h = new URLSearchParams((new URL(url).hash || "").slice(1));
    const err = q.get("error_description") || q.get("error") || h.get("error_description") || h.get("error");
    const code = q.get("code");
    const p = read(PKCE);
    write(PKCE, null);
    if (err) throw new Error(err.replace(/\+/g, " "));
    if (!code || !p) throw new Error("Sign-in didn't finish. Please try again.");
    keep(await auth("token?grant_type=pkce", { auth_code: code, code_verifier: p.verifier }));
    return user();
  }

  async function signIn() {
    if (!CFG) throw new Error("Sign-in isn't set up in this copy of the app.");
    const back = redirectTo();
    if (!back) throw new Error("Sign-in isn't set up in this copy of the app.");
    const p = await pkce();
    write(PKCE, { verifier: p.verifier, at: Date.now() });
    const url = CFG.url + "/auth/v1/authorize?" + new URLSearchParams({
      provider: "google", redirect_to: back, code_challenge: p.challenge, code_challenge_method: p.method,
    }).toString();
    if (!native()) { location.assign(url); return new Promise(() => {}); }   // the page reloads
    const Browser = plugin("Browser");
    if (!Browser) throw new Error("Sign-in needs the Browser plugin. Run npm run sync.");
    // Resolved by the appUrlOpen listener below.
    const done = new Promise((resolve, reject) => { waiting = { resolve, reject }; });
    // Closing the browser without finishing cancels. (On Android the
    // browser also "finishes" on the way back to the app, so wait a moment
    // for appUrlOpen first.)
    let fin = null;
    try {
      fin = await Browser.addListener("browserFinished", () => setTimeout(() => {
        if (waiting) { const w = waiting; waiting = null; const e = new Error("cancelled"); e.cancelled = true; w.reject(e); }
      }, 1500));
    } catch (e) {}
    await Browser.open({ url, presentationStyle: "popover" });
    return done.finally(() => { try { fin && fin.remove(); } catch (e) {} });
  }

  function deferred() {
    let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; });
    promise.catch(() => {});
    return { promise, resolve, reject };
  }
  // A redirect nobody was waiting for (the app was restarted while the
  // browser was open) is announced instead, so the shell can carry on.
  async function onAppUrl(url) {
    if (!url || !url.startsWith(REDIRECT_APP)) return;
    const w = waiting || afterRedirect || (afterRedirect = deferred());
    const orphan = w !== waiting;
    waiting = null;
    try { const B = plugin("Browser"); if (B) await B.close(); } catch (e) {}   // iOS closes it; Android may not have one open
    try { const u = await finish(url); w.resolve(u); if (orphan) document.dispatchEvent(new CustomEvent("bn-signed-in", { detail: u })); }
    catch (e) { w.reject(e); }
  }

  // A browser coming back from Google: ?code=... or ?error=... in the address.
  let afterRedirect = null;
  function pendingReturn() {
    if (native()) return !!afterRedirect;
    const q = new URLSearchParams(location.search);
    return !!(read(PKCE) && (q.has("code") || q.has("error")));
  }
  function returned() {
    if (afterRedirect) return afterRedirect.promise;
    const url = location.href;
    const clean = () => { try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) {} };
    const promise = finish(url).finally(clean);
    afterRedirect = { promise, resolve() {}, reject() {} };
    return promise;
  }

  if (native()) {
    const App = plugin("App");
    if (App) {
      App.addListener("appUrlOpen", (e) => onAppUrl(e && e.url));
      // The app was closed while the browser was open and has just started.
      if (App.getLaunchUrl) App.getLaunchUrl().then((r) => {
        if (r && r.url && r.url.startsWith(REDIRECT_APP) && read(PKCE)) onAppUrl(r.url);
      }).catch(() => {});
    }
  }

  // -- tokens --------------------------------------------------------------- //
  async function token() {
    if (!CFG || !session) return null;
    if (session.expires_at - 60 > Date.now() / 1000) return session.access_token;
    if (!refreshing) {
      refreshing = auth("token?grant_type=refresh_token", { refresh_token: session.refresh_token })
        .then((d) => { keep(d); return session.access_token; })
        .catch((e) => {
          // A refused refresh token means the session is over; a network
          // error just means we're offline, so keep it for later.
          if (e.status === 400 || e.status === 401 || e.status === 403) setSession(null);
          return null;
        })
        .finally(() => { refreshing = null; });
    }
    return refreshing;
  }

  async function signOut() {
    const s = session;
    setSession(null);
    write(PKCE, null);
    if (s && CFG) { try { await auth("logout", {}, s.access_token); } catch (e) {} }
  }

  // PostgREST, as the signed-in user. Row Level Security on the server is
  // what keeps each user to their own rows; this only adds the token.
  async function rest(method, path, body, prefer) {
    const tok = await token();
    if (!tok) { const e = new Error("signed out or offline"); e.offline = true; throw e; }
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 12000);
    try {
      const r = await fetch(CFG.url + "/rest/v1/" + path, {
        method, signal: ctl.signal,
        headers: Object.assign({ apikey: CFG.key, Authorization: "Bearer " + tok, "Content-Type": "application/json" }, prefer ? { Prefer: prefer } : {}),
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (r.status === 401) { await token(); }
      if (!r.ok) { let d = ""; try { const j = await r.json(); d = j.message || j.hint || ""; } catch (e) {} const e = new Error(d || method + " " + path + " " + r.status); e.status = r.status; throw e; }
      if (r.status === 204) return null;
      const txt = await r.text();
      return txt ? JSON.parse(txt) : null;
    } finally { clearTimeout(timer); }
  }

  window.BN_ACCOUNT = {
    ready: () => !!(CFG && CFG.url && CFG.key && redirectTo()),
    configured: () => !!(CFG && CFG.url && CFG.key),
    user, signIn, signOut, token, rest, pendingReturn, returned,
    on(fn) { subs.push(fn); return () => { const i = subs.indexOf(fn); if (i >= 0) subs.splice(i, 1); }; },
  };
})();
