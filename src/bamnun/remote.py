"""The booth remote: commands from a staff phone, through Supabase.

At the booth nobody should have to leave the game to click on the Pi. A
teammate's phone opens the staff page (frontend/build/staff.html, published
as staff.html?k=<code>) and taps: a wake-up stage (1-4, 0 = all off), next
person, calibrate, photos on/off, volume, voice. The page puts the command
in a mailbox (supabase/booth_remote.sql); this checks it every POLL_S
seconds in the background and hands each command to the app's loop.

Needs the Pi online and STAFF_CODE in frontend/.env (with SUPABASE_URL and
SUPABASE_ANON_KEY). Without them it does nothing; nothing else depends on it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Deque, Optional

from .visit import read_env

log = logging.getLogger("bamnun.remote")

POLL_S = 1.0
COMMANDS = ("stage0", "stage1", "stage2", "stage3", "stage4", "next", "calibrate",
            "photos_off", "photos_on", "vol_up", "vol_down", "voice")


class Remote:
    def __init__(self, root: Path) -> None:
        env = read_env(Path(root) / "frontend" / ".env")
        self.url = env.get("SUPABASE_URL", "").rstrip("/")
        self.key = env.get("SUPABASE_ANON_KEY", "")
        self.code = env.get("STAFF_CODE", "")
        self.inbox: Deque[str] = deque()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def ready(self) -> bool:
        return bool(self.url and self.key and self.code)

    def start(self) -> None:
        if not self.ready:
            log.info("booth remote off (no STAFF_CODE / Supabase settings in frontend/.env)")
            return
        self._thread = threading.Thread(target=self._run, name="booth-remote", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def take(self) -> list[str]:
        """Commands that arrived since the last call (the app's loop)."""
        out = []
        while self.inbox:
            out.append(self.inbox.popleft())
        return out

    def poll_once(self) -> list[str]:
        req = urllib.request.Request(
            self.url + "/rest/v1/rpc/take_commands", data=json.dumps({"k": self.code}).encode(),
            method="POST", headers={"apikey": self.key, "Authorization": "Bearer " + self.key,
                                    "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            rows = json.loads(r.read() or b"[]")
        cmds = [str(row.get("cmd", "")) for row in sorted(rows, key=lambda x: x.get("id", 0))]
        return [c for c in cmds if c in COMMANDS]

    def _run(self) -> None:  # pragma: no cover - network loop
        quiet_until = 0.0
        while not self._stop.is_set():
            try:
                for c in self.poll_once():
                    self.inbox.append(c)
            except Exception as exc:  # noqa: BLE001
                if time.monotonic() >= quiet_until:          # don't flood the log offline
                    log.warning("booth remote: %s", exc)
                    quiet_until = time.monotonic() + 60.0
            self._stop.wait(POLL_S)
