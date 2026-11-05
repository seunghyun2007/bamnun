#!/usr/bin/env bash
# Switch the booth on or off. Run on the Pi after setup_booth.sh.
#
#   tools/booth/booth.sh on       hotspot on; the booth starts now and at every login
#   tools/booth/booth.sh try 10   the same for 10 minutes, then off by itself (for
#                                 trying it over Pi Connect or SSH, which drop)
#   tools/booth/booth.sh off      hotspot off, normal Wi-Fi back, booth stops starting
#   tools/booth/booth.sh home     the booth on the normal Wi-Fi: camera on the monitor,
#                                 the app for phones on the same Wi-Fi, and the Pi stays
#                                 reachable (Tailscale, Pi Connect) for practising
#   tools/booth/booth.sh stop     stop the booth program, leave the Wi-Fi alone
#   tools/booth/booth.sh status

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CON=bamnun-booth
AUTOSTART="$HOME/.config/autostart/bamnun-booth.desktop"

# Its own service, so it outlives the SSH or Pi Connect session that started it.
start_booth() {
    pgrep -f "bamnun.app.*--booth" >/dev/null && return
    systemctl --user reset-failed bamnun-booth.service >/dev/null 2>&1 || true
    systemd-run --user --quiet --unit=bamnun-booth "$ROOT/tools/booth/start.sh"
}

case "${1:-status}" in
try)
    # Booth on for a few minutes, then back to normal Wi-Fi by itself, so it
    # can be tried over Pi Connect or SSH, which drop while the hotspot is on.
    # Nothing is set to start at boot: unplugging the Pi also undoes it.
    MIN="${2:-10}"
    systemctl --user stop bamnun-booth-revert.timer >/dev/null 2>&1 || true
    systemd-run --user --quiet --unit=bamnun-booth-revert --on-active="${MIN}m" \
        "$ROOT/tools/booth/booth.sh" off
    echo "Booth on for $MIN minutes, then back to normal Wi-Fi by itself."
    echo "Your remote session will drop now and come back after that."
    sleep 2
    start_booth
    sudo nmcli connection up "$CON"
    ;;
on)
    sudo nmcli connection modify "$CON" connection.autoconnect yes connection.autoconnect-priority 100
    mkdir -p "$(dirname "$AUTOSTART")"
    cp "$HOME/.local/share/applications/bamnun-booth.desktop" "$AUTOSTART"
    echo "Hotspot on. Phones: join 'Bamnun-Demo'. The booth starts at every login."
    start_booth
    sudo nmcli connection up "$CON"
    ;;
home)
    start_booth
    ip="$(hostname -I | awk '{print $1}')"
    echo "Booth running on the normal Wi-Fi. Phones on the same Wi-Fi: http://$ip"
    ;;
stop)
    systemctl --user stop bamnun-booth.service >/dev/null 2>&1 || true
    pkill -f "tools/booth/start.sh" || true
    pkill -f "bamnun.app.*--booth" || true
    echo "Booth program stopped. Wi-Fi unchanged."
    ;;
off)
    # Over SSH on the booth's Wi-Fi, taking the hotspot down cuts the
    # session halfway through, so finish in the background.
    if [ -n "${SSH_CONNECTION:-}" ] && [ -z "${BOOTH_DETACHED:-}" ]; then
        systemctl --user reset-failed bamnun-booth-off.service >/dev/null 2>&1 || true
        systemd-run --user --quiet --unit=bamnun-booth-off --setenv=BOOTH_DETACHED=1 "$ROOT/tools/booth/booth.sh" off
        echo "Switching the booth off. This session will drop; the Pi goes back to normal Wi-Fi."
        exit 0
    fi
    systemctl --user stop bamnun-booth-revert.timer >/dev/null 2>&1 || true
    rm -f "$AUTOSTART"
    systemctl --user stop bamnun-booth.service >/dev/null 2>&1 || true
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
    echo "Address:   http://$(hostname -I | awk '{print $1}')"
    ;;
*)
    echo "usage: $0 on|off|try [minutes]|home|stop|status" >&2; exit 2 ;;
esac
