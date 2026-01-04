#!/bin/bash

# Restart script for Batocera Games Catalog
# Stops and then starts all services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================="
echo "Restarting Batocera Games Catalog Services"
echo "========================================="
echo ""

# Stop services
echo "Stopping services..."
"$SCRIPT_DIR/stop.sh"

# Wait a moment for ports to be released
echo "Waiting for ports to be released..."
sleep 2

echo ""
# Start services
echo "Starting services..."
"$SCRIPT_DIR/start.sh"


