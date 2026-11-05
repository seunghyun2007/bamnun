# Accounts and cloud sync

Drivers can sign in with Google. Their profile, settings, trips and alert
events are then kept in a Supabase (Postgres) database, so they come back on a
new phone. Signing in is optional: detection and the wake-up ladder run on the
Pi and never wait for an account or the internet.

## How it fits together

```
Pi (SQLite, source of truth while driving)
  --hotspot Wi-Fi-->  phone outbox (localStorage)
  --any internet, later-->  Supabase (Postgres, Row Level Security)
```

- **Sign-in** (`frontend/build/account.js`): Supabase Auth with Google, PKCE.
  The Android/iOS app opens Google in the system browser and comes back through
  `kr.bamnun.app://auth-callback` (`@capacitor/browser`, `@capacitor/app`). A
  desktop browser comes back to the same page. No Android SHA-1 or iOS client
  is needed for this method.
- **Sync** (`frontend/build/sync.js`): on every connect to the Pi the phone
  copies finished trips (with their events) into an outbox, and uploads it
  whenever Supabase is reachable. A trip's key is
  `(user_id, device_uid, device_trip_id)`, where `device_uid` is the Pi's own
  random ID (`device_id` in `/api/health`), and every write is an upsert on
  that key: no duplicates, and a failed upload is simply retried.
- **Profile**: uploaded after every change; downloaded at sign-in. A returning
  account goes straight to Home; a new one goes through setup with an empty
  name. Signing in from Settings keeps what's already on the phone.
- **Trips and Insights** read from Supabase when signed in (plus anything still
  in the outbox, plus the Pi's current trip), and from the Pi otherwise.
- **Log out** keeps trips not yet uploaded for that account. **Delete account**
  removes the sign-in and all its cloud rows (`delete_my_account()`); trips on
  the Pi stay.
- Video never goes to Supabase.

## Tables (`supabase/schema.sql`)

| table | one row per | notes |
|---|---|---|
| `profiles` | user | name, owl name (always Ollie), vehicle, work week, voice and app language, settings, onboarded |
| `devices` | user × Bamnun | which device belongs to the user |
| `trips` | finished drive | start/end time and place, distance, route summary, alerts per stage, longest alert-free stretch, breaks, full summary |
| `alert_events` | event | time, kind, stage, reason, location (empty for now: the Pi doesn't record one) |

Row Level Security is on for all four; each policy allows only rows whose
`user_id` is the signed-in user. Signed-out (anon) requests get nothing.

## Setting up a Supabase project

1. supabase.com → New project (region Seoul).
2. Project Settings → Data API: copy the Project URL. Project Settings → API
   Keys: copy the **publishable** (or legacy `anon`) key. Put both in
   `frontend/.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_ANON_KEY=sb_publishable_...
   ```
   Never the secret / service role key: the build refuses it.
3. SQL Editor: run `supabase/schema.sql`.
4. Google Cloud → Google Auth Platform: audience External, status Testing, add
   the team's Gmail addresses as test users. Create an OAuth client of type
   **Web application** with the redirect URI
   `https://<project>.supabase.co/auth/v1/callback`.
5. Supabase → Authentication → Sign In / Providers → Google: on, paste the
   client ID and secret.
6. Supabase → Authentication → URL Configuration: Site URL
   `http://localhost:8000`; Redirect URLs `kr.bamnun.app://auth-callback`,
   `http://localhost:8000/**` (and any other local port you test on).

Then `npm run build` (or `python build/build.py ...`); only `www/index.html`
gets the keys, never `Bamnun_app.html`.

## Testing it

- **Browser:** `python tools/sim_server.py --port 8000`, open
  `http://localhost:8000`, Get started → Continue with Google → setup → All set.
  Supabase → Table Editor → `profiles` shows the row with `onboarded = true`.
- **Trip sync:** with the app open, end the simulated trip
  (`curl -X POST localhost:8000/api/trips/end`). A few seconds later it's in
  `trips` and its events in `alert_events`. Reconnecting doesn't add it again.
- **Offline first:** turn the laptop's Wi-Fi off, end a trip, see Settings →
  Account say a trip is waiting; Wi-Fi on, it uploads once.
- **New phone:** Log out, sign in again with the same Google account: straight
  to Home with the saved name.
- **Android:** `npm run sync`, `npx cap run android`, then the same steps; the
  Google page opens in Chrome and returns to the app.
