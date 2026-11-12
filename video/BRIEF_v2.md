# 밤눈 product film v2: brief and beat table

**Film in one line:** Ollie, the voice of the device, explains why night
drivers doze off and how 밤눈 wakes them in four gentle steps, ending at our
booth's QR code. About 72 s, 1920×1080, 30 fps, Korean first.

All v1 rules stay (BRIEF.md): palette, Pretendard, colour only where it is
physical, burned-in Korean 44 px + English 26 px subtitles, no gradients, no
text glow, no stock icons, no fake UI, Ollie always whole.

## What v1 got wrong, and what v2 does about it

| # | v1 problem (seen in check/sheet.jpg) | v2 change |
|---|---|---|
| 1 | Every scene is a hard fade through black, so the film reads as nine slides. | **One container.** A single rounded panel lives through the whole film and morphs: windshield → statistic card → light product table → the case's camera window → IR view → score → stage panel → phone → QR card → end mark. Only two true cuts (the eyelid black-out, and the push into the camera window). |
| 2 | The device is a drawn placeholder. | **The real photo is the hero.** device.png sits on a light panel (#F2EEE8) with multiply blending, so its white studio background and soft shadow become the panel. Slow 4% push-in, then the camera pushes *into the case's camera window* and comes out in the infrared view. That one move explains where the camera is. |
| 3 | The "face" is a grey egg with random dots. | **A real mesh, drawn in code.** A symmetric landmark set (face oval, brows, eyes, nose, mouth), triangulated, cream hairlines over a monochrome IR frame with sensor grain. The eyes really close, blink and the head really nods, and three live readouts move with them: 눈 감김, 깜빡임, 고개 떨굼. No colour here: infrared is grey. |
| 4 | The score is a lone bar on an empty frame. | The IR view stays on screen, shrinks left, and the **score is driven by the face**: as the eyelids get heavy the 1–9 scale climbs and its label changes 깨어 있음 → 졸림 → 위험. The scale is drawn like the real app's "졸음 정도 n / 9" strip. |
| 5 | Four numbered circles; nothing physical happens. | **The stages happen to the device.** The photo returns, small, on a dark panel; a four-step ladder sits beside it. 1: blue light blooms from the case and tints the panel. 2: mint mist drifts up from the case. 3: the real chime, then a speech bubble with a waveform driven by Ollie's actual audio. 4: amber rings pulse at the real alarm's 3 Hz while its level rises. Each stage's Korean name is 96 px. |
| 6 | Content fills about half the frame; type is small. | Bigger type (headlines 96–132 px, the 70% at 420 px), content fills the 1920 frame to a 120 px margin, one idea per shot. |
| 7 | The phone is small, off to the side, and cross-fades. | Phone at 92% of frame height. The **real captures scroll and slide** like the app (home → trip with the route line → insights). The route line and the drowsiness peak get a cream call-out line with a large Korean label outside the phone, never drawn on top of the capture. |
| 8 | The lane dash runs through the subtitle; the hook is dim. | Subtitles get a solid night band (no gradient); the road has headlight reach, roadside posts and a horizon for speed; the lids close with a slow blink, a second heavier one, then black exactly on "단 1초". |
| 9 | Sine-wave pad, sounds placed by hand at fixed times. | **One timeline file** (timeline.json) drives picture, subtitles and sound, so they cannot drift. New bed at 80 BPM: warm detuned pad, soft sub pulse, a sparse felt-piano motif that resolves on the end card; side-chained 6 dB under the voice. Ticks on chips, filtered whoosh on morphs, soft thump on the logo. Music drops out under the black-out and under the alarm. |
| 10 | The booth shot is the game's garage menu with the game's own UI on it. | Crop to the truck (no menu bar), inside the container, with the QR card as the large, bright object. See open question 2. |

## Narration changes (Ollie, Supertonic M1; regenerate only the changed ids)

| id | v1 | v2 | Why |
|---|---|---|---|
| s06 | 이 신호들을 모아 지금 얼마나 졸린지 점수로 알려 줘요. | 이 신호들을 모아, 지금 얼마나 졸린지 1부터 9까지 점수로 알려 줘요. | names the real scale |
| s07 | 졸음이 느껴지면, 네 단계로 깨워요. | 졸음이 쌓이면, 필요한 만큼만, 네 단계로 깨워요. | "only as needed" is the product's idea |
| s09 | 다음은 시원한 민트 향. | 다음은 시원한 민트 미스트. | matches the stage's name |
| s10 | 그래도 졸리면 제가 직접 말을 걸고, | 그래도 졸리면 차임이 울리고, 제가 직접 말을 걸어요. | stage 3 is chime + voice |
| s14 | 지금 부스에서 직접 체험해 보세요. QR 코드로 내 운전 기록도 받을 수 있어요. | 지금 부스에서 트럭을 직접 운전해 보세요. QR 코드로 내 운전 기록도 가져갈 수 있어요. | says what visitors do |

Other lines are unchanged. Times below use measured durations for kept lines
and estimates for rewritten ones; after regenerating I retime the picture to
the real durations and snap scene changes to the 0.75 s beat grid.

## Beat table

| Time (s) | Picture | Ollie (Korean) | English subtitle | Sound |
|---|---|---|---|---|
| 0.0–5.9 | **Hook.** The container is a windshield: night highway, dashes and posts rushing, headlight reach. Eyelids: a slow blink, a heavier one, then shut. On black, "단 1초" (132 px cream), small "just one second". | s01 밤길 운전, 가장 위험한 순간은 눈이 감기는 단 1초예요. | Night driving: the most dangerous moment is the one second your eyes close. | road hum, pad fades in; everything cuts to silence on the black-out, one low thump on "단 1초" |
| 5.9–12.2 | **Statistic.** The black opens into a panel. "70%" counts 0 → 70 (420 px). Above: 고속도로 사망 사고 원인. Below: 졸음 · 주시 태만. Source line stays on screen the whole shot: 출처: 한국도로공사, 최근 5년 고속도로 사망사고 원인 69.8% (서울신문 2022.9.27). | s02 고속도로 사망 사고 원인의 약 70%가 졸음과 주시 태만이에요. | About 70% of fatal highway crashes come from drowsiness and inattention. | whoosh in; fine ticks while counting, one tick on 70; pad enters |
| 12.2–16.0 | **Meet 밤눈.** The panel turns light and widens; the real device photo settles onto it with its own shadow, slow push-in. Left: "밤눈" 132 px, small "Bamnun · night-drive drowsiness monitor". | s03a 그래서 저희가 밤눈을 만들었어요. | So we built Bamnun. | whoosh on the morph, soft thump as the device lands; piano motif begins |
| 16.0–19.0 | **Meet Ollie.** Ollie (hello pose, whole body) hops in beside the device, one bounce, then sways. Label: 올리 · 밤눈의 운전 친구. At 18.2 the camera pushes into the case's camera window. | s03b 저는 밤눈의 운전 친구, 올리예요. | I'm Ollie, your night-driving companion. | soft pop on the hop; whoosh on the push-in |
| 19.0–23.4 | **How it sees.** We come out inside the infrared view: a grey driver's face in the dark, sensor grain. The mesh draws on from the nose outward. Headline: 어둠 속에서도 얼굴과 눈을 읽어요. Tag: 적외선 카메라. | s04 적외선 카메라가 어둠 속에서도 얼굴과 눈을 읽어요. | An infrared camera reads your face and eyes, even in the dark. | quiet shimmer as the mesh draws on |
| 23.4–29.6 | Three readouts appear one by one, each demonstrated by the face as Ollie says it: lids half close (눈 감김, a bar fills), two blinks (깜빡임, counter ticks), the head nods (고개 떨굼, angle line tilts). | s05 눈이 얼마나 감겼는지, 얼마나 자주 깜빡이는지, 고개가 떨어지는지까지요. | How closed your eyes are, how often you blink, whether your head drops. | tick on each readout, on the word |
| 29.6–35.2 | **Score.** The IR view shrinks left; the three readouts flow into one scale, 1–9. The face grows drowsy and the number climbs 1 → 3 → 6, label 깨어 있음 → 졸림. Headline: 지금, 얼마나 졸린지. | s06 이 신호들을 모아, 지금 얼마나 졸린지 1부터 9까지 점수로 알려 줘요. | Together they become a live drowsiness score, from 1 to 9. | whoosh on the morph; soft rising tone with the number |
| 35.2–39.0 | **Four stages.** The panel goes dark; the device photo returns on its light tile, left. Right: a four-step ladder (파란 불빛 · 민트 미스트 · 차임과 목소리 · 알람), all dim. Headline: 필요한 만큼만, 네 단계로. | s07 졸음이 쌓이면, 필요한 만큼만, 네 단계로 깨워요. | When drowsiness builds, I wake you in four steps, only as far as needed. | whoosh; four quiet ticks as the steps appear |
| 39.0–41.2 | **1 파란 불빛.** Blue light ramps on at the case over 0.3 s and tints the panel; step 1 lights; big "파란 불빛", small "soft blue light". | s08 먼저 은은한 파란 불빛. | First, a soft blue light. | soft low "on" tone with the ramp |
| 41.2–43.4 | **2 민트 미스트.** Mint mist drifts up from the case and thins out; step 2 lights. | s09 다음은 시원한 민트 미스트. | Then a cool mint mist. | airy filtered-noise puff |
| 43.4–47.8 | **3 차임과 목소리.** The real chime rings first, a ring expands from the case; then a speech bubble with a waveform that follows Ollie's real audio; step 3 lights (cream). | s10 그래도 졸리면 차임이 울리고, 제가 직접 말을 걸어요. | Still sleepy? A chime rings, and I talk to you. | **the device's real chime** (assets/chime.wav) at 43.5, in the clear, then the line |
| 47.8–51.6 | **4 알람.** Amber rings pulse at 3 Hz and grow with the alarm's level; step 4 lights; after the line the alarm plays alone for about 2 s, then everything settles. | s11 마지막엔 알람이 울려요. | And finally, an alarm. | **the device's real alarm** (assets/looming.wav), rising, music ducked out |
| 51.6–56.0 | **App.** The panel becomes the phone (real capture, 92% of frame height): Home ("깨어 있음", 졸음 정도 1/9), then it slides to the trip 서울 → 강릉 and the route line is traced. Headline left: 운전 기록, 실제 경로 위에. | s12 휴대폰 앱에서는 운전 기록과 졸음 패턴을 볼 수 있어요. | The phone app shows your drives and your drowsiness patterns. | whoosh on the morph; soft swipe; tick on the call-out |
| 56.0–60.2 | The trip scrolls to the drowsiness graph (call-out: 새벽 2시 43분, 한 번 졸았어요), then slides to Insights (call-out: 밤 12시가 가장 위험해요). | s13 언제 가장 졸린지, 무엇이 나를 깨웠는지까지요. | When you get sleepiest, and what woke you up. | swipe, two ticks |
| 60.2–67.6 | **Booth.** The phone screen turns into the white QR card (large, right). Left: the truck game image in the container, headline 부스에서 트럭을 직접 운전해 보세요; under the QR: 내 운전 기록 받기. Ollie (driving pose) in the corner. | s14 지금 부스에서 트럭을 직접 운전해 보세요. QR 코드로 내 운전 기록도 가져갈 수 있어요. | Drive the truck here at the booth, and scan the QR code to take your drive home. | whoosh; tick as the QR lands; music lifts |
| 67.6–72.5 | **End card.** The QR card shrinks to the corner and stays readable; flat Ollie (whole body) rises, "밤눈" 180 px cream, "밤길엔, 밤눈." under it; small "2026 창보고 전시회". Hold 2.5 s for the loop. | s15 밤길엔, 밤눈. | For night roads: Bamnun. | soft thump on the logo; piano resolves; pad tail |

## Motion and layout rules for v2

- Entries: cubic ease-out 0.5–0.8 s, rise 24 px. Container morphs: 0.7 s
  ease-in-out on position, size, corner radius and fill together.
- Nothing moves while a number is being read, except the number.
- Ollie sways ±3° and bounces exactly once, on his entrance.
- Subtitles: one line of Korean where possible, on a solid night band;
  nothing else enters the bottom 190 px.
- Everything is a pure function of `t` (no CSS animations, seeded noise), so
  stills and the full render are identical.

## Pipeline changes

- `timeline.json` is written once by `render.js` from script.json + measured
  durations + a beat list; `index.html` and `make_audio.py` both read it.
- `index.html?layout=v` gives the 1080×1920 cut as a real re-layout (stacked,
  not a crop); rendered after the 16:9 film is approved.
- Waveform (stage 3) and alarm level (stage 4) are precomputed from the wav
  files into `audio/envelopes.json` so the picture follows the real sound.
- Outputs: `bamnun_film_ko_v2.mp4`, `bamnun_film_ko_v2_silent.mp4`,
  `bamnun_film_ko_v2_vertical.mp4`. Not committed: mp4s, frames, stills.

## Changes after gate 1 (11 Nov)

- Real photos (kept on this Mac only, in .gitignore) are used as photos:
  crop, slow zoom or pan, small tags only.
  - `device_real.jpg`: a new beat right after the hero shot and Ollie
    (18.3–21.4 s), tagged 적외선 카메라 · 적외선 LED · 민트 미스터 · 스피커.
    The camera then pushes into its lens and comes out in the infrared view.
  - `booth.jpg`: the real mist in stage 2 (42.5–44.8 s), and the close shot of
    the booth scene (visitor at the wheel, game, 밤눈 on the tablet).
  - `booth_wide.jpg`: opens the booth scene, cropped left of the neighbouring
    poster, panning from our poster down to the table.
- Stage 3 now plays the device's real slow chime (`assets/chime_slow.wav`,
  the file the device uses for stage 3) and then its recorded warning
  (`assets/voice/ko/stage3.wav`: "눈이 감기고 있어요. 쉴 곳을 찾아봐요."),
  subtitled in cream as a quote, with a waveform that follows the recording.
- Length is 75.0 s. Final times are in `make_timeline.py` (the one timeline
  for picture, subtitles and sound); the beat table above is the plan, the
  timeline is the truth.
- The phone is 77% of frame height, not 92%, so it stays clear of the
  subtitles.
- The QR is the website's QR, so its label is "밤눈 앱 바로 가기".

## Critique loop (a frame every 0.5 s, scored 1-10)

| | Korean legibility | Story clarity | Motion | Sync to voice and sound | Brand fidelity | Doesn't look AI-generated |
|---|---|---|---|---|---|---|
| Round 1 | 8.5 | 8 | 7.5 | 7 | 9 | 8 |
| Round 2 | 9 | 9 | 8 | 8.5 | 9 | 8 |

Round 1 fixes: eyelids became a smooth ellipse (they looked polygonal) and
shut on the spoken "단 1초" (0.35 s earlier); the 70% lands on "칠십" and
"졸음 · 주시 태만" appears when it is said; the app call-outs follow the
narration's order (route, the doze and what woke you, the sleepiest hour);
blue hands over to amber at stage 4; the container's fill changes late in a
morph instead of passing slowly through grey; the source line is 28 px.
Round 2 fix: the device's alarm was at -31 dB because its recording rises
over 4 s; the film now plays its louder 1.4-4.0 s (about -17 dB).
Sync was judged from cue times and measured levels, not by ear.

Not done: the optional 9:16 cut.

## Open questions

All three from gate 1 are settled: device.png is restored, the booth photos
replace game_drive.jpg, and the stage-3 warning is in. Still open: the booth
poster in booth_wide.jpg shows 76% where the film says 약 70% (69.8%).
