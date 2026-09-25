"""bamnun: low-cost IR driver state monitoring for the Raspberry Pi 5.

Layering, from sensor to actuator:

    capture     -> Frame           pixels plus a monotonic clock
    landmarks   -> LandmarkResult  478 facial points
    features    -> FeatureFrame    EAR, PERCLOS, blinks, pose, gaze, yawns
    state       -> DriverState     fused drowsiness + independent distraction
    predictor   -> RestPlan        forward projection and rest timing
    alerts      -> AlertDecision   graded escalation across actuators

Each layer depends only on the one above it, so any layer can be replaced
without touching the others. That is what makes it possible to swap the
hand-weighted fusion in ``state`` for a learned model trained on the logs
without rewriting the pipeline.
"""

__version__ = "0.1.0"

__all__ = [
    "capture",
    "landmarks",
    "features",
    "state",
    "predictor",
    "alerts",
    "session",
    "viz",
]
