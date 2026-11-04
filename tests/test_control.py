"""Profile and trip storage, the controller, and the API the phone uses.

docs/SPEC.md, sections 1-9b. Everything runs on stub actuators and an
in-memory or temporary database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import AudioActuator, EscalationPolicy  # noqa: E402
from bamnun.control import STEP_KEYS, Controller  # noqa: E402
from bamnun.session import load_config  # noqa: E402
from bamnun.state import StateEstimator  # noqa: E402
from bamnun.store import InvalidUpdate, Store  # noqa: E402
from bamnun.telemetry import Hub  # noqa: E402
from bamnun.trips import TripConfig, TripTracker, insights  # noqa: E402
from bamnun.voice import LINES, Speaker  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def stub_policy() -> EscalationPolicy:
    cfg = load_config()["alerts"]
    for spec in cfg["actuators"].values():
        spec["type"] = "null"
    return EscalationPolicy(cfg)


class FakeCal:
    """A calibration that is ready a set time after it starts."""

    def __init__(self, ready_after=12.0, fails=0):
        self.t0 = None
        self.t = 0.0
        self.ready_after = ready_after
        self.committed = 0
        self.cancelled = 0
        self._fails = fails

    def start(self, t):
        self.t0 = t

    def cancel(self):
        self.t0 = None
        self.cancelled += 1

    def progress(self, t):
        return 0.0 if self.t0 is None else min(1.0, (t - self.t0) / 12.0)

    def ready(self):
        return self.t0 is not None and self.t - self.t0 >= self.ready_after

    def failures(self):
        return self._fails

    def failure(self):
        return "no face detected at all"

    def open_level(self):
        return 0.30

    def closed_fraction(self):
        return 0.65

    def commit(self):
        self.committed += 1


def make_controller(store=None, cal=None):
    hub = Hub()
    policy = stub_policy()
    speaker = Speaker(player=None)
    c = Controller(hub, store, policy, estimator=StateEstimator(load_config()["state"]),
                   calibration=cal, speaker=speaker,
                   trip_cfg={"break_min_s": 60, "end_after_s": 300})
    return hub, policy, c


def events(hub, kind):
    return [e for e in hub.events_after(0) if e["type"] == kind]


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


def test_profile_starts_empty_and_the_owl_is_always_ollie(store):
    p = store.profile()
    assert p["name"] == "" and p["owl_name"] == "Ollie"
    p = store.update_profile({"name": "  민수 의 아주 아주 긴 이름입니다 정말로요  ", "owl_name": "Hootie"})
    assert len(p["name"]) <= 20 and p["name"].startswith("민수")
    assert p["owl_name"] == "Ollie"


def test_profile_and_settings_survive_a_restart(tmp_path):
    s = Store(tmp_path / "x.db")
    s.update_profile({"name": "Minsu", "voice_lang": "ko"})
    s.update_settings({"sensitivity": "strict", "ladder": {"mint": False}})
    s.close()
    s = Store(tmp_path / "x.db")
    assert s.profile()["name"] == "Minsu" and s.profile()["voice_lang"] == "ko"
    assert s.settings()["sensitivity"] == "strict"
    assert s.settings()["ladder"] == {"mint": False, "voice": True}
    s.close()


def test_choosing_a_vehicle_sets_its_defaults(store):
    store.update_profile({"vehicle": "car"})
    assert store.settings()["volume"] == "medium"
    store.update_profile({"vehicle": "delivery"})
    assert store.settings()["volume"] == "high"


@pytest.mark.parametrize("patch", [
    {"vehicle": "spaceship"}, {"voice_lang": "fr"}, {"nickname": "x"},
    {"work": {"start": "25:00"}}, {"work": {"days": [True]}},
])
def test_bad_profile_updates_are_refused(store, patch):
    with pytest.raises(InvalidUpdate):
        store.update_profile(patch)


def test_emergency_settings_are_off_and_in_demo_by_default(store):
    e = store.settings()["emergency"]
    assert e["call_services"] is False and e["demo"] is True
    e = store.update_settings({"emergency": {"contact_phone": "010-1234-5678; rm -rf"}})
    assert e["emergency"]["contact_phone"] == "01012345678"


# --------------------------------------------------------------------------- #
# Trips
# --------------------------------------------------------------------------- #


def run(tracker, t0, t1, wall0=1_700_000_000.0, dt=0.5, **kw):
    t = t0
    while t < t1:
        tracker.tick(t, wall0 + t, **kw)
        t += dt
    return t


def test_a_trip_starts_with_a_calibrated_driver_and_counts_alert_free_time(store):
    tr = TripTracker(store, TripConfig(break_min_s=60, end_after_s=300))
    run(tr, 0, 10, face=True, calibrated=False, stage=0)
    assert tr.trip is None                      # not before calibration
    run(tr, 10, 70, face=True, calibrated=True, stage=0)
    run(tr, 70, 100, face=True, calibrated=True, stage=2)
    run(tr, 100, 130, face=True, calibrated=True, stage=0)
    s = tr.end(130, 1_700_000_130.0)
    assert s["alerts"] == 1 and s["max_stage"] == 2
    assert s["alert_free"] == pytest.approx(90 / 120, abs=0.02)
    assert s["longest_calm_s"] == pytest.approx(60, abs=1)
    store.flush()
    rows = store.trips()
    assert len(rows) == 1 and rows[0]["ended_at"] is not None


def test_an_empty_seat_is_a_break_then_the_end_of_the_trip(store):
    tr = TripTracker(store, TripConfig(break_min_s=60, end_after_s=300))
    run(tr, 0, 100, face=True, calibrated=True, stage=0)
    run(tr, 100, 200, face=False, calibrated=True, stage=0)     # 100 s away
    run(tr, 200, 300, face=True, calibrated=True, stage=0)
    assert tr.trip.breaks == 1
    assert tr.drive_since_break_s(300) == pytest.approx(100, abs=1)
    run(tr, 300, 620, face=False, calibrated=True, stage=0)
    assert tr.trip is None
    store.flush()
    trip = store.trips()[0]
    assert trip["summary"]["breaks"] == 1
    # It ended when the driver left, not 300 s later.
    assert trip["ended_at"] - trip["started_at"] == pytest.approx(300, abs=1)


def test_a_trip_left_open_by_a_power_cut_is_closed_at_start_up(tmp_path):
    s = Store(tmp_path / "p.db")
    s.insert_trip(1, 1000.0)
    s.save_trip(1, {"duration_s": 50.0})
    assert s.close_open_trips(9999.0) == 1
    assert s.trips()[0]["ended_at"] == 1050.0
    s.close()


def test_insights_add_up_the_week(store):
    now = 1_700_000_000.0
    tr = TripTracker(store, TripConfig())
    for day in (3, 1):
        w = now - day * 86400
        tr.start(0, w)
        tr.tick(0.5, w + 0.5, face=True, calibrated=True, stage=0)
        for i in range(1, 600):
            stage = 1 if 200 <= i < 260 else 0
            tr.tick(i, w + i, face=True, calibrated=True, stage=stage)
        tr.end(600, w + 600)
    store.flush()
    ins = insights(store, "week", now=now)
    assert ins["trips"] == 2 and ins["alerts"] == 2
    assert ins["woke_by"] == [2, 0, 0, 0] and ins["first_step_enough"] == 2
    assert 0.85 < ins["alert_free"] < 0.95
    assert len(ins["per"]) == 7 and sum(d["alerts"] for d in ins["per"]) == 2
    assert sum(ins["hours"]) == 2


# --------------------------------------------------------------------------- #
# Controller
# --------------------------------------------------------------------------- #


def test_settings_from_the_phone_reach_the_ladder(store):
    hub, policy, c = make_controller(store)
    hub.command({"cmd": "apply", "settings": store.update_settings(
        {"ladder": {"mint": False}, "sensitivity": "strict", "co2_alert": False})})
    c.tick(0.0, face=True, calibrated=True, eye_closed=False, microsleep=False)
    assert policy.muted == {"scent", "open_window"}
    assert c.estimator.sensitivity == "strict"
    d = policy.trigger(2, 1.0)
    assert [a.actuator for a in d.fired] == ["blue_light"]
    assert any("off in settings" in s for s in d.suppressed)


def test_voice_language_switches_ladder_clips(store, tmp_path):
    hub, policy, c = make_controller(store)
    hub.command({"cmd": "apply", "profile": store.update_profile({"voice_lang": "ko"})})
    c.tick(0.0, face=True, calibrated=True, eye_closed=False, microsleep=False)
    assert AudioActuator.lang == "ko"
    a = AudioActuator("x", {"file": str(tmp_path / "{lang}" / "stage3.wav")})
    (tmp_path / "ko").mkdir()
    (tmp_path / "ko" / "stage3.wav").write_bytes(b"RIFF")
    assert a.present == [tmp_path / "ko" / "stage3.wav"]
    AudioActuator.lang = "en"
    assert a.present == []          # no English clip and no fallback file


def test_say_and_device_test_answer_over_the_socket():
    hub, policy, c = make_controller()
    hub.command({"cmd": "say", "line": "greet", "lang": "ko"})
    hub.command({"cmd": "test", "part": "mist"})
    c.tick(0.0, face=True, calibrated=True, eye_closed=False, microsleep=False)
    say = events(hub, "say")[0]
    assert say["lang"] == "ko" and say["text"] == LINES["greet"][1]
    assert say["result"] == "simulated"
    assert events(hub, "test_result") == [
        {"type": "test_result", "part": "mist", "result": "simulated", "seq": 2}]


def test_guided_calibration_walks_every_step():
    cal = FakeCal()
    hub, policy, c = make_controller(cal=cal)
    hub.command({"cmd": "cal_start"})
    t = 0.0

    def tick(seconds, face=True, ear=0.30):
        nonlocal t
        end = t + seconds
        while t < end:
            cal.t = t
            c.tick(t, face=face, calibrated=True, eye_closed=False, microsleep=False,
                   ear_raw=ear)
            t += 0.05

    tick(2.5)
    assert c.guided.step == "look"
    tick(12.5)
    assert c.guided.step == "close"
    tick(2.0, ear=0.05)
    assert c.guided.step == "speaker" and cal.committed == 1
    for step, ok in (("speaker", True), ("chime", True), ("light", False), ("mist", True)):
        assert c.guided.step == step
        hub.command({"cmd": "cal_answer", "step": step, "ok": ok})
        tick(0.1)
    assert not c.guided.active and c.guided.message == "done"
    assert c.guided.results["light"] == "fail" and c.guided.results["mist"] == "ok"
    said = [e["line"] for e in events(hub, "say")]
    assert said[:3] == ["cal_position", "cal_look", "cal_close"] and said[-1] == "cal_done"
    steps = {e["step"] for e in events(hub, "calibration")}
    assert set(STEP_KEYS) - {"done"} <= steps


def test_eyes_that_never_close_repeat_the_look_step_once_then_fail():
    cal = FakeCal(ready_after=0.0)
    hub, policy, c = make_controller(cal=cal)
    hub.command({"cmd": "cal_start"})
    t = 0.0
    while t < 30 and (c.guided.active or t < 1):
        cal.t = t
        c.tick(t, face=True, calibrated=True, eye_closed=False, microsleep=False, ear_raw=0.3)
        t += 0.05
    assert not c.guided.active
    assert c.guided.results["close"] == "fail" and cal.committed == 0
    assert any(e.get("message") == "retry" for e in events(hub, "calibration"))


def test_cancel_keeps_the_old_calibration():
    cal = FakeCal()
    hub, policy, c = make_controller(cal=cal)
    hub.command({"cmd": "cal_start"})
    c.tick(0.0, face=True, calibrated=True, eye_closed=False, microsleep=False)
    hub.command({"cmd": "cal_cancel"})
    c.tick(0.1, face=True, calibrated=True, eye_closed=False, microsleep=False)
    assert not c.guided.active and cal.committed == 0 and cal.cancelled >= 1


def test_no_response_twenty_seconds_into_the_alarm_is_an_emergency(store):
    hub, policy, c = make_controller(store)
    policy.trigger(4, 0.0)
    t = 0.0
    while t < 25:
        c.tick(t, face=True, calibrated=True, eye_closed=True, microsleep=False)
        t += 0.1
    em = events(hub, "emergency")
    assert len(em) == 1 and em[0]["reason"] == "eyes_closed" and em[0]["demo"] is True
    assert "emergency_check" in [e["line"] for e in events(hub, "say")]
    first = em[0]["at"]
    assert first > 0


def test_eyes_open_at_the_alarm_is_not_an_emergency():
    hub, policy, c = make_controller()
    policy.trigger(4, 0.0)
    t = 0.0
    while t < 30:
        c.tick(t, face=True, calibrated=True, eye_closed=False, microsleep=False)
        t += 0.1
    assert events(hub, "emergency") == []


def test_break_reminder_after_the_interval(store):
    hub, policy, c = make_controller(store)
    hub.command({"cmd": "apply", "settings": store.update_settings({"break_every_min": 1})})
    t = 0.0
    while t < 70:
        c.tick(t, face=True, calibrated=True, eye_closed=False, microsleep=False)
        t += 0.5
    assert [e["kind"] for e in events(hub, "reminder")] == ["break_due"]
    assert "break_due" in [e["line"] for e in events(hub, "say")]


def test_the_phone_clock_dates_the_trip(store):
    hub, policy, c = make_controller(store)
    hub.set_client_clock(1_800_000_000_000, 540)
    c.tick(0.0, face=True, calibrated=True, eye_closed=False, microsleep=False)
    assert c.trips.trip.started_at == pytest.approx(1_800_000_000, abs=2)
    assert c.trips.trip.tz_min == 540


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@pytest.fixture
def api(store, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from bamnun.server import create_app
    hub = Hub()
    return hub, TestClient(create_app(hub, tmp_path, store))


def test_api_profile_round_trip_queues_an_apply(api):
    hub, client = api
    r = client.put("/api/profile", json={"name": "Minsu", "vehicle": "bus"})
    assert r.status_code == 200 and r.json()["name"] == "Minsu"
    assert client.get("/api/profile").json()["vehicle"] == "bus"
    assert client.put("/api/profile", json={"vehicle": "boat"}).status_code == 422
    assert client.put("/api/profile", json=[1, 2]).status_code == 422
    cmds = hub.take_commands()
    assert cmds[0]["cmd"] == "apply" and cmds[0]["settings"]["volume"] == "medium"


def test_api_commands_are_queued_for_the_camera_loop(api):
    hub, client = api
    assert client.post("/api/say/greet?lang=ko").status_code == 202
    assert client.post("/api/say/nope").status_code == 404
    assert client.post("/api/test/mist").status_code == 202
    assert client.post("/api/test/engine").status_code == 404
    assert client.post("/api/calibration/start").status_code == 202
    assert client.post("/api/calibration/answer", json={"step": "speaker", "ok": True}).status_code == 202
    assert client.post("/api/calibration/answer", json={"step": "look", "ok": True}).status_code == 422
    assert client.post("/api/emergency/1", json={"outcome": "ok"}).status_code == 202
    assert client.post("/api/emergency/1", json={"outcome": "nuke"}).status_code == 422
    assert client.put("/api/trips/current/route", json={"to": "Busan"}).status_code == 202
    assert [c["cmd"] for c in hub.take_commands()] == [
        "say", "test", "cal_start", "cal_answer", "emergency_outcome", "route"]


def test_api_trips_and_insights(api, store):
    hub, client = api
    store.insert_trip(1, 1_700_000_000.0)
    store.save_trip(1, {"drive_s": 100.0, "calm_s": 90.0, "episodes": []}, 1_700_000_100.0)
    rows = client.get("/api/trips").json()
    assert rows[0]["id"] == 1 and "episodes" not in rows[0]["summary"]
    assert client.get("/api/trips/1").json()["events"] == []
    assert client.get("/api/trips/9").status_code == 404
    assert client.get("/api/trips/current").status_code == 404
    ins = client.get("/api/insights?range=all").json()
    assert ins["trips"] == 1 and ins["alert_free"] == 0.9
    assert client.get("/api/insights?range=year").status_code == 422
    assert set(client.get("/api/lines").json()["greet"]) == {"en", "ko"}


def test_no_store_means_503_not_a_crash(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bamnun.server import create_app
    client = TestClient(create_app(Hub(), tmp_path))
    assert client.get("/api/profile").status_code == 503
    assert client.post("/api/say/greet").status_code == 202


def test_the_ladder_holds_while_eyes_are_closed_on_request():
    cal = FakeCal(ready_after=0.0)
    hub, policy, c = make_controller(cal=cal)
    hub.command({"cmd": "cal_start"})
    t, held = 0.0, []
    while t < 10:
        cal.t = t
        c.tick(t, face=True, calibrated=True, eye_closed=False, microsleep=False,
               ear_raw=0.05 if c.guided.step == "close" else 0.3)
        held.append((c.guided.step, c.holds_ladder(t)))
        t += 0.05
    assert all(h for step, h in held if step == "close")
    assert not held[0][1] and not held[-1][1]


def test_an_alert_still_going_counts_in_the_live_trip(store):
    tr = TripTracker(store, TripConfig())
    run(tr, 0, 10, face=True, calibrated=True, stage=0)
    run(tr, 10, 20, face=True, calibrated=True, stage=3)
    assert tr.live(20)["summary"]["alerts"] == 1


# --------------------------------------------------------------------------- #
# Kakao route (section 9)
# --------------------------------------------------------------------------- #


def test_kakao_directions_are_summarised_for_the_app():
    from bamnun import kakao
    data = {"routes": [{"result_code": 0, "summary": {"distance": 390000, "duration": 16200, "fare": {"toll": 21000}},
                        "sections": [{"roads": [{"vertexes": [126.7, 37.4, 126.8, 37.3]},
                                                {"vertexes": [128.9, 35.1]}]}]}]}
    r = kakao.summarise(data)
    assert r == {"distance_m": 390000, "duration_s": 16200, "toll_won": 21000,
                 "path": [[126.7, 37.4], [126.8, 37.3], [128.9, 35.1]]}
    assert len(kakao.thin([[i, i] for i in range(5000)], 100)) == 100
    with pytest.raises(kakao.KakaoError):
        kakao.summarise({"routes": [{"result_code": 104, "result_msg": "too close"}]})


def test_kakao_needs_a_key_and_points_in_korea(tmp_path, monkeypatch):
    from bamnun import kakao
    with pytest.raises(kakao.KakaoError, match="REST key"):
        kakao.directions("126.7,37.4", "129.0,35.1", rest_key="")
    with pytest.raises(ValueError):
        kakao.parse_point("2.35,48.85")          # Paris
    env = tmp_path / ".env"
    env.write_text("# keys\nKAKAO_JS_KEY = 'abc'\nKAKAO_REST_KEY=xyz\n", encoding="utf-8")
    assert kakao.read_env(env) == {"KAKAO_JS_KEY": "abc", "KAKAO_REST_KEY": "xyz"}


def test_api_route_reports_a_missing_key(api, monkeypatch):
    from bamnun import kakao
    hub, client = api
    monkeypatch.setattr(kakao, "key", lambda name: "")
    assert client.get("/api/config").json() == {"kakao_js_key": None, "kakao_directions": False}
    r = client.get("/api/route?origin=126.7,37.4&destination=129.0,35.1")
    assert r.status_code == 503 and "REST key" in r.json()["detail"]
    assert client.get("/api/route?origin=x&destination=129.0,35.1").status_code == 422
