"""Four-stage ladder, blue light, per-stage overrides, voice cues and CO2.

The stage design comes from the team research doc: blue light, then mint,
then a slow chime, then a looming alarm, each entered on the fused score or
on PERCLOS 5 / 10 / 15 / 20 %.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bamnun.air import CabinAir, _crc8, parse_measurement  # noqa: E402
from bamnun.alerts import (  # noqa: E402
    AudioActuator, EscalationPolicy, LightActuator, stage_entries,
)
from bamnun.features import FeatureFrame  # noqa: E402
from bamnun.session import load_config  # noqa: E402
from bamnun.state import StateEstimator  # noqa: E402


def ff(t=0.0, **kw) -> FeatureFrame:
    base = dict(t=t, face_found=True, pose_valid=True, gaze_valid=True,
                interocular_px=120.0, ear_norm=1.0)
    base.update(kw)
    return FeatureFrame(**base)


LEVELS = [
    {"name": "alert", "min_score": 0.00, "dwell_s": 0.0},
    {"name": "a_bit", "min_score": 0.30, "min_perclos": 0.05, "dwell_s": 2.0},
    {"name": "drowsy", "min_score": 0.45, "min_perclos": 0.10, "dwell_s": 2.0},
]


def _quiet_policy_cfg():
    """The shipped alert config with every sound stubbed out."""
    cfg = load_config()["alerts"]
    for spec in cfg["actuators"].values():
        if spec.get("type") == "audio":
            spec["type"] = "null"
    return cfg


# --------------------------------------------------------------------------- #
# PERCLOS route into the levels
# --------------------------------------------------------------------------- #


def test_perclos_alone_enters_a_level_after_its_dwell():
    est = StateEstimator({"weights": {"perclos": 1.0}, "levels": LEVELS})
    # PERCLOS 7 % ramps to a tiny score, far below min_score 0.30.
    s = est.update(ff(t=0.0, perclos=0.07), calibrated=True)
    assert s.score < 0.30 and s.level == 0
    s = est.update(ff(t=2.5, perclos=0.07), calibrated=True)
    assert s.level == 1, "PERCLOS gate did not raise the level"


def test_perclos_route_has_its_own_hysteresis():
    est = StateEstimator({"weights": {"perclos": 1.0}, "levels": LEVELS,
                          "perclos_hysteresis": 0.02})
    for t in (0.0, 2.5):
        s = est.update(ff(t=t, perclos=0.07), calibrated=True)
    assert s.level == 1
    s = est.update(ff(t=3.0, perclos=0.04), calibrated=True)   # within 2 points
    assert s.level == 1, "flapped down inside the hysteresis band"
    s = est.update(ff(t=3.5, perclos=0.02), calibrated=True)
    assert s.level == 0


def test_levels_without_a_perclos_gate_behave_as_before():
    est = StateEstimator({"weights": {"perclos": 1.0},
                          "levels": [{"name": "alert", "min_score": 0.0},
                                     {"name": "mild", "min_score": 0.5}]})
    s = est.update(ff(t=0.0, perclos=0.10), calibrated=True)
    assert s.level == 0


# --------------------------------------------------------------------------- #
# Blue light
# --------------------------------------------------------------------------- #


def test_light_latches_and_turns_itself_off_after_the_hold():
    light = LightActuator("blue", {"hold_s": 100.0})
    assert not light.is_on
    assert light.fire(0.0, "light") is not None
    assert light.is_on
    light.tick(99.0)
    assert light.is_on
    light.tick(100.0)
    assert not light.is_on


def test_firing_a_lit_light_restarts_the_hold_instead_of_toggling():
    light = LightActuator("blue", {"hold_s": 100.0})
    light.fire(0.0, "light")
    light.fire(80.0, "scent")
    light.tick(150.0)
    assert light.is_on, "the second fire should have extended the hold"
    light.tick(180.0)
    assert not light.is_on


def test_light_drives_a_dimmed_pwm_pin_when_gpio_exists():
    try:
        from gpiozero import Device
    except Exception:             # noqa: BLE001 - laptop: the stub path is covered above
        return
    light = LightActuator("blue", {"gpio_pin": 24, "brightness": 0.2, "hold_s": 10.0})
    pin = Device.pin_factory.pin(24)    # MockFactory from conftest
    light.fire(0.0, "light")
    assert pin.state == pytest.approx(0.2)
    light.tick(10.0)
    assert pin.state == 0
    light.close()


def test_policy_ticks_the_light_off_while_the_driver_is_alert():
    pol = EscalationPolicy(_quiet_policy_cfg())
    est = StateEstimator(load_config()["state"])
    light = pol.actuators["blue_light"]
    # PERCLOS 7 % for 12 s clears the 10 s dwell into "a bit drowsy".
    t = 0.0
    while t < 12.0:
        pol.update(est.update(ff(t=t, perclos=0.07), calibrated=True))
        t += 0.5
    assert pol.stage == 1 and light.is_on
    # Then alert for longer than the hold.
    t += light.hold_s + 1.0
    pol.update(est.update(ff(t=t, perclos=0.0), calibrated=True))
    assert not light.is_on


# --------------------------------------------------------------------------- #
# Ladder shape and per-stage overrides
# --------------------------------------------------------------------------- #


def test_shipped_ladder_has_one_stage_per_level():
    cfg = load_config()
    assert len(cfg["state"]["levels"]) == len(cfg["alerts"]["stages"]) == 5
    gates = [lv["min_perclos"] for lv in cfg["state"]["levels"][1:]]
    assert gates == sorted(gates) == [0.05, 0.10, 0.15, 0.20]


def test_shipped_ladder_escalates_light_scent_sound():
    stages = load_config()["alerts"]["stages"]
    names = [[n for n, _ in stage_entries(s)] for s in stages]
    assert names[1] == ["blue_light"], "stage 1 must be the light alone"
    assert "scent" in names[2] and "warn" not in names[2]
    assert "warn" in names[3]
    assert "alarm" in names[4]


def test_stage_entries_accept_overrides():
    spec = {"actuators": ["chime", {"scent": {"duration_s": 20.0}}]}
    assert stage_entries(spec) == [("chime", None), ("scent", {"duration_s": 20.0})]


def test_microsleep_fires_the_long_scent_burst():
    pol = EscalationPolicy(_quiet_policy_cfg())
    est = StateEstimator(load_config()["state"])
    s = est.update(ff(t=0.0, ongoing_closure_s=1.0, microsleep_now=True),
                   calibrated=True)
    d = pol.update(s)
    assert pol.stage == 4
    scent = [a for a in d.fired if a.actuator == "scent"]
    assert scent and "20.00s" in scent[0].detail


def test_distraction_nudges_without_touching_the_ladder():
    pol = EscalationPolicy(_quiet_policy_cfg())
    est = StateEstimator(load_config()["state"])
    s = est.update(ff(t=0.0, off_road_alarm=True, off_road_glance_s=2.5),
                   calibrated=True)
    assert s.distracted
    d = pol.update(s)
    assert [a.actuator for a in d.fired] == ["chime"]
    assert pol.stage == 0, "a glance away must not light the cabin for 30 min"
    # Inside the distraction cooldown: no second nudge.
    d = pol.update(est.update(ff(t=5.0, off_road_alarm=True, off_road_glance_s=7.5),
                              calibrated=True))
    assert not d.fired


def test_prompt_respects_refractory_and_is_recorded():
    pol = EscalationPolicy(_quiet_policy_cfg())
    assert pol.prompt("open_window", 0.0) is not None
    assert pol.prompt("open_window", 10.0) is None          # 300 s refractory
    assert pol.prompt("open_window", 301.0) is not None
    assert [a.actuator for a in pol.history] == ["open_window", "open_window"]
    assert pol.prompt("no_such_thing", 0.0) is None


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #


def test_audio_skips_recordings_that_do_not_exist_yet(tmp_path):
    tone = tmp_path / "tone.wav"
    tone.write_bytes(b"")
    a = AudioActuator("warn", {"files": [str(tone), str(tmp_path / "missing.wav")]})
    assert a.present == [tone]


def test_audio_paths_resolve_against_the_repo():
    a = AudioActuator("chime", {"file": "assets/chime.wav"})
    assert a.path == ROOT / "assets" / "chime.wav"
    assert a.present == [a.path]


def test_generated_tones_exist_at_the_card_rate():
    for name in ("chime.wav", "chime_slow.wav", "looming.wav"):
        with wave.open(str(ROOT / "assets" / name), "rb") as w:
            assert (w.getframerate(), w.getnchannels()) == (48000, 2), name


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_recordings_are_trimmed_and_levelled():
    rec = _load_tool("record_prompts")
    rate = rec.RATE
    quiet = [0.001 * math.sin(i) for i in range(rate)]           # 1 s of hiss
    speech = [0.05 * math.sin(2 * math.pi * 200 * i / rate) for i in range(rate // 2)]
    out = rec.trim_and_level(quiet + speech + quiet)
    dur = len(out) / rate
    assert 0.5 <= dur <= 0.5 + 2 * rec.PAD_S + 0.05
    assert max(abs(v) for v in out) == pytest.approx(rec.TARGET_PEAK, rel=0.02)


def test_every_voice_file_the_config_plays_has_a_recording_slot():
    rec = _load_tool("record_prompts")
    acts = load_config()["alerts"]["actuators"]
    voiced = set()
    for spec in acts.values():
        for f in spec.get("files") or [spec.get("file", "")]:
            if str(f).startswith("assets/voice/"):
                voiced.add(Path(f).stem)
    assert voiced <= set(rec.PROMPTS), f"no recorder entry for {voiced - set(rec.PROMPTS)}"


# --------------------------------------------------------------------------- #
# CO2
# --------------------------------------------------------------------------- #


def test_sensirion_crc_matches_the_datasheet_example():
    assert _crc8(bytes([0xBE, 0xEF])) == 0x92


def _frame(co2: int, t_raw: int = 0x6667, rh_raw: int = 0x5EB9) -> bytes:
    out = b""
    for w in (co2, t_raw, rh_raw):
        b = bytes([w >> 8, w & 0xFF])
        out += b + bytes([_crc8(b)])
    return out


def test_scd41_frame_parses_and_rejects_corruption():
    co2, temp, rh = parse_measurement(_frame(1234))
    assert co2 == 1234
    assert temp == pytest.approx(25.0, abs=0.1)
    assert rh == pytest.approx(37.0, abs=0.1)
    bad = bytearray(_frame(1234))
    bad[1] ^= 0x01
    with pytest.raises(ValueError):
        parse_measurement(bytes(bad))


def test_co2_prompt_fires_once_per_excursion():
    air = CabinAir({"enabled": False, "prompt_ppm": 1500, "rearm_drop_ppm": 200})
    assert not air.should_prompt(0)                 # no reading yet
    seq = [(800, False), (1500, True), (1700, False), (1400, False),
           (1550, False), (1250, False), (1600, True)]
    for ppm, expect in seq:
        air.ppm = ppm
        assert air.should_prompt(0) is expect, ppm


def test_co2_threshold_drops_once_the_driver_is_drowsy():
    air = CabinAir({"enabled": False, "prompt_ppm": 1500,
                    "drowsy_prompt_ppm": 1000, "drowsy_level": 2})
    air.ppm = 1100
    assert not air.should_prompt(1)
    assert air.should_prompt(2)
