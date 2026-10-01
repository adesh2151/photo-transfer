#!/usr/bin/env bash
# Build a standalone, double-clickable "Photo Transfer" app for Linux.
# Run this on a Linux machine. Produces: dist/PhotoTransfer/
set -e
cd "$(dirname "$0")"

python3 -m pip install --user -q segno pyinstaller

python3 -m PyInstaller --noconfirm --onedir --windowed \
  --name PhotoTransfer \
  --hidden-import segno \
  app.py

# Drop the icon next to the binary and add a double-click .desktop launcher.
cp -f icon.png "dist/PhotoTransfer/icon.png" 2>/dev/null || true
cat > "dist/PhotoTransfer/PhotoTransfer.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Photo Transfer
Comment=Share files between phones and computers over WiFi
Exec=./PhotoTransfer
Icon=./icon.png
Terminal=false
Categories=Network;Utility;
EOF
chmod +x "dist/PhotoTransfer/PhotoTransfer" "dist/PhotoTransfer/PhotoTransfer.desktop" 2>/dev/null || true

echo
echo "✅ Done -> dist/PhotoTransfer/"
echo "   Share the whole 'PhotoTransfer' folder. The user double-clicks 'PhotoTransfer'."
