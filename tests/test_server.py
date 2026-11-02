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
