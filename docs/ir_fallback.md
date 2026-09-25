# If MediaPipe does not track reliably on NoIR imagery

## The risk

MediaPipe's Face Landmarker is trained on visible-light RGB faces. A NoIR
image under 850 or 940 nm illumination is out of that distribution: skin is
uniformly bright and low-contrast, eyebrows and lashes lose most of their
contrast against skin, the sclera/iris boundary changes appearance, and there
is no colour information at all. It generally still tracks, which is why this
is the primary path, but detection confidence drops and the failure is not
graceful: when it loses the face it loses everything downstream.

Test this on day one of having the camera. Run `tools/bench.py` and look at
the reported face-detection percentage. Below about 90% under your intended
mounting geometry and lighting, work the list below before reaching for a
different model.

## Cheap fixes, in the order to try them

1. **Pin the focus.** `tools/focus_sweep.py`. An autofocus module hunting at
   50 cm in a low-contrast scene is the most likely cause of intermittent
   tracking, and it costs nothing to rule out.

2. **Fix exposure and gain, and check for saturation.** IR illumination from
   close range blows out the forehead and the bridge of the nose while leaving
   the eye sockets dark. The fix is geometric, not computational: move the
   emitters further back and use more of them, diffused. Aim for a mean frame
   brightness around 90–130 with under 1% saturated pixels.

3. **Use several diffuse emitters, not one.** Two or three emitters at 40 cm+,
   off-axis from the lens, give far flatter illumination than one bright LED
   beside the lens. This also reduces the corneal hot spot that confuses iris
   landmarks, and it is better for eye safety.

4. **Avoid the on-axis retroreflection.** An emitter very close to the optical
   axis produces bright-pupil (red-eye) retinal return; further off-axis gives
   dark-pupil. Dark-pupil is what the model expects, since that is what visible
   light normally produces.

5. **CLAHE before inference.** Contrast-limited adaptive histogram
   equalisation on the grayscale frame, converted back to three channels, is
   two lines of OpenCV and often recovers most of the lost confidence:

   ```python
   clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
   gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
   rgb = cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2RGB)
   ```

   Measure detection rate with and without, and report the delta. It is a
   small, honest, quantified engineering contribution.

## If those are not enough: the two-stage fallback

Keep coarse face localisation, replace only the eye-state decision. Coarse
localisation is the robust part; it is the fine eyelid geometry that degrades.

1. **Face box.** MediaPipe Face Detector (BlazeFace, `face_detector.task`) is
   markedly more robust than the full landmark mesh because it only has to
   find a face-shaped blob. Or Haar/LBP cascades, which are old but were
   designed for grayscale and work fine here.

2. **Eye crops.** Take the eye regions from the detector's keypoints, or from
   fixed proportions of the face box.

3. **Open/closed classifier trained on IR.** The **MRL Eye Dataset** is the
   right resource: roughly 85,000 cropped human eye images captured in
   infrared, labelled for open/closed, and it includes glasses and reflection
   variants, which is exactly the failure mode that worries us. A small CNN
   (three conv blocks on 24×24 or 32×32 grayscale crops) reaches high accuracy
   on it and runs in under a millisecond per eye on a Pi 5.

Note what this costs, and be honest about it in the report: a binary
open/closed classifier gives you PERCLOS and blink timing, which is most of
the drowsiness signal, but it does **not** give you eyelid aperture as a
continuous value, nor head pose, nor gaze. So the distraction channel would
need the landmark mesh anyway, or a separate head-pose estimator. The sensible
architecture is therefore hybrid: landmarks for pose and gaze, where
occasional dropouts are tolerable, and the IR-trained classifier for eye state,
where they are not.

## Why this is a good thing to have written down

Two reasons, both worth saying out loud at the exhibition. First, it is the
honest answer to "what if your model does not work on infrared?", which is the
sharpest question a technical judge can ask about this project, and having a
specific, costed, dataset-backed answer is much stronger than confidence.
Second, the reason the fallback is cheap is the layered architecture: only
`landmarks.py` and the eye-state part of `features.py` would change, and the
state estimation, prediction and alert policy are untouched. That is a
structural argument for the design, and it is the kind of thing that
distinguishes a built system from a demo.
