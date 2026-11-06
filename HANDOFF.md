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
- Tests: `python -m pytest -q` (322 pass). On the Mac a venv with the deps is
  needed; on the Pi use `~/bamnun/.venv/bin/python`.
- `local-wip` branch (Mac and Pi): the owner's own older uncommitted edits
  (dashboard, rotation, voice recordings). Never compared with the friend's
  detection code beyond what was ported (dashboard, camera rotation).

## What the Bamnun window does now (on `demo-booth`)

- **Dashboard** layout (viz.Dashboard): camera + panels (state, CO2 air, eyes,
  head, system response lights, rest plan, charts, what drives the score).
  Buttons drawn on it: QR + STAGES (above NEXT PERSON: opens the learn-more
  screen straight away), NEXT PERSON (bottom-left: lights off, the briefing
  from page 1, a fresh pop-up), VOL -, VOL +, CALIBRATE, FULL SCREEN (clicks
  work over Pi Connect; keys don't always). Keys: m learn-more screen, n next person, c calibrate, f full screen, l layout,
  - / = volume, space briefing, Esc skip standby/briefing, q quit.
- **Speaker** (USB, ALSA card `UACDemoV10`, control `PCM`) set to **80% at
  every start**; VOL buttons change it in 10% steps.
- **Camera rotated 180°** (`capture.picamera.rotate_180: true`).
- **Calibration**: stops after 3 failed tries and keeps the old one; turns the
  wake-up lights off first (the blue light darkened the exposure); thresholds
  relaxed for the side camera. While calibrating, a full-screen page says
  "게임 화면을 보세요 / Look at the game screen" with a big moving arrow to
  the right, a progress bar and the live hint.
- **Blocked camera is not a head drop** (`features.nod.head_drop_when_lost:
  false`): the driver's arm passes in front of the low left camera; the face
  vanished after a jump in the landmarks, which read as a head drop and fired
  stage 4 (four false alarms in the 2026-11-06 22:32 log). Now a lost face is
  just unseen; shut eyes and nods with the face in view still count.
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
- **Face mesh** on the camera (`ui.draw_mesh: true`): face oval, brows, nose,
  lips as lines, all 478 landmarks as dots, eyes still outlined in green
  (`viz.draw_face_mesh`, about 0.2 ms). Also on the standby screen's camera,
  which now spans the whole grey panel under a smaller Ollie.
- **Ollie's voice**: 17 lines EN + KO generated with Supertonic voice M1
  (`tools/make_voice.py`), in `assets/voice/{en,ko}/`.
- **Learn more pop-up** (`ui.learn_more`): after a visitor has driven 45 s
  (face seen, on the dashboard, not calibrating), a white website-style card
  (bigger, drawn at the window's own size so it's sharp) drops in with a
  little bounce over the camera's top-right corner, Ollie waving and the
  button glowing: Ollie, "밤눈이 궁금하세요? /
  Want to learn more about Bamnun?" and a "QR 코드 보기 · Learn more" button.
  A click opens the **learn-more screen**: QR code for the website on the
  left ("휴대폰으로 더 알아보기"), and on the right "깨우기 단계 체험" with four
  stage cards (파란 불빛, 민트 미스트, 차임과 음성, 알람). A click on a card
  (or keys 1-4) plays that stage on the real device (`control.SHOWCASE_STAGES`,
  the same commands a phone used to send), one at a time; the card lights up
  with a progress bar. "‹ 돌아가기 / Back", Esc, space or 60 s untouched
  goes back. The × or 40 s untouched hides it. Once per
  visitor (reset at standby). QR made by OpenCV (`cv2.QRCodeEncoder`), no new
  package.
- **Mac simulator**: `tools/sim_server.py` (port 8000) plays a fake sleepy
  driver on repeat; an app tab open on localhost:8000 then rings alarms and
  "Are you OK? … tap your phone". Stop it with Ctrl+C when not needed.
- **Website** (the phone app as a web page): **https://seunghyun2007.github.io/bamnun/**,
  GitHub Pages from the `gh-pages` branch (just `index.html` + `.nojekyll`).
  There's no Pi behind it, so on `*.github.io` the app runs its built-in demo
  (`live.js` WEBSITE): Product demo = simulated driver, labelled "Demo";
  Product control = sound preview on the phone. The website skips the
  splash and the Product demo / control choice: it opens straight on the demo
  Home, in the phone's language (`shell.html` start logic). "‹ Start" still
  leads back to the choice.
  To update it: `cd frontend && npm run build` (reads `frontend/.env`), then
  copy `frontend/www/index.html` onto the `gh-pages` branch and push. Google
  sign-in there needs this address in Supabase → Authentication → URL
  Configuration (redirect URLs): `https://seunghyun2007.github.io/bamnun/**`
  added 2026-11-06 (also `http://localhost:8000/**`, `kr.bamnun.app://auth-callback`).
- **Pi temperature watch** (`thermal.py` PiHealth, config `thermal:`): reads
  the chip temperature every 2 s and `vcgencmd get_throttled` every 10 s. The
  dashboard footer always shows "Pi NN C". At 75 °C an orange bar appears on
  top of the window ("Pi가 뜨거워지고 있어요 / The Pi is getting warm"); at
  80 °C or when the Pi throttles, a red bar ("너무 뜨거워요: 잠시 꺼서 식혀
  주세요"); a weak power supply gets its own red bar. The screen shrinks to fit
  under the bar, nothing is covered. Changes are logged as `pi_health` events.
  (Pi 5 throttles itself at 85 °C; normal at the booth was about 59 °C.)
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

- 2026-11-06: QR + STAGES button and m key open the learn-more screen directly.
- 2026-11-06: learn-more screen gets four stage cards that play on the real device.
- 2026-11-06: arm blocking the camera no longer fires stage 4; website opens straight on the demo.
- 2026-11-06: NEXT PERSON button (n); pop-up bigger, sharp, animated.
- 2026-11-06: website runs the built-in demo drive (Product demo was stuck on "connecting").
- 2026-11-06: website address added to Supabase redirect URLs.
- 2026-11-06: website on GitHub Pages; "learn more" pop-up after 45 s of driving -> QR screen.
- 2026-11-06: Pi temperature/power warning bar + "Pi NN C" in the footer.
- 2026-11-06: face mesh (outlines + 478 dots); standby camera as wide as the
  grey panel.
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
