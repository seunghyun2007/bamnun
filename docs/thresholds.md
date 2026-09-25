# Where every threshold comes from

Each number in `config/default.yaml` is either taken from published work, set
by a physical constraint, or chosen by us. This file says which, so that when
a judge asks "why 0.15?" the answer is a sentence and not a shrug. Anything
marked **ours** is a design choice we should be ready to defend as a choice,
not to misrepresent as a finding.

## Eye closure

| Parameter | Value | Basis |
|---|---|---|
| `ear_closed_fraction` | 0.65 of the driver's calibrated open EAR | **ours.** The widely cited absolute threshold is EAR < 0.21, from Soukupová & Čech's 2016 real-time blink detection work. Absolute thresholds do not transfer across eye shapes: a narrow aperture sits near 0.17 fully open and is classified as permanently closed. Expressing closure as a fraction of a per-driver baseline is the fix. 0.65 was chosen so that the equivalent absolute threshold for a typical 0.30 open EAR is 0.195, i.e. close to the published figure, while scaling correctly for everyone else. |
| `ear_reopen_fraction` | 0.75 | **ours.** Hysteresis band of 0.10. Without it, EAR noise around a single threshold splits one blink into several and inflates the blink rate. |
| `ear_smoothing_alpha` | 0.4 | **ours.** EWMA on raw EAR. At 25 fps this is roughly a 60 ms time constant, short relative to a 100–300 ms blink so genuine blinks survive, long enough to suppress single-frame landmark jitter. |

## PERCLOS

| Parameter | Value | Basis |
|---|---|---|
| `perclos_baseline_fraction` | 0.80 | Standard. PERCLOS is conventionally reported as P80: the proportion of time the eyes are more than 80% closed. Wierwille and colleagues' work at Virginia Tech for the FHWA established PERCLOS as the best-correlated single ocular measure of drowsiness. |
| `perclos_window_s` | 60 | Standard. One minute is the usual PERCLOS integration window. |
| `PERCLOS_RANGE` sub-score anchors | 0.05 → 0 and 0.30 → 1 | Anchored on the commonly used drowsy criterion of PERCLOS > 0.15, which sits at the midpoint of our ramp. The 0.30 saturation point is **ours**. |

## Blinks

| Parameter | Value | Basis |
|---|---|---|
| `min_duration_s` | 0.05 | Physiological floor. Voluntary blinks do not complete in under ~50 ms, so anything shorter is landmark noise. |
| `max_normal_duration_s` | 0.40 | Normal spontaneous blink duration is roughly 100–400 ms; longer closures are a distinct category. |
| `microsleep_duration_s` | 0.50 | **ours, conservative.** Definitions of microsleep in the literature range from 0.5 s to 15 s of behavioural sleep. We take the low end deliberately: the cost of acting on a 0.5 s closure is one chime, the cost of missing a real one can be a lane departure. Worth stating in the report that our "microsleep" is the conservative end of the definition. |
| `BLINK_DURATION_RANGE` | 0.15 → 0.45 s | Blink duration lengthens measurably with sleepiness; the range spans alert to strongly sleepy mean durations. Anchors are **ours**. |

## Head and gaze

| Parameter | Value | Basis |
|---|---|---|
| `off_road_alert_s` | 2.0 | NHTSA's visual-manual driver distraction guidelines treat single off-road glances longer than 2 s as the risk criterion; this also matches the Klauer/Dingus 100-car naturalistic study finding that eyes-off-road beyond about 2 s sharply raises crash risk. Citable, not invented. |
| `yaw_limit_deg` / `pitch_limit_deg` | 25 / 20 | **ours.** A rough forward gaze cone, measured relative to the calibration pose, not to the camera. Should be tuned once the camera is on its real mount, and the tuned value reported. |
| `nod_pitch_std_deg` | 6.0 over 10 s | **ours.** Placeholder. This one needs real data before it goes in a report; it is currently the weakest threshold in the system. |

## Fusion and levels

The fusion weights (`perclos` 0.35, `microsleep` 0.25, `blink_duration` 0.20,
`yawn` 0.10, `head_nod` 0.10) are **ours**, reflecting the relative evidential
strength of each measure: PERCLOS is the best-validated single indicator,
microsleeps are the most specific, yawning is suggestive but noisy, and nodding
is our least trustworthy channel. They are not fitted, and the report should
say so. Replacing them with weights learned from the session logs is the
obvious next step once there is labelled data.

Level boundaries (0.35 / 0.55 / 0.75) and dwell times are **ours**, chosen so
that the intermediate level is reachable without microsleeps while the top
level effectively requires them.

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
