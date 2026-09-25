#!/usr/bin/env bash
# Install a desktop launcher for bamnun on Raspberry Pi OS.
#
#   ./tools/install_desktop_entry.sh
#
# Adds the app to the menu and puts an icon on the desktop, so the monitor can
# be started from a Raspberry Pi Connect screen-sharing session without typing
# the display environment every time. Paths are written absolute from wherever
# this repo actually lives, so the entry keeps working if the checkout moves
# only if you re-run this.
#
# Terminal=true on purpose: calibration prints why it restarted ("N/M frames
# rejected for head pose ..."), which is the single most useful message the
# program emits, and a windowed launch with no console throws it away.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/bamnun.desktop"

chmod +x "$ROOT/tools/run_pi.sh"

if [ ! -f "$ROOT/assets/bamnun.png" ]; then
    echo "icon missing; generating it" >&2
    "$ROOT/.venv/bin/python" "$ROOT/tools/make_icon.py"
fi

mkdir -p "$APPS"
cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=bamnun
GenericName=Driver state monitor
Comment=Near-infrared drowsiness and distraction monitor
Exec=$ROOT/tools/run_pi.sh
Icon=$ROOT/assets/bamnun.png
Terminal=true
Categories=Utility;
StartupNotify=true
Actions=Record;Headless;

[Desktop Action Record]
Name=Record a 10-minute session
Exec=$ROOT/tools/run_pi.sh --duration 600 --tag session

[Desktop Action Headless]
Name=Run without a preview window
Exec=$ROOT/tools/run_pi.sh --no-window
EOF

chmod +x "$ENTRY"
echo "installed $ENTRY"

# The desktop folder is localised, so ask rather than assume "Desktop".
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ]; then
    cp "$ENTRY" "$DESKTOP_DIR/bamnun.desktop"
    chmod +x "$DESKTOP_DIR/bamnun.desktop"
    # pcmanfm will not launch an entry it does not trust; harmless if absent.
    gio set "$DESKTOP_DIR/bamnun.desktop" metadata::trusted true 2>/dev/null || true
    echo "installed $DESKTOP_DIR/bamnun.desktop"
fi

command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$APPS" 2>/dev/null || true

echo
echo "Done. It appears in the application menu, and on the desktop."
echo "If the desktop icon shows a quote mark, right-click it and allow launching."
