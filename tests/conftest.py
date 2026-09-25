"""Test-wide fixtures.

Keeps the suite off real hardware.

On a laptop gpiozero is simply absent, every actuator falls back to its logging
stub, and the alert tests exercise the policy without touching anything. On the
Pi gpiozero IS importable and its default factory is LGPIOFactory, so the same
tests construct real OutputDevices and drive real pins: a full run left GPIO23
energised (`is_active=True`) and every later test that wanted pin 23 failed with
"already in use", because the actuators are only closed by the app, not by the
tests that build them ad hoc.

Two reasons that matters more than the red test output. Once the atomizer and
the Peltier are wired, running pytest on the Pi would physically fire them, and
the README is explicit that an unsunk Peltier can destroy itself. And a suite
whose results depend on which pins a previous test leaked is not measuring the
code under test.

gpiozero ships MockFactory for exactly this. Installing a fresh one per test
makes every device virtual and gives each test its own pin reservations.
"""

from __future__ import annotations

import pytest

try:  # pragma: no cover - depends on the host, not on the code under test
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory
except Exception:  # noqa: BLE001 - gpiozero is absent on dev laptops
    Device = None
    MockFactory = None


@pytest.fixture(autouse=True)
def _never_touch_real_gpio():
    """Point gpiozero at a mock factory for the duration of each test."""
    if Device is None or MockFactory is None:
        yield
        return

    previous = Device.pin_factory
    Device.pin_factory = MockFactory()
    try:
        yield
    finally:
        try:
            Device.pin_factory.reset()   # releases every pin this test claimed
        except Exception:                # noqa: BLE001
            pass
        Device.pin_factory = previous
