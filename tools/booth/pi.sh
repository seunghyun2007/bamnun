#!/usr/bin/env bash
# Control the booth Pi from a laptop, wherever it is.
#
#   tools/booth/pi.sh status          what the Pi is doing
#   tools/booth/pi.sh off             booth off, Pi back on its normal Wi-Fi
#   tools/booth/pi.sh on              booth on (and at every start-up)
#   tools/booth/pi.sh try 10          booth for 10 minutes, then off by itself
#   tools/booth/pi.sh restart         restart the booth program (after an update)
#   tools/booth/pi.sh logs            follow the booth's log (Ctrl+C to stop)
#   tools/booth/pi.sh update          pull this branch onto the Pi
#   tools/booth/pi.sh ssh             a shell on the Pi
#
# It reaches the Pi over Tailscale when the Pi is online, and otherwise over
# the booth's own Wi-Fi: join "Bamnun-Demo" on this laptop first, and the Pi
# is at 10.42.0.1. The second way needs this laptop's SSH key on the Pi once:
#     ssh-copy-id inpi            (while the Pi is online)
#
# BAMNUN_PI and BAMNUN_PI_USER pick another Pi (default: inpi, user inpi).

set -euo pipefail

TS_HOST="${BAMNUN_PI:-inpi}"
USER_ON_PI="${BAMNUN_PI_USER:-inpi}"
BOOTH_IP=10.42.0.1
REPO='~/bamnun'

pick() {
    if ssh -o ConnectTimeout=4 -o BatchMode=yes "$TS_HOST" true 2>/dev/null; then
        echo "$TS_HOST"
    elif ssh -o ConnectTimeout=4 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
            "$USER_ON_PI@$BOOTH_IP" true 2>/dev/null; then
        echo "$USER_ON_PI@$BOOTH_IP"
    else
        echo "Can't reach the Pi." >&2
        echo "  Online: check Tailscale is on, on this laptop and the Pi." >&2
        echo "  In booth mode: join the 'Bamnun-Demo' Wi-Fi on this laptop," >&2
        echo "  and make sure this laptop's key is on the Pi (ssh-copy-id $TS_HOST)." >&2
        exit 1
    fi
}

run() {   # run a booth.sh command on the Pi
    local host; host="$(pick)"
    echo "(via $host)"
    ssh -o StrictHostKeyChecking=accept-new "$host" "cd $REPO && tools/booth/booth.sh $*"
}

case "${1:-status}" in
status|on|off) run "$1" ;;
try)     run try "${2:-10}" ;;
restart) host="$(pick)"; echo "(via $host)"
         ssh "$host" 'systemctl --user restart bamnun-booth.service 2>/dev/null && echo "booth restarted" || echo "the booth isn'"'"'t running; start it with: on or try"' ;;
logs)    host="$(pick)"; echo "(via $host)"; ssh -t "$host" 'tail -n 40 -f ~/bamnun-booth.log' ;;
update)  host="$(pick)"; echo "(via $host)"
         ssh "$host" "cd $REPO && git pull --ff-only && git log --oneline -1" ;;
ssh)     host="$(pick)"; exec ssh -t "$host" "cd $REPO; exec \$SHELL -l" ;;
*) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
