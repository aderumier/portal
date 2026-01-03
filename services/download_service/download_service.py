import os
import time
import json
import requests
import threading
import socket
from pathlib import Path
from loguru import logger

# Load environment variables
#load_dotenv()

# Configuration
API_URL = os.getenv('API_URL', 'http://localhost:8000')
DOWNLOAD_PATH = os.getenv('DOWNLOAD_PATH', '/var/downloads')
GAMES_PATH = os.getenv('GAMES_PATH', '/var/roms')
API_TOKEN = os.getenv('API_TOKEN', 'a7a9437939b5cdf3f9a902dcaf2e36ce6cc65231fd27ffb928dca272d9cdc565')
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '10'))
BANDWIDTH_UPDATE_INTERVAL = int(os.getenv('BANDWIDTH_UPDATE_INTERVAL', '5'))
SERVICE_ID = os.getenv('SERVICE_ID', socket.gethostname())

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
            headers=headers
        )
        response.raise_for_status()
        result = response.json()
        return result.get('download')
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to request download: {e}")
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
            headers=headers
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to report progress: {e}")
        return False

def download_game(download_info):
    """Download a game file with progress reporting and resume support."""
    try:
        download_id = download_info['download_id']
        file_path = download_info['file_path']
        game_id = download_info['game_id']  # This is the rompath (e.g., "apshai.zip")
        system = download_info.get('system', '')  # System ID (e.g., "atari2600")
        allocated_bandwidth = download_info.get('allocated_bandwidth', 0)
        expected_file_size = download_info.get('file_size')
        bytes_already_transferred = download_info.get('bytes_transferred', 0)
        
        if not file_path or not os.path.exists(file_path):
            logger.error(f"Source file not found: {file_path}")
            return False
        
        # Determine destination path: DOWNLOAD_PATH/system/rompath
        if system:
            dest_path = os.path.join(DOWNLOAD_PATH, system, game_id)
            logger.info(f"Destination path: {dest_path} (system: {system}, game_id: {game_id})")
        else:
            # Fallback if system is not provided (shouldn't happen, but handle gracefully)
            logger.warning(f"System not provided in download_info, using game_id only: {game_id}")
            dest_path = os.path.join(DOWNLOAD_PATH, game_id)
        
        # Create destination directory
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        source_file_size = os.path.getsize(file_path)
        
        # Check if destination file already exists (resume scenario)
        resume_from = 0
        if os.path.exists(dest_path):
            existing_size = os.path.getsize(dest_path)
            if existing_size > 0 and existing_size < source_file_size:
                # Partial file exists, resume from this point
                resume_from = existing_size
                logger.info(f"Resuming download: {game_id} from byte {resume_from} (already have {existing_size}/{source_file_size} bytes)")
            elif existing_size == source_file_size:
                # File already complete
                logger.info(f"File already complete: {game_id} ({existing_size} bytes)")
                # Report completion and return success
                report_progress(download_id, existing_size, 0)
                return True
            else:
                # File is larger than source (corrupted?), remove it
                logger.warning(f"Destination file larger than source, removing corrupted file: {dest_path}")
                os.remove(dest_path)
                resume_from = 0
        
        # Use bytes_already_transferred from API if available and larger than local file
        if bytes_already_transferred > resume_from:
            resume_from = bytes_already_transferred
            logger.info(f"Using progress from API: resuming from byte {resume_from}")
        
        if resume_from > 0:
            logger.info(f"Resuming download: {game_id} from byte {resume_from}")
        else:
            logger.info(f"Starting new download: {game_id} ({source_file_size} bytes), allocated bandwidth: {allocated_bandwidth} bytes/s")
        
        bytes_transferred_this_session = 0
        total_bytes_transferred = resume_from
        start_time = time.time()
        last_report_time = start_time
        progress_thread_running = True
        
        def progress_reporter():
            """Background thread to report progress periodically."""
            nonlocal bytes_transferred_this_session, last_report_time, progress_thread_running, total_bytes_transferred
            while progress_thread_running:
                time.sleep(BANDWIDTH_UPDATE_INTERVAL)
                if bytes_transferred_this_session > 0:
                    elapsed = time.time() - last_report_time
                    if elapsed > 0:
                        bytes_per_second = int(bytes_transferred_this_session / elapsed)
                        total_bytes_transferred = resume_from + bytes_transferred_this_session
                        report_progress(download_id, total_bytes_transferred, bytes_per_second)
                        last_report_time = time.time()
                        bytes_transferred_this_session = 0  # Reset for next interval
        
        # Start progress reporting thread
        progress_thread = threading.Thread(target=progress_reporter, daemon=True)
        progress_thread.start()
        
        # Copy the file with progress tracking and resume support
        chunk_size = 1024 * 1024  # 1MB chunks
        try:
            with open(file_path, 'rb') as src, open(dest_path, 'ab' if resume_from > 0 else 'wb') as dst:
                # Seek to resume position in source file
                if resume_from > 0:
                    src.seek(resume_from)
                    # If appending, we're already at the end
                    # If writing new, position doesn't matter
                
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
                    bytes_transferred_this_session += len(chunk)
                    total_bytes_transferred = resume_from + bytes_transferred_this_session
                    
                    # Verify we haven't exceeded source file size
                    if total_bytes_transferred > source_file_size:
                        logger.error(f"Downloaded more bytes than source file size! {total_bytes_transferred} > {source_file_size}")
                        raise Exception("Download size mismatch")
        
        except Exception as e:
            # On error, keep the partial file for resume
            logger.error(f"Error during download, partial file kept for resume: {e}")
            progress_thread_running = False
            progress_thread.join(timeout=1)
            # Report current progress before failing
            if total_bytes_transferred > 0:
                report_progress(download_id, total_bytes_transferred, 0)
            return False
        
        progress_thread_running = False
        progress_thread.join(timeout=1)
        
        # Verify file is complete
        final_size = os.path.getsize(dest_path)
        if final_size != source_file_size:
            logger.error(f"File size mismatch after download: {final_size} != {source_file_size}")
            # Keep partial file for resume
            report_progress(download_id, final_size, 0)
            return False
        
        # Final progress report
        total_time = time.time() - start_time
        final_bytes_per_second = int(bytes_transferred_this_session / total_time) if total_time > 0 else 0
        report_progress(download_id, final_size, final_bytes_per_second)
        
        logger.info(f"Successfully downloaded: {game_id} ({final_size} bytes in {total_time:.2f}s, resumed from {resume_from} bytes)")
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
        return

    logger.info(f"Starting download service (Service ID: {SERVICE_ID})...")
    ensure_directories()

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
