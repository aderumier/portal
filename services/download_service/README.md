# Pixel Nostalgia Download Service

This service polls the Pixel Nostalgia API every minute to process game downloads from the queue.

## Setup

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Copy the environment file and configure it:
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. Install the init.d service:

**Step 1: Edit the init script if needed:**
```bash
nano batocera-games-catalog-download
# Default SERVICE_DIR is /userdata/system/rgs/download_service
# Default log file is /userdata/system/logs/rgs_download.log
# Update paths only if your installation differs
```

**Step 2: Copy the init script:**
```bash
sudo cp batocera-games-catalog-download /etc/init.d/
sudo chmod +x /etc/init.d/batocera-games-catalog-download
```

**Step 3: (Optional) Create default configuration:**
```bash
sudo cp default-config /etc/default/batocera-games-catalog-download
sudo nano /etc/default/batocera-games-catalog-download  # Edit as needed
```

**Step 4: Enable and start the service:**
```bash
# For SysV init systems (Debian/Ubuntu older versions)
sudo update-rc.d batocera-games-catalog-download defaults
sudo service batocera-games-catalog-download start

# For systems with chkconfig (RedHat/CentOS)
sudo chkconfig --add batocera-games-catalog-download
sudo chkconfig batocera-games-catalog-download on
sudo service batocera-games-catalog-download start

# Or manually enable for runlevels 2-5
sudo ln -s /etc/init.d/batocera-games-catalog-download /etc/rc2.d/S90batocera-games-catalog-download
sudo ln -s /etc/init.d/batocera-games-catalog-download /etc/rc3.d/S90batocera-games-catalog-download
sudo ln -s /etc/init.d/batocera-games-catalog-download /etc/rc4.d/S90batocera-games-catalog-download
sudo ln -s /etc/init.d/batocera-games-catalog-download /etc/rc5.d/S90batocera-games-catalog-download
sudo ln -s /etc/init.d/batocera-games-catalog-download /etc/rc0.d/K10batocera-games-catalog-download
sudo ln -s /etc/init.d/batocera-games-catalog-download /etc/rc6.d/K10batocera-games-catalog-download
```

## Configuration

The service uses environment variables for configuration. You can set them in two ways:

### Option 1: Edit the init script (default values)

Edit `/etc/init.d/batocera-games-catalog-download` and modify the environment variables at the top:

```bash
export API_URL="${API_URL:-https://rgs-retro.ddns.net}"
export ROMS_PATH="${ROMS_PATH:-/userdata/roms}"
export POLLING_INTERVAL="${POLLING_INTERVAL:-10}"
export BANDWIDTH_UPDATE_INTERVAL="${BANDWIDTH_UPDATE_INTERVAL:-5}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
```

### Option 2: Use default configuration file (recommended)

Create `/etc/default/batocera-games-catalog-download`:

```bash
sudo cp default-config /etc/default/batocera-games-catalog-download
sudo nano /etc/default/batocera-games-catalog-download
```

Edit the values as needed:
```bash
API_URL="https://rgs-retro.ddns.net"
ROMS_PATH="/userdata/roms"
POLLING_INTERVAL="10"
BANDWIDTH_UPDATE_INTERVAL="5"
LOG_LEVEL="INFO"
SERVICE_ID="batocera-download-1"
```

The init script will automatically source this file if it exists. After editing, restart the service:
```bash
sudo service batocera-games-catalog-download restart
```

### Configuration Variables

- `API_URL`: The URL of your backend API (typically `http://localhost:8000` or `https://your-server.com`). **IMPORTANT**: This should point to the backend API, NOT the frontend (port 3000).
- `ROMS_PATH`: Where downloaded games will be stored (default: `/userdata/roms`)
- `POLLING_INTERVAL`: How often to check the queue (in seconds, default: 10)
- `BANDWIDTH_UPDATE_INTERVAL`: How often to update bandwidth stats (in seconds, default: 5)
- `LOG_LEVEL`: Logging level (INFO, DEBUG, WARNING, ERROR, default: INFO)
- `SERVICE_ID`: Optional identifier for this service instance (default: hostname)

### API Token Setup

1. Generate an API token in your account settings
2. Create `API_TOKEN.txt` file in the service directory:
   ```bash
   echo "your-api-token-here" > /path/to/services/download_service/API_TOKEN.txt
   chmod 600 /path/to/services/download_service/API_TOKEN.txt
   ```
3. Make sure the token has the necessary permissions for the download service

## Usage

The service runs automatically in the background once installed and started.

### Using the init.d script

```bash
# Start the service
sudo service batocera-games-catalog-download start
# or
sudo /etc/init.d/batocera-games-catalog-download start

# Stop the service
sudo service batocera-games-catalog-download stop

# Restart the service
sudo service batocera-games-catalog-download restart

# Check status
sudo service batocera-games-catalog-download status
# or
sudo /etc/init.d/batocera-games-catalog-download status

# View logs
sudo /etc/init.d/batocera-games-catalog-download logs

# Follow logs in real-time
sudo /etc/init.d/batocera-games-catalog-download logs -f

# Reload configuration (restarts the service)
sudo service batocera-games-catalog-download reload
```

### Disable auto-start on boot

```bash
# For SysV init systems
sudo update-rc.d batocera-games-catalog-download remove

# For chkconfig systems
sudo chkconfig batocera-games-catalog-download off

# Or manually remove symlinks
sudo rm /etc/rc*.d/*batocera-games-catalog-download
```

## Development

To run the service manually for testing:
```bash
python3 download_service.py
```

## Troubleshooting

### UPnP Import Errors

If you see errors like "cannot import name 'SSDP_ST_ALL' from 'async_upnp_client.const'", this usually means there are old local library directories (async_upnp_client, defusedxml, voluptuous) in the service directory. Remove them:

```bash
cd /userdata/system/rgs/download_service
rm -rf async_upnp_client defusedxml voluptuous
```

The service now uses pip-installed packages. The virtual environment will automatically install all required dependencies when the service starts. 