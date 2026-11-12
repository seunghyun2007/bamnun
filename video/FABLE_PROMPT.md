# Prompt: make the 밤눈 product film (v2) with Fable

Open Claude Code in `~/Downloads/bamnun/video`, choose **Fable**, set effort
to **high** (or max), and paste everything in the box below.

```text
You are the director, motion designer, sound designer and render engineer
for a 60–75 second product film made entirely in code, in Korean.

FILM IN ONE LINE
A calm, premium Korean product film where Ollie, the owl who is the voice of
our device, explains why night drivers doze off and how 밤눈 (Bamnun) wakes
them in four gentle steps, ending at our booth's QR code. Go all out: this is
our team's show reel for a university exhibition (창보고 전시회) and the
final competition on 24 Nov 2026. We are foreign students, so the film has to
present the product for us, in Korean.

THE PRODUCT (facts only, don't invent features)
- 밤눈 is a drowsiness monitor for night drivers: a Raspberry Pi 5 in a matte
  black 3D-printed case with a cream owl logo, an infrared camera, a blue
  light, a mint mister, and a speaker.
- It reads the face and eyes in the dark (face mesh: eye closure, blinks,
  head drops) and turns them into a live drowsiness score (1–9).
- Four wake-up stages, only as needed: 1 파란 불빛 (soft blue light),
  2 민트 미스트 (cool mint mist), 3 차임과 목소리 (chime + Ollie's voice),
  4 알람 (rising alarm).
- A phone app shows drives on real routes, when you get sleepiest, and what
  woke you.
- At the booth, visitors drive a truck game with a wheel; their own QR code
  takes their drive home to their phone.
- Statistic (verified, keep the source on screen): 한국도로공사에 따르면 최근
  5년간 고속도로 사망 사고 원인의 69.8%가 졸음 등 주시 태만 (서울신문
  2022.9.27). Say "약 70%".

WHAT ALREADY EXISTS IN THIS FOLDER (read all of it first)
- BRIEF.md: the v1 brief, style guide and beat sheet. Keep its rules.
- script.json + audio/s01..s15.wav + audio/durations.json: Ollie's Korean
  narration lines (Supertonic voice M1, the device's own voice). You may
  rewrite lines; regenerate with `.venv/bin/python make_narration.py <ids>`
  (the "say" field is what is spoken, e.g. numbers written out in Korean).
- assets/: device.png (a clean product shot of the case, 2048², white
  background: cut it out or place it on a light panel; it's the hero shot),
  app_home/app_trip/app_insights/app_stages.png (real captures of the phone
  app, 390×844 @3x; recapture with `node capture_app.js` if needed),
  hello/sleepy/wake/driving/thinking/celebrate.webp (Ollie's poses),
  ollie_flat_M.svg (flat Ollie for the end card), game_drive.jpg (the truck
  game at the booth), qr_site.png (the website's QR).
- index.html + render.js + make_audio.py: v1 pipeline. One HTML page with a
  deterministic window.render(t); `node render.js stills 3 8 15` for test
  frames; `node render.js frames` renders 30 fps JPEGs; make_audio.py builds
  audio/mix.wav; ffmpeg joins them (see HANDOFF.md log). v1 output:
  bamnun_film_ko.mp4. Watch v1's frames (check/, stills/) and beat it.
- Fonts: ../frontend/fonts/pretendard.woff2. Real sounds: ../assets/chime.wav,
  ../assets/looming.wav (the device's own alarm).
- Tools on this Mac: node + playwright (chromium installed), ffmpeg,
  .venv with supertonic + numpy. Use them; no paid APIs, no new accounts.

LOOK AND FEEL (hard rules)
- Palette: night #141218, panel #1F1C24, line #2E2A33, text #F2EEE8,
  muted #9A93A0, cream #E8D7AE (the case's logo colour). Colour only where it
  is physical: blue light #4C7DFF, mint #8FE3C8, alarm amber #F2B66D.
- Korean first, big and confident (Pretendard 700–850). English small and
  muted under it. Burned-in subtitles of every narration line (Korean 44px +
  English 26px) so the film works muted on the booth tablet.
- Calm, premium motion: ease-out entries, one idea per shot, a single
  container that morphs between states instead of hard cuts where you can.
  Numbers count, lights ramp on, Ollie gently sways (he may bounce once).
- Banned: gradient backgrounds, neon text glow, centred text on a gradient,
  stock icons, emoji, fake UI. Product screens are real captures only.
- Ollie keeps his whole body (a head alone reads as a cat).

STRUCTURE (keep the story, improve the craft)
Hook (night road, eyes closing, "단 1초") → the 70% statistic with source →
meet 밤눈 (device.png hero shot) and Ollie → how it sees (IR face mesh, eye
closure, blinks, head drop) → the live score → the four stages, each synced
to its real sound → the phone app (real screens, route map, insights) → the
booth + QR → end card "밤눈 · 밤길엔, 밤눈." Total 60–75 s, 1920×1080, 30 fps.

SOUND
Ollie's narration on top; an original soft pad/music bed synthesized in code
on the same timeline (keep it under the voice); UI sounds synthesized in code
(tick on chips, whoosh on container morphs, soft thump on the logo); the
device's real chime and alarm on stages 3 and 4. Retime the picture to the
narration and to the beats, not the other way round.

WORKFLOW GATES (stop and show me at each)
1. Read everything, then write BRIEF_v2.md: what you'll change from v1 and
   why, and a beat table (time, picture, Korean line, English line, sound).
   Wait for my OK.
2. Render 12–16 stills across the film and show them as a contact sheet.
   Wait for my OK.
3. Full render to bamnun_film_ko_v2.mp4 (+ a silent copy for the tablet).

CRITIQUE LOOP (before showing me the final)
Extract a frame every 0.5 s, review them, and score 1–10: Korean legibility,
story clarity, motion quality, sync to voice and sound, brand fidelity, and
"doesn't look AI-generated". Fix anything under 8 and re-render; repeat until
every score is 8+. Report the scores per round.

DELIVERABLES
- bamnun_film_ko_v2.mp4 (with sound) and bamnun_film_ko_v2_silent.mp4
- an optional 9:16 1080×1920 cut (bamnun_film_ko_v2_vertical.mp4)
- BRIEF_v2.md and the updated code, committed to the demo-booth branch with a
  line in ../HANDOFF.md (don't commit mp4s, frames or .venv/node_modules).
```
