#!/bin/bash

# Configuration
LOCAL_IMAGE="batocera-download-service"
LOCAL_TAG="debian13"
REMOTE_REPO="aderumier/rgs-download-service"
REMOTE_TAG="latest"

# Ensure build script matches
cd "$(dirname "$0")"

# Check if local image exists, if not build it
if [[ "$(docker images -q ${LOCAL_IMAGE}:${LOCAL_TAG} 2> /dev/null)" == "" ]]; then
    echo "Local image ${LOCAL_IMAGE}:${LOCAL_TAG} not found. Building..."
    if [ -f "./build_docker.sh" ]; then
        ./build_docker.sh
    else
        echo "Error: build_docker.sh not found."
        exit 1
    fi
fi

echo "Tagging image as ${REMOTE_REPO}:${REMOTE_TAG}..."
docker tag ${LOCAL_IMAGE}:${LOCAL_TAG} ${REMOTE_REPO}:${REMOTE_TAG}

echo "Pushing image to Docker Hub..."
docker push ${REMOTE_REPO}:${REMOTE_TAG}

if [ $? -eq 0 ]; then
    echo "Successfully deployed to https://hub.docker.com/r/${REMOTE_REPO}"
else
    echo "Push failed. Please ensure you are logged in with 'docker login'."
    exit 1
fi
