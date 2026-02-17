#!/bin/bash

# Configuration
IMAGE_NAME="aderumier/rgs-download-service"
TAG="latest"
CONTAINER_NAME="batocera-download-service"

# Check if API_TOKEN is set
if [ -z "$API_TOKEN" ]; then
    echo "Error: API_TOKEN environment variable is not set."
    echo "Usage: API_TOKEN=your_token ./run_docker_hub.sh"
    exit 1
fi

echo "Pulling latest image..."
docker pull "$IMAGE_NAME:$TAG"

echo "stopping existing container..."
docker stop $CONTAINER_NAME 2>/dev/null
docker rm $CONTAINER_NAME 2>/dev/null

echo "Running Docker container from Hub..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p 8765:8765 \
    -e API_TOKEN="$API_TOKEN" \
    -e API_URL="${API_URL:-https://rgs-retro.ddns.net}" \
    -e SERVICE_ID="${SERVICE_ID:-docker-client-1}" \
    -e P2P_PORT=8765 \
    -v /userdata/roms:/userdata/roms \
    -v /home/aderumier/cursorscraper/saves:/userdata/saves \
    -v "$(pwd)/config.ini:/app/config.ini" \
    "$IMAGE_NAME:$TAG"

if [ $? -eq 0 ]; then
    echo "Container started successfully!"
    echo "Logs:"
    docker logs -f "$CONTAINER_NAME"
else
    echo "Failed to start container."
    exit 1
fi
