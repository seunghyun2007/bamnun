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
| `ear_shut_fraction` | 0.40 | "Really shut", separate from the blink threshold. A closed eye's EAR is roughly a third of its open value (our bench sessions; see the PERCLOS note in the config), so below 40 % the lids are closed rather than narrowed. Microsleeps and PERCLOS use this line. **Why it exists:** with only the 0.65 blink line, a hard squint held for 0.5 s counted as a microsleep and sent the ladder straight to its top stage. Now a squint is scored gradually (below) and only shut eyes take the bypass. **ours**, tune per driver once the guided calibration stores a closed-eye EAR. |

## PERCLOS

| Parameter | Value | Basis |
|---|---|---|
| `perclos_baseline_fraction` | 0.40 of open EAR | PERCLOS is conventionally P80, the share of time the eyes are more than 80 % closed (Wierwille et al. 1994 for the FHWA; Dinges & Grace 1998, who found it the best-correlated single ocular measure of lapses). EAR never reaches zero on a shut eye, so "80 % closed" is not "EAR below 20 %". The value was 0.80 originally (counted eyes only ~30 % closed), then 0.50 after the bench sessions (see the config comment), and is now 0.40, the same "really shut" line as `ear_shut_fraction`. At 0.50 a hard squint counted as closed on every frame and PERCLOS read 100 %. |
| `perclos_window_s` | 60 | Standard. One minute is the usual PERCLOS integration window. |
| `ranges.perclos` | 0.03 → 0 and 0.20 → 1 | Under the stricter "really shut" definition, alert drivers sit at 1–2 % (bench sessions). 0.15 is the usual drowsy criterion; 0.20 saturates. Anchors **ours**. |
| PERCLOS gates on the levels (`min_perclos`) | 5 / 10 / 15 / 20 % | The four-stage stratification in the team research doc (KSS 6–9 at PERCLOS 5–20 %). Kept: with the stricter definition they only open for real closures, not squints. |

## Squint (eye openness)

| Parameter | Value | Basis |
|---|---|---|
| `openness_window_s` | 45 s | **ours.** Long enough that one narrowed glance doesn't count, short enough to follow a slide into drowsiness within a minute. |
| `openness_percentile` | 60th | **ours.** Blinks take ~3 % of frames and pull a plain average down; a percentile above the median ignores them but follows a held squint. |
| `ranges.squint` | 1 − openness: 0.10 → 0, 0.40 → 1 | Reduced lid opening between blinks is an early drowsiness sign (Caffier et al. 2003 report lower lid opening alongside longer blinks; Johns et al. 2007 use partial closures in the Johns Drowsiness Scale). The anchors are **ours**: 10 % is normal variation in EAR from posture and expression, 40 % narrower than the driver's own open level is a sustained heavy squint. Relative to the driver's calibrated level, so glasses and naturally narrow eyes are not mistaken for squinting. |
| `look_down_pitch_deg` | 12° | The upper lid follows vertical gaze: looking down lowers it substantially with no drowsiness at all (Becker & Fuchs 1988, lid–eye coordination). Head pitch past 12° below the calibrated straight-ahead marks a look at the dashboard; those frames are left out of squint, PERCLOS and the blink averages. **ours** as a number; tune on the real mount. |

## Blinks

| Parameter | Value | Basis |
|---|---|---|
| `min_duration_s` | 0.05 | Physiological floor. Voluntary blinks do not complete in under ~50 ms, so anything shorter is landmark noise. |
| `max_normal_duration_s` | 0.40 | Normal spontaneous blink duration is roughly 100–400 ms; longer closures are a distinct category. |
| `microsleep_duration_s` | 0.50 | **ours, conservative.** Definitions of microsleep in the literature range from 0.5 s to 15 s of behavioural sleep. We take the low end deliberately: the cost of acting on a 0.5 s closure is one chime, the cost of missing a real one can be a lane departure. Worth stating in the report that our "microsleep" is the conservative end of the definition. |
| `microsleep_looking_down_s` | 1.5 s | **ours.** With the head pitched down (phone, keyboard, low dashboard) the lids can close almost completely while awake, which our own webcam test showed: a glance at the keyboard read as a microsleep. Requiring 1.5 s shut while looking down removes that, and a head dropping forward with the eyes shut (nodding off) still passes it within two seconds. Covered by tests both ways. |
| `ranges.blink_duration` | 0.15 → 0, 0.35 s → 1 | Normal spontaneous blinks last about 0.10–0.15 s at the closure threshold we measure them at; blink duration lengthens with sleepiness and correlates with KSS (Ingre et al. 2006; Schleicher et al. 2008; Caffier et al. 2003). Measured between our 0.65 / 0.75 thresholds, a 0.4 s blink reads about 0.33 s, hence the 0.35 s saturation. **ours** as anchors. |
| `slow_blink_s` / `ranges.slow_blinks` | 0.30 s; share 0.10 → 0, 0.50 → 1 | Blinks of 0.3 s or more are a recognised early sign of sleepiness (Schleicher et al. 2008 describe the growth of these long blinks before lapses). The share, not the count, so a high or low blink rate doesn't distort it. Anchors **ours**. |
| `ranges.lid_speed` | reopening 0.10 → 0, 0.30 s → 1 | Drowsy eyelids reopen slowly: Johns et al. 2007 base their drowsiness scale on the amplitude–velocity ratio of reopening, and Caffier et al. 2003 report prolonged reopening times. We measure from the deepest point back to open. Anchors **ours**. |
| `ranges.blink_rate` | 24 → 0, 40 /min → 1 | Blink rate rises with fatigue (Stern et al. 1994) but varies widely between people, so it gets the smallest weight. **ours**. |
| `min_blinks_for_stats` | 5 | **ours.** Fewer blinks than this in the last minute and the blink averages read "no evidence" (0), not "fast". 3 was too few: two odd blinks moved the score by 20 points in our webcam test. |
| `max_blink_stat_s` | 1.0 s | **ours.** A "closure" longer than this is a held squint or a look down, not a blink, and is kept out of the blink averages. |
| `eyes_closed_label_s` | 0.30 s | **ours.** The app shows "Eyes closed" only after this long shut, so a normal blink never flashes it. |

## Head and gaze

| Parameter | Value | Basis |
|---|---|---|
| `off_road_alert_s` | 2.0 | NHTSA's visual-manual driver distraction guidelines treat single off-road glances longer than 2 s as the risk criterion; this also matches the Klauer/Dingus 100-car naturalistic study finding that eyes-off-road beyond about 2 s sharply raises crash risk. Citable, not invented. |
| `yaw_limit_deg` / `pitch_limit_deg` | 25 / 20 | **ours.** A rough forward gaze cone, measured relative to the calibration pose, not to the camera. Should be tuned once the camera is on its real mount, and the tuned value reported. |
| `nod_pitch_std_deg` | 6.0 over 10 s | **ours.** Placeholder. This one needs real data before it goes in a report; it is currently the weakest threshold in the system. |

## Fusion and levels

The drowsiness score is a weighted sum of nine sub-scores, each a clamped
linear ramp between the two anchors in `state.ranges`:

| Weight | Signal | Why this much |
|---|---|---|
| 0.28 | squint | Eye-closure measures are the best single predictors; squint is the gradual one, so it carries the most. |
| 0.20 | PERCLOS | The best-validated single indicator (Dinges & Grace 1998). |
| 0.15 | blink duration | Rises early and correlates with KSS (Ingre et al. 2006). |
| 0.12 | slow blinks | Early sign; complements the average. |
| 0.09 | microsleeps in the last minute | Very specific, but also handled by the bypass, so not weighted heavily here. |
| 0.06 | lid reopening time | Early sign (Johns et al. 2007), noisier on a webcam. |
| 0.04 | yawns | Suggestive but noisy. |
| 0.04 | head nodding | Our least trustworthy channel. |
| 0.02 | blink rate | Varies most between people. |

All weights and anchors are **ours**, not fitted, and the report should say
so. `tools/record_session.py` and `tools/replay_session.py` exist to tune them
against recorded sessions; learning them from labelled sessions is the next
step.

**Smoothing** (`score_rise_tau_s` 6 s, `score_fall_tau_s` 20 s, **ours**): the
score moves towards the raw sum exponentially, faster up than down. Drowsiness
builds over minutes and doesn't vanish when the driver opens their eyes wide
for a second; the slow fall also stops the ladder flickering between stages.

**Levels** (`min_score` 0.25 / 0.45 / 0.65 / 0.82, **ours**), each entered
after a short dwell and left only below the threshold minus
`recovery_hysteresis` (0.08). Level 1 fires stage 1 (blue light) and so on.
Chosen so that a single mild sign (a held squint, a minute of slow blinks)
reaches level 1 and no further, two or more together reach level 2, and the
top levels need strong or sustained evidence. The tests in
`tests/test_gradual.py` pin those cases.

**Safety bypass:** eyes really shut (below `ear_shut_fraction`) for
`microsleep_duration_s` sets the score to at least `microsleep_score` (0.90)
and jumps the ladder to its top stage at once, as before.

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
