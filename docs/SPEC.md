# Bamnun app — spec

How the Bamnun phone app and the Raspberry Pi backend should behave. This is the source of truth: build to it, and update it when a decision changes.

Status: draft v2 (Android and iOS from the start). Sections 0–2 apply to everything; sections 3–9 are features, built one at a time in the order of section 10. Section 12 lists every place the two platforms differ, and what needs a Mac.

---

## 0. Architecture

- **The Pi does the safety work on its own.** Camera, detection, and the four-stage wake-up ladder (blue light → mint mist → chime + voice → rising alarm) all run on the Pi and keep working if the phone is off, locked, or out of range.
- **The phone app is a Capacitor app** built from `frontend/`, for **Android and iOS from the start**, with one shared codebase. Only plugins that support both platforms are used. Where a platform can't do what this spec asks, section 12 says what happens instead.
- **Phone ↔ Pi link**
  - Bluetooth LE is used only to find a nearby Bamnun and set it up (see section 7).
  - Live data and commands go over the Pi's own Wi-Fi hotspot. A FastAPI server on the Pi gives a REST API for settings and trips, and a WebSocket at `/ws` for live data and events.
  - The same server also serves the built app at `/`, so any browser on the Pi's network can open it without installing anything. This is for development and demos; drivers use the Capacitor app.
  - **Camera video only ever goes to the driver's phone, over the Pi's own Wi-Fi, and never online.** The Pi streams it only while the Camera screen is open, with the tracked eye outlines drawn on top, and encodes nothing when nobody is watching. Everything else is numbers. Video is never recorded or uploaded, and Supabase sync will never include it. When there's no video (the simulated device, or the stream fails), the Camera screen falls back to a drawing whose eyes follow the measured eye openness.
  - Until the Pi runs its own password-protected hotspot, anyone on the same Wi-Fi network as the Pi can open the video. Don't run `--serve` on a shared network with a driver in view.
  - The server runs on its own thread, and only reads what the camera loop publishes. If the server fails, or a phone is slow, detection and the ladder carry on unaffected.
- **Storage**
  - The Pi is the master copy of the driver profile and settings, in SQLite (`runs/bamnun.db`), so the device behaves correctly without the phone.
  - The phone keeps a cached copy in Capacitor Preferences so screens load instantly, and pushes changes to the Pi whenever it's connected.
  - Supabase comes later, for cloud sync of trips.
- **Language**: every user-facing string, notification and voice line exists in English and Korean, and follows the app language setting.

## 1. Phone ↔ Pi protocol (shared by all features)

REST (JSON):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | device id, firmware version, parts status, calibrated yes/no |
| GET / PUT | `/api/profile` | name, owl name, vehicle, work week, voice language, app language |
| GET / PUT | `/api/settings` | ladder toggles, sensitivity, volumes, break interval |
| POST | `/api/calibration/start` · `/api/calibration/cancel` | guided calibration (section 6) |
| POST | `/api/say/{line}` | play one of Ollie's recorded lines on the device speaker, in the saved voice language |
| POST | `/api/test/{part}` | fire one part for the device test: `speaker`, `chime`, `blue_light`, `mist`, `alarm` |
| GET | `/api/trips` · `/api/trips/{id}` | trip history |
| GET | `/video` | live camera as MJPEG at up to the camera's frame rate (about 30 per second on a laptop webcam), 640 px wide, eye outlines drawn on. Encoded on its own thread, only while someone watches, so it never slows detection |

WebSocket `/ws`, server → phone messages (JSON with `type`):

- `snapshot` (5×/s): eye openness (`null` if no face), blink rate, PERCLOS, alert stage 0–4, CO₂ ppm + age, trip time. Every field:

  | Field | Meaning |
  |---|---|
  | `face` | a face is in view |
  | `eye_open` | eye openness as a fraction of this driver's calibrated open level (1.0 = normal); `null` with no face or while calibrating |
  | `eye_closed` | the eyes count as closed right now; `null` when not measured |
  | `blink_rate` | blinks per minute; `null` when not measured |
  | `perclos` | share of the last 60 s with the eyes closed, 0–1; `null` when not measured |
  | `last_blink_s` | length of the last normal blink, in seconds |
  | `microsleep` | the eyes have been shut for 0.5 s or more, right now |
  | `stage`, `stage_name` | wake-up ladder stage, 0–4, and its config name |
  | `level`, `level_name`, `score`, `kss` | drowsiness level, fused score 0–1, and the display-only KSS estimate 1–9 |
  | `drowsiness` | the same smoothed score as 0–100, for the Camera screen (section 13) |
  | `label` | the driver's state in one word, decided on the device so every screen and the laptop overlay agree: `alert`, `a_bit`, `drowsy`, `very`, `eyes_closed`, `away`, `no_face` (section 13) |
  | `signals` | the separate drowsiness signals and their share of the score, for the debug panel (section 14) |
  | `face_box` | where the face is in the video, as `[x, y, w, h]` fractions of the frame; `null` with no face. The Home tile crops the video to it |
  | `distracted`, `distraction_reason` | eyes-off-road channel |
  | `yaw`, `off_road` | head turn in degrees (negative = driver's left), and whether it's outside the safe zone |
  | `calibrated`, `calibrating`, `cal_progress` | calibration state; progress is 0–1 |
  | `co2_ppm`, `co2_age_s` | cabin CO₂, and how old that reading is; `null` without the sensor |
  | `trip_s` | seconds since monitoring started (until trips exist, a "trip" is one run of the Pi program) |
  | `fps` | camera frames processed per second |
  | `age_s`, `stale` | how old this snapshot is; `stale` is true after 2 s, meaning the camera loop has stopped sending |
  | `video` | the device has a camera picture to stream at `/video` (false on the simulated device) |
  | `video_size` | the camera's `[width, height]`, so the app can show the video in its real aspect ratio |

- `alert`: stage changed, with stage, reason and timestamp. Sent immediately.
- `calibration`: step changes and progress (section 6).
- `test_result`: a part's result.
- `trip`: started / ended, with summary.
- `emergency`: the driver hasn't responded after stage 4 (section 9b). Sent immediately.

The phone sends `hello` with its clock time and language on connect (the Pi has no reliable clock).

## 2. Ollie's voice: one speaker, two languages

- **Ollie speaks through the Bamnun device's speaker, always.** Every time the app plays Ollie's voice, the sound comes out of the device in the truck, not the phone:
  - previews while the driver is choosing something,
  - calibration instructions,
  - alerts and break reminders,
  - CO₂ prompts.
  The phone sends a command (`POST /api/say/{line}`) and the Pi plays it.
- **Two voice languages: English and Korean.** Each line exists as a recorded clip in both, in `assets/voice/en/` and `assets/voice/ko/`.
  - The voice language is chosen on the voice screen (section 6) and defaults to the app language.
  - It can differ from the app language. For example, the app can be in English while Ollie speaks Korean.
- **The clips are recorded by the team**, using `tools/record_prompts.py` extended with `--lang en|ko`, through the device's own mic. The repo already argues that a familiar human voice wakes people better than a synthetic one. Because the clips are fixed recordings, Ollie never says the driver's name out loud; the name appears on screen and in notifications.
- **The phone** shows a notification for every alert, with an owl hoot sound, in the app language.
  - Android: `owl_hoot.wav` in `res/raw`, on its own notification channel.
  - iOS: there are no channels. `owl_hoot.wav` is bundled in the app and set on each notification. It must be under 30 s, and the ring/silent switch mutes it.
  - The phone only receives alerts while the app can run. See "Drive mode" in section 12.

---

## 3. Name and owl name (screen 04)

**User sees**: two fields, "Your name" and "Your owl's name" (default "Ollie" / "올리"), and a Next button.

**Behaviour**
- Next is disabled while the driver's name is empty. Names are trimmed and limited to 20 characters.
- On Next:
  - save to phone Preferences;
  - `PUT /api/profile` if the Pi is connected, otherwise queue it and send on the next connect.
- The **driver's name** replaces "Siroj" everywhere: the Home greeting, the speech bubble, "You're all set, {name}!", Settings, and notifications ("{name}, your eyes are closing.").
- The **owl name** replaces "Ollie" everywhere: screen copy, notifications ("{owl} says…"), and Settings. Use one helper, `t(key, {name, owl})`, so no screen hard-codes either name.
- Editable later from Settings → profile card.

## 4. What do you drive (screen 05)

Every option is selectable and saved to `profile.vehicle`. The choice sets these defaults, all editable later in Settings:

| Vehicle | Alert volume | Break reminder | Camera setup hint |
|---|---|---|---|
| Long-haul truck | High (loud cab) | every 2 h, 15 min | mount 50–70 cm, high dashboard |
| Delivery truck | High | every 2 h | mount 50–70 cm |
| Bus or coach | Medium | every 2 h, 15 min | mount 50–70 cm |
| Taxi or van | Medium | every 2 h | mount 40–60 cm |
| My own car | Medium | every 2 h | mount 40–60 cm |

- 2 h / 15 min follows the Korean rule for commercial drivers (verify the exact law before quoting it).
- Volume maps to the Pi's chime, voice and alarm gain.
- The camera hint is shown during calibration (section 6), and its distance sets the focus preset in `config` (`lens_position`).

## 5. When do you work (screen 06)

**Layout, cleaned up**: title and subtitle, the **Days** row, a **Usual shift** preset row (Day / Evening / Night / Custom), and a **Starts / Ends** row. That's all. The bottom card (24 h timeline bar, legend, and "Your hardest stretch…") is **removed**.

**Behaviour**
- Days: tap to toggle. At least one day must be on for Next to work.
- Presets fill Starts and Ends. Tapping Starts or Ends opens a native time picker, which switches the preset to Custom.
- "My hours change every week" saves `shift: variable` and skips the times.
- Skip saves nothing and moves on.
- Saved to `profile.work = {days, start, end, variable}`. The Pi uses it to estimate hours awake for the rest prediction and the tired window.

## 6. Ollie's voice (screen 07, moved to after the device is connected)

There are no personality styles; Ollie has one voice and one way of talking. This screen only picks **which language Ollie speaks**.

**Position in onboarding**: this screen needs the device, so it moves to right after "Connect device" (screen 11) and before calibration. New order:

Welcome → Meet → Name → Vehicle → Work week → Wake-up ladder → Privacy → Permissions → Connect device → **Ollie's voice** → Calibrate → All set

**User sees**
- Ollie, a title ("How should Ollie talk to you?"), and two big cards: **English** and **한국어**, with a speaker button on each.
- Under them, a "Hear both" button.

**Behaviour**
- When the screen opens, Ollie greets the driver through the device speaker **once in Korean, then once in English**:
  - "안녕하세요! 저는 올리예요. 어떤 언어로 말할까요?"
  - "Hi! I'm Ollie. Which language should I speak?"
  - The matching card glows while each line plays.
- Tapping a card selects it and plays a sample line in that language on the device speaker:
  - "운전하는 동안 제가 지켜볼게요."
  - "I'll keep watch while you drive."
- "Hear both" replays the greeting.
- Saved to `profile.voice_lang`, both on the phone and on the Pi.
- If the device isn't connected, the cards still work, but show "Connect your Bamnun to hear Ollie", and nothing plays on the phone.
- Changeable later in Settings → Sound → "Ollie's voice language".

**Ollie's lines** (recorded in both languages; one set, no styles)

| Key | When | English | Korean |
|---|---|---|---|
| `greet` | voice screen opens | Hi! I'm Ollie. Which language should I speak? | 안녕하세요! 저는 올리예요. 어떤 언어로 말할까요? |
| `sample` | card tapped | I'll keep watch while you drive. | 운전하는 동안 제가 지켜볼게요. |
| `stage3` | stage 3, after the slow chime | Your eyes are closing. Let's find a place to rest. | 눈이 감기고 있어요. 쉴 곳을 찾아봐요. |
| `stage4` | stage 4, after the alarm | Wake up! Pull over now. | 일어나세요! 지금 차를 세우세요. |
| `rest_soon` | rest planner says stop soon | Plan a break in the next few minutes. | 몇 분 안에 휴식을 계획하세요. |
| `break_due` | break interval reached | Two hours in. Time for a break. | 두 시간 운전했어요. 쉬어갈 시간이에요. |
| `open_window` | CO₂ above 1500 ppm | The air is stale. Open a window. | 공기가 탁해요. 창문을 열어주세요. |
| `emergency_check` | emergency countdown starts | Are you OK? Say something or tap your phone. | 괜찮으세요? 휴대폰을 눌러주세요. |
| calibration lines | section 8 | see section 8 | see section 8 |

- **Phone notifications**: title = owl name, body = the same line in the app language, with the owl hoot sound.
  - Stages 1–2 (light and mint) don't speak. They only send a quiet notification: "A little light to keep you fresh" / "A breath of mint".

## 7. Permissions (screen 10) and finding the device (screen 11)

**Permissions**: three rows, each with a button that triggers the **real system prompt**.

| Row | Android permission | iOS permission | Why (shown to user) |
|---|---|---|---|
| Bluetooth | `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT` | `NSBluetoothAlwaysUsageDescription` | Find your Bamnun |
| Location | `ACCESS_FINE_LOCATION` | `NSLocationWhenInUseUsageDescription` | Map, route and rest stops |
| Notifications | `POST_NOTIFICATIONS` | System prompt, no Info.plist text | Ollie's alerts and break reminders |

- Each row shows the real result: Allow (not asked), Allowed ✓, or Denied → "Open settings" (deep link to app settings).
- The screen re-checks when the app returns from settings.
- Next is always enabled. Missing permissions are explained where they're needed, never a dead end.
- Android 6–11 has no Bluetooth scan permission and needs Location to scan, so on those versions the Bluetooth row also asks for Location.

**iOS only**
- iOS asks for each permission once. After a refusal the only route back is the Settings app, so the Denied state always shows "Open settings".
- **Local network** is a fourth permission on iOS (`NSLocalNetworkUsageDescription`). iOS shows it the first time the app contacts the Pi, and gives apps no way to ask for it early or read its state. So it isn't a row here. It's handled on screen 11: if `/api/health` fails while on the Bamnun Wi-Fi, show "Allow Local Network for Bamnun in Settings" with a button.
- Info.plist usage texts, in English and Korean:

| Key | English | Korean |
|---|---|---|
| `NSBluetoothAlwaysUsageDescription` | Bamnun uses Bluetooth to find your device and set it up. | 밤눈 기기를 찾고 설정하기 위해 블루투스를 사용해요. |
| `NSLocationWhenInUseUsageDescription` | Bamnun uses your location for the map, your route and rest stops. | 지도, 경로, 휴게소 안내를 위해 위치를 사용해요. |
| `NSLocalNetworkUsageDescription` | Bamnun connects to your device over its own Wi-Fi to show live data. | 실시간 정보를 보여주기 위해 밤눈 기기의 Wi-Fi로 연결해요. |

**Finding the device (screen 11)**
1. The radar animation runs while scanning BLE for devices advertising the Bamnun service UUID.
2. When one is found, show "Found Bamnun · {id}".
3. The phone reads the hotspot name and password over BLE and joins that Wi-Fi network.
   - Android: `WifiNetworkSpecifier`, with the app's traffic to the Pi bound to that network.
   - iOS: `NEHotspotConfiguration`. iOS shows its own "Join Wi-Fi?" prompt, and the driver taps Join. This needs the Hotspot capability, which needs a paid Apple Developer account (section 12).
   - If joining fails on either platform, or the capability isn't available, show the network name and password with a copy button and "Join this network in Wi-Fi settings, then come back". The app continues as soon as `/api/health` answers.
4. It calls `/api/health`.
5. The six part checks tick using the **real** status from `/api/health`. A failed part shows ✗ with a one-line fix.
6. If nothing is found in 20 s, show "Can't find Bamnun", with a checklist (powered on? within 3 m?) and Retry.

## 8. Calibration and device test (screen 12)

The Blinks / Open-eye level / Head angle boxes are **removed**. Instead there's a big Ollie, a one-line instruction, a progress ring, and a checklist that fills in as it goes. The Pi speaker says every instruction out loud in the chosen voice language (lines `cal_position`, `cal_look`, `cal_close`, `cal_hear`, `cal_chime`, `cal_light`, `cal_mist`, `cal_done`, recorded in English and Korean).

1. **Get in position.** "Sit like you're driving and look at me." Waits until a face is seen steadily for 2 s, showing the camera hint from section 4. If no face is seen for 15 s, say "I can't see you. Check the camera faces you."
2. **Look ahead (12 s).** "Look straight ahead and blink normally." Ring counts down. This is the existing 12 s calibrator.
3. **Close your eyes (3 s).** "Now close your eyes… and open." Checks that closure is detected with the new threshold. If not detected, repeat step 2 once, then fail with advice.
4. **Speaker.** Plays a voice line: "Can you hear me?" Phone shows Yes / No.
5. **Chime.** Plays the stage 3 chime: "That's my wake-up chime." Yes / No.
6. **Blue light.** Turns on for 3 s: "See the blue light?" Yes / No.
7. **Mint mist.** "Mist is coming out now." Fires 2 s: "Smell the mint?" Yes / No.
8. **Done.** "All set. I've got your eyes." Shows the summary checklist ✓/✗.

Rules:
- Cancel at any time keeps the previous calibration.
- The new calibration only replaces the old one if steps 1–3 pass.
- If calibration is started mid-drive, the ladder keeps running on the old calibration until the new one succeeds.
- A part that fails (No, or the Pi reports an error) is marked ✗, and the Home device card shows it.

## 9. Route (screen 14)

- **Map**: Kakao Maps JS SDK, centered on the phone's GPS position, with a blue dot.
- **Search**: the "Where to?" field uses Kakao Local keyword search; results show as a list with distance. Recent destinations are saved on the phone.
- **Route**: on pick, Kakao Mobility Directions draws the route line and shows distance and ETA.
- **Rest stops**: highway rest areas (휴게소) along the route are found with Kakao Local keyword search around points sampled along the route line, and shown as pins.
  - Ollie highlights the stop that comes **before** the driver's tired window and within the break interval, with the reason ("Stop here at 02:40, before your tired window").
- **Set route**: saves `{destination, route summary, planned stops}` to the current trip and sends it to the Pi, so the break reminder can say "rest stop in {km} km".
- **Without location permission**: the map still works, and the start point must be typed instead.
- **API keys**: Kakao JS key and REST key in `frontend/.env`, not committed. Register the app's Android package, iOS bundle ID and `http://localhost` in Kakao Developers.
- **iOS risk, to test at step 7**: the Kakao JS SDK checks the page's web address. The Android app runs at `http://localhost`, which can be registered. The iOS app runs at `capacitor://localhost`, and iOS doesn't allow http or https there. If Kakao rejects it, the fallback is to host the map page on a small https site and load it inside the app.

## 9b. Emergency response (no response after the alarm)

Ollie never calls the police directly. Drowsiness alone isn't an emergency, a false call to 112 is a legal problem, and the driver is usually fine once woken. Instead, the response escalates step by step to a person, with a countdown the driver can cancel.

**Trigger** (decided on the Pi, sent to the phone as `emergency`): stage 4 has been running for **20 s** and the driver still hasn't responded, meaning either
- the eyes stay closed, or
- no face is seen after one was.

**What happens**

1. **Countdown.** The phone takes over the screen with a full-screen alert, a loud alarm (even on silent), and a **30 s countdown**: "Are you OK? Contacting {contact} in 30 s". A big "I'm OK" button cancels it. The device speaker says `emergency_check` ("Are you OK? Say something or tap your phone." / "괜찮으세요? 휴대폰을 눌러주세요.").
2. **Emergency contact.** If the countdown ends, the phone sends an SMS to the driver's emergency contact (family member, dispatcher or fleet manager) with:
   - the driver's name,
   - "Bamnun detected that {name} may have fallen asleep at the wheel and isn't responding",
   - a map link to the GPS location,
   - the time.
   Then it calls that contact.
3. **119, optional and off by default.** If the driver turned on "Call 119 if I don't respond" in Settings, a second 30 s countdown follows. Then the phone opens the dialer with **119** filled in (fire and medical, the correct number for a possible crash or medical event; 112 is for crimes). **Someone has to tap Call on both platforms**: Android doesn't let an app place a call to an emergency number itself (`ACTION_CALL` is refused for them; only `ACTION_DIAL` works), and iOS always needs a tap.

**What each platform can do at the end of the countdown**

| Action | Android | iOS |
|---|---|---|
| SMS to the contact | Sent automatically (`SEND_SMS`) | **Needs a tap.** The Messages sheet opens with the text filled in. iOS has no way for an app to send an SMS by itself |
| Call the contact | Placed automatically (`CALL_PHONE`) | **Needs a tap.** A `tel:` link hands over to the Phone app and may ask for confirmation |
| Dial 119 | Dialer opens, **needs a tap** | Same as a contact call, **needs a tap** |
| Full-screen alert | Yes, including over the lock screen (full-screen intent) | Only while the app is open. Otherwise a notification |
| Loud alarm on silent | Yes (alarm audio stream) | While the app is open: yes. Otherwise muted, unless Apple grants Critical Alerts (section 12) |

**This matters**: the driver who triggers this flow is by definition not responding, so on iOS, the SMS and call won't go out unless someone taps. See Q6 for the fix.

**Setup**
- Emergency contact (name + phone) is added in onboarding after Permissions, and is skippable. It's editable in Settings → Safety.
- The 119 toggle lives in Settings → Safety, with a clear warning.
- Permissions: `SEND_SMS` and `CALL_PHONE` (Android), requested only when the driver turns these features on. iOS needs no permission for the Messages sheet or `tel:`.
- Google Play restricts `SEND_SMS` to default SMS apps and approved exceptions, so a Play release needs a Permissions Declaration, and may be refused. Installing the APK directly is unaffected.

**Logging**: every emergency event is saved to the trip, along with whether it was cancelled.

**Demo mode**: a "Demo" switch in Settings → Safety runs the full flow but only shows what *would* be sent, never really texting or dialing. **Always use it at the exhibition.**

---

## 10. Build order

1. Capacitor shell: wrap `frontend/` as an Android and iOS app; it runs on a real Android phone, and the iOS project is generated and ready for its first Mac build (section 12).
2. Pi FastAPI server + `/api/health` + `/ws` snapshot stream.
3. Profile and settings storage (Pi SQLite + phone cache): sections 3, 4, 5.
4. Permissions + BLE find + Wi-Fi join: section 7.
5. Guided calibration + device test: section 8.
6. Voice language screen, recorded EN/KO clips, `/api/say`, notification channel with the owl sound, alert notifications: sections 2 and 6.
7. Route with Kakao: section 9.
7b. Emergency response with countdown, contact SMS and call, optional 119: section 9b.
8. Live Home and Camera screens, trips, insights (from the earlier plan).

**Done early** (branch `live-camera`), viewed in a browser rather than the Capacitor app:
- Step 2: the Pi server, `/api/health`, and the `/ws` snapshot and `alert` stream.
- The live parts of step 8: the Home "Right now", camera tile, cab air and wake-up step cards, and the Camera screen, including the device's live video.
- The Privacy screen says video goes only to the driver's phone and never online, matching section 0.
- A simulated driver (`tools/sim_server.py`), so the app can be developed without a camera.
- A **demo mode** inside the app: a simulated 2½-minute drive played by the page itself, so the live screens can be seen with nothing installed. It starts only when the app is opened as a file (`frontend/Bamnun_app.html`) or with `?demo` in the address. The connection chip says "Demo · simulated driver", so the real app never shows made-up numbers when it loses the Pi.

**Device side done**, and the app screens are connected to it (name, vehicle, work week, ladder, permissions in the browser, emergency contact, device check, voice language, guided calibration, Home, Trips, Insights, Settings, the emergency countdown), in English and Korean. The Kakao route screen is built (map, search, directions through the device at `/api/route`, rest areas, Ollie's stop) and needs only the two keys in `frontend/.env`. Still to do: Bluetooth search and Wi-Fi join (native), and native notifications.
- Step 3: profile and settings in SQLite on the Pi (`runs/bamnun.db`), `GET/PUT /api/profile` and `/api/settings`, vehicle defaults, and the settings applied to the running ladder (mint and voice toggles, sensitivity, volume, CO₂ prompt). The owl is always called Ollie: there is no owl-name field.
- Step 5: the guided calibration and device test, steps 1–8 of section 8, with the ladder still running on the old calibration until the eyes-closed check passes. The ladder holds while the driver closes their eyes on request.
- Step 6, device side: every line of section 6 and 8 in English and Korean (`src/bamnun/voice.py`), `POST /api/say/{line}`, voice-language ladder clips (`assets/voice/{lang}/`), and `tools/record_prompts.py --lang en|ko`.
- Step 7b, device side: the emergency trigger (stage 4 for 20 s with no response), the `emergency` event, `emergency_check` on the speaker, and the outcome saved to the trip. The emergency switch is off and Demo is on by default. **This build never dials 119 or any real emergency number**: the phone only opens the dialer.
- Section 13 and 14: real camera on the Home tile and Camera screen, one shared state label, a smoother 30 fps stream, and the gradual drowsiness score (branch `app-camera-page`).
- Step 8, device side: trips (auto start and end, breaks, alerts, alert-free time), `/api/trips`, `/api/insights`, and the break reminder.

## 11. Open questions

- **Q1. Who records the voice?** One teammate for both languages, or a native Korean speaker for Korean and someone else for English?
- **Q2. Owl hoot sound.** Record a real one, or use a free sound effect (check the license)?
- **Q3. Truck routing.** Does Kakao Mobility offer truck-specific routes (height and weight limits)? If not, use car routing and say so in the app.
- **Q4. Hotspot vs phone hotspot.** In a real truck, does the Pi make its own Wi-Fi, or join the driver's phone hotspot (which keeps the phone online)?
- **Q5. Emergency thresholds.** Are 20 s of no response after stage 4 and a 30 s countdown right? Ask an expert (faculty or a truck company) for the report.
- **Q6. Unattended SMS on iOS.** iOS can't send an SMS or place a call without a tap, so section 9b can't reach anyone from an iPhone if the driver doesn't respond. The fix is for the phone to ask a small cloud service to send the SMS over mobile data, through an SMS provider. That brings a small part of the cloud work forward, costs per message, and only works while the app is running (see Drive mode). Do this, or accept the tap on iOS for now?
- **Q7. Alerts with the app closed on iOS.** Drive mode needs the app open on iOS. Keeping a Bluetooth connection to the Pi could wake the app for alerts, but it needs native Swift code and testing on a real iPhone. Is keeping the app open acceptable?
- **Q8. Apple account and Mac.** Who has a Mac with Xcode 26 or later, and does the team have a paid Apple Developer account (section 12)?

## 12. Android and iOS differences

### App setup

| | Android | iOS |
|---|---|---|
| App ID | `kr.bamnun.app` | `kr.bamnun.app` |
| App runs at | `http://localhost` | `capacitor://localhost` (iOS doesn't allow http or https here) |
| Plain HTTP to the Pi | Allowed by the app's `http` scheme and `cleartext` | Allowed for local addresses by `NSAllowsLocalNetworking`. **Test on an iPhone at step 2**: if the WebView refuses `ws://`, use a native WebSocket plugin |
| Address of the Pi | Hotspot IP | `bamnun.local` where possible, because iOS's local networking exception covers `.local` names. Falls back to the hotspot IP |

### Drive mode

iOS suspends an app seconds after it leaves the screen, which closes the WebSocket. The Pi can't send a push notification either, because it has no internet. So alerts only reach the phone while the app is able to run.

- **The device itself is unaffected.** The ladder, voice and alarm all run on the Pi. This only concerns the phone's notifications and the emergency flow.
- **On both platforms**, while connected to the Pi the app shows a Drive mode screen and keeps the screen on (`keep-awake`). The phone should sit in a mount, on charge.
- **Android** also runs a foreground service, so the connection survives the app being in the background or the screen being off.
- **iOS** needs the app open and on screen. If the driver leaves it, the app shows a notification saying alerts are paused until it's reopened.
- See Q7 for the Bluetooth option on iOS.

### Staying online on the Pi's Wi-Fi

The Pi's hotspot has no internet, but the Kakao map, search and routes need it. The hotspot gives phones an address with **no default gateway**, so they should keep using mobile data for internet and use Wi-Fi only to reach the Pi. Test this on both platforms at step 4, because it affects Q4.

### Notifications and alarms on iOS

- **Sound on silent.** Apps can't override the ring/silent switch from a notification without the **Critical Alerts** entitlement. Apple grants it on request, only for justified safety uses, it can take weeks, and it may be refused. Apply early.
- Until then, alerts use **Time Sensitive** notifications, which get through Focus modes but are still muted by the silent switch.
- While the app is open, the alarm plays through a native audio session, which does ignore the switch.

### Needs a Mac

All the shared code and the Android app can be built on Windows. The iOS project can also be generated and its text files edited on Windows, but nothing there can compile or run it. Everything below needs a Mac with Xcode 26 or later.

| Task | Needs |
|---|---|
| Compile the iOS app | Mac, or a cloud Mac such as a GitHub Actions macOS runner |
| Run on an iPhone or the iOS Simulator | Mac |
| Add Korean translations of the Info.plist texts to the Xcode project | Mac |
| Turn on Hotspot, Background Modes and other capabilities in Xcode | Mac |
| Test BLE, Wi-Fi join, Local Network, notifications, and the Messages and Phone hand-off | Mac and a real iPhone (the Simulator has no Bluetooth or calling) |
| TestFlight and App Store releases | Mac (or a cloud Mac), and a paid account |

### Needs a paid Apple Developer account

A free Apple ID can run the app on your own iPhone, but the app expires after 7 days, and the free tier doesn't cover everything. The paid program is US$99 a year.

- Hotspot capability, for joining the Pi's Wi-Fi from inside the app. Confirm against Apple's capability table before paying. Until then, use the manual Wi-Fi fallback in section 7.
- Critical Alerts entitlement.
- TestFlight, App Store, and installing on teammates' iPhones.

---

## 13. Camera (Home tile and Camera screen)

**The driver's state, one word.** The device decides it and sends it as `label`; the app and the laptop overlay show the same thing, so they can't disagree. In order of priority:

| Label | English | Korean | When |
|---|---|---|---|
| `no_face` | No face | 얼굴 없음 | no face in view |
| `away` | Looking away | 다른 곳을 봄 | head or eyes off the road past the glance limit |
| `eyes_closed` | Eyes closed | 눈 감김 | eyes shut for longer than a normal blink (0.3 s), or a microsleep |
| `very` | Very drowsy | 매우 졸림 | drowsiness level 3 or 4 |
| `drowsy` | Drowsy | 졸림 | level 2 |
| `a_bit` | A bit tired | 조금 피곤 | level 1 |
| `alert` | Alert | 또렷함 | level 0 |

Colours run along the app's lavender → pink scale: Alert peach-lavender, then deeper lavender, pink, and the strongest pink for Eyes closed. No face and Looking away are neutral grey and amber. A normal blink never shows "Eyes closed".

**Home tile**
- The real camera video fills the tile, cropped around the face (`face_box`), never stretched.
- The state chip sits on the video.
- Not connected: a plain grey tile that says "Not connected" / "연결 안 됨". No drawn face.

**Camera screen**
- The video keeps its real shape (16:9): in portrait it spans the full width, with the stats underneath.
- The eye outlines are drawn on the same frame they were measured on, after scaling, so they sit exactly on the eyes.
- The live drowsiness score (0–100) and the label are shown under the video, with a "Signals" toggle that opens a debug panel listing each signal and its share of the score.
- An expand icon in the top-right corner of the video opens it full screen in landscape. On the phone this uses `@capacitor/screen-orientation` to rotate; in a browser the video is rotated with CSS. A close icon in the same corner goes back.
- Not connected: a grey box that says "Not connected" with a Retry button.

**Video stream**
- Up to the camera's frame rate, 640 px wide, JPEG quality 80.
- The camera loop only hands the latest frame and its eye points to the encoder thread (about 1 ms); drawing, scaling and JPEG encoding happen there. If the encoder falls behind it skips frames; detection never waits for it.

## 14. Gradual drowsiness

Drowsiness builds up gradually, so the score does too. A little squinting or a few slow blinks raise it a little; only sustained or strong signs climb the ladder. Looking-away detection is unchanged.

**Signals** (all relative to the driver's own calibrated open-eye level, so glasses and narrow eyes aren't mistaken for squinting):

| Signal | What it measures | Drowsy direction |
|---|---|---|
| Squint | average eye openness over the last 45 s, blinks left out | partly closed eyes |
| PERCLOS | share of the last 60 s with the eyes really shut (below 35 % of the driver's open level) | more |
| Blink duration | average length of recent normal blinks | longer (normal 0.10–0.15 s) |
| Slow blinks | share of recent blinks lasting 0.3 s or more | more |
| Lid speed | how long the eyelid takes to reopen after a blink | slower |
| Blink rate | blinks per minute | well above normal |
| Microsleeps, yawns, head nods | as before | more |

Frames where the driver looks down (head pitched down or eyes lowered, e.g. at the dashboard) are left out of the squint and PERCLOS windows, because eyelids naturally lower when looking down.

**Score.** The signals are weighted and summed into a raw score, which is smoothed so it rises over seconds and falls more slowly, and shown as 0–100. Levels use the smoothed score with a dwell on the way up and hysteresis on the way down, so they don't flicker. Level 1 fires ladder stage 1 (blue light), and so on up.

**Safety bypass, kept.** Eyes really shut (below 35 % of open) for 0.5 s or more is a microsleep: the score jumps to at least 90 and the ladder goes straight to its top stage. A hard squint is not a microsleep any more; before, anything below 65 % open for 0.5 s was.

Every threshold is in `config/default.yaml` with a comment, and the reasoning and sources are in `docs/thresholds.md`.

**Tuning tools**
- `tools/record_session.py` records a webcam session to a video file, with timestamps, and lets you press keys to mark what you were doing (squinting, slow blinks, looking down).
- `tools/replay_session.py` runs the real pipeline over a recording, as fast as it can, with any config override, and writes every signal, the score and the level per frame to CSV, plus a summary per marked stretch.

---

## 15. Detection that learns the driver (branch `detection-software`)

The audit and the before/after numbers are in `docs/detection-audit.md`. Decisions made on this branch:

**Personal eye scale.** Eye openness is a 0–100 % scale between the driver's own calibrated closed level (0 %) and their normal open level (100 %, the median of the look-ahead step). Every eye threshold is on this scale, so small eyes, big eyes and glasses behave the same.
- Eye aspect ratio (EAR) is the width-weighted mean of both eyes, corrected for head yaw and pitch relative to the calibrated neutral. An eye much narrower than the other (turned away, covered, at the frame edge) is dropped.
- MediaPipe blendshapes are on. `eyeBlink` gives a second, independent openness on the same personal scale (its open and closed levels are calibrated too). The two are averaged; if they disagree strongly (glare, landmark error) the frame is unreliable.

**Unreliable frames** are left out of every eye signal (and out of PERCLOS's time base): head down past the calibrated wobble, yaw or pitch beyond ±30 %, face at the frame edge, face too small, a smile, laugh, talking or a yawn, the 1 s after a sudden lighting change, and EAR/blendshape disagreement. Blinks inside them don't count either. A microsleep is still possible during them, but needs longer (looking down 1.5 s, expression 1.0 s).

**Eye signals** (all relative to the driver's calibration):
- Heavy lids: typical openness over 45 s.
- PERCLOS: P80 (openness ≤ 20 %) over 60 s.
- Blink duration at half amplitude, with sub-frame crossing times; compared with the driver's own normal blink.
- Long blinks: 0.3–0.5 s, counted per minute.
- Lid speed: amplitude–velocity ratio of reopening, compared with the driver's normal.
- Blink rate: change from the driver's normal (small weight).

**Head nods.** Pitch relative to the calibrated neutral. A nod is a drop of at least `nod_depth_deg` (and well past the driver's wobble), at a slow-to-moderate speed with the eyes heavy or closed, followed by a fast recovery (a jerk back up) — or a face lost within 0.6 s of a downward movement. A face lost that way is "Head dropping", never "No face", and after 0.5 s it counts as a microsleep (top stage). A deliberate look at the dashboard (fast, eyes open, no jerk) is not a nod.

**Expressions.** With blendshapes: `mouthSmile` / `cheekSquint` mark a smile or laugh, `jawOpen` above its threshold for 1 s marks a yawn, jaw movement at speech rate marks talking. Without blendshapes: mouth width relative to the calibrated rest, and MAR, do the same.

**Score.** Weighted sub-scores (heavy lids, PERCLOS, blink duration, long blinks, lid speed, nods, microsleeps, yawns, blink rate), smoothed (up over seconds, down more slowly), shown 0–100. Every anchor sits beyond the driver's normal variation, so an alert, calibrated driver scores about 0–10. Levels and the ladder mapping are as in section 14. The microsleep bypass is kept: shut (≤ 25 % openness, confirmed by blendshapes when available) for 0.5 s → top stage at once.

**Time-of-day risk is separate.** The camera score reflects only what the camera sees. The rest planner's two-process estimate (hours awake, time of day) is sent as `time_risk` (`low`, `medium`, `high`) and shown on its own line on the Camera screen. It never changes the score or the ladder.

**New label** `head_drop` ("Head dropping" / "고개 떨굼"), between `away` and `eyes_closed` in priority.

**Calibration** (guided, from the phone):
1. Position: hints until the face is centred, close enough, lit, facing the camera, still.
2. Look ahead (15 s, extended up to 25 s for blinks): learns the open-level distribution (EAR and eyeBlink), normal blink duration and rate, neutral head pose and its wobble, face size, brightness and the mouth at rest.
3. Close your eyes (3 s): learns the closed level.
4. Quality checks, each with a plain reason, redoing the step that failed (up to twice): steady face, light, distance, at least 3 blinks, open and closed clearly apart.
5. Summary: eye size (small/medium/large), open and closed levels, normal blink (ms and per minute), neutral head pose and wobble, and the quality checks.
6. Device test: speaker, chime, light, mist, as before.

It is saved per driver as `runs/drivers/<driver>/calibration.json` (the driver is the profile name; "default" when there is none) and loaded at start-up. The start-up auto-calibration (no phone) only runs the look-ahead step and estimates the closed level from population data, marked as estimated; the guided calibration replaces it.

**Calibration screen.** The live camera is the main element, with a face-guide oval. One step at a time: Ollie with one big instruction, a progress ring for that step, a check animation when it passes, then it slides away and the next appears. Live hints (Move closer, Move back, Too dark, Too bright, Face the camera, Hold still) appear on the video. The device-test steps use the same style with Yes / No. The summary shows what was learned.

**Frame rate.** Detection runs on the camera loop at the camera's rate (≥ 25–30 fps on a laptop webcam in normal light), and the snapshot reports the capture rate and the processing capacity separately. The phone video is encoded on its own thread (section 13). Measured on the laptop webcam: processing capacity 58 fps (17 ms a frame with blendshapes), detection 24–30 fps, limited by the camera in low light. Pi plan: 1536×864 binned at 30 fps from the camera, blendshapes on; if processing drops below 25 fps, turn the preview off first, then try `landmarks.input_width` (off by default: on the laptop it was slower and shifted EAR by 2.7 %), then blendshapes off.

**Validation.** `src/bamnun/scenarios.py` simulates every case (alert, talking, smiling/laughing, mirror/dashboard/phone glances, head turns, yawning, glasses glare, lighting changes, face partly out, one eye hidden; slow blinks, heavy eyelids, head nods, microsleeps, progressive drowsiness) for four eye types at 30 and 15 fps. `tools/evaluate_detection.py` reports detection rate, false alarms per hour, reaction time and resting score; `tests/test_detection_eval.py` runs a subset every time and fails if a drowsy case is missed or a not-drowsy case alarms. `tools/record_session.py --script` runs a 10-minute labelled webcam protocol; its recordings are evaluated the same way.
