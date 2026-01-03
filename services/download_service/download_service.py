import os
import time
import json
import requests
import threading
import socket
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# Load environment variables from .env file in the same directory as this script
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"Loaded environment variables from {env_path}")
else:
    logger.warning(f"No .env file found at {env_path}. Using system environment variables or defaults.")

# Configuration
API_URL = os.getenv('API_URL', 'http://localhost:8000')
DOWNLOAD_PATH = os.getenv('DOWNLOAD_PATH', '/var/downloads')
GAMES_PATH = os.getenv('GAMES_PATH', '/var/roms')
API_TOKEN = os.getenv('API_TOKEN', 'a7a9437939b5cdf3f9a902dcaf2e36ce6cc65231fd27ffb928dca272d9cdc565')
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '10'))
BANDWIDTH_UPDATE_INTERVAL = int(os.getenv('BANDWIDTH_UPDATE_INTERVAL', '5'))
SERVICE_ID = os.getenv('SERVICE_ID', socket.gethostname())

# Log configuration on startup
logger.info(f"Download service configuration:")
logger.info(f"  API_URL: {API_URL}")
logger.info(f"  DOWNLOAD_PATH: {DOWNLOAD_PATH}")
logger.info(f"  GAMES_PATH: {GAMES_PATH}")
logger.info(f"  SERVICE_ID: {SERVICE_ID}")
logger.info(f"  POLLING_INTERVAL: {POLLING_INTERVAL}s")
logger.info(f"  BANDWIDTH_UPDATE_INTERVAL: {BANDWIDTH_UPDATE_INTERVAL}s")

# Validate API_URL is not pointing to frontend
if ':3000' in API_URL:
    logger.error(f"WARNING: API_URL is set to {API_URL} which appears to be the frontend URL!")
    logger.error(f"API_URL should point to the backend API (typically http://localhost:8000)")
    logger.error(f"Please check your .env file and update API_URL to the correct backend URL")

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

def test_api_connection():
    """Test connection to the API and verify it's accessible."""
    try:
        logger.info(f"Testing API connection to {API_URL}...")
        response = requests.get(
            f"{API_URL}/health",
            timeout=5
        )
        response.raise_for_status()
        logger.info(f"✓ Successfully connected to API at {API_URL}")
        return True
    except requests.exceptions.ConnectionError as e:
        logger.error(f"✗ Failed to connect to API at {API_URL}")
        logger.error(f"  Connection error: {e}")
        logger.error(f"  Please verify:")
        logger.error(f"    1. The backend API is running")
        logger.error(f"    2. API_URL in .env is correct (should be backend URL, typically http://localhost:8000)")
        logger.error(f"    3. The backend is accessible from this machine")
        return False
    except requests.exceptions.Timeout:
        logger.error(f"✗ Connection to API at {API_URL} timed out")
        logger.error(f"  Please verify the backend is running and accessible")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"API health check returned error: {e}")
        logger.warning(f"  This might be OK if the /health endpoint doesn't exist")
        # Try a simple request to see if API is reachable
        try:
            response = requests.get(f"{API_URL}/", timeout=5)
            logger.info(f"✓ API is reachable at {API_URL} (health endpoint may not exist)")
            return True
        except:
            logger.error(f"✗ API at {API_URL} is not reachable")
            return False

def request_download(queue_type=None):
    """Request next available download from the API."""
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        data = {
            'service_id': SERVICE_ID
        }
        if queue_type:
            data['queue_type'] = queue_type
        
        response = requests.post(
            f"{API_URL}/api/download/request",
            json=data,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return result.get('download')
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to API at {API_URL}")
        logger.error(f"  Error: {e}")
        logger.error(f"  Please verify the backend is running and API_URL is correct")
        return None
    except requests.exceptions.Timeout:
        logger.error(f"Request to API at {API_URL} timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to request download: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"  Response status: {e.response.status_code}")
            logger.error(f"  Response body: {e.response.text[:200]}")
        return None

def report_progress(download_id, bytes_transferred, bytes_per_second):
    """Report download progress to the API."""
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        data = {
            'download_id': download_id,
            'bytes_transferred': bytes_transferred,
            'bytes_per_second': bytes_per_second
        }
        response = requests.post(
            f"{API_URL}/api/download/progress",
            json=data,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        # If it's a 404, the download might already be completed/deleted - this is OK
        if e.response and e.response.status_code == 404:
            logger.debug(f"Progress report returned 404 (download may already be completed): {e}")
            return True  # Return True to avoid error spam
        logger.error(f"Failed to report progress: {e}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to report progress: {e}")
        return False

def get_total_size(path):
    """Calculate total size of a file or directory recursively."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    elif os.path.isdir(path):
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.isfile(filepath):
                    total += os.path.getsize(filepath)
        return total
    return 0

def get_all_files(path):
    """Get all files in a directory recursively, or return single file path."""
    if os.path.isfile(path):
        return [(path, path)]
    elif os.path.isdir(path):
        files = []
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.isfile(filepath):
                    # Store relative path from source root
                    rel_path = os.path.relpath(filepath, path)
                    files.append((filepath, rel_path))
        return files
    return []

def copy_file_with_progress(src_path, dst_path, bytes_transferred_this_session_ref, chunk_size=1024*1024):
    """Copy a single file with progress tracking."""
    bytes_copied = 0
    resume_from = 0
    
    # Check if destination file exists and is smaller than source (resume scenario)
    if os.path.exists(dst_path):
        existing_size = os.path.getsize(dst_path)
        source_size = os.path.getsize(src_path)
        if existing_size > 0 and existing_size < source_size:
            resume_from = existing_size
            logger.debug(f"Resuming file {dst_path} from byte {resume_from}")
        elif existing_size == source_size:
            logger.debug(f"File already complete: {dst_path}")
            return source_size  # Already complete
    
    # Ensure destination directory exists
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    
    try:
        with open(src_path, 'rb') as src, open(dst_path, 'ab' if resume_from > 0 else 'wb') as dst:
            if resume_from > 0:
                src.seek(resume_from)
            
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
                bytes_copied += len(chunk)
                bytes_transferred_this_session_ref[0] += len(chunk)
    except Exception as e:
        logger.error(f"Error copying file {src_path} to {dst_path}: {e}")
        raise
    
    return bytes_copied + resume_from

def download_game(download_info):
    """Download a game file or directory with progress reporting and resume support."""
    try:
        download_id = download_info['download_id']
        file_path = download_info['file_path']
        game_id = download_info['game_id']  # This is the rompath (e.g., "apshai.zip" or "board/chess/")
        system = download_info.get('system', '')  # System ID (e.g., "atari2600")
        allocated_bandwidth = download_info.get('allocated_bandwidth', 0)
        expected_file_size = download_info.get('file_size')
        bytes_already_transferred = download_info.get('bytes_transferred', 0)
        
        # Construct HTTP URL for the file (files are served at /media/{system}/{game_id})
        http_url = None
        if system and game_id:
            # Remove leading ./ from game_id if present
            clean_game_id = game_id.lstrip('./')
            # URL encode the game_id for HTTP
            import urllib.parse
            encoded_game_id = urllib.parse.quote(clean_game_id, safe='/')
            http_url = f"{API_URL}/media/{system}/{encoded_game_id}"
        
        logger.info(f"Downloading file from: {file_path}")
        if http_url:
            logger.info(f"  HTTP URL: {http_url}")
        logger.info(f"  Download ID: {download_id}")
        logger.info(f"  Game ID: {game_id}")
        logger.info(f"  System: {system}")
        
        if not file_path or not os.path.exists(file_path):
            logger.error(f"Source path not found: {file_path}")
            return False
        
        # Determine destination path: DOWNLOAD_PATH/system/rompath
        if system:
            dest_base = os.path.join(DOWNLOAD_PATH, system, game_id)
            logger.info(f"Destination path: {dest_base}")
        else:
            logger.warning(f"System not provided in download_info, using game_id only: {game_id}")
            dest_base = os.path.join(DOWNLOAD_PATH, game_id)
            logger.info(f"Destination path: {dest_base}")
        
        # Check if source is a file or directory
        is_directory = os.path.isdir(file_path)
        is_file = os.path.isfile(file_path)
        
        if not is_file and not is_directory:
            logger.error(f"Source path is neither a file nor a directory: {file_path}")
            return False
        
        # Calculate total size
        if is_file:
            source_total_size = os.path.getsize(file_path)
            all_files = [(file_path, os.path.basename(file_path))]
        else:
            source_total_size = get_total_size(file_path)
            all_files = get_all_files(file_path)
            logger.info(f"Source is a directory with {len(all_files)} files, total size: {source_total_size} bytes")
        
        if source_total_size == 0:
            logger.warning(f"Source path has zero size: {file_path}")
            return False
        
        # Calculate already transferred bytes (for resume)
        bytes_already_copied = 0
        if is_file:
            # Single file: check if destination exists
            if os.path.exists(dest_base):
                existing_size = os.path.getsize(dest_base)
                if existing_size <= source_total_size:
                    bytes_already_copied = existing_size
        else:
            # Directory: check all files
            for src_file, rel_path in all_files:
                dst_file = os.path.join(dest_base, rel_path)
                if os.path.exists(dst_file):
                    existing_size = os.path.getsize(dst_file)
                    src_size = os.path.getsize(src_file)
                    if existing_size <= src_size:
                        bytes_already_copied += existing_size
                    else:
                        bytes_already_copied += src_size  # File is complete or larger
        
        # Use bytes_already_transferred from API if available and larger
        if bytes_already_transferred > bytes_already_copied:
            bytes_already_copied = bytes_already_transferred
            logger.info(f"Using progress from API: {bytes_already_copied} bytes already transferred")
        
        if bytes_already_copied > 0:
            logger.info(f"Resuming download: {game_id} from {bytes_already_copied}/{source_total_size} bytes")
        else:
            logger.info(f"Starting new download: {game_id} ({source_total_size} bytes), allocated bandwidth: {allocated_bandwidth} bytes/s")
        
        bytes_transferred_this_session = [0]  # Use list to allow modification in nested function
        total_bytes_transferred = bytes_already_copied
        start_time = time.time()
        last_report_time = start_time
        progress_thread_running = True
        
        def progress_reporter():
            """Background thread to report progress periodically."""
            nonlocal last_report_time, progress_thread_running, total_bytes_transferred
            while progress_thread_running:
                time.sleep(BANDWIDTH_UPDATE_INTERVAL)
                if bytes_transferred_this_session[0] > 0:
                    elapsed = time.time() - last_report_time
                    if elapsed > 0:
                        bytes_per_second = int(bytes_transferred_this_session[0] / elapsed)
                        total_bytes_transferred = bytes_already_copied + bytes_transferred_this_session[0]
                        report_progress(download_id, total_bytes_transferred, bytes_per_second)
                        last_report_time = time.time()
                        bytes_transferred_this_session[0] = 0  # Reset for next interval
        
        # Start progress reporting thread
        progress_thread = threading.Thread(target=progress_reporter, daemon=True)
        progress_thread.start()
        
        # Copy files
        chunk_size = 1024 * 1024  # 1MB chunks
        try:
            for src_file, rel_path in all_files:
                if is_directory:
                    dst_file = os.path.join(dest_base, rel_path)
                else:
                    dst_file = dest_base
                
                logger.debug(f"Copying {src_file} to {dst_file}")
                copy_file_with_progress(src_file, dst_file, bytes_transferred_this_session, chunk_size)
        
        except Exception as e:
            logger.error(f"Error during download, partial files kept for resume: {e}")
            progress_thread_running = False
            progress_thread.join(timeout=1)
            # Report current progress before failing
            if total_bytes_transferred > 0:
                report_progress(download_id, total_bytes_transferred, 0)
            return False
        
        progress_thread_running = False
        progress_thread.join(timeout=1)
        
        # Verify total size
        if is_file:
            final_size = os.path.getsize(dest_base)
        else:
            final_size = get_total_size(dest_base)
        
        if final_size != source_total_size:
            logger.error(f"Total size mismatch after download: {final_size} != {source_total_size}")
            # Keep partial files for resume
            report_progress(download_id, final_size, 0)
            return False
        
        # Final progress report (before marking as completed)
        total_time = time.time() - start_time
        final_bytes_per_second = int(bytes_transferred_this_session[0] / total_time) if total_time > 0 else 0
        # Report final progress - if it fails (download already deleted), that's OK
        try:
            report_progress(download_id, final_size, final_bytes_per_second)
        except Exception as e:
            logger.debug(f"Final progress report failed (download may already be completed): {e}")
        
        logger.info(f"Successfully downloaded: {game_id}")
        logger.info(f"  Source path: {file_path}")
        if http_url:
            logger.info(f"  HTTP URL: {http_url}")
        logger.info(f"  Destination: {dest_base}")
        logger.info(f"  Size: {final_size} bytes ({final_size / (1024*1024):.2f} MB)")
        logger.info(f"  Time: {total_time:.2f}s")
        logger.info(f"  Resumed from: {bytes_already_copied} bytes")
        return True
    except Exception as e:
        logger.error(f"Failed to download {game_id}: {e}", exc_info=True)
        return False

def mark_completed(download_id):
    """Mark a download as completed in the queue."""
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        response = requests.post(
            f"{API_URL}/api/download/complete",
            json={'download_id': download_id},
            headers=headers
        )
        response.raise_for_status()
        logger.info(f"Marked download {download_id} as completed")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to mark download as completed: {e}")
        return False

def process_queue():
    """Process downloads from the queue."""
    logger.info("Requesting next download...")
    
    # Try fast queue first, then slow queue
    download_info = request_download(queue_type='fast')
    if not download_info:
        download_info = request_download(queue_type='slow')
    
    if not download_info:
        logger.debug("No downloads available")
        return
    
    logger.info(f"Got download: {download_info.get('game_name', 'Unknown')} (ID: {download_info['download_id']})")
    
    if download_game(download_info):
        mark_completed(download_info['download_id'])
    else:
        logger.error(f"Failed to download {download_info.get('game_id', 'Unknown')}")

def main():
    """Main function to run the download service."""
    if not API_TOKEN:
        logger.error("API_TOKEN not set in environment variables")
        logger.error("Please set API_TOKEN in your .env file")
        return

    logger.info(f"Starting download service (Service ID: {SERVICE_ID})...")
    ensure_directories()
    
    # Test API connection before starting
    if not test_api_connection():
        logger.error("Cannot start download service: API connection failed")
        logger.error("Please fix the API_URL in your .env file and ensure the backend is running")
        return

    # Main loop: poll for downloads
    while True:
        try:
            process_queue()
            time.sleep(POLLING_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutting down download service...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(POLLING_INTERVAL)

if __name__ == "__main__":
    main() 
