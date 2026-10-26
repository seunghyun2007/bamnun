#!/usr/bin/env bash
# Launch the monitor on the Pi with a preview window.
#
# Exists because an SSH session, and anything started from a desktop entry,
# has no display environment of its own. OpenCV's wheel bundles only
# libqxcb.so -- X11, no Wayland plugin -- so the window has to go through
# XWayland, which labwc starts on demand at :0. Without these three variables
# cv2.imshow fails with "Available platform plugins are: xcb", which reads
# like a broken install rather than a missing DISPLAY.
#
#   ./tools/run_pi.sh                      live monitor, preview window
#   ./tools/run_pi.sh --no-window          headless, for a recording session
#   ./tools/run_pi.sh --duration 600 --tag drive1
#   ./tools/run_pi.sh --demo               showcase: keys fire each feature
#
# Any arguments are passed straight through to bamnun.app.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/python" ]; then
    echo "no venv at $ROOT/.venv -- see the Raspberry Pi section of README.md" >&2
    exit 1
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DISPLAY="${DISPLAY:-:0}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
# Qt ships no fonts in the opencv wheel and says so loudly on every start. It
# affects the title bar only; the overlay is drawn with cv2.putText into the
# image itself. Silenced so a real warning is visible.
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.fonts=false}"

# Not exec: the pins need resetting after the app has gone. gpiozero releases
# a pin as a floating input when it closes the device, and a floating MOSFET
# gate half-switches its load, so after every run the mister and the IR LED
# could sit partly on until the next reboot. Drive them low again, matching
# the gpio= line in /boot/firmware/config.txt. The trap also covers Ctrl-C
# and a crash.
ACTUATOR_PINS="17,24,25"
release_pins() {
    command -v pinctrl >/dev/null 2>&1 && pinctrl set "$ACTUATOR_PINS" op dl || true
}
trap release_pins EXIT

.venv/bin/python -m bamnun.app --source picamera "$@"
