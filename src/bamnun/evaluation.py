"""Score the detection pipeline against the scenarios (and labelled recordings).

    python tools/evaluate_detection.py            # full table, every eye type
    python tools/evaluate_detection.py --quick    # the subset the tests run

Per case it reports:

* detection rate   drowsy cases: the share of events caught in time. A
                   gradual case or a nod counts when the drowsiness level
                   reaches 1 (ladder step 1, blue light) within its window; a
                   microsleep only when the ladder reaches its TOP step
                   within 1.5 s, because that is the safety bypass.
* false alarms/h   not-drowsy cases: how often the drowsiness ladder starts
                   (step 0 -> 1 or higher), per hour. The separate glance
                   nudge for looking away is not a false alarm.
* reaction s       median seconds from the event's onset to the catch.
* rest score       median 0-100 score over the case, for the "alert drivers
                   sit near 0-10" check.

The pipeline adapter mirrors the device: the first CAL_LOOK_S of every
scenario is the look-ahead calibration, the closed-eyes step follows with the
ladder held, then detection runs.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .alerts import EscalationPolicy
from .features import FeatureExtractor, FeatureFrame, HeadPose
from .scenarios import CAL_LOOK_S, LEAD_S, Frame, Scenario
from .session import load_config
from .state import StateEstimator


@dataclass
class Out:
    t: float
    score: float
    level: int
    label: str
    stage: int
    microsleep: bool


class Pipeline:
    """The device's detection chain, driven by scenario frames."""

    def __init__(self, cfg: Optional[dict] = None) -> None:
        cfg = cfg or load_config()
        self.cfg = cfg
        self.fx = FeatureExtractor(cfg["features"], cfg["calibration"])
        self.est = StateEstimator(cfg["state"])
        alerts = {**cfg["alerts"], "actuators": {k: {**v, "type": "null"} for k, v in cfg["alerts"]["actuators"].items()}}
        self.policy = EscalationPolicy(alerts)
        self.top = len(self.policy.stages) - 1
        self._cal_started = False

    def _measure(self, f: Frame) -> FeatureFrame:
        if not f.face:
            no_face = getattr(self.fx, "no_face", None)
            return no_face(f.t) if no_face else FeatureFrame(t=f.t, face_found=False)
        pose = HeadPose(f.yaw, f.pitch, f.roll, True)
        extra = getattr(self.fx, "accepts_extra", False)
        if extra:
            return self.fx.measure(f.t, max(f.ear_l, f.ear_r), f.mar, pose, (0.0, 0.0, True), f.iod, extra=f)
        return self.fx.measure(f.t, max(f.ear_l, f.ear_r), f.mar, pose, (0.0, 0.0, True), f.iod)

    def step(self, f: Frame) -> Optional[Out]:
        if f.phase == "look":
            if not self._cal_started:
                self._cal_started = True
                self.fx.calibrator.duration_s = CAL_LOOK_S - 0.2
                self.fx.start_calibration(f.t)
            self._measure(f)
            return None
        if f.phase == "close":
            hook = getattr(self.fx, "calibrate_closed", None)
            if hook is not None:
                hook(f.t, f)
            self._closing = True
            return None                           # the ladder holds during this step
        if getattr(self, "_closing", False):
            self._closing = False
            end = getattr(self.fx, "end_closed", None)
            if end is not None:
                self.cal_result = end()
        ff = self._measure(f)
        st = self.est.update(ff, calibrated=self.fx.calibration.complete)
        d = self.policy.update(st)
        return Out(f.t, st.score, st.level, getattr(st, "label", ""), d.stage, bool(ff.microsleep_now))


def run(sc: Scenario, cfg: Optional[dict] = None) -> list[Out]:
    p = Pipeline(cfg)
    return [o for o in (p.step(f) for f in sc.frames) if o is not None]


@dataclass
class CaseResult:
    name: str
    eyes: str
    drowsy: bool
    events: int = 0
    caught: int = 0
    latencies: list[float] = field(default_factory=list)
    false_alarms: int = 0
    body_h: float = 0.0
    rest_score: float = 0.0
    p90_score: float = 0.0
    time_flagged: float = 0.0      # share of the body at drowsiness level >= 1


def score_case(sc: Scenario, outs: list[Out], top: int = 4) -> CaseResult:
    body = [o for o in outs if o.t >= LEAD_S]
    r = CaseResult(sc.name, sc.eyes, sc.drowsy, body_h=max(1e-9, sc.body_s / 3600.0))
    if body:
        scores = sorted(o.score for o in body)
        r.rest_score = 100 * scores[len(scores) // 2]
        r.p90_score = 100 * scores[int(len(scores) * 0.9)]
        r.time_flagged = sum(1 for o in body if o.level >= 1) / len(body)
        prev = 0
        for o in body:
            if prev == 0 and o.stage >= 1:
                r.false_alarms += 1
            prev = o.stage
    for ev in sc.events:
        r.events += 1
        hit = None
        for o in body:
            if o.t < ev.onset:
                continue
            if o.t > ev.onset + ev.window:
                break
            if (ev.kind == "microsleep" and o.stage >= top) or (ev.kind != "microsleep" and o.level >= 1):
                hit = o.t
                break
        if hit is not None:
            r.caught += 1
            r.latencies.append(hit - ev.onset)
    if sc.drowsy:
        r.false_alarms = 0          # alarms are the point in a drowsy case
    return r


def evaluate(cases: Iterable[Scenario], cfg: Optional[dict] = None) -> list[CaseResult]:
    cfg = cfg or load_config()
    top = len(cfg["alerts"]["stages"]) - 1
    return [score_case(sc, run(sc, cfg), top) for sc in cases]


def summarise(results: list[CaseResult]) -> list[dict[str, Any]]:
    """One row per case name, pooled over eye types and seeds."""
    rows = []
    for name in dict.fromkeys(r.name for r in results):
        rs = [r for r in results if r.name == name]
        drowsy = rs[0].drowsy
        ev = sum(r.events for r in rs)
        lat = [x for r in rs for x in r.latencies]
        hours = sum(r.body_h for r in rs)
        rows.append({
            "case": name, "drowsy": drowsy,
            "detection": (sum(r.caught for r in rs) / ev) if ev else None,
            "missed_eyes": sorted({r.eyes for r in rs if r.events and r.caught < r.events}),
            "reaction_s": round(statistics.median(lat), 1) if lat else None,
            "false_alarms_h": round(sum(r.false_alarms for r in rs) / hours, 1) if not drowsy else None,
            "rest_score": round(statistics.median(r.rest_score for r in rs), 1),
            "p90_score": round(max(r.p90_score for r in rs), 1),
            "time_flagged": round(100 * statistics.mean(r.time_flagged for r in rs), 1),
        })
    return rows


def table(rows: list[dict[str, Any]]) -> str:
    lines = ["| Case | Kind | Detection | Reaction (s) | False alarms / h | Rest score | p90 score | Time flagged |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        det = "–" if r["detection"] is None else f"{100 * r['detection']:.0f} %"
        if r["missed_eyes"]:
            det += f" (missed: {', '.join(r['missed_eyes'])})"
        lines.append(f"| {r['case']} | {'drowsy' if r['drowsy'] else 'not drowsy'} | {det} | "
                     f"{'–' if r['reaction_s'] is None else r['reaction_s']} | "
                     f"{'–' if r['false_alarms_h'] is None else r['false_alarms_h']} | "
                     f"{r['rest_score']} | {r['p90_score']} | {r['time_flagged']} % |")
    return "\n".join(lines)
