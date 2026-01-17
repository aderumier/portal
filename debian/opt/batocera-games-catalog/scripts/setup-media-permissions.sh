#!/bin/bash
# Script to setup permissions for nginx to access media files

set -e

GAMES_PATH="$1"

if [ -z "$GAMES_PATH" ]; then
    echo "Usage: $0 <GAMES_PATH>"
    echo "Example: $0 /home/pixn/roms"
    exit 1
fi

if [ ! -d "$GAMES_PATH" ]; then
    echo "Error: Directory $GAMES_PATH does not exist"
    exit 1
fi

echo "Setting up permissions for nginx to access media files in $GAMES_PATH..."

# Get nginx user (usually www-data)
NGINX_USER="www-data"
if ! id "$NGINX_USER" &>/dev/null; then
    echo "Warning: nginx user '$NGINX_USER' not found. Trying to detect nginx user..."
    # Try to get nginx user from systemd or process
    NGINX_USER=$(ps aux | grep '[n]ginx: master' | awk '{print $1}' | head -1)
    if [ -z "$NGINX_USER" ]; then
        echo "Error: Could not determine nginx user. Please set NGINX_USER manually."
        exit 1
    fi
    echo "Detected nginx user: $NGINX_USER"
fi

# Add nginx user to pixn group (if pixn group exists)
if getent group pixn > /dev/null 2>&1; then
    echo "Adding $NGINX_USER to pixn group..."
    usermod -a -G pixn "$NGINX_USER" || echo "Warning: Failed to add $NGINX_USER to pixn group"
fi

# Set directory permissions: owner can read/write, group can read, others can read
# This allows nginx (www-data) to read if it's in the pixn group or if others have read access
echo "Setting directory permissions..."
find "$GAMES_PATH" -type d -exec chmod 755 {} \;

# Set file permissions: owner can read/write, group can read, others can read
echo "Setting file permissions..."
find "$GAMES_PATH" -type f -exec chmod 644 {} \;

# Ensure the directory itself is readable
chmod 755 "$GAMES_PATH"

# If GAMES_PATH is in /home/pixn, ensure the home directory is accessible
if [[ "$GAMES_PATH" == /home/pixn/* ]]; then
    echo "Ensuring /home/pixn is accessible..."
    chmod 755 /home/pixn 2>/dev/null || echo "Warning: Could not set permissions on /home/pixn"
fi

echo ""
echo "Permissions setup complete!"
echo ""
echo "Note: If nginx still cannot access files, you may need to:"
echo "1. Restart nginx: sudo systemctl restart nginx"
echo "2. Verify nginx user can access the directory: sudo -u $NGINX_USER test -r $GAMES_PATH"
echo "3. Check nginx error logs: sudo tail -f /var/log/nginx/error.log"













