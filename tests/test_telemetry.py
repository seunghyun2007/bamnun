"""Live data for the app: what a snapshot may claim, and the Hub hand-off."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import Actuation, AlertDecision  # noqa: E402
from bamnun.features import BlinkTracker, FeatureFrame  # noqa: E402
from bamnun.state import DriverState  # noqa: E402
from bamnun.telemetry import STALE_AFTER_S, Hub, alert_event, build_snapshot  # noqa: E402


def snap(ff, state=None, **kw):
    args = dict(stage=0, stage_name="none", calibrated=True, calibrating=False,
                cal_progress=0.0, trip_s=12.0, fps=25.0)
    args.update(kw)
    return build_snapshot(ff, state or DriverState(t=ff.t, calibrated=True), **args)


def test_an_empty_seat_is_not_reported_as_open_eyes():
    # A FeatureFrame with no face still carries ear_norm=1.0 by default.
    s = snap(FeatureFrame(t=1.0, face_found=False))
    assert s["face"] is False
    for key in ("eye_open", "eye_closed", "blink_rate", "perclos", "off_road", "yaw"):
        assert s[key] is None, key


def test_nothing_ocular_is_reported_while_calibrating():
    s = snap(FeatureFrame(t=1.0, face_found=True), calibrating=True, cal_progress=0.4)
    assert s["calibrating"] is True and s["cal_progress"] == 0.4
    assert s["eye_open"] is None and s["perclos"] is None


def test_a_measured_frame_carries_its_values():
    ff = FeatureFrame(t=3.0, face_found=True, ear_norm=0.42, eye_closed=True,
                      blink_rate_per_min=17.0, perclos=0.061, yaw=-4.0,
                      pose_valid=True, off_road=False)
    st = DriverState(t=3.0, score=0.31, level=1, level_name="a_bit", kss=3.48,
                     calibrated=True)
    s = snap(ff, st, stage=1, stage_name="light", co2_ppm=812.4, co2_age_s=3.3,
             last_blink_s=0.183)
    assert s["eye_open"] == 0.42 and s["eye_closed"] is True
    assert s["blink_rate"] == 17.0 and s["perclos"] == 0.061
    assert s["yaw"] == -4.0 and s["off_road"] is False
    assert (s["stage"], s["stage_name"], s["level"], s["kss"]) == (1, "light", 1, 3.5)
    assert s["co2_ppm"] == 812 and s["last_blink_s"] == 0.18
    assert s["cal_progress"] is None


def test_a_snapshot_is_plain_json():
    s = snap(FeatureFrame(t=1.0, face_found=True, ear_norm=0.9))
    assert json.loads(json.dumps(s)) == s


def test_alert_event_names_the_change_and_what_fired():
    d = AlertDecision(t=5.0, stage=2, stage_name="scent", changed=True,
                      fired=[Actuation(5.0, "blue_light", "scent"),
                             Actuation(5.0, "scent", "scent")],
                      message="microsleep override")
    e = alert_event(d, previous_stage=1)
    assert e["type"] == "alert" and e["stage"] == 2 and e["previous"] == 1
    assert e["fired"] == ["blue_light", "scent"] and e["reason"] == "microsleep override"


def test_hub_hands_each_client_only_newer_events():
    hub = Hub()
    hub.emit({"type": "alert", "stage": 1})
    seen = hub.seq
    hub.emit({"type": "alert", "stage": 2})
    hub.emit({"type": "alert", "stage": 3})
    assert [e["stage"] for e in hub.events_after(seen)] == [2, 3]
    assert hub.events_after(hub.seq) == []


def test_hub_marks_a_snapshot_stale_once_the_loop_stops_publishing(monkeypatch):
    hub = Hub()
    assert hub.latest() is None
    hub.publish({"type": "snapshot"})
    assert hub.latest()["stale"] is False and hub.health()["camera_live"] is True
    later = time.monotonic() + STALE_AFTER_S + 1.0
    monkeypatch.setattr("bamnun.telemetry.time.monotonic", lambda: later)
    assert hub.latest()["stale"] is True
    assert hub.health()["camera_live"] is False


def test_publishing_never_waits_on_a_reader():
    # A reader holding the Hub for a long time must not be possible: every
    # read copies under the lock and returns. Hammer it from another thread
    # and check the writer keeps its pace.
    hub = Hub()
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            hub.latest()
            hub.events_after(0)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    t0 = time.perf_counter()
    for i in range(2000):
        hub.publish({"type": "snapshot", "i": i})
        if i % 100 == 0:
            hub.emit({"type": "alert", "stage": i % 5})
    elapsed = time.perf_counter() - t0
    stop.set()
    th.join(1.0)
    assert elapsed < 1.0, f"2000 publishes took {elapsed:.2f}s"


def test_blink_tracker_remembers_the_last_ordinary_blink():
    bt = BlinkTracker({"blink": {}})
    # Shut at t=0.2, open again at t=0.4: a 0.2 s blink.
    for t, ear in ((0.1, 0.30), (0.2, 0.10), (0.3, 0.10), (0.4, 0.30)):
        bt.update(t, ear, 0.30)
    assert bt.last_blink_s is not None and abs(bt.last_blink_s - 0.2) < 1e-6
    bt.reset()
    assert bt.last_blink_s is None


def test_video_is_wanted_only_while_someone_watches():
    hub = Hub()
    assert not hub.wants_video()
    hub.add_viewer()
    hub.add_viewer()
    hub.publish_frame(b"jpeg-1")
    hub.remove_viewer()
    assert hub.wants_video() and hub.latest_frame() == (1, b"jpeg-1")
    hub.remove_viewer()
    assert not hub.wants_video()
    # The last viewer leaving drops the picture: nothing of the driver lingers.
    assert hub.latest_frame()[1] is None
    hub.remove_viewer()                      # an extra remove never goes negative
    assert not hub.wants_video()


def test_snapshots_and_health_say_whether_there_is_video():
    hub = Hub()
    hub.publish({"type": "snapshot"})
    assert hub.latest()["video"] is False and hub.health()["video"] is False
    hub.video_capable = True
    assert hub.latest()["video"] is True and hub.health()["video"] is True
