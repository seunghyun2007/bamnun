#!/usr/bin/env bash
# One-shot setup on a fresh Raspberry Pi OS (64-bit) install, bookworm or trixie.
#
#   bash setup_pi.sh
#
# Idempotent: safe to re-run.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "== checking platform =="
if ! grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
  echo "   not a Raspberry Pi; this script is for the Pi only." >&2
  exit 1
fi
echo "   $(tr -d '\0' < /proc/device-tree/model)"
echo "   python $(python3 --version)"

echo "== apt packages =="
# picamera2 and libcamera are apt-only. libgl1/libglib are opencv's runtime
# deps. lgpio backs gpiozero on the Pi 5, where RPi.GPIO does not work.
#
# trixie renamed libglib2.0-0 to libglib2.0-0t64 (the 64-bit time_t
# transition) and dropped libatlas-base-dev; asking for either old name makes
# apt fail the whole install. numpy's wheels bundle OpenBLAS, so ATLAS is not
# needed on either release.
sudo apt-get update
GLIB=libglib2.0-0t64
apt-cache show "$GLIB" >/dev/null 2>&1 || GLIB=libglib2.0-0   # bookworm
sudo apt-get install -y \
  python3-picamera2 python3-libcamera python3-venv python3-dev \
  libgl1 "$GLIB" \
  python3-lgpio

echo "== virtual environment =="
if [ ! -d .venv ]; then
  # --system-site-packages is required: a plain venv cannot see the apt-
  # installed picamera2, and there is no usable pip version of it.
  python3 -m venv --system-site-packages .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
pip install gpiozero lgpio

echo "== landmark model =="
python tools/download_models.py

echo "== camera check =="
if command -v rpicam-hello >/dev/null 2>&1; then
  rpicam-hello --list-cameras || true
elif command -v libcamera-hello >/dev/null 2>&1; then
  libcamera-hello --list-cameras || true
else
  echo "   no rpicam-hello/libcamera-hello found" >&2
fi

echo "== gpio check =="
python - <<'PY' || true
try:
    from gpiozero import Device
    from gpiozero.pins.lgpio import LGPIOFactory
    Device.pin_factory = LGPIOFactory()
    print("   gpiozero + lgpio OK")
except Exception as exc:
    print(f"   gpiozero unavailable ({exc}); actuators will run as stubs")
PY

echo "== self test =="
python -m pytest tests/ -q

cat <<'EOS'

Done. Next:

  source .venv/bin/activate
  python tools/focus_sweep.py            # pin the IMX708 lens position FIRST
  python -m bamnun.app --source picamera

If --source picamera fails with "no cameras available", the cable is the
usual cause: the Pi 5 needs a 22-pin to 15-pin camera cable, not the 15-pin
one that ships with Camera Module 3.
EOS
