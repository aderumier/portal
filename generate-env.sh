#!/bin/bash

# Script to generate .env file for backend

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/backend/.env"

# Generate a secure secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)

# Check if .env already exists
if [ -f "$ENV_FILE" ]; then
    echo "Warning: .env file already exists at $ENV_FILE"
    read -p "Do you want to overwrite it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Existing .env file preserved."
        exit 0
    fi
fi

# Create .env file
cat > "$ENV_FILE" << EOF
# Discord OAuth2 Configuration
# Get these from https://discord.com/developers/applications
DISCORD_CLIENT_ID=your_discord_client_id_here
DISCORD_CLIENT_SECRET=your_discord_client_secret_here
# This must be the backend API endpoint where Discord redirects after authentication
DISCORD_REDIRECT_URI=http://localhost:8000/api/auth/callback
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_GUILD_ID=1006854943157788722

# Discord Role Mappings
# Role name required for download queue access
DISCORD_DOWNLOAD_ROLE=download
# Role name required for fast download queue access
DISCORD_FASTDOWNLOAD_ROLE=fastdownload
# Role name required for media validation access
DISCORD_ADMIN_ROLE=admin
# Optional comma-separated role names allowed to browse each catalog.
# Leave empty to allow any authenticated guild member.
RELEASE_CATALOG_VIEWERS=
WIP_CATALOG_VIEWERS=

# Bandwidth Management
# Global bandwidth limit in Mbits/s (e.g., 1000 for 1 Gbits/s, 100 for 100 Mbits/s)
GLOBAL_BANDWIDTH_LIMIT=1000
# Interval in seconds between bandwidth progress updates
BANDWIDTH_UPDATE_INTERVAL=5

# Per-user bandwidth limits for testing (optional, in Mbits/s)
# If not set, users share available bandwidth equally (no per-user limit)
# PER_USER_SLOW_QUEUE_LIMIT_Mbits=1
# PER_USER_FAST_QUEUE_LIMIT_Mbits=2

# Application Configuration
# Path to your Batocera games directory (where gamelist.xml files are located)
GAMES_PATH=/path/to/your/batocera/games

# Path to user-uploaded media (pending validation)
USERS_MEDIA_PATH=/path/to/users/media

# Frontend URL (where users are redirected after authentication)
FRONTEND_URL=http://localhost:3000

# Backend API URL (used for internal API calls)
API_URL=http://localhost:8000

# Public URL for download file endpoint (optional)
# Use this if download service needs to access files from a different domain/port
# If not set, defaults to API_URL
# DOWNLOAD_FILE_URL=

# Database Configuration
DATABASE_URL=sqlite:///./data/database.sqlite

# Secret Key (auto-generated, change if needed)
SECRET_KEY=$SECRET_KEY
EOF

echo "✓ .env file generated at: $ENV_FILE"
echo ""
echo "⚠️  IMPORTANT: Please update the following values:"
echo "   1. DISCORD_CLIENT_ID - Get from Discord Developer Portal"
echo "   2. DISCORD_CLIENT_SECRET - Get from Discord Developer Portal"
echo "   3. DISCORD_BOT_TOKEN - Get from Discord Developer Portal (Bot section)"
echo "   4. GAMES_PATH - Set to your actual Batocera games directory path"
echo ""
echo "The SECRET_KEY has been auto-generated. You can change it if needed."
echo ""
