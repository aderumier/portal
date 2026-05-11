# Batocera Games Catalog

A web portal catalog for Batocera gamelist.xml files, displaying game catalogs with Discord authentication and download queue management.

## Architecture

- **Backend**: Python FastAPI (Port 8000)
- **Frontend**: React with Vite (Port 3000)
- **Database**: SQLite

## Features

- Discord OAuth2 authentication
- Guild membership verification
- Creator role checking
- Game catalog browsing by system
- Search functionality across all systems
- Download queue management
- API token system for download service integration

## Setup

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the `backend` directory:
```bash
cp .env.example .env
```

5. Edit `.env` with your configuration:
```
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=http://localhost:8000/api/auth/callback
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=1006854943157788722
RELEASE_CATALOG_VIEWERS=release_viewer,admin
WIP_CATALOG_VIEWERS=wip_viewer,admin
GAMES_PATH=/path/to/your/games
DATABASE_URL=sqlite:///./data/database.sqlite
SECRET_KEY=your-secret-key-here
```

6. Run the backend:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Create a `.env` file:
```bash
cp .env.example .env
```

4. Edit `.env`:
```
VITE_API_URL=http://localhost:8000
```

5. Run the frontend:
```bash
npm run dev
```

### Quick Start Scripts

For convenience, you can use the provided shell scripts to manage all services:

**Start all services:**
```bash
./start.sh
```

**Stop all services:**
```bash
./stop.sh
```

**Restart all services:**
```bash
./restart.sh
```

**Check service status:**
```bash
./status.sh
```

These scripts will:
- Automatically create virtual environments if needed
- Install dependencies on first run
- Start both backend and frontend servers
- Track process IDs for easy stopping
- Store logs in the `logs/` directory

## Discord OAuth2 Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to the OAuth2 section
4. Add your redirect URI: `http://localhost:8000/api/auth/callback`
5. Copy the Client ID and Client Secret to your `.env` file
6. Go to the Bot section and create a bot
7. Copy the bot token to your `.env` file
8. Enable "SERVER MEMBERS INTENT" under Privileged Gateway Intents
9. Add the bot to your Discord server with appropriate permissions

## Usage

1. Start the backend server
2. Start the frontend development server
3. Visit `http://localhost:3000` in your browser
4. Login with Discord
5. Browse games by system or search for specific games
6. Add games to your download queue (requires Creator role)
7. Generate API tokens in the Account page for the download service

## Download Service Integration

The existing Python download service can be used with the new API. Configure it with:
- `API_URL`: `http://localhost:8000`
- `API_TOKEN`: Generated from the Account page

## Project Structure

```
/
├── backend/          # FastAPI backend
│   ├── app/
│   │   ├── api/     # API routes and middleware
│   │   ├── services/ # Business logic
│   │   └── models/  # Database models
│   └── requirements.txt
├── frontend/        # React frontend
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   └── package.json
└── data/            # SQLite database
```

## License

MIT License
