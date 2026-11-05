#!/usr/bin/env bash
# Build "Bamnun Control.app" (buttons for tools/booth/pi.sh) into ~/Applications.
#
#   bash tools/booth/mac/build.sh
#
# Needs the Xcode command line tools (xcode-select --install). The app runs
# pi.sh from this checkout, whose path is written into the app; rebuild if
# the repo moves.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
APP="$HOME/Applications/Bamnun Control.app"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

xcrun swiftc -O -swift-version 5 -parse-as-library -target arm64-apple-macos13 \
    -o "$APP/Contents/MacOS/BamnunControl" "$HERE/BamnunControl.swift"

# Icon from the device's own artwork.
ICONSET="$WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256; do
    sips -z $s $s "$ROOT/assets/bamnun.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2)); [ $d -le 256 ] && sips -z $d $d "$ROOT/assets/bamnun.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Bamnun Control</string>
  <key>CFBundleDisplayName</key><string>Bamnun Control</string>
  <key>CFBundleIdentifier</key><string>kr.bamnun.control</string>
  <key>CFBundleExecutable</key><string>BamnunControl</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>BamnunRepo</key><string>$ROOT</string>
</dict></plist>
PLIST

codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "Built: $APP"
