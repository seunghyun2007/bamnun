"""Actuators and the graded escalation policy.

The novelty claim of this project rests here, so the design has to survive
questioning. Three points to be ready for:

1. WHY ESCALATE AT ALL. A single loud alarm has two failure modes. If it is
   quiet enough to be tolerable it gets ignored, and if it is startling enough
   to work it gets switched off after the second false positive, or it causes
   a startle response that is itself dangerous. Graded escalation spends the
   cheapest stimulus first and reserves the strong one for evidence that is
   already strong.

2. WHY SCENT AND COLD AIR. Both act through arousal pathways that do not
   habituate the way a repeated tone does. Trigeminal stimulation from
   peppermint (menthol) and cutaneous cooling of the face and neck both raise
   sympathetic tone. Crucially for a driver, neither one demands a visual or
   manual response, so neither competes with the driving task the way a
   screen or a button does. That is the argument: not "it is novel", but "it
   is a modality that is currently unused because it is inconvenient to
   build, and we built it for 30,000 won".

3. WHY REFRACTORY PERIODS. Olfactory adaptation is fast, on the order of
   tens of seconds of continuous exposure. Firing the atomizer repeatedly
   makes it useless and makes the cabin unpleasant. Each actuator therefore
   declares a refractory period and an hourly budget, and the policy respects
   both. This is the kind of detail that separates a built prototype from a
   block diagram, and it belongs on the poster.

Hardware note for the Pi 5: RPi.GPIO does not work on the Pi 5 because of the
RP1 I/O controller. Use gpiozero with the lgpio pin factory. If gpiozero is
absent, every actuator degrades to a logging stub, which is what lets the full
policy be exercised on a laptop.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Optional

log = logging.getLogger("bamnun.alerts")

try:  # pragma: no cover - hardware only
    from gpiozero import PWMOutputDevice, OutputDevice  # type: ignore
    _HAVE_GPIO = True
except Exception:  # noqa: BLE001
    _HAVE_GPIO = False


# --------------------------------------------------------------------------- #
# Actuators
# --------------------------------------------------------------------------- #


@dataclass
class Actuation:
    t: float
    actuator: str
    stage: str
    detail: str = ""


class Actuator(ABC):
    """Base class. Enforces refractory period and hourly budget centrally."""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self.cfg = cfg
        self.refractory_s = float(cfg.get("refractory_s", 0.0))
        self.max_per_hour = int(cfg.get("max_per_hour", 0)) or None
        self._last_fired: Optional[float] = None
        self._history: Deque[float] = deque()
        self.available = True

    def can_fire(self, t: float) -> tuple[bool, str]:
        if not self.available:
            return (False, "unavailable")
        if self._last_fired is not None and (t - self._last_fired) < self.refractory_s:
            remaining = self.refractory_s - (t - self._last_fired)
            return (False, f"refractory {remaining:.0f}s")
        if self.max_per_hour is not None:
            cutoff = t - 3600.0
            while self._history and self._history[0] < cutoff:
                self._history.popleft()
            if len(self._history) >= self.max_per_hour:
                return (False, "hourly budget exhausted")
        return (True, "")

    def fire(self, t: float, stage: str) -> Optional[Actuation]:
        ok, why = self.can_fire(t)
        if not ok:
            log.debug("%s suppressed: %s", self.name, why)
            return None
        self._last_fired = t
        self._history.append(t)
        detail = self._do_fire()
        log.info("actuator %s fired (stage=%s) %s", self.name, stage, detail)
        return Actuation(t=t, actuator=self.name, stage=stage, detail=detail)

    @abstractmethod
    def _do_fire(self) -> str: ...

    def prepare(self, t: float) -> None:
        """Optional pre-arming hook. Used by the thermal actuator."""

    def close(self) -> None: ...


class NullActuator(Actuator):
    """Logging stub used when the hardware is absent. Keeps timing identical."""

    def _do_fire(self) -> str:
        return "(simulated)"


class BuzzerActuator(Actuator):
    """Piezo buzzer on a PWM pin. Stage-1 notification."""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.pin = int(cfg.get("gpio_pin", 18))
        self.hz = float(cfg.get("pwm_hz", 2400))
        self.duration = float(cfg.get("duration_s", 0.6))
        self._dev = None
        if _HAVE_GPIO:  # pragma: no cover
            try:
                self._dev = PWMOutputDevice(self.pin, frequency=self.hz, initial_value=0.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("buzzer init failed on pin %s: %s", self.pin, exc)
                self.available = False
        else:
            log.info("gpiozero absent, buzzer %s simulated", name)

    def _do_fire(self) -> str:
        if self._dev is None:
            return "(simulated buzz)"

        def run():  # pragma: no cover - hardware only
            try:
                self._dev.value = 0.5
                time.sleep(self.duration)
            finally:
                self._dev.value = 0.0

        threading.Thread(target=run, daemon=True).start()
        return f"{self.hz:.0f} Hz for {self.duration:.2f}s"

    def close(self) -> None:
        if self._dev is not None:  # pragma: no cover
            try:
                self._dev.value = 0.0
                self._dev.close()
            except Exception:
                pass


class AudioActuator(Actuator):
    """Spoken warning through the Pi's audio output."""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.path = Path(str(cfg.get("file", "")))
        self._player = None
        for candidate in ("aplay", "paplay", "afplay", "ffplay"):
            if shutil.which(candidate):
                self._player = candidate
                break
        if self._player is None or not self.path.exists():
            log.info("audio actuator %s simulated (player=%s, file exists=%s)",
                     name, self._player, self.path.exists())

    def _do_fire(self) -> str:
        if self._player is None or not self.path.exists():
            return "(simulated voice prompt)"
        cmd = [self._player]
        if self._player == "ffplay":
            cmd += ["-nodisp", "-autoexit", "-loglevel", "quiet"]
        cmd.append(str(self.path))
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            return f"(failed: {exc})"
        return f"played {self.path.name}"


class AtomizerActuator(Actuator):
    """Piezo ultrasonic atomizer holding peppermint solution.

    Driven through a MOSFET, not directly from a GPIO: the atomizer driver
    board pulls far more than the 16 mA a Pi pin can source. The refractory
    period is the important part of this class, not the pin toggle.
    """

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.pin = int(cfg.get("gpio_pin", 23))
        self.duration = float(cfg.get("duration_s", 0.35))
        self._dev = None
        if _HAVE_GPIO:  # pragma: no cover
            try:
                self._dev = OutputDevice(self.pin, active_high=True, initial_value=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("atomizer init failed on pin %s: %s", self.pin, exc)
                self.available = False
        else:
            log.info("gpiozero absent, atomizer %s simulated", name)

    def _do_fire(self) -> str:
        if self._dev is None:
            return f"(simulated {self.duration:.2f}s scent burst)"

        def run():  # pragma: no cover
            try:
                self._dev.on()
                time.sleep(self.duration)
            finally:
                self._dev.off()

        threading.Thread(target=run, daemon=True).start()
        return f"{self.duration:.2f}s burst"

    def close(self) -> None:
        if self._dev is not None:  # pragma: no cover
            try:
                self._dev.off()
                self._dev.close()
            except Exception:
                pass


class PeltierFanActuator(Actuator):
    """Thermoelectric cold-air burst aimed at the face and neck.

    Physics that determines the design: a TEC1-12706 module moves heat, it
    does not create cold instantly. The cold side needs a heat-sunk hot side
    and roughly 15 to 30 seconds of lead time to reach a useful delta-T. So
    this actuator has a ``prepare`` step: the policy pre-cools the module as
    soon as the driver reaches the intermediate drowsiness level, and the
    burst itself only switches on the fan. That is what makes the stage-3
    response instantaneous instead of half a minute late.

    Practical figures to measure and report: delta-T achieved at the outlet,
    electrical power drawn, and the measured latency from trigger to a
    2-degree drop at 30 cm. Those three numbers are exactly what a hardware
    judge will ask for.
    """

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.fan_pin = int(cfg.get("fan_gpio_pin", 24))
        self.peltier_pin = int(cfg.get("peltier_gpio_pin", 25))
        self.precool_s = float(cfg.get("precool_s", 20.0))
        self.burst_s = float(cfg.get("burst_s", 4.0))
        self._fan = None
        self._peltier = None
        self._precooling_since: Optional[float] = None
        if _HAVE_GPIO:  # pragma: no cover
            try:
                self._fan = OutputDevice(self.fan_pin, initial_value=False)
                self._peltier = OutputDevice(self.peltier_pin, initial_value=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("thermal init failed: %s", exc)
                self.available = False
        else:
            log.info("gpiozero absent, thermal actuator %s simulated", name)

    @property
    def precooled(self) -> bool:
        return (self._precooling_since is not None
                and (time.monotonic() - self._precooling_since) >= self.precool_s)

    def prepare(self, t: float) -> None:
        if self._precooling_since is not None:
            return
        self._precooling_since = time.monotonic()
        log.info("thermal actuator pre-cooling started (%.0fs to ready)", self.precool_s)
        if self._peltier is not None:  # pragma: no cover
            self._peltier.on()

    def standdown(self) -> None:
        if self._precooling_since is None:
            return
        self._precooling_since = None
        log.info("thermal actuator pre-cool stopped")
        if self._peltier is not None:  # pragma: no cover
            self._peltier.off()

    def _do_fire(self) -> str:
        ready = "ready" if self.precooled else "NOT pre-cooled, reduced effect"
        if self._fan is None:
            return f"(simulated {self.burst_s:.1f}s cold burst, {ready})"

        def run():  # pragma: no cover
            try:
                if self._peltier is not None:
                    self._peltier.on()
                self._fan.on()
                time.sleep(self.burst_s)
            finally:
                self._fan.off()

        threading.Thread(target=run, daemon=True).start()
        return f"{self.burst_s:.1f}s burst, {ready}"

    def close(self) -> None:  # pragma: no cover
        for dev in (self._fan, self._peltier):
            if dev is not None:
                try:
                    dev.off()
                    dev.close()
                except Exception:
                    pass


_ACTUATOR_TYPES = {
    "buzzer": BuzzerActuator,
    "audio": AudioActuator,
    "atomizer": AtomizerActuator,
    "peltier_fan": PeltierFanActuator,
    "null": NullActuator,
}


def build_actuators(cfg: dict[str, Any]) -> dict[str, Actuator]:
    out: dict[str, Actuator] = {}
    for name, spec in (cfg.get("actuators") or {}).items():
        kind = str(spec.get("type", "null"))
        cls = _ACTUATOR_TYPES.get(kind, NullActuator)
        try:
            out[name] = cls(name, spec)
        except Exception as exc:  # noqa: BLE001
            log.warning("actuator %s (%s) failed to build: %s; using stub", name, kind, exc)
            out[name] = NullActuator(name, spec)
    return out


# --------------------------------------------------------------------------- #
# Escalation policy
# --------------------------------------------------------------------------- #


@dataclass
class AlertDecision:
    t: float = 0.0
    stage: int = 0
    stage_name: str = "none"
    changed: bool = False
    fired: list[Actuation] = field(default_factory=list)
    suppressed: list[str] = field(default_factory=list)
    message: str = ""


class EscalationPolicy:
    """Maps driver state level onto actuator stages.

    Stage index tracks the state level index by default, so the mapping is
    trivially auditable: level 1 (mild) fires stage 1, and so on. Distraction
    short-circuits to stage 1 regardless of the drowsiness level, because the
    correct response to a two-second glance away is an immediate small nudge,
    not a scent burst.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.enabled = bool(cfg.get("enabled", True))
        self.stages = list(cfg.get("stages", [{"name": "none", "actuators": []}]))
        self.actuators = build_actuators(cfg)
        self._stage = 0
        self._stage_entered_at = 0.0
        self._stage_cooldown_until = 0.0
        self.history: list[Actuation] = []

    @property
    def stage(self) -> int:
        return self._stage

    def _thermal(self) -> Optional[PeltierFanActuator]:
        for a in self.actuators.values():
            if isinstance(a, PeltierFanActuator):
                return a
        return None

    def update(self, state, distracted_override: Optional[bool] = None) -> AlertDecision:
        t = state.t
        if not self.enabled:
            return AlertDecision(t=t, stage=0, stage_name="disabled")

        distracted = state.distracted if distracted_override is None else distracted_override

        target = min(int(state.level), len(self.stages) - 1)
        if distracted:
            target = max(target, 1)
        # Never alert before calibration: an uncalibrated EAR baseline makes
        # false positives near-certain and a false positive in front of a
        # judge is worse than a miss.
        if not state.calibrated:
            target = 0
        # A face that has been lost for a long time also should not drive the
        # escalation ladder upward; there is no ocular evidence.
        if state.face_lost and state.face_lost_s > 5.0:
            target = min(target, 1)

        decision = AlertDecision(t=t, stage=self._stage,
                                 stage_name=str(self.stages[self._stage].get("name", "")))

        thermal = self._thermal()
        if thermal is not None:
            # Pre-cool one stage ahead of need, stand down when calm again.
            if target >= max(1, len(self.stages) - 2):
                thermal.prepare(t)
            elif target == 0:
                thermal.standdown()

        if target == self._stage:
            # Re-fire within a stage once the cooldown expires and the
            # condition still holds. Without this a driver who parks at the
            # top level with their eyes open gets exactly one warning for the
            # rest of the drive.
            if self._stage > 0 and t >= self._stage_cooldown_until:
                note = "re-fire (microsleep)" if state.emergency else "re-fire (sustained)"
                return self._fire_stage(t, self._stage, changed=False, note=note)
            return decision

        if target < self._stage:
            self._stage = target
            self._stage_entered_at = t
            # Arm the new stage's cooldown rather than clearing it. Clearing it
            # meant that the frame after a microsleep ended, the policy dropped
            # from "shock" to "rouse" and then instantly re-fired "rouse",
            # producing a burst of alternating alerts every time a closure
            # finished. Entering a lower stage is a relaxation, not a reason to
            # actuate.
            self._stage_cooldown_until = t + float(
                self.stages[target].get("cooldown_s", 30.0)
            )
            if target == 0 and thermal is not None:
                thermal.standdown()
            return AlertDecision(t=t, stage=target,
                                 stage_name=str(self.stages[target].get("name", "")),
                                 changed=True, message="de-escalated")

        # Escalation. An active microsleep skips the ladder and goes straight
        # to the target stage, but only as a STEP UP. Without that guard the
        # override re-entered the top stage on every frame for the whole
        # duration of the closure, so a two-second closure at 25 Hz produced
        # fifty actuation attempts; per-actuator refractory periods hid most of
        # it, but any actuator without one fired fifty times.
        #
        # The cooldown gate on the normal path is the other half of the
        # design. Stepping "one stage per update" sounds like a ladder, but
        # the loop runs at 25 Hz, so all three stages would fire inside
        # 120 ms. Gating on the cooldown makes the ladder real: notify, wait,
        # rouse, wait, shock.
        if state.emergency and target > self._stage:
            return self._fire_stage(t, target, changed=True, note="microsleep override")
        if self._stage > 0 and t < self._stage_cooldown_until:
            return decision
        return self._fire_stage(t, min(self._stage + 1, target), changed=True)

    def _fire_stage(self, t: float, stage_idx: int, changed: bool,
                    note: str = "") -> AlertDecision:
        spec = self.stages[stage_idx]
        name = str(spec.get("name", str(stage_idx)))
        fired: list[Actuation] = []
        suppressed: list[str] = []

        for act_name in spec.get("actuators", []) or []:
            act = self.actuators.get(act_name)
            if act is None:
                suppressed.append(f"{act_name}: not configured")
                continue
            ok, why = act.can_fire(t)
            if not ok:
                suppressed.append(f"{act_name}: {why}")
                continue
            a = act.fire(t, name)
            if a is not None:
                fired.append(a)
                self.history.append(a)

        self._stage = stage_idx
        self._stage_entered_at = t
        self._stage_cooldown_until = t + float(spec.get("cooldown_s", 30.0))
        return AlertDecision(t=t, stage=stage_idx, stage_name=name, changed=changed,
                             fired=fired, suppressed=suppressed, message=note)

    def close(self) -> None:
        for a in self.actuators.values():
            a.close()
