import os
import time
import json
import requests
#import schedule
from pathlib import Path
#from dotenv import load_dotenv
from loguru import logger

# Load environment variables
#load_dotenv()

# Configuration
API_URL = os.getenv('API_URL', 'http://localhost')
DOWNLOAD_PATH = os.getenv('DOWNLOAD_PATH', '/var/downloads')
GAMES_PATH = os.getenv('GAMES_PATH', '/var/roms')
API_TOKEN = os.getenv('API_TOKEN', 'a7a9437939b5cdf3f9a902dcaf2e36ce6cc65231fd27ffb928dca272d9cdc565')
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '60'))

# Setup logging
logger.add(
    "download_service.log",
    rotation="500 MB",
    retention="10 days",
    level=os.getenv('LOG_LEVEL', 'INFO')
)

def ensure_directories():
    """Ensure all required directories exist."""
    Path(DOWNLOAD_PATH).mkdir(parents=True, exist_ok=True)
    logger.info(f"Download directory ensured: {DOWNLOAD_PATH}")

def get_queue():
    """Fetch the download queue from the API."""
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        import pprint
        pprint.pprint(headers)
        response = requests.get(f"{API_URL}/api/download/queue", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch queue: {e}")
        return []

def download_game(game):
    """Download a game file."""
    try:
        system_id = game['system_id']
        game_id = game['game_id']
        source_path = os.path.join(GAMES_PATH, system_id, game_id)
        dest_path = os.path.join(DOWNLOAD_PATH, system_id, game_id)

        # Create destination directory
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        # Copy the file
        with open(source_path, 'rb') as src, open(dest_path, 'wb') as dst:
            dst.write(src.read())

        logger.info(f"Successfully downloaded: {game_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to download {game_id}: {e}")
        return False

def mark_completed(game_id):
    """Mark a game as completed in the queue."""
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        response = requests.post(
            f"{API_URL}/api/download/complete",
            json={'game_id': game_id},
            headers=headers
        )
        response.raise_for_status()
        logger.info(f"Marked {game_id} as completed")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to mark game as completed: {e}")
        return False

def process_queue():
    """Process the download queue."""
    logger.info("Processing download queue...")
    queue = get_queue()
    
    if not queue:
        logger.info("Queue is empty")
        return

    for game in queue:
        if download_game(game):
            mark_completed(game['game_id'])

def main():
    """Main function to run the download service."""
    if not API_TOKEN:
        logger.error("API_TOKEN not set in environment variables")
        return

    logger.info("Starting download service...")
    ensure_directories()

    # Schedule the queue processing
#    schedule.every(POLLING_INTERVAL).seconds.do(process_queue)

    # Run immediately on startup
    process_queue()

    # Keep the script running
#    while True:
#        schedule.run_pending()
#        time.sleep(1)

if __name__ == "__main__":
    main() 
