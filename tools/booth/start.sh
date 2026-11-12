#!/usr/bin/env bash
# What the booth runs at login (booth.sh on puts it in autostart): the
# monitor with the real camera, full screen on the Pi's monitor, serving the
# app to visitors' phones on port 80 with the Wi-Fi sign-in pop-up. If it
# ever stops, it starts again after a few seconds. Log: ~/bamnun-booth.log

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG="$HOME/bamnun-booth.log"

# Rebuild the app so the Pi always serves what's in this checkout.
python3 "$ROOT/frontend/build/build.py" "$ROOT/frontend/screens" \
    "$ROOT/frontend/www/index.html" "$ROOT/frontend/ollie" >>"$LOG" 2>&1

while true; do
    echo "== $(date) starting" >>"$LOG"
    "$ROOT/tools/run_pi.sh" --booth --host 0.0.0.0 --port 80 "$@" >>"$LOG" 2>&1
    echo "== $(date) stopped ($?), restarting in 5 s" >>"$LOG"
    sleep 5
done
