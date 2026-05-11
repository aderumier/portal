#!/bin/bash
# Build a standalone Linux binary using PyInstaller inside a Docker container.
# Using Debian Bookworm (glibc 2.36) for broad compatibility with target systems.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/dist"
BINARY_NAME="rgs_download_service"
BUILD_IMAGE="rgs-pyinstaller-linux"

cd "$SCRIPT_DIR"

echo "=== Building Linux binary for rgs_download_service ==="

# Build a throw-away Docker image that runs PyInstaller
docker build -f - -t "$BUILD_IMAGE" . <<'DOCKERFILE'
FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv libpython3.11 \
        binutils \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pyinstaller
COPY . .
RUN pyinstaller --clean download_service_linux.spec
DOCKERFILE

# Extract the binary from the container without leaving it running
echo "Extracting binary..."
CONTAINER_ID=$(docker create "$BUILD_IMAGE")
mkdir -p "$OUTPUT_DIR"
docker cp "$CONTAINER_ID:/app/dist/$BINARY_NAME" "$OUTPUT_DIR/$BINARY_NAME"
docker rm "$CONTAINER_ID" > /dev/null

# Remove the build image (it's large and not needed after extraction)
docker rmi "$BUILD_IMAGE" > /dev/null

echo ""
echo "=== Build complete ==="
echo "Binary: $OUTPUT_DIR/$BINARY_NAME"
ls -lh "$OUTPUT_DIR/$BINARY_NAME"
echo ""
echo "Usage:"
echo "  API_TOKEN=your_token $OUTPUT_DIR/$BINARY_NAME"
