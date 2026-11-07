"""The booth remote (remote.py) and what the app does with each command."""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.app import Monitor  # noqa: E402
from bamnun.remote import COMMANDS, Remote  # noqa: E402


def test_without_a_staff_code_the_remote_stays_off(tmp_path):
    r = Remote(tmp_path)
    assert not r.ready
    r.start()                                          # does nothing, no thread
    assert r._thread is None and r.take() == []


def test_polling_keeps_known_commands_in_order(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / ".env").write_text("SUPABASE_URL=https://x.supabase.co\nSUPABASE_ANON_KEY=a\nSTAFF_CODE=s\n")
    r = Remote(tmp_path)
    assert r.ready
    rows = [{"id": 5, "cmd": "next"}, {"id": 3, "cmd": "stage2"}, {"id": 4, "cmd": "nonsense"}]

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5: Resp(json.dumps(rows).encode()))
    assert r.poll_once() == ["stage2", "next"]


def test_each_command_does_its_thing():
    done = []
    m = SimpleNamespace(
        remote=SimpleNamespace(take=lambda: ["stage3", "next", "calibrate", "photos_off", "vol_up", "voice", "stage0"]),
        logger=SimpleNamespace(log_event=lambda *a: None),
        mode="briefing", _seat_empty=True, _stage_play=(3, 0.0, 9.0), _last_alert=None,
        policy=SimpleNamespace(reset=lambda t: done.append("reset") or "reset"),
        visit=SimpleNamespace(photos_off=False),
        volume=SimpleNamespace(change=lambda d: done.append(("vol", d))),
    )
    m._play_stage = lambda n, now, t: done.append(("stage", n))
    m._next_visitor = lambda now: done.append("next")
    m._start_calibration = lambda t: done.append("calibrate")
    m._voice = lambda k, t: None
    m._set_voice_lang = lambda lang: done.append(("voice", lang))
    Monitor._remote_commands(m, 1.0, 1.0)
    assert ("stage", 3) in done and "next" in done and "calibrate" in done and "reset" in done
    assert m.visit.photos_off and m.mode == "live" and not m._seat_empty
    assert any(d[0] == "vol" and d[1] > 0 for d in done if isinstance(d, tuple))
    assert set(COMMANDS) >= {"stage0", "next", "calibrate"}
