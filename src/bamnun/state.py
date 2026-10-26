"""Driver state estimation.

Two independent channels, because they are different problems with different
evidence and different correct responses:

* DROWSINESS is slow. It is estimated by fusing several ocular and facial
  measures over a window of tens of seconds. Its response is escalating
  arousal plus a rest recommendation.

* DISTRACTION is fast. It is a single geometric condition, sustained: the eyes
  and head are away from the forward cone for longer than a threshold. Its
  response is immediate and stops the moment the driver looks back.

Fusing those two into one number, which many implementations do, produces a
system that either alerts late on distraction or flaps on drowsiness.

The drowsiness fusion is a transparent weighted sum of normalised sub-scores
rather than a black box. That is a deliberate choice: on a poster you can show
the contribution of each term to the final number, and a judge can interrogate
any single one of them. A learned model on top is a strictly later step, and
it should be trained on the session logs this module writes, not invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .features import FeatureFrame

# Sub-score saturation points. Each pair is (value at score 0, value at score 1).
# Sources for the anchor values are given in docs/thresholds.md.
PERCLOS_RANGE = (0.05, 0.30)          # P80 over 60 s; >0.15 is the usual drowsy mark
BLINK_DURATION_RANGE = (0.15, 0.45)   # seconds, mean normal-blink duration
MICROSLEEP_RANGE = (0.0, 2.0)         # events per 60 s
YAWN_RATE_RANGE = (0.0, 12.0)         # per hour
PITCH_STD_RANGE = (2.0, 10.0)         # degrees over 10 s


# The fused sub-scores, in a fixed order. The session CSV takes its columns
# from this, so a frame with no face (and so no components) cannot leave them
# out of the header.
COMPONENTS = ("perclos", "blink_duration", "microsleep", "yawn", "head_nod")


def _ramp(x: float, lo: float, hi: float) -> float:
    """Clamped linear map from [lo, hi] onto [0, 1]."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


@dataclass
class DriverState:
    t: float = 0.0
    score: float = 0.0                  # fused drowsiness, 0..1
    level: int = 0                      # index into the configured level list
    level_name: str = "alert"
    kss: float = 1.0                    # heuristic Karolinska Sleepiness Scale estimate
    components: dict[str, float] = field(default_factory=dict)
    distracted: bool = False
    distraction_reason: str = ""
    microsleep_now: bool = False
    face_lost: bool = False
    face_lost_s: float = 0.0
    confidence: float = 1.0
    calibrated: bool = False

    @property
    def emergency(self) -> bool:
        """Conditions that must bypass the escalation ladder entirely.

        Deliberately narrow: only a closure that is happening RIGHT NOW. An
        earlier version also treated "level 3" as an emergency, which meant
        every gradual slide into severe drowsiness skipped straight to the
        strongest stimulus. Gradual decline should climb the ladder; an eye
        that is shut at this instant should not wait for it.
        """
        return self.microsleep_now


class StateEstimator:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.weights: dict[str, float] = dict(cfg.get("weights", {}))
        total = sum(abs(v) for v in self.weights.values()) or 1.0
        self.weights = {k: v / total for k, v in self.weights.items()}

        self.levels = list(cfg.get("levels", [{"name": "alert", "min_score": 0.0, "dwell_s": 0.0}]))
        self.levels.sort(key=lambda d: float(d.get("min_score", 0.0)))
        self.hysteresis = float(cfg.get("recovery_hysteresis", 0.08))
        self.perclos_hysteresis = float(cfg.get("perclos_hysteresis", 0.02))
        self.no_face_grace_s = float(cfg.get("no_face_grace_s", 1.5))
        # MediaPipe stops finding a face somewhere past 45-50 deg of yaw, so a
        # shoulder check or a far-side mirror check ENDS in a lost face. Judged
        # by no_face_grace_s alone that reads as "driver not visible" after
        # 1.5 s, which is shorter than an ordinary blind-spot check: the system
        # accused an attentive driver of leaving the seat for doing the thing
        # the mirror is there for. A loss that begins from an already-turned
        # head is treated as the tail of that glance and gets a longer grace.
        self.turn_away_yaw_deg = float(cfg.get("turn_away_yaw_deg", 35.0))
        self.lost_glance_grace_s = float(cfg.get("lost_glance_grace_s", 4.0))
        self._last_pose_yaw = 0.0
        self._last_pose_valid = False
        # Iris offset beyond which the eyes count as off-road even though the
        # head is still forward: the phone-in-the-lap case.
        self.gaze_off_road = float(cfg.get("gaze_off_road_threshold", 0.55))

        self._level = 0
        self._candidate: Optional[int] = None
        self._candidate_since: float = 0.0
        self._face_lost_since: Optional[float] = None
        self._last_good: Optional[FeatureFrame] = None
        self._last_score = 0.0
        self._last_kss = 1.0

    # ----------------------------------------------------------------- #

    def _components(self, f: FeatureFrame) -> dict[str, float]:
        return {
            "perclos": _ramp(f.perclos, *PERCLOS_RANGE),
            "blink_duration": _ramp(f.mean_blink_duration_s, *BLINK_DURATION_RANGE),
            "microsleep": _ramp(float(f.microsleep_count), *MICROSLEEP_RANGE),
            "yawn": _ramp(f.yawn_rate_per_hour, *YAWN_RATE_RANGE),
            "head_nod": _ramp(f.pitch_std, *PITCH_STD_RANGE),
        }

    def _meets(self, lv: dict, score: float, perclos: float, slack: float = 0.0,
               perclos_slack: float = 0.0) -> bool:
        """A level is reached on the fused score OR on PERCLOS alone.

        The PERCLOS gate maps the four-stage literature scheme (5 / 10 / 15 /
        20 % PERCLOS, after Wierwille and Dinges) straight onto the levels, so
        a stage can be quoted against a published threshold. The fused score
        stays as a second route in, because it also carries blink duration,
        microsleeps, yawns and nodding, which PERCLOS does not see.
        """
        if score >= float(lv.get("min_score", 0.0)) - slack:
            return True
        gate = lv.get("min_perclos")
        return gate is not None and perclos >= float(gate) - perclos_slack

    def _resolve_level(self, t: float, score: float, force_top: bool = False,
                       perclos: float = 0.0) -> tuple[int, str]:
        """Level selection with dwell on the way up and hysteresis on the way down.

        ``force_top`` bypasses the dwell entirely. It is set while the eye is
        shut past the microsleep threshold. Without it the top level's dwell
        timer swallowed short microsleeps: a 0.6 s closure could never reach
        the level whose own dwell was 1.0 s, so the alert policy's microsleep
        override was unreachable for exactly the events it existed to catch.
        """
        target = 0
        for i, lv in enumerate(self.levels):
            if self._meets(lv, score, perclos):
                target = i

        if force_top:
            self._level = target
            self._candidate = None
            return self._level, str(self.levels[self._level].get("name", str(self._level)))

        if target > self._level:
            dwell = float(self.levels[target].get("dwell_s", 0.0))
            if self._candidate != target:
                self._candidate = target
                self._candidate_since = t
            if (t - self._candidate_since) >= dwell:
                self._level = target
                self._candidate = None
        elif target < self._level:
            # Require the evidence to fall clearly below the level we are in,
            # on both routes in.
            if not self._meets(self.levels[self._level], score, perclos,
                               slack=self.hysteresis,
                               perclos_slack=self.perclos_hysteresis):
                self._level = target
                self._candidate = None
            else:
                self._candidate = None
        else:
            self._candidate = None

        return self._level, str(self.levels[self._level].get("name", str(self._level)))

    # ----------------------------------------------------------------- #

    def update(self, f: FeatureFrame, calibrated: bool = True) -> DriverState:
        t = f.t

        if not f.face_found:
            if self._face_lost_since is None:
                self._face_lost_since = t
            lost_s = t - self._face_lost_since
            # Hold the previous state while the face is missing. A face lost
            # for longer than the grace period is itself informative: either
            # the driver has slumped out of frame or the camera is blocked,
            # and in a real product both warrant attention. It is surfaced as
            # zero confidence plus a distraction flag rather than as a new
            # drowsiness reading, because there is no ocular evidence.
            #
            # The retained score and KSS are the last measured ones, not zero.
            # Returning level="mild" alongside score=0.0 and kss=1.0, as an
            # earlier version did, put three mutually contradictory numbers on
            # the overlay at once. Confidence 0.0 is the flag that says these
            # are stale; the numbers themselves stay self-consistent.
            # Was the head already turned away when tracking dropped? Then this
            # is the far end of a glance, not an empty seat.
            turned_away = (self._last_pose_valid
                           and abs(self._last_pose_yaw) >= self.turn_away_yaw_deg)
            grace = self.lost_glance_grace_s if turned_away else self.no_face_grace_s
            if lost_s <= grace:
                reason = ""
            elif turned_away:
                reason = f"head turned away {self._last_pose_yaw:+.0f} deg"
            else:
                reason = "driver not visible"
            return DriverState(
                t=t,
                score=self._last_score,
                level=self._level,
                level_name=str(self.levels[self._level].get("name", "")),
                kss=self._last_kss,
                components={},
                distracted=lost_s > grace,
                distraction_reason=reason,
                face_lost=True,
                face_lost_s=lost_s,
                confidence=0.0,
                calibrated=calibrated,
            )

        self._face_lost_since = None
        # Remember the pose while we still have one; it is what decides, on the
        # next lost frame, whether the driver turned away or simply vanished.
        if f.pose_valid:
            self._last_pose_yaw = f.yaw
            self._last_pose_valid = True
        self._last_good = f

        comps = self._components(f)
        score = sum(self.weights.get(k, 0.0) * v for k, v in comps.items())

        # A closure in progress that has already passed the microsleep
        # threshold is not something to average into a 60 s window. Override.
        #
        # The flag comes from the BlinkTracker, which owns the configured
        # threshold. This used to be re-derived here as
        # `ongoing_closure_s >= 0.5`, a second hardcoded copy of
        # features.blink.microsleep_duration_s, so editing the config moved
        # the event classification but not the alert trigger.
        microsleep_now = f.microsleep_now
        if microsleep_now:
            score = max(score, 0.90)

        score = max(0.0, min(1.0, score))
        level, level_name = self._resolve_level(t, score, force_top=microsleep_now,
                                                perclos=f.perclos)

        # Distraction channel, independent of the score above.
        distracted = False
        reason = ""
        # Same story here: the 2-second criterion lives in
        # features.head.off_road_alert_s and is applied by the HeadTracker.
        # This branch used to compare against its own literal 2.0.
        if f.off_road_alarm:
            distracted = True
            reason = f"head off-road {f.off_road_glance_s:.1f}s"
        elif f.gaze_valid and abs(f.gaze_h) > self.gaze_off_road and not f.off_road:
            # Eyes away while the head stays forward: the phone-in-lap case.
            distracted = True
            reason = "gaze off-road"

        confidence = 1.0
        if not f.pose_valid:
            confidence *= 0.7
        if not f.gaze_valid:
            confidence *= 0.85
        if f.interocular_px < 40:
            confidence *= 0.6  # face too small for reliable eyelid geometry

        kss = 1.0 + 8.0 * score      # heuristic mapping; see docs/thresholds.md
        self._last_score = score
        self._last_kss = kss

        return DriverState(
            t=t,
            score=score,
            level=level,
            level_name=level_name,
            kss=kss,
            components=comps,
            distracted=distracted,
            distraction_reason=reason,
            microsleep_now=microsleep_now,
            face_lost=False,
            face_lost_s=0.0,
            confidence=confidence,
            calibrated=calibrated,
        )
