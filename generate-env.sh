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

# Application Configuration
# Path to your Batocera games directory (where gamelist.xml files are located)
GAMES_PATH=/path/to/your/batocera/games

# Frontend URL (where users are redirected after authentication)
FRONTEND_URL=http://localhost:3000

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

