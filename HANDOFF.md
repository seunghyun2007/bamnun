# Handoff: where the Bamnun booth work stands

**New session on another computer? Start with `docs/NEW_SESSION.md`.**

Read this first if you're picking up the work (a new Claude session, another
account, or a teammate). It's kept up to date with every change; the date of
the last update is at the bottom.

## The goal right now

**Exhibition 10 Nov 2026. No personal monitor allowed: the booth runs on the
teammate's Windows laptop, game ⅔ + the Pi's screen over VNC ⅓. See
`docs/LAPTOP_SETUP.md`.**

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
- Tests: `python -m pytest -q` (344 pass). On the Mac a venv with the deps is
  needed; on the Pi use `~/bamnun/.venv/bin/python`.
- `local-wip` branch (Mac and Pi): the owner's own older uncommitted edits
  (dashboard, rotation, voice recordings). Never compared with the friend's
  detection code beyond what was ported (dashboard, camera rotation).

## What the Bamnun window does now (on `demo-booth`)

- **Dashboard** layout (viz.Dashboard): camera + panels (state, CO2 air, eyes,
  head, system response lights, rest plan, charts, what drives the score).
  Buttons drawn on it: GUIDE (top of the left stack: the guided tour again),
  VOICE: KOREAN/ENGLISH (Ollie's language; Korean at every start,
  `ui.voice_lang`), QR + STAGES (above NEXT PERSON: opens the learn-more
  screen straight away), NEXT PERSON (bottom-left: lights off, the briefing
  from page 1, a fresh pop-up), VOL -, VOL +, CALIBRATE, FULL SCREEN (clicks
  work over Pi Connect; keys don't always). Keys: g guided tour, v voice language, m learn-more screen, n next person, c calibrate, f full screen, l layout,
  - / = volume, space briefing, Esc skip standby/briefing, q quit.
- **SETTINGS menu** (replaces the row/stack of buttons): one SETTINGS button
  at the camera's bottom-right; a click opens a menu above it: GUIDE, VOICE,
  QR + STAGES, NEXT PERSON, CALIBRATE, FULL SCREEN, VOL - / speaker % / VOL +.
  An item closes the menu (volume keeps it open); a click beside it closes it.
  Keys still work (g v m n c f - =). The Pi tour's last step points at it.
- **Speaker** (USB, ALSA card `UACDemoV10`, control `PCM`) set to **80% at
  every start**; VOL buttons change it in 10% steps.
- **Camera rotated 180°** (`capture.picamera.rotate_180: true`).
- **Calibration**: stops after 3 failed tries and keeps the old one; turns the
  wake-up lights off first (the blue light darkened the exposure); thresholds
  relaxed for the side camera. While calibrating, a full-screen page says
  "게임 화면을 보세요 / Look at the game screen" with a big moving arrow to
  the right, a progress bar and the live hint.
- **Visitor's drive to their phone** (`visit.py`, until **24 Nov 2026**):
  from the end of calibration the Pi keeps the drive (sleepiness every 2 s,
  alerts, highest step, microsleeps) and two small face photos (profile:
  centred, eyes open; "caught": first alert). On the learn-more screen the
  left panel asks "내 운전 기록을 휴대폰으로 받을까요?" with the photo and
  예 / 아니요 (no = photos deleted at once). Yes uploads one row to Supabase
  `visits` (`supabase/booth_visits.sql`, already run: insert-only for the
  public key, read one by code via `get_visit`, everything stops/deletes
  after 24 Nov) and shows the visitor's own QR: website `?v=<code>`.
  NEXT PERSON / standby wipe it. The Pi needs `frontend/.env` with
  SUPABASE_URL and SUPABASE_ANON_KEY (public; installed on the Pi, not in git).
- **Website for a visitor** (`frontend/build/visit.js`): with `?v=code` it
  loads their visit: name "체험 운전자 #N", their photo on Home, their booth
  drive as the newest trip (curve, alert markers, caught photo), on top of
  ~35 generated night drives over 2 months on 10 real expressway routes
  (`routes_kr.json`, paths from OSRM, real 휴게소 names), the same history
  per code. Trip details show the route map and sleepiness curve. A 6-step
  phone tour (photo, latest drive, detail, history, insights, wake-up
  stages) runs once per code. Without a code (the general QR, or a visitor
  who said no) a 6-step general walkthrough runs once per phone. Expired code: a note and the plain demo.
- **Lights end on time on any screen** (`policy.tick`): a stage card's blue
  light stayed on, because lights only switched off inside the ladder's
  update, which the booth screens skip.
- **Booth screens are never interrupted** (`app._mode_changed`): on the QR,
  briefing and standby screens no ladder alert, rest or CO2 voice prompt, or
  "are you OK?" check; opening the QR screen turns the lights off; coming
  back to the dashboard resets the live eye windows and keeps alerts off for
  8 s (`QUIET_AFTER_SCREEN_S`).
- **Hover**: whatever the mouse is over lights up: dashboard buttons turn
  white, the pop-up's button lightens (grey disc behind ×), stage cards and
  Back lighten with a thick white edge.
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
  sit at the wheel, **center your face** (live camera with an oval that turns
  green when the face fits, hints closer/back/into the oval, a big arrow down
  to the device), **click Drive in the game** (game screenshot
  `assets/booth/game_drive.jpg` with an arrow), 15 s calibration, four
  wake-up steps). The last page starts calibration. "Try being sleepy" is no
  longer a page: 20 s into the drive a card (sleepy Ollie) and Ollie's voice
  (`try_sleepy`) suggest closing the eyes for 2 s; it hides after 15 s or when
  an alert answers it. The learn-more pop-up now comes at 60 s, after it.
- **Guided tour** (`attract.TOUR`, mode "tour"): right after a calibration,
  4 steps each light one part of the dashboard (camera, state, wake-up
  stages, then "after your drive: QR + STAGES takes it home") with a card;
  click = next, Esc = skip, 12 s untouched = next. No alerts during it.
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
- **Phone app look** (redesign part 1, `docs/REDESIGN_PLAN.md`): one flat
  dark page (#15131A), flat cards (#1F1C24, radius 20, no borders), one cream
  accent (#E8D7AE) for what matters, amber (#F2B66D) only for real warnings,
  no gradients, glass, glow or stars; one font, Pretendard (OFL,
  `frontend/fonts/pretendard.woff2`, cut down by `frontend/build/subset_font.py`,
  run it again after adding text with rare Hangul). The default Ollie is the
  flat one (`frontend/ollie/flat.svg`, from `assets/brand/ollie_flat_M.svg`;
  the other moods are still painted); the favicon is `frontend/ollie/icon.svg`.
  Home: "Right now" as one big word (깨어 있음 / 조금 피곤 / 졸림…), a cream
  sleepiness bar (KSS / 9), blinks/min and next rest (break_every_min), the
  last trip as one row, links to Live camera and the wake-up stages. Trips: a
  one-line summary and, opened, one sentence ("새벽 2시 38분, 추풍령휴게소
  지나서 두 번 졸았어요", `tripSentence` in dyn.js), cream route map and
  curve, then the numbers. Insights: leads with one finding ("새벽 2시가 가장
  위험해요") over the hourly chart with one cream bar. The 6-step phone tour
  still lands on each step (checked in KO and EN at 375×812).
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

- **Phone app redesign part 1 is built** (on `demo-booth`, 2026-11-07), see
  `docs/REDESIGN_PLAN.md`. **Not yet on the website**: waiting for the owner's
  OK (and the friend's, it's their design) before publishing to `gh-pages`.
  Part 2 (setup screens, Settings, Camera, maps, Ollie's moods) after 10 Nov.
- PR #5 (`demo-booth` -> `main`) is open: the friend should review it before
  it's merged. No CI on the repo.
- Compare `local-wip` with the friend's detection code.
- Check the sources for the "why we chose it" text (phone app stage cards).
- An old Wi-Fi profile called "hotspot" on the Pi (not Bamnun's) autoconnects.
- Try with several visitors in a row at the real booth.

## Log (newest first)

- 2026-11-11: **booth film tested on the Windows PC**: `booth_film.ps1 -Test` plays full screen on the game monitor (1920x1080) and goes back to ETS2 at the end, on a click and on Esc; Booth guard (desktop shortcut) starts the player. Sound not confirmed by ear yet. Fixes: Tailscale SSH to the Pi can ask for a browser sign-in check (`login.tailscale.com/a/...`), which made the first-start fetch hang silently; ssh/scp now have a time limit and the link is logged, copied and shown. Esc was swallowed (the Alt tap that brings the film forward leaves WPF in menu mode); the timer now reads Esc from the keyboard. Approve a Tailscale check while its ssh is still waiting, or it doesn't count.
- 2026-11-11: **the film now plays on the booth PC's game monitor**, not the Pi (over RealVNC + spacedesk it stuttered). `tools/booth/windows/booth_film.ps1` (started hidden by Booth guard; or run by hand, `-Test` plays once, `-Setup` re-fetches) polls Supabase `take_film_commands` every 1 s. ▶ 영상 재생 = the film full screen over ETS2 with sound (WPF MediaElement, no install); ■ 영상 정지, its end, a click or Esc = back to the game. First start fetches `config.txt` (SUPABASE_URL / ANON_KEY / STAFF_CODE from the Pi's frontend/.env) and `film.mp4` (the Pi's `assets/booth/film_pc.mp4` = `bamnun_film_ko_v2_bigsub.mp4`) over `ssh inpi` into %APPDATA%\BamnunFilm (log: film.log there). Supabase: `take_commands` skips video/video_stop, new `take_film_commands` takes only those (run 2026-11-11, in supabase/booth_remote.sql). The guard allows the powershell window titled "Bamnun film". The Pi's own film loop is off (`film: on_pi: false` in config/default.yaml). Not yet run on the Windows PC.
- 2026-11-11: booth flow change (judges read the poster rather than play): **the film plays on the Pi screen while nobody is driving** (`film.py`, muted loop of `assets/booth/film.mp4`; the files are copied by hand to the Pi, not in git; made from v2 as 1280x720 no-audio mp4 + `film.wav`). Remote **▶ 영상 재생** = from the start with sound (`aplay film.wav`; at the end it goes back to the muted loop if the seat is empty), **■ 영상 정지** = film off; a click on the Pi window also stops it. **No standby/briefing any more**: a face no longer starts anything; NEXT PERSON (remote, space, n, the button) goes straight to calibration, drawn as the camera full screen with the oval, one instruction, hint and progress (`Screens.calibrating_full`). Nothing goes off on its own while the film plays (`_alerts_allowed`). Remote commands `video`, `video_stop` (remote.py, staff.html, gh-pages updated). Supabase CHECK on `booth_commands.cmd` widened (done 2026-11-11; SQL kept in `supabase/booth_remote.sql`: `alter table public.booth_commands drop constraint if exists booth_commands_cmd_check; alter table public.booth_commands add constraint booth_commands_cmd_check check (cmd ~ '^(stage[0-4]|next|calibrate|photos_off|photos_on|vol_up|vol_down|voice|video|video_stop)$');` in the SQL editor). The Pi's film is now Fable's large-Korean-subtitle cut (`bamnun_film_ko_v2_bigsub.mp4` → 1280x720 film.mp4 + film.wav).
- 2026-11-11: product film v2 (`video/`): 75 s, one container that morphs between scenes, the real case photo as the hero, the real prototype and booth photos (on this Mac only, in `video/.gitignore`), a code-drawn infrared face with a triangulated mesh that drives the three readouts and the 1-9 score, stages shown on the device with its real slow chime, recorded stage-3 warning and alarm. One timeline for picture, subtitles and sound: `python3 make_timeline.py` → `timeline.json`, then `.venv/bin/python make_audio.py`, `node render.js frames` (or `sheet`/`review`/`frames 52 56`), ffmpeg (crf 21). Five narration lines rewritten (`script.json`: s06, s07, s09, s10, s14). Plan, changes and critique scores in `video/BRIEF_v2.md`. Outputs (not in git): `video/bamnun_film_ko_v2.mp4` and `_silent`. Not done: the 9:16 cut. The poster in the wide booth photo says 76% where the film says 약 70%.
- 2026-11-10: product film (`video/`): 66 s, Korean narration by Ollie (Supertonic M1, `make_narration.py`), Korean + English subtitles, real app captures from the live site (`capture_app.js`), code-drawn scenes in one HTML timeline (`index.html`, `render.js` → Playwright frames → ffmpeg), soundtrack `make_audio.py` (pad, UI sounds, the device's chime/alarm). Plan and beat sheet in `video/BRIEF.md`. Outputs (not in git): `video/bamnun_film_ko.mp4` and a silent copy. The device shot is a drawn placeholder until a photo is added.
- 2026-11-10: the Pi's headless screen is now 1280x800 landscape (a Samsung tablet held sideways as the laptop's second screen via spacedesk, showing RealVNC). Bamnun then uses its normal wide dashboard, not the tall layout. Change back with `wlr-randr --output NOOP-1 --custom-mode 720x1200` (and in ~/.config/labwc/autostart).
- 2026-11-10: tall layout redone to the owner's sketch: the camera on top and ONE panel under it filling the rest (`viz.column_compose`, `panel_size`): standby words while the seat is empty, the driver's data (state, eyes, system response, enlarged) while driving, and the visitor's QR as big as the panel once it works. The QR shows only when the drive is on the server (`Visit.ready`), after `learn_more.qr_after_s` (40 s) of driving, and gives way to the data while an alert is up. Only the camera part (SETTINGS) is clickable in the tall layout. The Mac's scratch test venv is gone: tests were run in a scratch copy on the Pi (/tmp/bt).
- 2026-11-10: one rule for anything going off on its own (`Monitor._alerts_allowed`): only while a visitor is driving: never while waiting (seat empty), during the next person's guide or calibration, on booth screens, or 8 s after one. Covers the ladder, the distraction chime, rest/CO2 voice prompts and "are you OK?". The staff remote and stage cards still fire on demand.
- 2026-11-10 (exhibition day): the test/showcase mist (stage card 2, the remote's 2, the device test) now runs 6 s instead of 2 s (`control.MIST_TEST_S`); the 2 s pulse barely got the disc misting. Real alerts were already 10-20 s.
- 2026-11-09: Booth guard (`tools/booth/windows/booth_guard.ps1`, desktop shortcut "Booth guard"): runs Booth layout, then only ETS2 and RealVNC can be used; anything else in front gets a full-screen lock (Back to the game / staff PIN), Windows keys, Alt+F4, Ctrl+Esc, Ctrl+Shift+Esc blocked. PIN unlocks 10 min. PIN chosen at first start, salted hash in %APPDATA%\BamnunBoothGuard (not in git). No Windows settings changed; Ctrl+Alt+Del always works. Booth layout also removes the RealVNC window's title bar (and its X) until that window is closed; `-KeepVncTitleBar` skips it.
- 2026-11-09: Windows split screen: `tools/booth/windows/booth_layout.ps1` (desktop shortcut "Booth layout") puts ETS2 on the left ⅔ and the RealVNC window showing the Pi on the right ⅓, in real pixels at any scaling (owner confirmed it works with the Pi connected). Snap failed on the owner's PC because ETS2's window was 1920×1080 on a 1920×1080 screen (125% scaling); its config.cfg is now 1280×980 (backup `config.cfg.before-booth`). Owner's new Windows PC set up: Git, Node, Tailscale (`ssh inpi` works via Tailscale SSH), RealVNC Connect Viewer 8.6 (the old "VNC Viewer" winget package 404s).
- 2026-11-09: full screen on Android: the remote has a ⛶ 전체 화면 button (Fullscreen API) and bigger buttons on tablets; both pages have app manifests (`frontend/build/pwa/`: app.webmanifest, staff.webmanifest, icons, `display: fullscreen`), so Chrome ⋮ > 홈 화면에 추가 / 앱 설치 opens them with no browser bars. The remote remembers its staff code (localStorage) so the installed app works without ?k=. build.py copies pwa/ into www; publish all of www/ to gh-pages.
- 2026-11-09: website: on any touch screen (unfolded foldables, tablets, phones sideways) the app fills the screen with no phone frame: the 390-wide layout scales up to 1.6x and is centred on the app's own background (`fit()` in shell.html). Only desktop browsers still show the framed phone.
- 2026-11-09: docs/NEW_SESSION.md, a brief for a Claude Code session on another computer.
- 2026-11-07: booth remote: a staff phone controls the Pi without touching the laptop. Page `staff.html?k=<STAFF_CODE>` (frontend/build/staff.html, published next to the website): stages 1-4, 0 = all off, next person, recalibrate, photos off/on, volume, voice. Mailbox `booth_commands` in Supabase (supabase/booth_remote.sql, run with the real code; the code is NOT in git: it's in the Pi's frontend/.env as STAFF_CODE and in the staff link). The Pi polls every 1 s (`remote.py`), commands older than 15 s are dropped. Needs the Pi online.
- 2026-11-07: QR always on the dashboard (middle bottom card; under the camera in a tall window), no pop-ups/hints over the camera (the team explains and asks consent in person). Each visitor gets a code when their guide starts (`Visit.begin`); from calibration the drive is sent every 15 s and once more when they leave: the Pi records the yes in `visit_consents`, then `put_visit` (supabase/booth_consent.sql, run and tested). SETTINGS > PHOTOS: OFF (p) for someone who says no to photos. The website waits (up to 10 min) for a drive scanned early and refreshes it every 20 s. GUIDE is gone from the menu.
- 2026-11-07: no standby screen and no slideshow: the dashboard stays up; 30 s with nobody = visitor forgotten; the next face (3 s) starts their guide = one page (fit your face in the oval; moves on when green 2 s) → calibration → live hints on the dashboard in the pop-up's place with the part outlined (운전해 보세요 / 지금 졸음 상태예요 / 눈을 보고 있어요; each alert explained when it fires, "1단계: 파란 불빛"…; "잘했어요" then the QR offer). The 'click Drive' page is gone (the team helps). GUIDE replays the hints. Old standby/briefing/tour code remains but is unused.
- 2026-11-07: fewer clicks: standby starts the briefing by itself 3 s after someone sits, pages turn by themselves (7 s; the centring page once the face fits the oval 2 s, at most 14 s), the last page starts calibration, the tour moves every 6 s; clicks still skip ahead. Standby is the big live camera + lines fading in and out (no owl); briefing pages and calibration show the live camera (calibration with the face oval). docs/LAPTOP_NAV_PROMPT.md: a prompt for the laptop's Claude Code to make switching between the game and Bamnun easy.
- 2026-11-07: laptop dry run worked (RealVNC over the cable, game ⅔ / Bamnun ⅓). Fixes: one sound at a time (wake-up sounds cut in, tips/cues skip if busy); `alerts.face_lost_alerts: false` (an unseen face sets off nothing); the sleepy tip only with a face and no alert; the Pi's headless screen is 720x1200 at every start (`~/.config/labwc/autostart`, copy in tools/booth/labwc_autostart). Recalibrate after moving the camera for the laptop.
- 2026-11-07: laptop setup: VNC on the Pi (wayvnc :5900), cable profile `bamnun-laptop` (Pi = 10.43.0.1, DHCP, no route/DNS), Bamnun auto-switches to a tall layout (stacked dashboard and slides, arrow left) when its window is taller than wide; docs/LAPTOP_SETUP.md.
- 2026-11-07: website published with redesign part 1 + walkthrough for everyone; fixed the app frame sliding out of place on phones (the walkthrough's scrollIntoView scrolled the stage/phone frame; now only `.screen` scrolls, and `BN_UNSCROLL` in shell.html snaps the frame back).
- 2026-11-07: dashboard buttons folded into one SETTINGS menu (bottom-right of the camera); phone walkthrough for every website visitor (not only with a personal code; not published yet).
- 2026-11-07: phone app redesign part 1 built (flat colours, Pretendard, flat Ollie, Home/Trips/Insights/Stages layouts); website not updated yet.
- 2026-11-07: redesign plan + flat Ollie drafts (docs/REDESIGN_PLAN.md, assets/brand/); not built yet.
- 2026-11-07: visitor drive + photos to their phone (consent, Supabase, own QR), history on real Korean routes, phone tour; Pi tour 4 steps.
- 2026-11-07: face-centring page, sleepy tip while driving, guided tour, Korean voice + toggle, blue light off on time.
- 2026-11-06: nothing interrupts the booth screens; hover highlights on every button and card.
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

_Last updated: 2026-11-09._
