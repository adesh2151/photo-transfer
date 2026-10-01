#!/usr/bin/env bash
# Linux: add "Photo Transfer" to your app menu so you can launch it without a terminal.
# (macOS/Windows: see README for how to make a shortcut.)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
DESKTOP="$APPS/photo-transfer.desktop"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Photo Transfer
Comment=Share files between phones and computers over WiFi
Exec=bash "$DIR/run.sh"
Icon=$DIR/icon.png
Terminal=true
Categories=Network;FileTransfer;Utility;
EOF

chmod +x "$DESKTOP" 2>/dev/null || true
update-desktop-database "$APPS" >/dev/null 2>&1 || true
echo "✅ Installed. Search your apps for 'Photo Transfer'."
echo "   (To remove: rm \"$DESKTOP\")"
