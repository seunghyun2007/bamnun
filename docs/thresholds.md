# Where every threshold comes from

Each number in `config/default.yaml` is either taken from published work, set
by a physical constraint, or chosen by us. This file says which, so that when
a judge asks "why 0.15?" the answer is a sentence and not a shrug. Anything
marked **ours** is a design choice we should be ready to defend as a choice,
not to misrepresent as a finding.

## Eye openness on the driver's own scale

Every eye threshold below is on a personal 0–100 % scale: 100 % is this
driver's normal open eyes, 0 % their closed eyes, both learned by the guided
calibration (section *Calibration*). That is what makes small eyes, large eyes
and glasses behave the same (audit F8, F24). The simulator checks it on four
eye types (EAR open 0.20 / 0.26 / 0.28 / 0.36).

| Parameter | Value | Basis |
|---|---|---|
| Open level | median EAR of the look-ahead step, blinks excluded | **ours.** The old 75th percentile sat above the driver's typical eyes: a real 17-minute session read 84–89 % "open" while alert, a permanent squint. The median is the typical open eye. |
| Closed level | median EAR of the eyes-closed step (darkest 60 % of its frames, after a 0.7 s lead) | **ours.** MediaPipe never reaches EAR 0 on a shut eye; measured shut EARs are 28–42 % of open, so fixed fractions of the open level (the old 0.65 / 0.40) can't work for everyone. |
| `estimated_closed_ratio` | 0.33 | **ours**, from the bench sessions (closed EAR ≈ a third of open). Used only until the eyes-closed step has run. |
| `blendshape_weight` | 0.5 | **ours.** MediaPipe's `eyeBlink` is a second, independent estimate of upper-lid closure, calibrated on the same scale (its own open and closed levels). Equal weight; either alone works. |
| `eye_disagreement` | 0.45 | **ours.** When EAR and `eyeBlink` disagree by more than this, a reflection or landmark error is likely (glasses glare); the frame is unreliable and the more open estimate is used, so a reflection can't fake a closure. |
| `eye_drop_width_ratio` | 0.60 | **ours.** An eye narrower than 60 % of the other is turned away, covered or cut by the frame edge; it is ignored and the other eye used (audit F6, F20). Replaces "max of both eyes", which picked the foreshortened far eye. |
| `pose_compensation_max_deg` | 30° | Geometry: yaw narrows the eye's width by cos(yaw), raising EAR; pitch shortens its height by cos(pitch). EAR is corrected by the head angle relative to the calibrated neutral. Beyond ±30° the correction is unreliable and the frame is too (`reliable_yaw_deg`, `reliable_pitch_deg`). |

## Frames that are not scored

Eye signals skip frames that can't be trusted, and PERCLOS leaves their time
out of both numerator and denominator.

| Parameter | Value | Basis |
|---|---|---|
| `smile_threshold`, `cheek_threshold` | 0.35, 0.30 (MediaPipe `mouthSmile`, `cheekSquint`) | A genuine smile raises the cheeks and narrows the eyes from below (Duchenne smile; Ekman, Davidson & Friesen 1990). Thresholds **ours**. Without blendshapes: mouth 12 % wider than at rest (`smile_mouth_width_ratio`). |
| `talk_jaw_std`, `talk_window_s` | 0.05 over 1 s | Speech moves the jaw at the syllable rate, 3–7 Hz (Chandrasekaran et al. 2009), which shows as variance of `jawOpen` within a second. Threshold **ours**. |
| `yawn_jaw_open`, `yawn_min_s` | 0.50 held 1 s | Yawns last about 6 s with a ~2 s opening phase (Provine 1986); the eyes squeeze shut at the peak, so those frames are not eye evidence. A yawn is counted as its own signal. |
| `expression_hold_s` | 0.7 s | **ours.** The face takes a moment to relax after a smile or yawn. |
| `light_jump`, `light_hold_s` | 18 grey levels, 1 s | **ours.** A sudden brightness change (tunnel, streetlight) shifts landmarks for a moment; the next second is skipped and the new light becomes the new normal. |
| `min_iod_frac` | 0.045 of frame width | **ours.** Below this the eye is a few pixels tall and its geometry is noise. |
| `look_down_pitch_deg` | 10°, or 3× the calibrated pitch wobble | The upper lid follows vertical gaze, so looking down lowers it with no drowsiness at all (Becker & Fuchs 1988). Relative to the driver's own neutral pose and movement. |

## PERCLOS

| Parameter | Value | Basis |
|---|---|---|
| `perclos_closed_level` | openness ≤ 20 % | This is P80, the published definition: eyes more than 80 % closed (Wierwille et al. 1994; Dinges & Grace 1998). Only possible now that the closed level is measured; before it was approximated as 40–80 % of the open EAR. |
| `perclos_window_s` | 60 s | Standard integration window. |
| `ranges.perclos` | 3 % → 0, 15 % → 1 | On this scale ordinary blinking spends 3–5 % of the time below 20 % open; 15 % is the usual drowsy criterion (Dinges & Grace 1998). |
| PERCLOS level gates | removed | They opened at 5 %, inside normal blinking on the true P80 scale, and made levels jump; PERCLOS is already in the score. |

## Heavy eyelids

| Parameter | Value | Basis |
|---|---|---|
| `openness_window_s` | 45 s | **ours.** Typical openness = median of reliable frames over the window; blinks are ~3 % of frames and don't move a median, a held droop does. |
| `ranges.heavy_lids` | 1 − typical: 0.15 → 0, 0.45 → 1 | Lower lid opening between blinks is an early sign of drowsiness (Caffier et al. 2003; partial closures in the Johns Drowsiness Scale, Johns et al. 2007). Anchors **ours**: 15 % is normal variation in a real session, 45 % a heavy droop. |

## Blinks

| Parameter | Value | Basis |
|---|---|---|
| `blink_half_level` | 50 % | Blinks are timed at half amplitude, the convention in the blink-duration literature (Caffier et al. 2003; Schleicher et al. 2008), measured from where the lids currently rest, so heavy lids don't hide blinks. Crossing times are interpolated between frames: at 15 fps a frame is 67 ms, the size of the effect. |
| Per-frame smoothing | removed | The old α = 0.4 smoothing erased 1–2-frame blinks at 15 fps: 3 blinks / min measured on a real session instead of 15–20 (audit F9). |
| `long_blink_s` | 0.30 s | Blinks of 0.3 s or more are a recognised early sign (Schleicher et al. 2008). |
| `ranges.long_blinks` | 1 → 0, 5 per minute → 1 | **ours.** One long blink a minute happens to anyone. |
| `ranges.blink_duration` | +0.05 → 0, +0.18 s → 1 over the driver's normal blink | Alert half-amplitude blinks are ~100–150 ms and lengthen with sleepiness, correlating with KSS (Ingre et al. 2006). Scored as the change from this driver's calibrated blink. |
| `ranges.lid_speed` | reopening AVR 1.3× → 0, 2.3× → 1 the driver's normal | Drowsy lids reopen slowly; the amplitude–velocity ratio is the basis of the Johns Drowsiness Scale (Johns et al. 2007). Relative to the driver's own blinks, so the camera's frame rate cancels out. |
| `ranges.blink_rate` | 1.5× → 0, 2.5× → 1 the driver's normal | Blink rate changes with fatigue (Stern et al. 1994) but varies widely between people: smallest weight. |
| `held_closure_s` | 1.0 s | **ours.** Longer "blinks" are held squints or looks down. |
| `min_blinks_for_stats` | 5 | **ours.** Fewer judged blinks in the last minute = no evidence yet (0), not "fast". |

## Shut eyes and the microsleep bypass

| Parameter | Value | Basis |
|---|---|---|
| `shut_level` | openness ≤ 25 % (with blendshapes, EAR and `eyeBlink` each ≤ 40 %) | **ours.** Both estimates must agree, so glare can't trigger it. |
| `microsleep_s` | 0.5 s | Microsleeps are eye closures from 0.5 s to several seconds (Boyle et al. 2008; Hertig-Godeschalk et al. 2020). Bypass: score ≥ 0.90 and the top ladder stage at once. |
| `microsleep_looking_down_s` | 1.5 s | **ours.** With the head down the lids can close almost fully while awake; a head dropping with the eyes shut still passes 1.5 s. |
| `microsleep_unreliable_s` | 1.0 s | **ours.** During a laugh, yawn or lighting change. |
| `eyes_closed_label_s` | 0.3 s | **ours.** A normal blink never shows "Eyes closed". |

## Head nods

| Parameter | Value | Basis |
|---|---|---|
| Model | slow drift down, then a fast jerk back up | Head nodding / drooping is a late sign in observer rating schemes (Wierwille & Ellsworth 1994) and a classic fatigue cue in vision systems (Ji, Zhu & Lan 2004). The kinematic anchors below are **ours**, checked in the simulator against glances at the dashboard, phone and mirrors. |
| `nod_start_deg` | 6° below neutral | A drop must start by crossing out of the neutral band, so its whole descent is seen. |
| `nod_depth_deg`, `nod_wobble_multiple` | 12°, and 3× the calibrated pitch wobble | Deeper than the driver's normal head movement. |
| `nod_max_drop_speed_deg_s` | 45°/s (fastest 0.15 s of the drop) | A deliberate look down is fast (≥ 100°/s in the simulator's glances); nodding off drifts. |
| `nod_recovery_speed_deg_s` | 60°/s, and ≥ 2× the drop speed | The corrective jerk. A glance comes back as fast as it went down. |
| `nod_recovery_window_s`, `nod_max_drop_s` | 2.5 s, 4 s | A head held down longer is a deliberate look, not a nod. |
| `head_drop_lost_window_s`, `head_drop_min_speed_deg_s` | 0.6 s, 8°/s | A face lost within 0.6 s of a downward movement went down with the head: "Head dropping", never "No face" (audit F23). |
| `head_drop_microsleep_s` | 0.5 s | A head drop with the face lost this long is treated as a microsleep. |
| `ranges.nods` | 0 → 0, 2 nods in 2 min → 1 | **ours.** |
| `state.nod_score` | 0.50 | A detected nod lifts the score to level 2 at once: rater schemes put nodding at "very drowsy". |

## Calibration

| Parameter | Value | Basis |
|---|---|---|
| `duration_s`, `max_duration_s`, `min_blinks` | 15 s, up to 25 s, 3 blinks | **ours.** At 15–20 blinks / min, 15 s usually holds 3–5 blinks; the step waits up to 25 s for them, so the driver's normal blink is measured, not assumed. |
| `max_relative_pose_deg` | 12° | Frames this far from the session's own median pose are dropped. Relative, not absolute: the old ±20° absolute gate rejected dash cameras 15–25° off-axis (audit F25). |
| `max_wobble_deg` | 4° robust std | **ours.** More head movement than this: "Hold still", redo. Also learned as the driver's normal wobble for the nod detector. |
| `min_separation` | 30 % | (open − closed) / open EAR below this (or eyeBlink difference below 0.35): the eyes can't be told apart; redo. |
| `min_brightness`, `max_brightness` | 45, 235 grey levels | **ours.** Live hints "Too dark" / "Too bright". |
| `min_face_frac`, `max_face_frac`, `max_facing_deg` | 6 % and 32 % of the frame width, 28° | **ours.** Live hints "Move closer" / "Move back" / "Face the camera". |

## Fusion and levels

| Weight | Signal |
|---|---|
| 0.20 | heavy lids |
| 0.20 | PERCLOS (P80) |
| 0.15 | nods |
| 0.14 | blink duration vs normal |
| 0.14 | long blinks |
| 0.07 | lid reopening speed vs normal |
| 0.05 | microsleeps |
| 0.03 | yawns |
| 0.02 | blink rate vs normal |

All **ours**, not fitted. Tuned so every drowsy scenario is caught and every
not-drowsy one stays quiet in the simulator (`docs/detection-audit.md`), on
four eye types at 15 and 30 fps. Every lower anchor sits beyond the driver's
own normal variation, so an alert, calibrated driver scores ~0–5: the
simulated alert driver's median is 0.9 / 100, and a real 40 s webcam
recording replays at 0.

Smoothing (`score_rise_tau_s` 6 s, `score_fall_tau_s` 20 s) and the levels
(0.25 / 0.45 / 0.65 / 0.82 with dwell and 0.08 hysteresis) are unchanged from
the previous branch. Time-of-day risk (the two-process model below) is **not**
part of this score; it is shown separately.

## Validation scenarios (simulator timings)

`src/bamnun/scenarios.py`; every timing has a source or is marked ours.

| Scenario | Timing | Source |
|---|---|---|
| Alert blinking | 17 / min, half-amplitude 100–150 ms | Stern et al. 1994; Caffier et al. 2003 |
| Slow blinks | 14 / min, 300–450 ms, slow reopening | Schleicher et al. 2008; Johns et al. 2007 |
| Heavy eyelids | openness ~60 %, blinks 180–320 ms | Caffier et al. 2003 |
| Microsleep | eyes shut 0.6–2.0 s | Boyle et al. 2008; Hertig-Godeschalk et al. 2020 |
| Head nods | drop 16–32° over 1–2.2 s, eyes heavy, jerk back in 0.12–0.25 s | Wierwille & Ellsworth 1994 (description); speeds ours |
| Progressive | 10 min, blinks 0.10 → 0.43 s, lids → 65 %, nods at the end | composite of the above |
| Yawning | ~6 s, eyes squeezed at the peak | Provine 1986 |
| Talking | jaw at 4.5 Hz | Chandrasekaran et al. 2009 |
| Mirror glances | 0.7–1.3 s, ±40° yaw | Rockwell 1988 |
| Dashboard / phone | 0.6–1.5 s at 15–22° down / 1.8–3 s at 30–40° down | ours; lid lowering per Becker & Fuchs 1988 |
| Real-camera effects | open EAR drift ±4.5 %, pitch wander ~2°, 0.45° jitter, exposure blur, 15 and 30 fps | measured on a real 30 fps webcam recording |

`tests/test_detection_eval.py` runs every scenario once on every change.


## Head and gaze

| Parameter | Value | Basis |
|---|---|---|
| `off_road_alert_s` | 2.0 | NHTSA's visual-manual driver distraction guidelines treat single off-road glances longer than 2 s as the risk criterion; this also matches the Klauer/Dingus 100-car naturalistic study finding that eyes-off-road beyond about 2 s sharply raises crash risk. Citable, not invented. |
| `yaw_limit_deg` / `pitch_limit_deg` | 25 / 20 | **ours.** A rough forward gaze cone, measured relative to the calibration pose, not to the camera. Should be tuned once the camera is on its real mount, and the tuned value reported. |

## KSS

`kss = 1 + 8 * score` is **presentation only**. The Karolinska Sleepiness
Scale is a nine-point self-report instrument; mapping our fused score onto it
linearly gives an intuitive display number and nothing more. It is not a
validated KSS estimate and must not be described as one. If a KSS figure is
wanted in the report, collect it properly: ask the subject for a KSS rating
every five minutes during recording and timestamp it into the log. That also
gives the ground truth the system currently lacks.

## Alerting

| Parameter | Value | Basis |
|---|---|---|
| `scent.refractory_s` | 120 | Olfactory adaptation is fast, on the order of tens of seconds of continuous exposure; repeated bursts within a short window are wasted and make the cabin unpleasant. |
| `scent.max_per_hour` | 12 | **ours.** Consumable budget as much as a physiological one. |
| `thermal.precool_s` | 20 | Physical. A TEC1-12706 needs lead time to establish a useful ΔT across the module. **Measure this on the actual build and replace the number with the measured one.** |
| `rest_duration_min` | 20 | Short-nap research consistently finds ~20 minutes gives recovery without the sleep inertia that follows waking from deep sleep; longer naps leave the driver worse off immediately after. |
| `homeostatic_tau_h` 10, `circadian_amplitude` 0.12, `circadian_peak_hour` 16.5 | | Shape parameters of a reduced two-process alertness model in the Åkerstedt–Folkard tradition: a homeostatic component saturating with time awake plus a circadian component with a 24 h fundamental and a 12 h harmonic, the latter producing the early-afternoon dip. The parameter values are **ours**, chosen to give a plausible shape rather than fitted to any dataset. State this plainly: it is a physiologically motivated prior, not a calibrated model. |

## Sources

- Becker, W. & Fuchs, A. F. (1988). Lid-eye coordination during vertical gaze changes in man and monkey. *Journal of Neurophysiology*, 60(4).
- Caffier, P. P., Erdmann, U. & Ullsperger, P. (2003). Experimental evaluation of eye-blink parameters as a drowsiness measure. *European Journal of Applied Physiology*, 89.
- Dinges, D. F. & Grace, R. (1998). *PERCLOS: A valid psychophysiological measure of alertness as assessed by psychomotor vigilance.* FHWA-MCRT-98-006.
- Ingre, M., Åkerstedt, T., Peters, B., Anund, A. & Kecklund, G. (2006). Subjective sleepiness, simulated driving performance and blink duration. *Journal of Sleep Research*, 15.
- Johns, M. W., Tucker, A., Chapman, R., Crowley, K. & Michael, N. (2007). Monitoring eyelid and eye movements by infrared reflectance oculography to measure drowsiness in drivers. *Somnologie*, 11.
- Schleicher, R., Galley, N., Briest, S. & Galley, L. (2008). Blinks and saccades as indicators of fatigue in sleepiness warnings: looking tired? *Ergonomics*, 51(7).
- Stern, J. A., Boyer, D. & Schroeder, D. (1994). Blink rate: a possible measure of fatigue. *Human Factors*, 36(2).
- Wierwille, W. W., Ellsworth, L. A., Wreggit, S. S., Fairbanks, R. J. & Kirn, C. L. (1994). *Research on vehicle-based driver status/performance monitoring.* NHTSA / Virginia Tech.
- Boyle, L. N., Tippin, J., Paul, A. & Rizzo, M. (2008). Driver performance in the moments surrounding a microsleep. *Transportation Research Part F*, 11(2).
- Chandrasekaran, C., Trubanova, A., Stillittano, S., Caplier, A. & Ghazanfar, A. A. (2009). The natural statistics of audiovisual speech. *PLoS Computational Biology*, 5(7).
- Ekman, P., Davidson, R. J. & Friesen, W. V. (1990). The Duchenne smile: emotional expression and brain physiology II. *Journal of Personality and Social Psychology*, 58(2).
- Hertig-Godeschalk, A., Skorucak, J., Malafeev, A., Achermann, P., Mathis, J. & Schreier, D. R. (2020). Microsleep episodes in the borderland between wakefulness and sleep. *Sleep*, 43(1).
- Ji, Q., Zhu, Z. & Lan, P. (2004). Real-time nonintrusive monitoring and prediction of driver fatigue. *IEEE Transactions on Vehicular Technology*, 53(4).
- Provine, R. R. (1986). Yawning as a stereotyped action pattern and releasing stimulus. *Ethology*, 72(2).
- Rockwell, T. H. (1988). Spare visual capacity in driving — revisited. In *Vision in Vehicles II*, Elsevier.
- Wierwille, W. W. & Ellsworth, L. A. (1994). Evaluation of driver drowsiness by trained raters. *Accident Analysis & Prevention*, 26(5).
