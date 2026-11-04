"""The Pi's HTTP and WebSocket server: the phone's window onto the monitor.

    python -m bamnun.app --serve              # live, with the camera
    python tools/sim_server.py                # no camera: a simulated driver

Serves (docs/SPEC.md, sections 0 and 1):

* ``GET /api/health``  device id, version, part status, calibration.
* ``WS  /ws``          a ``snapshot`` 5 times a second, and every event
                       (``alert``, ``say``, ``calibration``, ``test_result``,
                       ``trip``, ``reminder``, ``emergency``) as it happens.
* ``GET|PUT /api/profile``, ``/api/settings``   the driver's choices, kept in
                       SQLite on the Pi (store.py).
* ``POST /api/calibration/start|cancel|answer``, ``GET /api/calibration``
* ``POST /api/say/{line}``, ``POST /api/test/{part}``, ``GET /api/lines``
* ``GET /api/trips``, ``/api/trips/{id}``, ``/api/trips/current``,
  ``/api/insights``; ``POST /api/trips/start|end``,
  ``PUT /api/trips/current/route``
* ``POST /api/emergency/{id}``  what the phone did about an emergency.
* ``GET /video``       the camera as MJPEG, for the Camera screen only. The
                       camera loop encodes frames only while a stream is open.
* ``GET /``            the built app from ``frontend/www``, so a browser on
                       the Pi's network can open it with nothing installed.

It runs on a thread of its own. It reads from the Hub (telemetry.py) and
the store; anything that has to happen in the pipeline is queued on the Hub
as a command for the camera loop to pick up (control.py). That is the whole
safety argument for having a web server in the same process as the alert
ladder: nothing in here can make the camera loop wait.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import kakao
from .session import repo_root
from .store import InvalidUpdate, Store
from .telemetry import Hub
from .trips import RANGES, insights
from .voice import LINES, line_text

log = logging.getLogger("bamnun.server")

SNAPSHOT_PERIOD_S = 0.2     # 5 per second, as the spec asks
EVENT_POLL_S = 0.05         # an alert reaches the phone within 50 ms
FRAME_POLL_S = 0.03
BOUNDARY = "frame"


def default_www() -> Path:
    return repo_root() / "frontend" / "www"


async def mjpeg_stream(hub: Hub, poll_s: float = FRAME_POLL_S):
    """multipart/x-mixed-replace parts, one per new frame, while connected.

    Registering as a viewer is what makes the camera loop start encoding;
    the ``finally`` runs when the client goes away, so it stops again.
    """
    hub.add_viewer()
    try:
        seen = -1
        while True:
            seq, jpeg = hub.latest_frame()
            if jpeg is not None and seq != seen:
                seen = seq
                yield (b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                       + jpeg + b"\r\n")
            await asyncio.sleep(poll_s)
    finally:
        hub.remove_viewer()


CAL_STEPS_ASKED = ("speaker", "chime", "light", "mist")
TEST_PARTS = ("speaker", "chime", "blue_light", "mist", "alarm")
OUTCOMES = ("ok", "contacted", "called", "dismissed")


def create_app(hub: Hub, www: Optional[Path] = None,
               store: Optional[Store] = None) -> FastAPI:
    app = FastAPI(title="Bamnun", version=__version__)
    # The Capacitor app runs at http://localhost or capacitor://localhost,
    # which are different origins from the Pi. Nothing here is secret, and
    # there are no cookies, so any origin may read it.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"device": socket.gethostname(), "version": __version__,
                **hub.health()}

    def need_store() -> Store:
        if store is None:
            raise HTTPException(503, "this device keeps no profile or trips")
        return store

    def as_object(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise HTTPException(422, "send a JSON object")
        return body

    # -- profile and settings (sections 3-5) ------------------------------ #

    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        return need_store().profile()

    @app.put("/api/profile")
    def put_profile(body: Any = Body(...)) -> dict[str, Any]:
        st = need_store()
        try:
            profile = st.update_profile(as_object(body))
        except InvalidUpdate as exc:
            raise HTTPException(422, str(exc)) from None
        # A new vehicle can change the settings too, so send both.
        hub.command({"cmd": "apply", "profile": profile, "settings": st.settings()})
        return profile

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return need_store().settings()

    @app.put("/api/settings")
    def put_settings(body: Any = Body(...)) -> dict[str, Any]:
        st = need_store()
        try:
            settings = st.update_settings(as_object(body))
        except InvalidUpdate as exc:
            raise HTTPException(422, str(exc)) from None
        hub.command({"cmd": "apply", "settings": settings})
        return settings

    # -- voice, device test, calibration (sections 2, 6, 8) --------------- #

    @app.get("/api/lines")
    def lines() -> dict[str, Any]:
        return {k: {"en": line_text(k, "en"), "ko": line_text(k, "ko")} for k in LINES}

    @app.post("/api/say/{line}", status_code=202)
    def say(line: str, lang: Optional[str] = None) -> dict[str, Any]:
        if line not in LINES:
            raise HTTPException(404, f"no line {line!r}")
        if lang is not None and lang not in ("en", "ko"):
            raise HTTPException(422, "lang must be en or ko")
        hub.command({"cmd": "say", "line": line, "lang": lang})
        return {"queued": line}

    @app.post("/api/test/{part}", status_code=202)
    def test_part(part: str) -> dict[str, Any]:
        if part not in TEST_PARTS:
            raise HTTPException(404, f"part must be one of {TEST_PARTS}")
        hub.command({"cmd": "test", "part": part})
        return {"queued": part}

    @app.post("/api/calibration/start", status_code=202)
    def cal_start() -> dict[str, Any]:
        hub.command({"cmd": "cal_start"})
        return {"queued": "start"}

    @app.post("/api/calibration/cancel", status_code=202)
    def cal_cancel() -> dict[str, Any]:
        hub.command({"cmd": "cal_cancel"})
        return {"queued": "cancel"}

    @app.post("/api/calibration/answer", status_code=202)
    def cal_answer(body: Any = Body(...)) -> dict[str, Any]:
        body = as_object(body)
        step = body.get("step")
        if step not in CAL_STEPS_ASKED or not isinstance(body.get("ok"), bool):
            raise HTTPException(422, "send {step: speaker|chime|light|mist, ok: true|false}")
        hub.command({"cmd": "cal_answer", "step": step, "ok": body["ok"]})
        return {"queued": step}

    @app.get("/api/calibration")
    def cal_state() -> dict[str, Any]:
        return hub.cal_state or {"type": "calibration", "active": False, "step": None}

    # -- trips and insights ------------------------------------------------ #

    @app.get("/api/trips")
    def trips(limit: int = 50) -> list[dict[str, Any]]:
        rows = need_store().trips(limit=max(1, min(limit, 500)))
        live = hub.trip_live
        for r in rows:
            r["summary"].pop("episodes", None)
            if live is not None and r["id"] == live["id"]:
                r.update(summary=live["summary"], route=live["route"], open=True)
        return rows

    @app.get("/api/trips/current")
    def current_trip() -> dict[str, Any]:
        if hub.trip_live is None:
            raise HTTPException(404, "no trip running")
        return hub.trip_live

    @app.get("/api/trips/{trip_id}")
    def trip(trip_id: int) -> dict[str, Any]:
        row = need_store().trip(trip_id)
        if row is None:
            raise HTTPException(404, "no such trip")
        live = hub.trip_live
        if live is not None and live["id"] == trip_id:
            row.update(summary=dict(row["summary"], **live["summary"]), open=True)
        return row

    @app.post("/api/trips/start", status_code=202)
    def trip_start() -> dict[str, Any]:
        hub.command({"cmd": "trip_start"})
        return {"queued": "start"}

    @app.post("/api/trips/end", status_code=202)
    def trip_end() -> dict[str, Any]:
        hub.command({"cmd": "trip_end"})
        return {"queued": "end"}

    @app.put("/api/trips/current/route", status_code=202)
    def trip_route(body: Any = Body(None)) -> dict[str, Any]:
        if body is not None and not isinstance(body, dict):
            raise HTTPException(422, "send the route as an object, or null to clear it")
        hub.command({"cmd": "route", "route": body})
        return {"queued": "route"}

    @app.get("/api/insights")
    def get_insights(range: str = "week", tz: Optional[int] = None) -> dict[str, Any]:
        if range not in RANGES:
            raise HTTPException(422, f"range must be one of {tuple(RANGES)}")
        return insights(need_store(), range, tz_min=hub.tz_min if tz is None else tz)

    # -- route (section 9) -------------------------------------------------- #

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        """Public settings for the app: the Kakao map key, if there is one."""
        return {"kakao_js_key": kakao.key("KAKAO_JS_KEY") or None,
                "kakao_directions": bool(kakao.key("KAKAO_REST_KEY"))}

    @app.get("/api/route")
    def route(origin: str, destination: str, vehicle: str = "car") -> dict[str, Any]:
        """Driving directions from Kakao Mobility; the REST key stays here.

        A plain ``def``: FastAPI runs it on a worker thread, so the wait for
        Kakao holds up neither the event loop nor the camera loop.
        """
        try:
            return kakao.directions(origin, destination, kakao.CAR_TYPE.get(vehicle, 1))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except kakao.KakaoError as exc:
            raise HTTPException(503 if isinstance(exc, kakao.NoKey) else 502, str(exc)) from None

    # -- emergency (section 9b) -------------------------------------------- #

    @app.post("/api/emergency/{event_id}", status_code=202)
    def emergency_outcome(event_id: int, body: Any = Body(...)) -> dict[str, Any]:
        outcome = as_object(body).get("outcome")
        if outcome not in OUTCOMES:
            raise HTTPException(422, f"outcome must be one of {OUTCOMES}")
        hub.command({"cmd": "emergency_outcome", "id": event_id, "outcome": outcome})
        return {"queued": outcome}

    @app.get("/video")
    def video():
        if not hub.video_capable:
            return PlainTextResponse("no camera on this device", status_code=404)
        return StreamingResponse(
            mjpeg_stream(hub), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()

        async def reader() -> None:
            # The phone's ``hello`` carries its clock and time zone, because
            # the Pi has no reliable clock (SPEC.md, section 1). Trip times
            # and the Insights hours use it.
            while True:
                msg = await sock.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "hello":
                    hub.client_hello = msg
                    hub.set_client_clock(msg.get("time"), msg.get("tz_min"))

        reading = asyncio.create_task(reader())
        seq = hub.seq       # only events from now on, not the backlog
        # A phone that joins mid-calibration needs to know where it is.
        if hub.cal_state is not None and hub.cal_state.get("active"):
            await sock.send_json(hub.cal_state)
        loop = asyncio.get_running_loop()
        next_snapshot = 0.0
        try:
            while not reading.done():
                for event in hub.events_after(seq):
                    await sock.send_json(event)
                    seq = event["seq"]
                now = loop.time()
                if now >= next_snapshot:
                    snap = hub.latest()
                    if snap is not None:
                        await sock.send_json(snap)
                    # Step the schedule, not "now + period": sleep overshoot
                    # (15 ms timer ticks on Windows) would otherwise pile up
                    # and run the stream at about 4 per second, not 5.
                    next_snapshot += SNAPSHOT_PERIOD_S
                    if next_snapshot < now:
                        next_snapshot = now + SNAPSHOT_PERIOD_S
                await asyncio.sleep(EVENT_POLL_S)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reading.cancel()

    www = Path(www) if www is not None else default_www()
    if (www / "index.html").exists():
        app.mount("/", StaticFiles(directory=www, html=True), name="app")
    else:
        @app.get("/")
        def no_app() -> PlainTextResponse:
            return PlainTextResponse(
                "The app hasn't been built yet. From the repo root run:\n"
                "    python frontend/build/build.py frontend/screens "
                "frontend/www/index.html frontend/ollie\n", status_code=503)
    return app


class ServerThread:
    """uvicorn on a daemon thread. Failure to start is logged, never raised.

    A port that is already taken must not stop the monitor: the ladder is
    the product, the server is a view onto it.
    """

    def __init__(self, hub: Hub, host: str = "0.0.0.0", port: int = 8000,
                 www: Optional[Path] = None, store: Optional[Store] = None) -> None:
        import uvicorn

        config = uvicorn.Config(create_app(hub, www, store), host=host, port=port,
                                log_level="warning", access_log=False)
        self._server = uvicorn.Server(config)
        self.host, self.port = host, port
        self._thread = threading.Thread(target=self._run, name="bamnun-server",
                                        daemon=True)

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:  # noqa: BLE001 - uvicorn exits via SystemExit
            log.warning("server stopped: %r", exc)

    def start(self) -> "ServerThread":
        self._thread.start()
        log.info("server on http://%s:%d (app at /, live data at /ws)",
                 self.host, self.port)
        return self

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def stop(self, timeout: float = 3.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout)
