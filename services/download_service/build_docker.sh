#!/bin/bash

# Configuration
IMAGE_NAME="batocera-download-service"
TAG="debian13"
DOCKERFILE="Dockerfile"

# Navigate to the script directory
cd "$(dirname "$0")"

echo "Building Docker image: $IMAGE_NAME:$TAG..."

# Build the image
docker build -t "$IMAGE_NAME:$TAG" -f "$DOCKERFILE" .

if [ $? -eq 0 ]; then
    echo "Build successful!"
    echo "You can run it with: docker run -e API_TOKEN=your_token -v /userdata/roms:/userdata/roms $IMAGE_NAME:$TAG"
else
    echo "Build failed!"
    exit 1
fi
