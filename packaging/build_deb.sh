#!/usr/bin/env bash
# Wrap the PyInstaller folder as a .deb:  packaging/build_deb.sh 0.1.4   ->  dist/writing-parrot_0.1.4_amd64.deb
# The app goes to /opt/writing-parrot, with a launcher in /usr/bin and a menu entry with its icon.
set -euo pipefail
VERSION="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/dist/WritingParrot"
PKG="$ROOT/build/deb/writing-parrot_${VERSION}_amd64"
[ -x "$SRC/WritingParrot" ] || { echo "$SRC/WritingParrot not found; run PyInstaller first" >&2; exit 1; }

rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -a "$SRC" "$PKG/opt/writing-parrot"
ln -s /opt/writing-parrot/WritingParrot "$PKG/usr/bin/writing-parrot"
cp "$ROOT/booktranscriber/assets/icon.png" "$PKG/usr/share/icons/hicolor/256x256/apps/writing-parrot.png"

cat > "$PKG/usr/share/applications/writing-parrot.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Writing Parrot
Name[fa]=طوطی‌نویس
Comment=Turn recordings into text on your own computer
Comment[fa]=تبدیل ضبط‌ها به متن روی کامپیوتر خودتان
Exec=/opt/writing-parrot/WritingParrot
Icon=writing-parrot
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupWMClass=WritingParrot
EOF

# Qt's own libraries are bundled; these are the system ones its xcb/Wayland plugins load.
# libxcb-cursor0 is the one a default Ubuntu install often lacks.
cat > "$PKG/DEBIAN/control" <<EOF
Package: writing-parrot
Version: $VERSION
Architecture: amd64
Maintainer: javadtavakoli <javadtavakoli@users.noreply.github.com>
Section: sound
Priority: optional
Installed-Size: $(du -sk "$PKG" | cut -f1)
Depends: libc6 (>= 2.35), libegl1, libgl1, libfontconfig1, libdbus-1-3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0
Homepage: https://github.com/javadtavakoli/book-transcriber
Description: Local, offline transcription of long recordings
 Writing Parrot turns long spoken-word recordings into Persian (or any
 language) text on your own computer. Nothing is uploaded.
EOF

# The user's downloads live in ~/.local/share/WritingParrot and are left alone on removal.
find "$PKG" -type d -exec chmod 755 {} +
dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/writing-parrot_${VERSION}_amd64.deb"
