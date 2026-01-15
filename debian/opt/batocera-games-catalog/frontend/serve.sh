#!/bin/bash
# Simple HTTP server for serving frontend static files

cd /opt/batocera-games-catalog/frontend/dist

# Use Python's built-in HTTP server
exec python3 -m http.server 3000












