# Building Debian Package

This guide explains how to build a Debian package for Batocera Games Catalog.

## Prerequisites

- Debian 13 (Trixie) or compatible system
- `dpkg-deb` package builder
- All source files in the project directory

## Building the Package

1. Make sure you have all the necessary files:
   ```bash
   ./build-deb.sh
   ```

2. The script will:
   - Copy backend and frontend files to build directory
   - Create proper directory structure
   - Set file permissions
   - Build the `.deb` package

3. The output will be: `batocera-games-catalog_1.0.0_all.deb`

## Installing the Package

```bash
sudo dpkg -i batocera-games-catalog_1.0.0_all.deb
sudo apt-get install -f  # Install any missing dependencies
```

## Configuration

After installation, configure the backend:

```bash
sudo nano /opt/batocera-games-catalog/backend/.env
```

Required settings:
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `GAMES_PATH`
- `DATABASE_URL`
- `SECRET_KEY`

## Starting Services

```bash
sudo systemctl start batocera-games-catalog-backend
sudo systemctl start batocera-games-catalog-frontend
```

## Enabling Services on Boot

```bash
sudo systemctl enable batocera-games-catalog-backend
sudo systemctl enable batocera-games-catalog-frontend
```

## Package Structure

- `/opt/batocera-games-catalog/` - Main installation directory
  - `backend/` - Backend Python application
  - `frontend/` - Frontend React application (built)
  - `data/` - Data directory
  - `logs/` - Log files
- `/etc/systemd/system/` - Systemd service files
- Configuration files are marked as conffiles (preserved on upgrade)

## Uninstalling

```bash
sudo systemctl stop batocera-games-catalog-backend
sudo systemctl stop batocera-games-catalog-frontend
sudo dpkg -r batocera-games-catalog
```



