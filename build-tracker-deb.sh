#!/bin/bash
# Build a standalone .deb package for batocera-tracker

set -e

PACKAGE_NAME="batocera-tracker"
VERSION="1.0.0"
ARCH="amd64"
BUILD_DIR="build-tracker-deb"
TRACKER_SRC="torrent-tracker"

echo "Building Debian package: ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

# Compile the Go binary
echo "Compiling tracker binary..."
(cd "$TRACKER_SRC" && GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o batocera-tracker .)
echo "Binary built: $TRACKER_SRC/batocera-tracker"

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/opt/batocera-tracker"
mkdir -p "$BUILD_DIR/etc/systemd/system"

# --- DEBIAN/control ---
cat > "$BUILD_DIR/DEBIAN/control" <<EOF
Package: batocera-tracker
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: Batocera Games Catalog <admin@example.com>
Depends: redis-server
Description: Batocera BitTorrent Tracker
 Private BitTorrent tracker (HTTP BEP 3 + UDP BEP 15) for the Batocera
 Games Catalog. Passkey validation is delegated to the main backend API.
 Peer state is stored in Redis.
EOF

# --- DEBIAN/postinst ---
cat > "$BUILD_DIR/DEBIAN/postinst" <<'POSTINST'
#!/bin/bash
set -e

INSTALL_DIR="/opt/batocera-tracker"

# Create pixn user if it doesn't exist
if ! id "pixn" &>/dev/null; then
    adduser --system --group --no-create-home --disabled-login pixn || true
fi

# Create config from example if not present
if [ -f "$INSTALL_DIR/config.yaml.example" ] && [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    cp "$INSTALL_DIR/config.yaml.example" "$INSTALL_DIR/config.yaml"
    echo "Created $INSTALL_DIR/config.yaml — please configure it before starting the service."
fi

# Fix ownership
if id "pixn" &>/dev/null; then
    chown -R pixn:pixn "$INSTALL_DIR" || true
fi
# Keep config.yaml writable by root/admin but readable by pixn
chmod 640 "$INSTALL_DIR/config.yaml" 2>/dev/null || true

systemctl daemon-reload
systemctl enable batocera-tracker.service || true

# Restart if it was already enabled (i.e. an upgrade)
if systemctl is-active --quiet batocera-tracker.service 2>/dev/null; then
    echo "Restarting batocera-tracker.service after upgrade..."
    systemctl restart batocera-tracker.service || true
fi

echo ""
echo "batocera-tracker installed."
echo "Configure: /opt/batocera-tracker/config.yaml"
echo "Start:     sudo systemctl start batocera-tracker"

exit 0
POSTINST

# --- DEBIAN/prerm ---
cat > "$BUILD_DIR/DEBIAN/prerm" <<'PRERM'
#!/bin/bash
set -e

if [ "$1" = "remove" ] || [ "$1" = "upgrade" ]; then
    if systemctl is-active --quiet batocera-tracker.service 2>/dev/null; then
        echo "Stopping batocera-tracker.service..."
        systemctl stop batocera-tracker.service || true
    fi
    if [ "$1" = "remove" ]; then
        systemctl disable batocera-tracker.service || true
    fi
fi

exit 0
PRERM

chmod +x "$BUILD_DIR/DEBIAN/postinst" "$BUILD_DIR/DEBIAN/prerm"

# --- Binary ---
cp "$TRACKER_SRC/batocera-tracker" "$BUILD_DIR/opt/batocera-tracker/batocera-tracker"
chmod +x "$BUILD_DIR/opt/batocera-tracker/batocera-tracker"

# --- Config example ---
cp "$TRACKER_SRC/config.yaml" "$BUILD_DIR/opt/batocera-tracker/config.yaml.example"

# --- Systemd service ---
cp "debian/etc/systemd/system/batocera-tracker.service" \
   "$BUILD_DIR/etc/systemd/system/batocera-tracker.service"

# --- Permissions ---
find "$BUILD_DIR" -type f ! -path "*/DEBIAN/*" -exec chmod 644 {} \;
find "$BUILD_DIR" -type d -exec chmod 755 {} \;
chmod +x "$BUILD_DIR/opt/batocera-tracker/batocera-tracker"
chmod +x "$BUILD_DIR/DEBIAN/postinst" "$BUILD_DIR/DEBIAN/prerm"

# --- Build .deb ---
echo "Building .deb package..."
dpkg-deb --root-owner-group --build "$BUILD_DIR" "${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

echo ""
echo "Package built: ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo ""
echo "Install:   sudo dpkg -i ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo "Configure: sudo nano /opt/batocera-tracker/config.yaml"
echo "Start:     sudo systemctl start batocera-tracker"
