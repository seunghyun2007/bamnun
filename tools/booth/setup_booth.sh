#!/usr/bin/env bash
# One-time setup that turns the Pi into a demo booth. Run on the Pi:
#
#   bash tools/booth/setup_booth.sh
#
# It prepares, but doesn't switch on:
#   * an open Wi-Fi hotspot, "Bamnun-Demo", at 10.42.0.1 (NetworkManager);
#   * DNS on that hotspot that answers every name with the Pi, so a phone's
#     "am I online?" check reaches Bamnun, which answers it so the phone
#     stays on the Wi-Fi (server.py, booth mode);
#   * permission for the app to listen on port 80, where phones look;
#   * a launcher that starts the booth when the desktop logs in.
#
# Then `tools/booth/booth.sh on` switches the Pi over, and `booth.sh off`
# puts it back on your normal Wi-Fi. Idempotent: safe to re-run.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSID="${BOOTH_SSID:-Bamnun-Demo}"
CON=bamnun-booth

if ! grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
    echo "not a Raspberry Pi; this script is for the Pi only." >&2
    exit 1
fi
if ! command -v nmcli >/dev/null; then
    echo "NetworkManager (nmcli) not found; Raspberry Pi OS bookworm or later uses it." >&2
    exit 1
fi

echo "== Wi-Fi country =="
# The radio refuses to be an access point until a country is set.
if [ -z "$(sudo raspi-config nonint get_wifi_country 2>/dev/null)" ]; then
    echo "   none set; using KR (change with: sudo raspi-config nonint do_wifi_country XX)"
    sudo raspi-config nonint do_wifi_country KR
else
    echo "   $(sudo raspi-config nonint get_wifi_country)"
fi

echo "== hotspot connection '$CON' (SSID $SSID, open) =="
if nmcli -t -f NAME connection show | grep -qx "$CON"; then
    sudo nmcli connection delete "$CON" >/dev/null
fi
sudo nmcli connection add type wifi ifname wlan0 con-name "$CON" autoconnect no \
    ssid "$SSID" 802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled >/dev/null
echo "   created (not switched on)"

echo "== catch-all DNS on the hotspot only =="
# NetworkManager runs its own dnsmasq for "shared" connections and reads this
# directory; the Pi's normal Wi-Fi and its own lookups are not affected.
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
echo "address=/#/10.42.0.1" | sudo tee /etc/NetworkManager/dnsmasq-shared.d/bamnun-booth.conf >/dev/null
echo "   every name -> 10.42.0.1"

echo "== port 80 for the app =="
# Phones check http://<something>/ on port 80. Letting ordinary programs use
# ports from 80 up means the app needs no root.
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/90-bamnun-booth.conf >/dev/null
sudo sysctl -q -p /etc/sysctl.d/90-bamnun-booth.conf
echo "   ok"

echo "== launcher =="
chmod +x "$ROOT/tools/booth/"*.sh "$ROOT/tools/run_pi.sh"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/bamnun-booth.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=Bamnun booth
Comment=Start the Bamnun demo booth
Exec=$ROOT/tools/booth/start.sh
Icon=$ROOT/assets/bamnun.png
Terminal=false
Categories=Utility;
EOD
echo "   menu entry 'Bamnun booth' added"

echo "== app build =="
python3 "$ROOT/frontend/build/build.py" "$ROOT/frontend/screens" \
    "$ROOT/frontend/www/index.html" "$ROOT/frontend/ollie"

cat <<EOS

Done. When you're ready (this disconnects the Pi from your normal Wi-Fi):

  tools/booth/booth.sh on      # hotspot on, and the booth starts at every login
  tools/booth/booth.sh off     # back to normal Wi-Fi, booth no longer starts

Use a keyboard and screen on the Pi, or an Ethernet cable, for this step:
an SSH or Pi Connect session over Wi-Fi drops when the hotspot comes on.
EOS
