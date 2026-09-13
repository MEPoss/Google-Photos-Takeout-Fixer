#!/bin/bash
# Builda e testa il pacchetto .deb dentro un container debian:bookworm.
# Va eseguito come root, con il repo montato in /workspace.
set -euxo pipefail

VERSION="${1:-0.0.0}"
REPO_DIR="/workspace"
INSTALL_PREFIX="/opt/google-photos-takeout-fixer"
PKGROOT="/build/pkgroot"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-soup-3.0 \
    perl dpkg-dev fakeroot xvfb curl ca-certificates

# --- 1. Installa l'app nel percorso finale reale (/opt/...), così il venv
#        creato qui incorpora già gli shebang corretti per dopo l'installazione. ---
rm -rf "$INSTALL_PREFIX"
mkdir -p "$INSTALL_PREFIX"
cp "$REPO_DIR"/app.py "$REPO_DIR"/core.py "$REPO_DIR"/launcher.py "$INSTALL_PREFIX"/
cp -r "$REPO_DIR"/templates "$INSTALL_PREFIX"/templates
cp -r "$REPO_DIR"/vendor "$INSTALL_PREFIX"/vendor
chmod +x "$INSTALL_PREFIX"/vendor/exiftool/exiftool

python3 -m venv --system-site-packages "$INSTALL_PREFIX"/venv
"$INSTALL_PREFIX"/venv/bin/pip install --upgrade pip
"$INSTALL_PREFIX"/venv/bin/pip install flask pywebview timezonefinder tzdata

# --- 2. Assembla l'albero del pacchetto Debian ricopiando l'installazione. ---
rm -rf /build
mkdir -p "$PKGROOT/DEBIAN" \
         "$PKGROOT/usr/bin" \
         "$PKGROOT/usr/share/applications" \
         "$PKGROOT/usr/share/icons/hicolor/512x512/apps" \
         "$PKGROOT$INSTALL_PREFIX"

cp -r "$INSTALL_PREFIX"/. "$PKGROOT$INSTALL_PREFIX"/

install -m 755 "$REPO_DIR/packaging/debian/launcher-wrapper.sh" "$PKGROOT/usr/bin/google-photos-takeout-fixer"
install -m 644 "$REPO_DIR/packaging/debian/google-photos-takeout-fixer.desktop" \
    "$PKGROOT/usr/share/applications/google-photos-takeout-fixer.desktop"
install -m 644 "$REPO_DIR/docs/icon.png" \
    "$PKGROOT/usr/share/icons/hicolor/512x512/apps/google-photos-takeout-fixer.png"

sed "s/__VERSION__/${VERSION}/" "$REPO_DIR/packaging/debian/control.template" > "$PKGROOT/DEBIAN/control"

DEB_FILE="$REPO_DIR/google-photos-takeout-fixer_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$PKGROOT" "$DEB_FILE"

# --- 3. Installa il .deb appena creato come farebbe un utente reale. ---
apt-get install -y --no-install-recommends "$DEB_FILE"

# --- 4. Smoke test: avvia l'app sotto un display virtuale e verifica che
#        risponda davvero, invece di limitarsi a controllare che dpkg non
#        abbia sollevato errori. ---
Xvfb :99 -screen 0 1280x1024x24 &
XVFB_PID=$!
export DISPLAY=:99
sleep 2

google-photos-takeout-fixer &
APP_PID=$!

READY=0
for i in $(seq 1 20); do
    if curl -sf http://127.0.0.1:5050/ > /dev/null; then
        READY=1
        break
    fi
    sleep 1
done

if [ "$READY" != "1" ]; then
    echo "L'app non ha risposto su http://127.0.0.1:5050 entro il timeout." >&2
    exit 1
fi

STATUS=$(curl -s http://127.0.0.1:5050/api/exiftool-status)
echo "exiftool status: $STATUS"
echo "$STATUS" | grep -q '"installed": *true' || {
    echo "exiftool bundlato non rilevato dal pacchetto installato." >&2
    exit 1
}

kill "$APP_PID" 2>/dev/null || true
kill "$XVFB_PID" 2>/dev/null || true

echo "OK: pacchetto creato e testato con successo -> $DEB_FILE"
