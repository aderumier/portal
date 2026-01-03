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

3. Install the systemd service:
```bash
sudo cp pixel-nostalgia-download.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pixel-nostalgia-download
sudo systemctl start pixel-nostalgia-download
```

## Configuration

Edit the `.env` file with your settings:

- `API_URL`: The URL of your Pixel Nostalgia API
- `API_TOKEN`: Your API token for authentication (required)
- `DOWNLOAD_PATH`: Where downloaded games will be stored
- `GAMES_PATH`: Where the source game files are located
- `POLLING_INTERVAL`: How often to check the queue (in seconds)
- `LOG_LEVEL`: Logging level (INFO, DEBUG, etc.)

### API Token Setup

1. Generate an API token in your Pixel Nostalgia account settings
2. Copy the token to your `.env` file
3. Make sure the token has the necessary permissions for the download service

## Usage

The service runs automatically in the background. You can check its status with:

```bash
sudo systemctl status pixel-nostalgia-download
```

View logs:
```bash
journalctl -u pixel-nostalgia-download -f
```

## Development

To run the service manually for testing:
```bash
python3 download_service.py
``` 