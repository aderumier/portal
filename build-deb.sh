#!/bin/bash
# Build script for Debian package

set -e

PACKAGE_NAME="batocera-games-catalog"
VERSION="1.0.0"
ARCH="all"
BUILD_DIR="build-deb"
DEBIAN_DIR="debian"

echo "Building Debian package: ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Copy debian structure (excluding build artifacts)
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/etc/nginx/sites-available"
mkdir -p "$BUILD_DIR/etc/systemd/system"
mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/scripts"
cp -r "$DEBIAN_DIR/DEBIAN"/* "$BUILD_DIR/DEBIAN/"
cp -r "$DEBIAN_DIR/etc"/* "$BUILD_DIR/etc/" 2>/dev/null || true
cp -r "$DEBIAN_DIR/opt"/* "$BUILD_DIR/opt/" 2>/dev/null || true

# Copy backend files
echo "Copying backend files..."
mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/backend"
cp -r backend/app "$BUILD_DIR/opt/batocera-games-catalog/backend/"
cp backend/requirements.txt "$BUILD_DIR/opt/batocera-games-catalog/backend/"
cp backend/migrate_database.py "$BUILD_DIR/opt/batocera-games-catalog/backend/" 2>/dev/null || true
cp backend/clear_database.py "$BUILD_DIR/opt/batocera-games-catalog/backend/" 2>/dev/null || true
cp backend/media_mapping.json "$BUILD_DIR/opt/batocera-games-catalog/backend/" 2>/dev/null || true

# Create data and logs directories
mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/data"
mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/logs"

# Copy system configuration files (for hardware categorization)
echo "Copying system configuration files..."
if [ -d "data/systemscfg" ]; then
    mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/data/systemscfg"
    # Copy all .cfg files from systemscfg directory
    # Use find to handle cases where there are many files
    if find data/systemscfg -maxdepth 1 -name "*.cfg" -type f | head -1 | grep -q .; then
        find data/systemscfg -maxdepth 1 -name "*.cfg" -type f -exec cp -v {} "$BUILD_DIR/opt/batocera-games-catalog/data/systemscfg/" \;
        COUNT=$(find "$BUILD_DIR/opt/batocera-games-catalog/data/systemscfg" -name "*.cfg" -type f 2>/dev/null | wc -l)
        echo "  Copied $COUNT system config files"
    else
        echo "  Warning: No .cfg files found in data/systemscfg/"
    fi
else
    echo "  Warning: data/systemscfg directory not found"
fi

# Copy frontend files
echo "Copying frontend files..."
mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/frontend"
cp -r frontend/src "$BUILD_DIR/opt/batocera-games-catalog/frontend/"
cp frontend/package.json "$BUILD_DIR/opt/batocera-games-catalog/frontend/"
cp frontend/package-lock.json "$BUILD_DIR/opt/batocera-games-catalog/frontend/" 2>/dev/null || true
cp frontend/index.html "$BUILD_DIR/opt/batocera-games-catalog/frontend/"
cp frontend/vite.config.js "$BUILD_DIR/opt/batocera-games-catalog/frontend/"
cp -r frontend/public "$BUILD_DIR/opt/batocera-games-catalog/frontend/" 2>/dev/null || true
# Copy serve script
cp "$DEBIAN_DIR/opt/batocera-games-catalog/frontend/serve.sh" "$BUILD_DIR/opt/batocera-games-catalog/frontend/"

# Create .env.example files
if [ -f "env.example" ]; then
    cp env.example "$BUILD_DIR/opt/batocera-games-catalog/.env.example"
fi

# Copy README
if [ -f "debian/opt/batocera-games-catalog/README.DEBIAN" ]; then
    cp debian/opt/batocera-games-catalog/README.DEBIAN "$BUILD_DIR/opt/batocera-games-catalog/"
fi

# Copy scripts
if [ -d "debian/opt/batocera-games-catalog/scripts" ]; then
    mkdir -p "$BUILD_DIR/opt/batocera-games-catalog/scripts"
    cp debian/opt/batocera-games-catalog/scripts/*.sh "$BUILD_DIR/opt/batocera-games-catalog/scripts/" 2>/dev/null || true
    chmod +x "$BUILD_DIR/opt/batocera-games-catalog/scripts"/*.sh 2>/dev/null || true
fi

# Set proper permissions
find "$BUILD_DIR" -type f -exec chmod 644 {} \;
find "$BUILD_DIR" -type d -exec chmod 755 {} \;
chmod +x "$BUILD_DIR/DEBIAN"/*
chmod +x "$BUILD_DIR/opt/batocera-games-catalog/frontend/serve.sh" 2>/dev/null || true

# Build the package
echo "Building .deb package..."
dpkg-deb --build "$BUILD_DIR" "${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

echo ""
echo "Package built successfully: ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo ""
echo "To install:"
echo "  sudo dpkg -i ${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo "  sudo apt-get install -f  # Install missing dependencies"
echo ""
echo "To configure:"
echo "  sudo nano /opt/batocera-games-catalog/backend/.env"
echo ""
echo "To start services:"
echo "  sudo systemctl start batocera-games-catalog-backend"
echo "  sudo systemctl start batocera-games-catalog-frontend"

