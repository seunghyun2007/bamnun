"""The Pi's HTTP and WebSocket server: the phone's window onto the monitor.

    python -m bamnun.app --serve              # live, with the camera
    python tools/sim_server.py                # no camera: a simulated driver

Serves three things (docs/SPEC.md, sections 0 and 1):

* ``GET /api/health``  device id, version, part status, calibration.
* ``WS  /ws``          a ``snapshot`` 5 times a second, and each ``alert`` as
                       soon as the stage changes.
* ``GET /video``       the camera as MJPEG, for the Camera screen only. The
                       camera loop encodes frames only while a stream is open.
* ``GET /``            the built app from ``frontend/www``, so a browser on
                       the Pi's network can open it with nothing installed.

It runs on a thread of its own and only reads from the Hub (telemetry.py).
That is the whole safety argument for having a web server in the same
process as the alert ladder: nothing in here can make the camera loop wait.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .session import repo_root
from .telemetry import Hub

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


def create_app(hub: Hub, www: Optional[Path] = None) -> FastAPI:
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
            # The phone's ``hello`` carries its clock and language, because
            # the Pi has no reliable clock (SPEC.md, section 1). Kept for the
            # trip and profile steps; nothing reads it yet.
            while True:
                msg = await sock.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "hello":
                    hub.client_hello = msg

        reading = asyncio.create_task(reader())
        seq = hub.seq       # only events from now on, not the backlog
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
                 www: Optional[Path] = None) -> None:
        import uvicorn

        config = uvicorn.Config(create_app(hub, www), host=host, port=port,
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
