# Handoff: where the Bamnun booth work stands

Read this first if you're picking up the work (a new Claude session, another
account, or a teammate). It's kept up to date with every change; the date of
the last update is at the bottom.

## The goal right now

A **demo booth / exhibition** for Bamnun, the Raspberry Pi drowsiness monitor.
The person at the booth sits at a game steering wheel (Euro Truck Simulator on
a separate computer), the Bamnun device sits **low on the table to the
driver's LEFT, looking up**, and the Pi's own monitor shows the Bamnun window.
The team controls the Pi with **Raspberry Pi Connect** (screen sharing), not
the Wi-Fi hotspot.

## Where things are

- Repo: `github.com/seunghyun2007/bamnun`, working branch **`demo-booth`**
  (pushed; **PR #5 into `main` is open**, not merged:
  https://github.com/seunghyun2007/bamnun/pull/5). `main` = the merged app + friend's
  detection rework (PR #4).
- Mac copy: `~/Downloads/bamnun` (on `demo-booth`).
- Pi: Raspberry Pi 5 called **`inpi`**, user `inpi`, repo at `~/bamnun`, on
  `demo-booth`. Reach it with `ssh inpi` (Tailscale, 100.118.127.48; the Mac's
  `~/.ssh/config` has the host) or Pi Connect. The Mac's SSH key is on the Pi.
- Update the Pi: `tools/booth/pi.sh update` from the Mac (git pull on the Pi),
  then **close and reopen bamnun on the Pi** (desktop icon → `tools/run_pi.sh`).
- Tests: `python -m pytest -q` (303 pass). On the Mac a venv with the deps is
  needed; on the Pi use `~/bamnun/.venv/bin/python`.
- `local-wip` branch (Mac and Pi): the owner's own older uncommitted edits
  (dashboard, rotation, voice recordings). Never compared with the friend's
  detection code beyond what was ported (dashboard, camera rotation).

## What the Bamnun window does now (on `demo-booth`)

- **Dashboard** layout (viz.Dashboard): camera + panels (state, CO2 air, eyes,
  head, system response lights, rest plan, charts, what drives the score).
  Buttons drawn on it: VOL -, VOL +, CALIBRATE, FULL SCREEN (clicks work over
  Pi Connect; keys don't always). Keys: c calibrate, f full screen, l layout,
  - / = volume, space briefing, Esc skip standby/briefing, q quit.
- **Speaker** (USB, ALSA card `UACDemoV10`, control `PCM`) set to **80% at
  every start**; VOL buttons change it in 10% steps.
- **Camera rotated 180°** (`capture.picamera.rotate_180: true`).
- **Calibration**: stops after 3 failed tries and keeps the old one; turns the
  wake-up lights off first (the blue light darkened the exposure); thresholds
  relaxed for the side camera. While calibrating, a full-screen page says
  "게임 화면을 보세요 / Look at the game screen" with a big moving arrow to
  the right, a progress bar and the live hint.
- **Side camera fix**: eye readings past 55° from the camera itself are
  "turned" (unseen, not shut): no closure, microsleep or PERCLOS from them.
- **Standby** after 30 s with no face: invitation screen (Ollie, animated),
  ladder rests (lights off, no chimes). It stays when someone sits down until
  space/click, which starts the **briefing** (6 pages, Korean first: Ollie,
  sit at the wheel, **click Drive in the game** (game screenshot
  `assets/booth/game_drive.jpg` with an arrow), 15 s calibration, try being
  sleepy, four wake-up steps). The last page starts calibration.
- **Look**: like the owner's lecture slides (Mandel Cabrera's deck): light grey
  left panel with one picture, charcoal right panel, white serif text
  (NanumMyeongjo on the Pi, `fonts-nanum`), title in a thin white box. No
  other colours.
- **Ollie's voice**: 17 lines EN + KO generated with Supertonic voice M1
  (`tools/make_voice.py`), in `assets/voice/{en,ko}/`.
- Normal (non-booth) mode still fires the real light/mist/alarm when drowsy.

Other pieces on the branch, built earlier and set aside by the owner: the
phone app's Product demo / Product control screens, the Wi-Fi hotspot booth
(`tools/booth/`, two QR codes), `pi.sh`. Google sign-in uses the owner's
Supabase project `oyfhampefdytoikzxcgd` (keys in `frontend/.env`, not in git).

## The owner's preferences

- Explain plainly, step by step; they test on the real Pi and send screenshots.
- Simple, calm visuals: few colours (see "Look" above). Korean first.
- Don't push to `main` or merge without asking. Pushing `demo-booth` is fine.
- Prefer Pi Connect for control; clicks over keys.

## Open items

- PR #5 (`demo-booth` -> `main`) is open: the friend should review it before
  it's merged. No CI on the repo.
- Compare `local-wip` with the friend's detection code.
- Check the sources for the "why we chose it" text (phone app stage cards).
- An old Wi-Fi profile called "hotspot" on the Pi (not Bamnun's) autoconnects.
- Try with several visitors in a row at the real booth.

## Log (newest first)

- 2026-11-06: opened PR #5, demo-booth -> main.
- 2026-11-06: owner checked the new look, Drive page and calibration screen on
  the Pi: approved.
- 2026-11-06: new calm look (grey/charcoal, serif), animated Ollie, "click
  Drive" briefing page, calibration screen with arrow, speaker 80% at start,
  this handoff file.
- 2026-11-06: standby + briefing (sharp at any size, Korean first), side-camera
  fix, calibration fixes, dashboard + buttons, camera rotation.
- 2026-11-05: booth mode, voice, Supabase sign-in, merge of app-accounts (PR #4).

_Last updated: 2026-11-06._
