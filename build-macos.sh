#!/usr/bin/env bash
# Build a standalone, double-clickable "Photo Transfer" app for macOS.
# Run this on a Mac. Produces: dist/Photo Transfer.app
set -e
cd "$(dirname "$0")"

python3 -m pip install --user -q segno pyinstaller pillow

# Make an .icns from icon.png (best-effort) for a nice Dock icon.
if command -v iconutil >/dev/null 2>&1; then
  rm -rf icon.iconset && mkdir -p icon.iconset
  for s in 16 32 64 128 256 512; do
    sips -z $s $s icon.png --out "icon.iconset/icon_${s}x${s}.png" >/dev/null 2>&1 || true
    d=$((s*2)); sips -z $d $d icon.png --out "icon.iconset/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns icon.iconset -o icon.icns 2>/dev/null || true
  rm -rf icon.iconset
fi

ICON=""
[ -f icon.icns ] && ICON="--icon icon.icns"

python3 -m PyInstaller --noconfirm --onedir --windowed \
  --name "Photo Transfer" \
  --hidden-import segno \
  $ICON \
  app.py

echo
echo "✅ Done -> dist/Photo Transfer.app"
echo "   Share the .app (zip it first). First open: right-click -> Open (unsigned app)."
