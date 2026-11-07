#!/usr/bin/env bash
# Control the booth Pi from a laptop, wherever it is.
#
#   tools/booth/pi.sh status          what the Pi is doing
#   tools/booth/pi.sh off             booth off, Pi back on its normal Wi-Fi
#   tools/booth/pi.sh on              booth on (and at every start-up)
#   tools/booth/pi.sh try 10          booth for 10 minutes, then off by itself
#   tools/booth/pi.sh home            booth on the normal Wi-Fi: stays reachable
#   tools/booth/pi.sh stop            stop the booth program, Wi-Fi unchanged
#   tools/booth/pi.sh restart         restart the booth program (after an update)
#   tools/booth/pi.sh logs            follow the booth's log (Ctrl+C to stop)
#   tools/booth/pi.sh log             the last 40 lines of it
#   tools/booth/pi.sh update          pull this branch onto the Pi
#   tools/booth/pi.sh stage 3         play wake-up stage 3 on the device (booth running)
#   tools/booth/pi.sh say greet ko    Ollie says a line on the device's speaker
#   tools/booth/pi.sh volume [80]     show, or set, the speaker volume in %
#   tools/booth/pi.sh ssh             a shell on the Pi
#   tools/booth/pi.sh rescue          the Pi is a hotspot and out of reach: join
#                                     "Bamnun-Demo" on this Mac and turn the booth off
#   tools/booth/pi.sh setup           once, while the Pi is online: let this Mac in
#                                     without a password (needed by rescue)
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

on_pi() {   # run a command on the Pi; BatchMode so nothing waits for typing
    local host; host="$(pick)"
    echo "(via $host)"
    # ServerAlive: when the Pi drops off (it switched to its hotspot), give up
    # in about 10 s instead of waiting for TCP to notice.
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -o ServerAliveInterval=5 -o ServerAliveCountMax=2 "$host" "cd $REPO && $*"
}
run() { on_pi "tools/booth/booth.sh $*"; }   # a booth.sh command

SPEAKER=UACDemoV10   # the USB speaker the device plays through (~/.asoundrc)

case "${1:-status}" in
status|on|off|home|stop) run "$1" ;;
try)     run try "${2:-10}" ;;
restart) on_pi 'systemctl --user restart bamnun-booth.service 2>/dev/null && echo "booth restarted" || echo "the booth isn'"'"'t running; start it with: on or try"' ;;
logs)    host="$(pick)"; echo "(via $host)"; ssh -t "$host" 'tail -n 40 -f ~/bamnun-booth.log' ;;
log)     on_pi 'tail -n 40 ~/bamnun-booth.log 2>/dev/null || echo "no booth log yet"' ;;
update)  on_pi "git pull --ff-only && git log --oneline -1" ;;
stage)   n="${2:-1}"; [[ "$n" =~ ^[1-4]$ ]] || { echo "stage must be 1 to 4" >&2; exit 2; }
         on_pi "curl -s -m 5 -X POST http://127.0.0.1/api/showcase/stage/$n || echo 'the booth isn'\''t running; start it with: on or try'"; echo ;;
say)     line="${2:-greet}"; lang="${3:-en}"
         [[ "$line" =~ ^[a-z_0-9]+$ && "$lang" =~ ^(en|ko)$ ]] || { echo "usage: say LINE [en|ko]" >&2; exit 2; }
         on_pi "aplay -q assets/voice/$lang/$line.wav && echo 'Ollie said $lang/$line'" ;;
volume)  if [ -n "${2:-}" ]; then
             [[ "$2" =~ ^[0-9]+$ ]] && [ "$2" -le 100 ] || { echo "volume must be 0 to 100" >&2; exit 2; }
             on_pi "amixer -q -c $SPEAKER sset PCM $2% && sudo alsactl store $SPEAKER && echo 'volume set to $2% (saved)'"
         else
             on_pi "amixer -c $SPEAKER sget PCM | grep -o '\\[[0-9]*%\\]' | head -1 | tr -d '[]' | sed 's/^/volume: /'"
         fi ;;
ssh)     host="$(pick)"; exec ssh -t "$host" "cd $REPO; exec \$SHELL -l" ;;
setup)   # Opens Terminal: the first connection may ask to approve or for a password.
         osascript -e "tell application \"Terminal\" to do script \"ssh-copy-id $TS_HOST && echo && echo 'Done: this Mac can now control the Pi in booth mode. You can close this window.'\"" \
             -e 'tell application "Terminal" to activate' >/dev/null
         echo "Opened Terminal to add this Mac's key to the Pi (ssh-copy-id $TS_HOST)." ;;
rescue)  # The Pi's Wi-Fi is the Bamnun-Demo hotspot, so it can only be reached from
         # inside that network. Join it, turn the booth off; when the hotspot goes,
         # this Mac rejoins its usual Wi-Fi by itself.
         dev="$(networksetup -listallhardwareports | awk '/Wi-Fi/{getline; print $2; exit}')"
         echo "Joining the Bamnun-Demo Wi-Fi on this Mac ($dev)..."
         if ! networksetup -setairportnetwork "$dev" "Bamnun-Demo" >/dev/null 2>&1; then
             echo "Couldn't join Bamnun-Demo. Is the booth hotspot on, and the Pi nearby?"; exit 1
         fi
         for _ in $(seq 1 25); do ping -c1 -t1 "$BOOTH_IP" >/dev/null 2>&1 && break; sleep 1; done
         if ssh -o ConnectTimeout=6 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
                "$USER_ON_PI@$BOOTH_IP" "cd $REPO && tools/booth/booth.sh off"; then
             echo "The Pi is going back to its normal Wi-Fi; this Mac will rejoin yours in a moment."
         else
             echo "On Bamnun-Demo, but the Pi didn't accept this Mac's key (run setup once, later)."
             echo "Opening Terminal: type the Pi's password there to turn the booth off."
             osascript -e "tell application \"Terminal\" to do script \"ssh -o StrictHostKeyChecking=accept-new $USER_ON_PI@$BOOTH_IP '$REPO/tools/booth/booth.sh off'\"" \
                 -e 'tell application "Terminal" to activate' >/dev/null
         fi ;;
*) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
