#!/usr/bin/env bash
# Switch the booth on or off. Run on the Pi after setup_booth.sh.
#
#   tools/booth/booth.sh on       hotspot on; the booth starts now and at every login
#   tools/booth/booth.sh off      hotspot off, normal Wi-Fi back, booth stops starting
#   tools/booth/booth.sh status

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CON=bamnun-booth
AUTOSTART="$HOME/.config/autostart/bamnun-booth.desktop"

case "${1:-status}" in
on)
    sudo nmcli connection modify "$CON" connection.autoconnect yes connection.autoconnect-priority 100
    sudo nmcli connection up "$CON"
    mkdir -p "$(dirname "$AUTOSTART")"
    cp "$HOME/.local/share/applications/bamnun-booth.desktop" "$AUTOSTART"
    echo "Hotspot on. Phones: join 'Bamnun-Demo'. The booth starts at every login."
    pgrep -f "bamnun.app.*--booth" >/dev/null || nohup "$ROOT/tools/booth/start.sh" >/dev/null 2>&1 &
    ;;
off)
    rm -f "$AUTOSTART"
    pkill -f "tools/booth/start.sh" || true
    pkill -f "bamnun.app.*--booth" || true
    sudo nmcli connection modify "$CON" connection.autoconnect no
    sudo nmcli connection down "$CON" || true
    # Hand the radio back to whatever normal Wi-Fi it knows.
    sudo nmcli device connect wlan0 >/dev/null 2>&1 || true
    echo "Booth off. Normal Wi-Fi: $(nmcli -t -f GENERAL.CONNECTION device show wlan0 | cut -d: -f2)"
    ;;
status)
    echo "Wi-Fi:     $(nmcli -t -f GENERAL.CONNECTION device show wlan0 | cut -d: -f2)"
    echo "Autostart: $([ -f "$AUTOSTART" ] && echo on || echo off)"
    echo "Running:   $(pgrep -f "bamnun.app.*--booth" >/dev/null && echo yes || echo no)"
    ;;
*)
    echo "usage: $0 on|off|status" >&2; exit 2 ;;
esac
