"""One sound at a time on the speaker (alerts.AudioActuator)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.alerts import AudioActuator  # noqa: E402


class FakeProc:
    def __init__(self):
        self.done, self.killed = False, False

    def poll(self):
        return 0 if self.done else None

    def terminate(self):
        self.killed, self.done = True, True


def make(name, tmp_path):
    f = tmp_path / f"{name}.wav"
    f.write_bytes(b"RIFF")
    a = AudioActuator(name, {"file": str(f)})
    a._player = "aplay"
    return a


def test_a_tip_is_skipped_while_another_sound_plays_and_an_alarm_cuts_in(tmp_path, monkeypatch):
    monkeypatch.setattr("threading.Thread.start", lambda self: None)   # don't really play
    playing = FakeProc()
    AudioActuator._playing, AudioActuator._playing_urgent = playing, False
    tip = make("sleepy_voice", tmp_path)
    assert tip._do_fire(0.0).startswith("skipped")
    alarm = make("alarm", tmp_path)
    assert alarm._do_fire(0.0).startswith("played") and playing.killed
    AudioActuator._playing = None
    assert tip._do_fire(0.0).startswith("played")
