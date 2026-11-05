"""The Pi's server: health, the live stream, and serving the app.

Skipped where FastAPI is not installed, so the suite still runs on a Pi
that has not had requirements.txt re-installed yet.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from bamnun.server import ServerThread, create_app  # noqa: E402
from bamnun.telemetry import Hub  # noqa: E402


@pytest.fixture
def www(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Bamnun App</title>",
                                         encoding="utf-8")
    return tmp_path


def test_health_reports_parts_and_whether_the_camera_is_live(www):
    hub = Hub()
    hub.set_health({"calibrated": True, "parts": {"mist": "ok"}})
    client = TestClient(create_app(hub, www))
    h = client.get("/api/health").json()
    assert h["calibrated"] is True and h["parts"] == {"mist": "ok"}
    assert h["camera_live"] is False          # nothing published yet
    hub.publish({"type": "snapshot"})
    assert client.get("/api/health").json()["camera_live"] is True
    assert "version" in h and "device" in h



def test_health_gives_a_device_id_that_stays_the_same(www, tmp_path):
    from bamnun.store import Store
    db = tmp_path / "d.db"
    store = Store(db)
    first = TestClient(create_app(Hub(), www, store)).get("/api/health").json()["device_id"]
    assert len(first) == 32
    assert TestClient(create_app(Hub(), www, store)).get("/api/health").json()["device_id"] == first
    store.close()
    again = Store(db)          # survives a restart
    assert again.device_id() == first
    again.close()
    assert Store(tmp_path / "other.db").device_id() != first

def test_the_app_is_served_at_the_root(www):
    client = TestClient(create_app(Hub(), www))
    r = client.get("/")
    assert r.status_code == 200 and "Bamnun App" in r.text


def test_a_missing_build_says_how_to_make_it(tmp_path):
    r = TestClient(create_app(Hub(), tmp_path)).get("/")
    assert r.status_code == 503 and "build.py" in r.text


def test_the_api_is_open_to_the_capacitor_app_origin(www):
    r = TestClient(create_app(Hub(), www)).get(
        "/api/health", headers={"Origin": "capacitor://localhost"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_websocket_streams_snapshots_and_pushes_alerts(www):
    hub = Hub()
    hub.publish({"type": "snapshot", "eye_open": 0.9})
    hub.emit({"type": "alert", "stage": 1})     # before connecting: not replayed
    client = TestClient(create_app(hub, www))
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["eye_open"] == 0.9
        assert "age_s" in first and first["stale"] is False
        ws.send_json({"type": "hello", "time": 1730000000000, "lang": "ko"})
        hub.emit({"type": "alert", "stage": 2, "stage_name": "scent"})
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "alert":
                break
        assert msg["stage"] == 2
    assert hub.client_hello == {"type": "hello", "time": 1730000000000, "lang": "ko"}


def test_a_taken_port_does_not_raise(www):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        server = ServerThread(Hub(), "127.0.0.1", port, www).start()
        deadline = time.monotonic() + 5.0
        while server.running and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not server.running        # gave up quietly instead of crashing us


def test_video_is_refused_when_the_device_has_no_camera(www):
    r = TestClient(create_app(Hub(), www)).get("/video")
    assert r.status_code == 404


def test_video_stream_sends_each_new_frame_once_and_releases_the_viewer():
    import asyncio

    from bamnun.server import mjpeg_stream

    async def run():
        hub = Hub()
        stream = mjpeg_stream(hub, poll_s=0.001)
        hub.publish_frame(b"JPEG-ONE")
        first = await stream.__anext__()
        assert hub.wants_video()                       # watching starts encoding
        hub.publish_frame(b"JPEG-TWO")
        second = await stream.__anext__()
        await stream.aclose()                          # the phone left the screen
        return hub, first, second

    hub, first, second = asyncio.run(run())
    assert first.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
    assert first.endswith(b"JPEG-ONE\r\n") and second.endswith(b"JPEG-TWO\r\n")
    assert not hub.wants_video()                       # and leaving stops it


def test_video_frame_is_a_small_jpeg():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from bamnun.viz import video_frame

    jpeg = video_frame(np.full((864, 1536), 90, np.uint8), None, eye_closed=False)
    assert jpeg[:2] == b"\xff\xd8" and len(jpeg) < 60_000


def test_product_control_plays_one_stage_at_a_time_on_the_device(www, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("bamnun.server.time.monotonic", lambda: clock[0])
    hub = Hub()
    client = TestClient(create_app(hub, www))

    r = client.post("/api/showcase/stage/3")
    assert r.status_code == 202 and r.json() == {"playing": 3, "hold_s": 6.0}
    assert hub.take_commands() == [{"cmd": "test", "part": "chime"},
                                   {"cmd": "say", "line": "stage3"}]
    assert [e["stage"] for e in hub.events_after(0) if e["type"] == "showcase"] == [3]

    clock[0] += 2.0                                    # another phone, mid-stage
    busy = client.post("/api/showcase/stage/1")
    assert busy.status_code == 409
    assert busy.json() == {"busy": True, "stage": 3, "retry_in": 4.0}
    assert hub.take_commands() == []                   # nothing fired

    clock[0] += 4.0                                    # stage 3 has finished
    assert client.post("/api/showcase/stage/1").status_code == 202
    assert hub.take_commands() == [{"cmd": "test", "part": "blue_light"}]
    assert client.post("/api/showcase/stage/5").status_code == 404


def test_booth_wifi_check_pops_up_the_app_then_lets_the_phone_stay(www):
    client = TestClient(create_app(Hub(), www, booth=True))
    for path in ("/hotspot-detect.html", "/generate_204", "/connecttest.txt"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/booth"
    assert "Open the Bamnun app" in client.get("/booth").text

    r = client.get("/booth/go", follow_redirects=False)  # the visitor taps through
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert "Success" in client.get("/hotspot-detect.html").text
    assert client.get("/generate_204").status_code == 204
    assert client.get("/connecttest.txt").text == "Microsoft Connect Test"


def test_without_booth_mode_there_is_no_wifi_pop_up(www):
    client = TestClient(create_app(Hub(), www))
    assert client.get("/booth").status_code == 404
    assert client.get("/generate_204").status_code == 404
