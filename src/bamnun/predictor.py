"""Forward prediction of driver state, and rest planning.

This is the part of the project that earns the phrase "AI powered" honestly,
and it is worth being precise about what it does.

It does NOT predict drowsiness from a single frame. Nothing can. What it does
is combine two sources of forward information:

  (a) The MEASURED trend. The fused drowsiness score is a noisy time series.
      A robust slope fit over the last several minutes extrapolates it. This
      is the driver in front of the camera, right now, and it is the term that
      makes the prediction personal.

  (b) A PHYSIOLOGICAL PRIOR. Alertness is not a random walk; it follows a
      well-characterised two-process shape, a homeostatic component that rises
      monotonically with time awake and a circadian component with a 24-hour
      fundamental and a 12-hour harmonic that produces the early-afternoon
      dip. This is the classical Akerstedt-Folkard form, reduced to the two
      terms that can be evaluated from a clock and one user input.

The extrapolation of (a) alone is useless beyond a couple of minutes, because
a linear fit to a bounded noisy signal happily predicts a score of 4.0 in an
hour. The prior (b) alone ignores the actual driver. Blending them gives a
curve that bends the population shape toward the measured evidence, which is
the standard structure for this kind of problem and is easy to defend.

The output is a rest plan: when the driver is predicted to cross the unsafe
threshold, and therefore when they should stop. That is the deliverable a
judge can act on, as opposed to another number on a dashboard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np

from .features import TimeWindow


def theil_sen_slope(t: np.ndarray, y: np.ndarray, max_pairs: int = 4000,
                    rng: Optional[np.random.Generator] = None) -> tuple[float, float]:
    """Robust (slope, intercept) via the median of pairwise slopes.

    Implemented directly rather than pulled from SciPy so that the Pi install
    does not need SciPy at runtime, and so the report can state exactly what
    the estimator is. Robustness matters here: a single 10 s microsleep
    override pins the score at 0.9 and would drag a least-squares slope into
    nonsense.
    """
    n = len(t)
    if n < 3:
        return (0.0, float(y.mean()) if n else 0.0)

    rng = rng or np.random.default_rng(0)
    n_all = n * (n - 1) // 2
    if n_all <= max_pairs:
        i, j = np.triu_indices(n, k=1)
    else:
        i = rng.integers(0, n, size=max_pairs)
        j = rng.integers(0, n, size=max_pairs)
        keep = i != j
        i, j = i[keep], j[keep]

    dt = t[j] - t[i]
    ok = np.abs(dt) > 1e-9
    if not np.any(ok):
        return (0.0, float(y.mean()))
    slopes = (y[j][ok] - y[i][ok]) / dt[ok]
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * t))
    return (slope, intercept)


def two_process_alertness(hours_awake: float, local_hour: float,
                          tau_h: float = 10.0, amplitude: float = 0.12,
                          peak_hour: float = 16.5) -> float:
    """Predicted baseline drowsiness in 0..1 from time awake and clock time.

    Homeostatic term saturates as 1 - exp(-t/tau). Circadian term is a
    24-hour cosine plus a 12-hour harmonic at 30% weight, which is what
    produces the post-lunch dip rather than a single smooth arc.
    """
    homeostatic = 1.0 - math.exp(-max(hours_awake, 0.0) / max(tau_h, 1e-3))
    phase = 2.0 * math.pi * (local_hour - peak_hour) / 24.0
    circadian = amplitude * (math.cos(phase) + 0.30 * math.cos(2.0 * phase))
    return max(0.0, min(1.0, homeostatic - circadian))


@dataclass
class RestPlan:
    valid: bool = False
    reason: str = "insufficient history"
    current_score: float = 0.0
    slope_per_min: float = 0.0
    time_to_unsafe_s: Optional[float] = None
    recommend_rest_now: bool = False
    rest_at_s: Optional[float] = None          # seconds from now
    rest_duration_min: int = 20
    horizon_s: float = 0.0
    curve_t_s: list[float] = field(default_factory=list)
    curve_score: list[float] = field(default_factory=list)
    confidence: float = 0.0
    unsafe_fraction: float = 0.0     # share of the trend window spent unsafe

    def summary(self) -> str:
        if not self.valid:
            return f"rest plan unavailable ({self.reason})"
        if self.recommend_rest_now:
            return "stop and rest now"
        if self.rest_at_s is None:
            return "no rest needed within the prediction horizon"
        mins = int(round(self.rest_at_s / 60.0))
        return f"plan a {self.rest_duration_min} min rest in about {mins} min"


class RestPlanner:
    """Maintains score history and produces a rest plan on demand."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.enabled = bool(cfg.get("enabled", True))
        self.window = TimeWindow(float(cfg.get("trend_window_s", 600.0)))
        self.min_history_s = float(cfg.get("min_history_s", 120.0))
        self.unsafe = float(cfg.get("unsafe_score", 0.55))
        self.w_measured = float(cfg.get("blend_measured_weight", 0.7))
        # e-folding distance over which the measured slope hands authority to
        # the physiological prior. 30 min: the measured trend is good for the
        # next half hour and speculative beyond it.
        self.measured_decay_tau_s = float(cfg.get("measured_decay_tau_s", 1800.0))
        self.tau_h = float(cfg.get("homeostatic_tau_h", 10.0))
        self.amp = float(cfg.get("circadian_amplitude", 0.12))
        self.peak_hour = float(cfg.get("circadian_peak_hour", 16.5))
        self.min_lead_s = float(cfg.get("min_rest_lead_time_s", 300.0))
        # Share of the trend window above the unsafe threshold that forces a
        # "rest now" regardless of the fitted trend.
        self.unsafe_exposure_fraction = float(cfg.get("unsafe_exposure_fraction", 0.20))
        self.cap_s = float(cfg.get("rest_interval_cap_s", 7200.0))

        # Driver-supplied context. Defaults assume a normal wake time; the app
        # exposes --hours-awake so the demo can set it truthfully.
        self.hours_awake_at_start = 8.0
        self._t0: Optional[float] = None
        self._wall_t0 = datetime.now()

    def set_driver_context(self, hours_awake: float) -> None:
        self.hours_awake_at_start = max(0.0, float(hours_awake))

    def push(self, t: float, score: float) -> None:
        if self._t0 is None:
            self._t0 = t
            self._wall_t0 = datetime.now()
        self.window.push(t, score)

    # ----------------------------------------------------------------- #

    def _model_at(self, elapsed_s: float, ahead_s: float) -> float:
        hours_awake = self.hours_awake_at_start + (elapsed_s + ahead_s) / 3600.0
        wall = self._wall_t0.hour + self._wall_t0.minute / 60.0 + (elapsed_s + ahead_s) / 3600.0
        return two_process_alertness(
            hours_awake, wall % 24.0, self.tau_h, self.amp, self.peak_hour
        )

    def plan(self, t: float, step_s: float = 60.0) -> RestPlan:
        if not self.enabled:
            return RestPlan(valid=False, reason="disabled")
        if self.window.span_s < self.min_history_s:
            return RestPlan(
                valid=False,
                reason=f"need {self.min_history_s:.0f}s of history, have {self.window.span_s:.0f}s",
                current_score=float(self.window.values()[-1]) if self.window.span_s > 0 else 0.0,
            )

        ts = self.window.times()
        ys = self.window.values()
        slope, intercept = theil_sen_slope(ts - ts[0], ys)
        # "Current" is the median over the last minute, not over a fixed
        # fraction of the buffer. With microsleep overrides pinning the score
        # at 0.9 the signal is heavy-tailed, and a fraction-of-buffer window
        # changes length with the session, which made the reported value
        # quietly less stable the longer the drive went on.
        recent = ys[ts >= (ts[-1] - 60.0)]
        current = float(np.median(recent if len(recent) >= 3 else ys[-3:]))
        elapsed = t - (self._t0 or t)

        # Sustained-exposure rule, independent of the trend.
        #
        # A driver who has spent a large share of the last ten minutes above
        # the unsafe threshold needs to stop, and the slope has nothing to say
        # about it: once the score is oscillating between 0.4 and 0.9 the fit
        # can easily come out negative, and an earlier version of this code
        # cheerfully reported "no rest needed" to a driver who had just logged
        # twenty microsleeps. Exposure is the safety net under the prediction.
        unsafe_fraction = self.window.time_fraction_above(self.unsafe)

        # Blend the two sources at the level of SLOPE, not level, and
        # integrate forward from the measured value.
        #
        # The obvious implementation blends the two predicted levels with a
        # weight that decays with distance. It is wrong twice over. It puts a
        # step discontinuity at the present, because the model's absolute
        # level has no reason to equal the measurement's; and because the
        # weight decays while the model's level stays flat, the blended curve
        # bends back DOWN, so a driver measurably deteriorating at 0.03 per
        # minute is told there is no need to rest for two hours. Blending
        # slopes removes both problems: the curve starts exactly at the
        # measured value, stays monotone when both slopes are positive, and
        # hands authority over the far future to the physiological model
        # without ever contradicting the near-term evidence.
        w = max(0.0, min(1.0, self.w_measured))
        curve_t: list[float] = []
        curve_y: list[float] = []
        cross: Optional[float] = None

        y = current
        n_steps = int(self.cap_s / step_s) + 1
        for k in range(n_steps):
            ahead = k * step_s
            curve_t.append(ahead)
            curve_y.append(y)
            if cross is None and y >= self.unsafe and ahead > 0:
                cross = ahead

            # Local slope of the physiological prior, by finite difference.
            m0 = self._model_at(elapsed, ahead)
            m1 = self._model_at(elapsed, ahead + step_s)
            model_slope = (m1 - m0) / step_s

            # Authority of the measured slope decays with prediction distance.
            w_eff = w * math.exp(-ahead / self.measured_decay_tau_s)
            eff_slope = w_eff * slope + (1.0 - w_eff) * model_slope
            y = max(0.0, min(1.0, y + eff_slope * step_s))

        # Confidence: more history and a steadier slope mean more trust.
        resid = ys - (intercept + slope * (ts - ts[0]))
        noise = float(np.std(resid)) + 1e-6
        span_factor = min(1.0, self.window.span_s / (self.min_history_s * 3.0))
        conf = max(0.0, min(1.0, span_factor * (1.0 - min(1.0, noise / 0.25))))

        if current >= self.unsafe:
            return RestPlan(
                valid=True, reason="already unsafe", current_score=current,
                slope_per_min=slope * 60.0, time_to_unsafe_s=0.0,
                recommend_rest_now=True, rest_at_s=0.0, horizon_s=self.cap_s,
                curve_t_s=curve_t, curve_score=curve_y, confidence=conf,
                unsafe_fraction=unsafe_fraction,
            )

        if unsafe_fraction >= self.unsafe_exposure_fraction:
            return RestPlan(
                valid=True,
                reason=(f"unsafe for {unsafe_fraction*100:.0f}% of the last "
                        f"{self.window.span_s/60:.0f} min"),
                current_score=current, slope_per_min=slope * 60.0,
                time_to_unsafe_s=0.0, recommend_rest_now=True, rest_at_s=0.0,
                horizon_s=self.cap_s, curve_t_s=curve_t, curve_score=curve_y,
                confidence=conf, unsafe_fraction=unsafe_fraction,
            )

        if cross is None:
            return RestPlan(
                valid=True, reason="no crossing within horizon", current_score=current,
                slope_per_min=slope * 60.0, time_to_unsafe_s=None,
                recommend_rest_now=False, rest_at_s=None, horizon_s=self.cap_s,
                curve_t_s=curve_t, curve_score=curve_y, confidence=conf,
                unsafe_fraction=unsafe_fraction,
            )

        # Recommend stopping with a margin before the predicted crossing, so
        # the driver acts while still competent rather than at the threshold.
        margin = max(300.0, 0.15 * cross)
        rest_at = max(0.0, cross - margin)
        return RestPlan(
            valid=True,
            reason="ok",
            current_score=current,
            slope_per_min=slope * 60.0,
            time_to_unsafe_s=cross,
            recommend_rest_now=rest_at < self.min_lead_s,
            rest_at_s=rest_at,
            rest_duration_min=20,   # short-nap literature: 20 min avoids deep-sleep inertia
            horizon_s=self.cap_s,
            curve_t_s=curve_t,
            curve_score=curve_y,
            confidence=conf,
            unsafe_fraction=unsafe_fraction,
        )
