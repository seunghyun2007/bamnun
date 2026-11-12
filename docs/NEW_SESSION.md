# Start here: brief for a new Claude Code session

Paste this into a new Claude Code session opened in the `bamnun` folder
(branch `demo-booth`), or tell it: "Read docs/NEW_SESSION.md and HANDOFF.md".

---

You're picking up work on **Bamnun (밤눈)**, a drowsiness monitor for night
drivers: a Raspberry Pi 5 with a camera, blue light, mint mist and a speaker,
plus a phone app. The previous session (another computer) built the
**exhibition booth** version. The exhibition is **10 Nov 2026 (창보고 전시회)**;
the visitor data is deleted after **24 Nov 2026**.

## Read first

1. `HANDOFF.md`: the full state, decisions and a dated log. Keep it updated
   with **every** change (state, open items, a log line) and commit it with
   the change.
2. `docs/LAPTOP_SETUP.md`: how the booth runs on one laptop.
3. `docs/REDESIGN_PLAN.md`: the phone app's look (part 1 is done and live).
4. `docs/LAPTOP_NAV_PROMPT.md`: a prompt for the laptop's own Claude Code
   (switching between the game and Bamnun without Alt+Tab).

## How the booth works now

- **No personal monitors allowed**, so everything is on a teammate's
  **Windows laptop**: Euro Truck Simulator 2 on the left ⅔, the Pi's screen
  in **RealVNC Viewer** on the right ⅓. Ethernet cable Pi ↔ laptop; the Pi is
  **10.43.0.1** (profile `bamnun-laptop`). The Pi's virtual screen is
  720×1200 (tall) when no monitor is plugged in (`~/.config/labwc/autostart`).
- **Bamnun** (`src/bamnun/app.py`, OpenCV window) switches to a tall layout
  by itself when its window is taller than wide.
- **Visitor flow, no clicks:** the dashboard is always up. After 30 s with
  nobody, the visitor is forgotten; the next face seen for 3 s starts their
  guide: "fit your face in the oval" (moves on when green), then calibration
  (look at the game). No pop-ups or hints over the camera: **the team explains
  and asks consent in person.**
- **QR code always on the dashboard** (bottom middle; under the camera in the
  tall layout): the current visitor's own code. The Pi uploads their drive and
  two small face photos to Supabase every 15 s and when they leave
  (`src/bamnun/visit.py`, `supabase/booth_consent.sql`). Their phone opens
  `https://seunghyun2007.github.io/bamnun/?v=<code>`: their photo, booth drive
  and ~35 generated past drives on real Korean routes, plus a phone walkthrough.
  Team switch **PHOTOS: OFF** for anyone who declines photos.
- **Staff remote on a teammate's phone:** `…/bamnun/staff.html?k=<STAFF_CODE>`
  (the owner has the link). Buttons: stages 1–4, 0 = all off, next person,
  recalibrate, photos off/on, volume, voice. Goes through a Supabase mailbox;
  the Pi checks every second (`src/bamnun/remote.py`, `supabase/booth_remote.sql`).
- **Detection rules for the booth:** an unseen face sets off nothing
  (`alerts.face_lost_alerts: false`); a face that vanishes isn't a head drop
  (`features.nod.head_drop_when_lost: false`); one sound at a time.
- Ollie's voice is **Korean at every start**; SETTINGS → VOICE switches.

## Where things are

- Repo: `github.com/seunghyun2007/bamnun`, branch **`demo-booth`** (PR #5 into
  `main` is open; **don't merge or push `main` without asking**; pushing
  `demo-booth` is fine).
- **Pi:** Raspberry Pi 5 `inpi`, user `inpi`, repo `~/bamnun`, venv
  `~/bamnun/.venv`. Update it with `git pull` there (or `tools/booth/pi.sh
  update` from a machine that has `ssh inpi`), then **close and reopen
  bamnun** on the Pi. Run tests on the Pi:
  `~/bamnun/.venv/bin/python -m pytest -q` (≈344 pass).
- **Reaching the Pi:** Pi Connect (connect.raspberrypi.com) always works.
  The old computer used `ssh inpi` over Tailscale (100.118.127.48); this
  computer needs Tailscale signed in and its own SSH key added to the Pi.
- **Website** (GitHub Pages, branch `gh-pages`: just `index.html`,
  `staff.html`, `.nojekyll`): build with `cd frontend && npm run build`
  (needs `frontend/.env`), then copy `frontend/www/index.html` and
  `staff.html` onto `gh-pages` (a temporary worktree), commit, push.
- **Supabase project** `oyfhampefdytoikzxcgd` (owner's account). SQL in
  `supabase/` was run in the dashboard's SQL editor. Tables: `visits`,
  `visit_consents`, `booth_commands`; functions `get_visit`, `put_visit`,
  `has_consent`, `send_command`, `take_commands`, `command_done`.

## Not in git (on purpose)

- `frontend/.env`: `SUPABASE_URL` and `SUPABASE_ANON_KEY` (public key);
  needed to build the website. Ask the owner to copy it from the old computer.
- On the Pi, `~/bamnun/frontend/.env` also has `STAFF_CODE` (the remote's
  code). Never commit it or print it in logs.

## The owner's preferences

- Explain step by step, plainly; they test on the real Pi/laptop and send
  screenshots. Korean first, English second.
- Calm visuals: few colours, no gradients or glow. The mascot is **Ollie**,
  an owl; keep his whole body or he reads as a cat or monkey
  (`assets/brand/`).
- Fewer moving parts beat clever tooling; minimise switching between the game
  and the Pi at the booth.
- Ask before merging to `main`, deleting data, or anything outward-facing.

## Open items (before/at the exhibition)

- A full dry run with a real visitor on the real laptop: sit → oval →
  calibration → drive → close eyes → scan QR → phone shows the drive.
- Check the Pi's own Wi-Fi at the venue (uploads and the remote need it);
  fall back to a phone hotspot.
- Laptop focus switching (Alt+Tab): run `docs/LAPTOP_NAV_PROMPT.md` on the
  laptop's Claude Code.
- After the exhibition: redesign part 2 (`docs/REDESIGN_PLAN.md`), flat Ollie
  on the Pi screens, friend's review of PR #5.
