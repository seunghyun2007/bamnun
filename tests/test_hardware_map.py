"""Pin map and IR illuminator tests.

The pin map is checked against the config rather than trusted, because the
failure it guards against is silent: an actuator configured on an I2S pin
does not raise, it just fights the audio clock and turns every speaker
output into crackle.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun.capture import Illuminator  # noqa: E402
from bamnun.session import load_config  # noqa: E402

I2C_PINS = {2, 3}                 # SCD41
I2S_PINS = {18, 19, 20, 21}       # INMP441 mic + MAX98357A amps
IR_CFG = {"enabled": True, "gpio_pin": 25, "sources": ["picamera"]}


def _gpio_pins(spec: dict) -> set[int]:
    return {int(v) for k, v in spec.items() if k.endswith("gpio_pin")}


def test_no_actuator_sits_on_a_bus_pin():
    cfg = load_config()
    for name, spec in cfg["alerts"]["actuators"].items():
        clash = _gpio_pins(spec) & (I2C_PINS | I2S_PINS)
        assert not clash, f"{name} is configured on bus pin(s) {sorted(clash)}"


def test_illuminator_does_not_share_a_pin_with_an_actuator():
    cfg = load_config()
    ir_pin = int(cfg["capture"]["illuminator"]["gpio_pin"])
    for name, spec in cfg["alerts"]["actuators"].items():
        assert ir_pin not in _gpio_pins(spec), f"{name} shares GPIO{ir_pin} with the IR LED"


def test_scent_is_on_the_mister_pin_and_chime_uses_the_speakers():
    acts = load_config()["alerts"]["actuators"]
    assert acts["scent"]["gpio_pin"] == 17
    assert acts["chime"]["type"] == "audio"


def test_every_staged_actuator_is_configured():
    cfg = load_config()["alerts"]
    for stage in cfg["stages"]:
        for name in stage.get("actuators", []):
            assert name in cfg["actuators"], f"stage {stage['name']} uses unknown {name}"


def test_illuminator_lights_only_for_listed_sources():
    for kind in ("webcam", "video"):
        ir = Illuminator(IR_CFG, kind)
        ir.on()
        assert not ir.is_on, f"IR LED lit for a {kind} source"
        ir.close()


def test_illuminator_is_off_by_default_and_after_close():
    ir = Illuminator(IR_CFG, "picamera")
    assert not ir.is_on
    ir.on()
    assert ir.is_on
    ir.close()
    assert not ir.is_on
    ir.close()                    # a second close (crash path) must be harmless


def test_illuminator_drives_the_real_pin_when_gpio_exists():
    try:
        from gpiozero import Device
    except Exception:             # noqa: BLE001 - laptop: the stub path is covered above
        return
    ir = Illuminator(IR_CFG, "picamera")
    pin = Device.pin_factory.pin(25)    # MockFactory from conftest, never a real pin
    assert pin.state == 0
    ir.on()
    assert pin.state == 1
    ir.close()
    assert pin.state == 0


def test_missing_illuminator_config_means_no_illuminator():
    ir = Illuminator(None, "picamera")
    ir.on()
    assert not ir.is_on
