# Detection audit

An audit of the whole drowsiness pipeline (capture → landmarks → features →
state → alerts) and calibration, done on the `detection-software` branch. Each
flaw has an id, where it is, what it does, and what was done about it. The
evidence comes from three places:

- **Real webcam sessions** in `runs/` (the session logs, sampled at 10 Hz),
  including the 17-minute session `20261104_191427` recorded while sitting
  alert at a desk, and a 40 s raw recording at 30 fps
  (`runs/recordings/tool-check`).
- **The scenario simulator** (`src/bamnun/scenarios.py`): 17 cases, 4 eye
  types, 2 frame rates, built to reproduce what the real sessions showed.
- **Reading the code.**

## What the real sessions showed

| Measure (alert driver at a desk, 17 min) | Value | Expected |
|---|---|---|
| Median drowsiness score | **34 / 100** | 0–10 |
| Time at "A bit tired" or above | **59 %** | ~0 % |
| Measured blink rate | **3 / min** | 15–20 / min |
| Median "eye open" vs baseline | 84–89 % | ~100 % |
| Mean sub-scores (0–1) | blink duration 0.49, slow blinks 0.48, lid speed 0.47, head nod 0.21, squint 0.17, microsleep 0.18 (0.61 in an earlier session) | ~0 |

The raw 30 fps recording shows real blinks are clear on the camera: 12 / min,
dipping to 26–38 % of normal openness. The sessions above ran at 13–15 fps
(the laptop preview window was redrawn every frame; fixed on the previous
branch), and that is where blinks disappear (flaw F9).

## Flaws

Status: **fixed** on this branch unless marked otherwise.

### Capture

| # | Flaw | Effect | Status |
|---|---|---|---|
| F1 | No check of the camera's real frame rate. A webcam in low light, or opened through DirectShow (YUY2 at 720p), silently delivers 10 fps. | Blinks are 1–2 frames; everything downstream degrades without a warning. | Fixed: the loop measures capture and processing rates separately and reports both; a warning is logged below 20 fps. |
| F2 | The laptop preview window was drawn every frame. | Detection fell from ~34 to ~13 fps. | Fixed on `app-camera-page` (15 Hz). |
| F3 | Every frame is converted to RGB at full resolution for MediaPipe. | A few ms per frame on the Pi. | Fixed: optional `landmarks.input_width` downscale (points are scaled back), see the Pi plan. |

### Landmarks

| # | Flaw | Effect | Status |
|---|---|---|---|
| F4 | MediaPipe blendshapes were off. | The model's own eyeBlink / eyeSquint / jawOpen / mouthSmile / cheekSquint estimates, which see blinks and smiles well, were unused. | Fixed: on, and fused (F18–F21). |
| F5 | Eye landmarks outside or at the edge of the frame are extrapolated, and were used as if real. | Face partly out of frame read as closing eyes. | Fixed: per-eye edge check; such an eye is ignored, a face clipped at the edge makes the frame unreliable. |

### Eye openness

| # | Flaw | Effect | Status |
|---|---|---|---|
| F6 | EAR was the MAX of the two eyes. With the head turned, the far eye is foreshortened, its EAR rises, and max picks it. | Turned heads read as wider eyes; closures hidden. | Fixed: width-weighted mean of the two eyes; an eye much narrower than the other (turned away, covered) is dropped. |
| F7 | No pose compensation. Yaw narrows the eye's width (EAR up), pitch shortens its height (EAR down). | Systematic error with every head movement. | Fixed: EAR is corrected by the head angle relative to the calibrated neutral, within ±30°; beyond that the frame is unreliable for eye measures. |
| F8 | One open-eye number (75th percentile) as the baseline, no closed level. | Normal relaxed eyes read 84–89 % "open", a permanent squint; thresholds expressed as fractions of open EAR can't account for MediaPipe never reaching 0 on a shut eye. | Fixed: personal 0–100 % openness between the driver's calibrated closed and open (median) levels. |
| F9 | Per-frame smoothing (EWMA α 0.4) on EAR. Its time constant depends on the frame rate. | At 15 fps a 120 ms blink is 1–2 frames and is smoothed away: 3 blinks / min measured. Blink stats were built from the few long blinks that survived, so an alert driver looked like a slow blinker. | Fixed: no per-frame smoothing on the blink path; a time-based filter only for the slow signals. |
| F10 | Blink duration measured between frames at the threshold. | Quantised to 67 ms at 15 fps, the size of the effect being measured. | Fixed: blink duration at half amplitude, with the crossing times interpolated between frames. |
| F11 | "Really shut" = 40 % of the open EAR. MediaPipe's shut EAR is 28–42 % of open, so small eyes may never get there. | Microsleeps caught in only 17 % of simulated cases. | Fixed: shut = below 25 % on the personal scale, using the calibrated closed level, confirmed by blendshapes. |
| F12 | PERCLOS on the same 40 %-of-open line. | Same as F11; also not the published P80 definition. | Fixed: P80 on the personal scale (openness ≤ 20 %), over reliable frames only. |
| F13 | Squint measured against the biased baseline (F8). | ~17 % squint component at rest. | Fixed by F8. |

### Expressions and conditions that are not drowsiness

| # | Flaw | Effect | Status |
|---|---|---|---|
| F14 | Smiling and laughing narrow the eyes (cheeks rise). | Counted as squint and closures; laughter caused false microsleeps. | Fixed: smile / cheek-squint blendshapes (or mouth width without blendshapes) mark the frame as an expression; eye signals skip it, a microsleep needs longer. |
| F15 | Talking moves the cheeks; yawning squeezes the eyes. | Closures during yawns counted as drowsy closures. | Fixed: talking (jaw motion at speech rate) and yawns (sustained jawOpen) are detected; eyes are not scored during them; yawns are their own signal. |
| F16 | Looking down at the dashboard or a phone lowers the lid (lid–gaze coupling). | Partly fixed on `app-camera-page` (frames left out, longer microsleep time); still counted in blink stats when within the forward cone. | Fixed: all eye signals skip head-down frames beyond the calibrated wobble. |
| F17 | Head turns within the road cone still used for eye measures. | Distorted EAR (F6, F7). | Fixed by F6, F7. |
| F18 | Glasses glare corrupts one or both eyes' landmarks. | Spurious closures. | Fixed: EAR and blendshape openness must agree; a frame where they disagree strongly is unreliable. |
| F19 | A lighting change (tunnel, streetlights) shifts landmarks. | Openness jumps. | Fixed: brightness tracked per frame; a sudden change makes the next second unreliable. |
| F20 | One eye hidden (hand, hair) or outside the frame. | Garbage EAR from that eye. | Fixed by F5, F6. |
| F21 | Small or distant face. | Noisy eyelid geometry. | Fixed: a face below `min_iod_px` is unreliable for eye measures (pose and distraction still work). |

### Head nods

| # | Flaw | Effect | Status |
|---|---|---|---|
| F22 | "Nodding" = pitch standard deviation over 10 s, from 2°. | Ordinary movement (2–3° on a real webcam) scored ~0.2; a real nod (slow drop, fast jerk back) was not recognised as an event. | Fixed: a nod detector on pitch relative to the calibrated neutral: depth, drop speed, and the fast recovery, with the eyes' state during the drop. |
| F23 | A face lost right after a downward head movement was "no face" (empty seat). | The most dangerous moment of a nod was discarded. | Fixed: a loss within 0.6 s of a downward movement is a head drop: label "Head dropping", counted as a nod, and after 0.5 s treated as a microsleep. |

### Calibration

| # | Flaw | Effect | Status |
|---|---|---|---|
| F24 | 12 s look-ahead learning one EAR number and the pose zero. | No blink duration, blink rate, pose wobble, closed level or eye-size awareness; "calibration feels useless". | Fixed: learns the open-level distribution, blink duration and rate, neutral pose and its wobble, and the closed level from the eyes-closed step. |
| F25 | Pose rejection used absolute camera angles (±20°). | A dash camera 15–25° off-axis rejected most frames. | Fixed: rejection is relative to the session's own median pose. |
| F26 | No quality checks; failures were technical messages after the fact. | A bad calibration (dark, far, moving, no blinks, eyes not separable) was silently accepted. | Fixed: live hints (Move closer, Too dark, Face the camera, Hold still) and pass/fail checks with a plain reason; a failed step is redone. |
| F27 | The "close your eyes" step only checked that closure was seen. | The closed level was never learned. | Fixed by F24. |
| F28 | One global `runs/calibration.json`. | The next driver inherits the last one's eyes. | Fixed: saved per driver (`runs/drivers/<name>/calibration.json`). |

### Score and state

| # | Flaw | Effect | Status |
|---|---|---|---|
| F29 | Blink duration, slow blinks and blink rate scored against population constants. | People with naturally long blinks start "drowsy". | Fixed: scored as change from the driver's calibrated blinks. |
| F30 | The microsleep count was also a score component. | One event kept the score up for a minute on top of the bypass. | Kept, small weight; the bypass does the work. |
| F31 | Score at rest ~34 from the sum of biased components (F8–F10, F22). | "A bit tired" while alert. | Fixed by the above; verified in the before/after table. |
| F32 | Time-of-day risk: checked. The rest planner is NOT mixed into the camera score (it only triggers a voice prompt), and the KSS figure is only `1 + 8 × score`. | Not the cause of the 45 / 100. | Kept separate, and now also shown separately as `time_risk`. |
| F33 | The session log is sampled at 10 Hz. | Blinks can't be replayed from it. | Partly: recordings (video + markers) are the replay format; the log keeps 10 Hz to save space. |

### Validation

| # | Flaw | Effect | Status |
|---|---|---|---|
| F34 | No systematic validation: no scenarios, no metrics, thresholds never tested against anything. | Every threshold was a guess. | Fixed: scenario simulator, evaluation, a test that runs it every time, a labelled recording tool with a 10-minute script. |

## Before and after

_Filled in below by `python tools/evaluate_detection.py` on the full set._
