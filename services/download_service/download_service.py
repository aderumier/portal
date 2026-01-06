import os
import sys
import time
import json
import requests
import threading
import socket
import xml.etree.ElementTree as ET
import subprocess
import logging
import platform
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Setup logging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

# Determine paths based on platform
if platform.system() == 'Windows':
    # Windows paths
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        SERVICE_DIR = Path(sys.executable).parent
    else:
        # Running as script
        SERVICE_DIR = Path(__file__).parent
    
    # Use AppData for logs (user-specific)
    appdata = os.getenv('APPDATA', os.path.expanduser('~'))
    log_dir = os.path.join(appdata, 'RGS', 'logs')
    log_file_path = os.path.abspath(os.getenv('LOG_FILE', os.path.join(log_dir, 'rgs_download.log')))
else:
    # Linux/Batocera paths
    SERVICE_DIR = Path(__file__).parent
    log_file_path = os.path.abspath(os.getenv('LOG_FILE', '/userdata/system/logs/rgs_download.log'))

# Ensure log directory exists
log_dir = os.path.dirname(log_file_path)
os.makedirs(log_dir, exist_ok=True)

# Configure root logger with file handler only (no console output)
logger = logging.getLogger()
logger.setLevel(getattr(logging, log_level, logging.INFO))

# Remove any existing handlers to avoid duplicates
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Add rotating file handler
file_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=500 * 1024 * 1024,  # 500 MB
    backupCount=10
)
file_handler.setLevel(getattr(logging, log_level, logging.INFO))
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(file_handler)

# Get logger for this module
logger = logging.getLogger(__name__)
logger.info(f"Logging initialized. Log file: {log_file_path}")

# Environment variables are read from system environment (os.getenv)
# No .env file loading - use system environment variables or set them before running

# Configuration
API_URL = os.getenv('API_URL', 'https://rgs-retro.ddns.net')

# Set ROMS_PATH based on platform
if platform.system() == 'Windows':
    DEFAULT_ROMS_PATH = os.path.join(os.getenv('PROGRAMDATA', 'C:\\ProgramData'), 'RGS', 'roms')
else:
    DEFAULT_ROMS_PATH = '/userdata/roms'

ROMS_PATH = os.getenv('ROMS_PATH', DEFAULT_ROMS_PATH)

# POLLING_INTERVAL will be fetched from backend on first request_download call
# No fallback - must be set by backend
POLLING_INTERVAL = None
BANDWIDTH_UPDATE_INTERVAL = int(os.getenv('BANDWIDTH_UPDATE_INTERVAL', '5'))
SERVICE_ID = os.getenv('SERVICE_ID', socket.gethostname())

# Read API_TOKEN from API_TOKEN.txt file in the service root directory
# Use SERVICE_DIR which is set based on platform above
api_token_path = SERVICE_DIR / 'API_TOKEN.txt'
API_TOKEN = None
if api_token_path.exists():
    try:
        with open(api_token_path, 'r', encoding='utf-8') as f:
            API_TOKEN = f.read().strip()
        if not API_TOKEN:
            logger.error(f"API_TOKEN.txt file is empty at {api_token_path}")
        else:
            logger.info(f"API_TOKEN loaded from {api_token_path} (length: {len(API_TOKEN)} characters)")
    except Exception as e:
        logger.error(f"Failed to read API_TOKEN from {api_token_path}: {e}")
else:
    logger.warning(f"API_TOKEN.txt file not found at {api_token_path}")
    logger.warning("API token must be provided in API_TOKEN.txt file")

if not API_TOKEN:
    raise ValueError("API_TOKEN is required. Please create API_TOKEN.txt file in the download service directory with your API token.")

# Log configuration on startup
logger.info(f"Download service configuration:")
logger.info(f"  API_URL: {API_URL}")
logger.info(f"  ROMS_PATH: {ROMS_PATH}")
logger.info(f"  SERVICE_ID: {SERVICE_ID}")
logger.info(f"  POLLING_INTERVAL: Will be set from backend on first connection")
logger.info(f"  BANDWIDTH_UPDATE_INTERVAL: {BANDWIDTH_UPDATE_INTERVAL}s")

# Validate API_URL is not pointing to frontend
if ':3000' in API_URL:
    logger.error(f"WARNING: API_URL is set to {API_URL} which appears to be the frontend URL!")
    logger.error(f"API_URL should point to the backend API (typically http://localhost:8000)")
    logger.error(f"Please check your .env file and update API_URL to the correct backend URL")

# Create a global HTTP session with keep-alive enabled
# This reuses TCP connections, improving performance for frequent API calls
http_session = requests.Session()
# Configure connection pool settings
adapter = requests.adapters.HTTPAdapter(
    pool_connections=10,  # Number of connection pools to cache
    pool_maxsize=20,      # Maximum number of connections to save in the pool
    max_retries=3,        # Number of retries for failed requests
    pool_block=False      # Don't block if pool is full
)
http_session.mount('http://', adapter)
http_session.mount('https://', adapter)
# Set default headers for all requests
http_session.headers.update({
    'Authorization': f'Bearer {API_TOKEN}',
    'Connection': 'keep-alive'  # Explicitly enable keep-alive
})
logger.info("HTTP session with keep-alive enabled")

def ensure_directories():
    """Ensure all required directories exist."""
    Path(ROMS_PATH).mkdir(parents=True, exist_ok=True)
    logger.info(f"ROMs directory ensured: {ROMS_PATH}")

def update_polling_interval(new_interval):
    """Update the global POLLING_INTERVAL value.
    
    Args:
        new_interval: New polling interval in seconds (int)
    """
    global POLLING_INTERVAL
    if isinstance(new_interval, int) and new_interval > 0:
        if POLLING_INTERVAL is None:
            logger.info(f"Setting POLLING_INTERVAL to {new_interval} seconds (from backend)")
            POLLING_INTERVAL = new_interval
        elif POLLING_INTERVAL != new_interval:
            logger.info(f"Updating POLLING_INTERVAL from {POLLING_INTERVAL} to {new_interval} seconds")
            POLLING_INTERVAL = new_interval
    else:
        logger.warning(f"Invalid polling interval received: {new_interval}, keeping current value: {POLLING_INTERVAL}")

def request_download(queue_type=None):
    """Request next available download from the API.
    
    Also updates POLLING_INTERVAL from the backend response.
    
    Returns:
        dict: Download info dict, or None if no download available
    
    Raises:
        SystemExit: If API token is invalid (401 Unauthorized)
    """
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        data = {
            'service_id': SERVICE_ID
        }
        if queue_type:
            data['queue_type'] = queue_type
        
        response = http_session.post(
            f"{API_URL}/api/download/request",
            json=data,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        # Always update polling interval from backend response (required, no fallback)
        polling_interval = result.get('polling_interval')
        if polling_interval is not None:
            update_polling_interval(int(polling_interval))
        else:
            logger.error("Backend did not return polling_interval in response!")
        
        return result.get('download')
    except requests.exceptions.HTTPError as e:
        # Check for 401 Unauthorized - invalid API token
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 401:
                logger.critical("=" * 80)
                logger.critical("FATAL ERROR: API token is invalid or expired (401 Unauthorized)")
                logger.critical("=" * 80)
                logger.critical(f"Response: {e.response.text[:200]}")
                logger.critical("The download service will now stop.")
                logger.critical("Please verify your API_TOKEN.txt file contains a valid token.")
                logger.critical("=" * 80)
                sys.exit(1)
        # For other HTTP errors, log and return None
        logger.error(f"Failed to request download: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"  Response status: {e.response.status_code}")
            # Don't log response body for server errors (5xx) to avoid noise
            if e.response.status_code < 500:
                logger.error(f"  Response body: {e.response.text[:200]}")
        return None
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
            # Don't log response body for server errors (5xx) to avoid noise
            if e.response.status_code < 500:
                logger.error(f"  Response body: {e.response.text[:200]}")
        return None

def check_download_status(download_id):
    """Check if a download is paused or still active."""
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        # Use the progress endpoint to check status (it will return 404 if paused/completed)
        # Actually, we need a better way - let's check the queue endpoint
        # For now, we'll use a simple approach: if progress update fails with 403, it might be paused
        # But actually, the best way is to check the queue status
        # Since we don't have a direct status endpoint, we'll infer from progress updates
        return None  # Will be implemented via progress reporting
    except Exception as e:
        logger.debug(f"Error checking download status: {e}")
        return None

def report_progress(download_id, bytes_transferred, bytes_per_second):
    """Report download progress to the API. 
    Returns:
        True: Progress reported successfully
        False: Download is paused
        None: Download was removed from queue (should stop downloading)
    
    Raises:
        SystemExit: If API token is invalid (401 Unauthorized)
    """
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        data = {
            'download_id': download_id,
            'bytes_transferred': bytes_transferred,
            'bytes_per_second': bytes_per_second
        }
        response = http_session.post(
            f"{API_URL}/api/download/progress",
            json=data,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        # Check for 401 Unauthorized - invalid API token
        if e.response and e.response.status_code == 401:
            logger.critical("=" * 80)
            logger.critical("FATAL ERROR: API token is invalid or expired (401 Unauthorized)")
            logger.critical("=" * 80)
            logger.critical(f"Response: {e.response.text[:200]}")
            logger.critical("The download service will now stop.")
            logger.critical("Please verify your API_TOKEN.txt file contains a valid token.")
            logger.critical("=" * 80)
            sys.exit(1)
        # If it's a 410 Gone, the download was removed from queue (likely completed) - this is expected
        if e.response and e.response.status_code == 410:
            logger.debug(f"Progress report returned 410 Gone - download {download_id} was removed from queue (likely completed)")
            return None  # Return None to indicate download was removed
        # If it's a 404, the download might already be completed/deleted - this is OK
        if e.response and e.response.status_code == 404:
            logger.debug(f"Progress report returned 404 (download may already be completed): {e}")
            return True  # Return True to avoid error spam
        # If it's a 403, the download is paused
        if e.response and e.response.status_code == 403:
            logger.info(f"Progress report returned 403 - download {download_id} is paused")
            return False  # Return False to indicate pause
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

def download_file_via_http(http_url, dest_path, resume_from=0, expected_size=None, bytes_transferred_ref=None, chunk_size=1024*1024, paused_ref=None, existing_response=None):
    """Download a file via HTTP with resume support. Throttling is handled server-side.
    
    Args:
        paused_ref: Optional list to check if download should be paused. If [False] becomes [True], download stops.
        existing_response: Optional existing response object to reuse (avoids duplicate request for single file downloads)
    
    Note: For streaming downloads, we use a separate requests.get() call instead of the session
    to avoid connection pool issues with long-lived streaming connections.
    """
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
    }
    
    # Add Range header for resume (only if we need to make a new request)
    if resume_from > 0 and existing_response is None:
        headers['Range'] = f'bytes={resume_from}-'
    
    try:
        # Reuse existing response if provided (avoids duplicate request for single file downloads)
        if existing_response is not None:
            response = existing_response
            # If we need to resume, we can't reuse the existing response
            if resume_from > 0:
                logger.warning(f"Cannot reuse existing response for resume, making new request")
                existing_response.close()
                headers['Range'] = f'bytes={resume_from}-'
                response = requests.get(http_url, headers=headers, stream=True, timeout=300)
        else:
            # Use a longer timeout for large files with throttling
            # Timeout is per read operation, not total download time
            # For streaming downloads, use requests.get() directly instead of session
            # to avoid connection pool issues with long-lived connections
            response = requests.get(http_url, headers=headers, stream=True, timeout=300)
        response.raise_for_status()
        
        # Check if response is JSON (directory listing) - this shouldn't happen but handle it gracefully
        # This can happen if the initial directory check failed or if Range request returns JSON
        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/json' in content_type or 'text/json' in content_type:
            logger.error(f"Received JSON response when expecting file - this is likely a directory. URL: {http_url}")
            # Try to read a small chunk to confirm it's JSON
            try:
                peek = next(response.iter_content(chunk_size=1024))
                response.close()
                # Try to parse as JSON
                import json
                parsed_json = json.loads(peek.decode('utf-8'))
                if isinstance(parsed_json, dict) and parsed_json.get('is_directory'):
                    logger.error(f"Confirmed JSON directory response - directory download should have been detected earlier!")
                    logger.error(f"Directory has {len(parsed_json.get('files', []))} files")
                    logger.error(f"This indicates the initial directory check failed. Aborting file download.")
                return False
            except (UnicodeDecodeError, json.JSONDecodeError, StopIteration) as e:
                # Not JSON, continue
                logger.debug(f"Not JSON after all: {e}")
                pass
        
        # Check if server supports range requests
        if resume_from > 0 and response.status_code != 206:
            logger.warning(f"Server doesn't support range requests, starting from beginning")
            resume_from = 0
        
        # Get file size from Content-Length or Content-Range header
        content_length = None
        if 'Content-Length' in response.headers:
            content_length = int(response.headers['Content-Length'])
        elif 'Content-Range' in response.headers:
            # Parse Content-Range: bytes 0-1023/2048
            content_range = response.headers['Content-Range']
            if '/' in content_range:
                content_length = int(content_range.split('/')[-1])
        
        # Open destination file
        mode = 'ab' if resume_from > 0 else 'wb'
        total_bytes_downloaded = resume_from
        bytes_downloaded_this_session = 0  # Track bytes downloaded in this session only
        chunk_count = 0
        download_start_time = time.time()
        last_log_time = download_start_time
        last_pause_check = download_start_time
        
        with open(dest_path, mode) as f:
            try:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    # Check if download is paused (every 2 seconds)
                    if paused_ref and time.time() - last_pause_check >= 2.0:
                        if paused_ref[0]:
                            logger.info(f"Download paused - stopping at {total_bytes_downloaded} bytes")
                            response.close()  # Close the connection
                            return False  # Return False to indicate pause
                        last_pause_check = time.time()
                    
                    if chunk:
                        f.write(chunk)
                        bytes_written = len(chunk)
                        total_bytes_downloaded += bytes_written
                        bytes_downloaded_this_session += bytes_written
                        chunk_count += 1
                        
                        if bytes_transferred_ref:
                            bytes_transferred_ref[0] += bytes_written
                        
                        # Log progress every 5 seconds or every 10MB
                        current_time = time.time()
                        if current_time - last_log_time >= 5.0 or (chunk_count % 100 == 0):
                            elapsed_total = current_time - download_start_time
                            # Calculate rate based on bytes downloaded in THIS session only
                            current_rate = bytes_downloaded_this_session / elapsed_total if elapsed_total > 0 else 0
                            logger.info(f"Downloaded {total_bytes_downloaded} bytes ({total_bytes_downloaded / (1024*1024):.2f} MB), {chunk_count} chunks this session, rate: {current_rate / 125000:.2f} Mbits/s")
                            last_log_time = current_time
                    elif chunk is None:
                        # Empty chunk might indicate end of stream, but continue
                        continue
            except Exception as e:
                logger.error(f"Error during download iteration: {e}", exc_info=True)
                raise
        
        logger.info(f"Download completed: {chunk_count} chunks, {total_bytes_downloaded} bytes")
        
        # Explicitly close the response to free the connection
        response.close()
        
        # Verify file size
        final_size = os.path.getsize(dest_path)
        if expected_size and final_size != expected_size:
            logger.error(f"File size mismatch: {final_size} != {expected_size}")
            return False
        
        return True
    except requests.exceptions.HTTPError as e:
        # Handle 404 errors - file doesn't exist, remove from queue
        if e.response and e.response.status_code == 404:
            logger.error(f"File not found (404) for URL: {http_url}")
            logger.error(f"This indicates the file doesn't exist on the server. The download should be removed from queue.")
            # Return a special value to indicate file not found
            return None  # None indicates file not found (different from False which indicates pause/failure)
        logger.error(f"HTTP download error: {e}", exc_info=True)
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP download error: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error during HTTP download: {e}", exc_info=True)
        return False

def download_directory_recursive(download_id, system, game_id, base_url, dest_base_path, files_list, bytes_already_transferred, paused_ref):
    """Download all files in a directory recursively."""
    import urllib.parse
    
    total_bytes_downloaded = bytes_already_transferred
    bytes_transferred_this_session = [0]
    start_time = time.time()
    last_report_time = start_time
    progress_thread_running = True
    
    def progress_reporter():
        """Background thread to report progress periodically and check for pause."""
        nonlocal last_report_time, progress_thread_running, total_bytes_downloaded
        while progress_thread_running:
            time.sleep(BANDWIDTH_UPDATE_INTERVAL)
            elapsed = time.time() - last_report_time
            if elapsed > 0:
                # Accumulate bytes from this session into total
                total_bytes_downloaded += bytes_transferred_this_session[0]
                
                if bytes_transferred_this_session[0] > 0:
                    bytes_per_second = int(bytes_transferred_this_session[0] / elapsed)
                else:
                    bytes_per_second = 0
                
                # Report progress - check return value
                progress_result = report_progress(download_id, total_bytes_downloaded, bytes_per_second)
                if progress_result is None:
                    # Download was removed from queue - stop downloading
                    logger.info(f"Download {download_id} was removed from queue, stopping download")
                    paused_ref[0] = True
                    progress_thread_running = False
                    break
                elif progress_result is False:
                    # Download is paused
                    logger.info(f"Download {download_id} is paused - checking status...")
                    paused_ref[0] = True
                    progress_thread_running = False
                    break
                
                last_report_time = time.time()
                bytes_transferred_this_session[0] = 0
    
    progress_thread = threading.Thread(target=progress_reporter, daemon=True)
    progress_thread.start()
    
    try:
        # Download each file in the directory
        for file_info in files_list:
            if paused_ref[0]:
                logger.info(f"Download {download_id} was paused")
                progress_thread_running = False
                progress_thread.join(timeout=1)
                return False
            
            relative_path = file_info['relative_path']
            file_size = file_info['size']
            
            # Construct URL for this file
            encoded_game_id = urllib.parse.quote(game_id.lstrip('./'), safe='/')
            encoded_system = urllib.parse.quote(system, safe='')
            encoded_rel_path = urllib.parse.quote(relative_path, safe='/')
            file_url = f"{base_url}/api/download/file?system={encoded_system}&game_id={encoded_game_id}&relative_path={encoded_rel_path}"
            
            # Destination path preserving directory structure
            dest_file_path = os.path.join(dest_base_path, relative_path)
            dest_file_dir = os.path.dirname(dest_file_path)
            os.makedirs(dest_file_dir, exist_ok=True)
            
            # Check if file already exists (for resume)
            resume_from = 0
            if os.path.exists(dest_file_path):
                existing_size = os.path.getsize(dest_file_path)
                if existing_size < file_size:
                    resume_from = existing_size
                    logger.info(f"Resuming file {relative_path} from byte {resume_from}")
                elif existing_size == file_size:
                    logger.info(f"File already complete: {relative_path}")
                    total_bytes_downloaded += file_size
                    continue
            
            logger.info(f"Downloading file: {relative_path} ({file_size} bytes)")
            
            # Download this file
            success = download_file_via_http(
                file_url,
                dest_file_path,
                resume_from=resume_from,
                expected_size=file_size,
                bytes_transferred_ref=bytes_transferred_this_session,
                chunk_size=1024 * 1024,
                paused_ref=paused_ref
            )
            
            # Check if file not found (404)
            if success is None:
                logger.error(f"File not found (404) for {relative_path} in download {download_id}")
                logger.info("Backend will handle removal of this download from queue")
                progress_thread_running = False
                progress_thread.join(timeout=1)
                return False
            
            if not success:
                if paused_ref[0]:
                    logger.info(f"Download {download_id} was paused")
                    progress_thread_running = False
                    progress_thread.join(timeout=1)
                    return False
                logger.error(f"Failed to download file: {relative_path}")
                return False
            
            # Verify file size
            final_size = os.path.getsize(dest_file_path)
            if final_size != file_size:
                logger.error(f"File size mismatch for {relative_path}: {final_size} != {file_size}")
                return False
        
        progress_thread_running = False
        progress_thread.join(timeout=1)
        
        # Final progress report
        total_time = time.time() - start_time
        final_bytes_per_second = int(bytes_transferred_this_session[0] / total_time) if total_time > 0 else 0
        try:
            report_progress(download_id, total_bytes_downloaded, final_bytes_per_second)
        except Exception as e:
            logger.debug(f"Final progress report failed: {e}")
        
        logger.info(f"Successfully downloaded directory: {game_id}")
        logger.info(f"  Total files: {len(files_list)}")
        logger.info(f"  Total size: {total_bytes_downloaded} bytes ({total_bytes_downloaded / (1024*1024):.2f} MB)")
        logger.info(f"  Time: {total_time:.2f}s")
        return True
        
    except Exception as e:
        logger.error(f"Error downloading directory: {e}", exc_info=True)
        progress_thread_running = False
        progress_thread.join(timeout=1)
        return False

def get_game_details_from_api(download_id):
    """Fetch game details from the download endpoint (requires game to be in queue with associated token).
    
    Args:
        download_id: Download ID from the download request
    
    Returns:
        dict: Game details including all media paths, or None if failed
    """
    try:
        url = f"{API_URL}/api/download/game-details/{download_id}"
        logger.info(f"Fetching game details from download endpoint: {url}")
        
        response = http_session.get(url, timeout=30)
        response.raise_for_status()
        
        game_data = response.json()
        logger.info(f"Successfully fetched game details for download {download_id}")
        return game_data
    except requests.exceptions.HTTPError as e:
        # Check for 401 Unauthorized - invalid API token
        if e.response and e.response.status_code == 401:
            logger.critical("=" * 80)
            logger.critical("FATAL ERROR: API token is invalid or expired (401 Unauthorized)")
            logger.critical("=" * 80)
            logger.critical(f"Response: {e.response.text[:200]}")
            logger.critical("The download service will now stop.")
            logger.critical("Please verify your API_TOKEN.txt file contains a valid token.")
            logger.critical("=" * 80)
            sys.exit(1)
        if e.response and e.response.status_code == 404:
            logger.warning(f"Game details not found for download {download_id}")
        else:
            logger.error(f"HTTP error fetching game details: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch game details from API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching game details: {e}", exc_info=True)
        return None

def ensure_directory_exists(path):
    """Create directory structure if it doesn't exist.
    
    Args:
        path: Directory path to create
    """
    try:
        os.makedirs(path, exist_ok=True)
        logger.debug(f"Ensured directory exists: {path}")
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        raise

def normalize_media_path(path):
    """Normalize media paths from gamelist.xml (remove `./`, handle relative paths).
    
    Args:
        path: Media path from gamelist.xml (e.g., "./media/thumbnails/game.png" or "media/thumbnails/game.png")
    
    Returns:
        str: Normalized path without leading `./`
    """
    if not path:
        return ''
    # Remove leading ./
    normalized = path.lstrip('./')
    return normalized

def format_path_for_xml(path):
    """Format path for gamelist.xml <path> field.
    
    Rules:
    - Always add './' prefix: "game.zip" -> "./game.zip"
    - Also for subdirectories: "subdir/game.zip" -> "./subdir/game.zip"
    
    Args:
        path: Game path (e.g., "game.zip" or "subdir/game.zip")
    
    Returns:
        str: Formatted path for XML with './' prefix
    """
    if not path:
        return ''
    # Remove leading ./ if present
    normalized = path.lstrip('./')
    # Always add ./ prefix (always relative path)
    return f'./{normalized}'

def format_media_path_for_xml(path):
    """Format media path for gamelist.xml media fields (boxart, thumbnail, etc.).
    
    Rules:
    - Always add './' prefix if not already present: "media/thumbnails/2010.jpg" -> "./media/thumbnails/2010.jpg"
    - If already has './', keep as is: "./media/thumbnails/2010.jpg" -> "./media/thumbnails/2010.jpg"
    
    Args:
        path: Media path (e.g., "media/thumbnails/2010.jpg")
    
    Returns:
        str: Formatted path for XML with './' prefix
    """
    if not path:
        return ''
    # Remove leading ./ if present
    normalized = path.lstrip('./')
    # Always add ./ prefix for media paths
    return f'./{normalized}'

def download_game_media(system, game_id, download_id, batocera_system):
    """Download all media files for a game.
    
    Args:
        system: System ID (e.g., "atari2600") - used for API calls and parsing paths
        game_id: Game ID (rompath, e.g., "apshai.zip")
        download_id: Download ID for logging
        batocera_system: Batocera system directory name - used for local destination paths (required)
    
    Returns:
        tuple: (downloaded_media_list, game_data_dict) or ([], None) if failed
    """
    if not batocera_system:
        logger.error(f"batocera_system is required for download_game_media")
        return [], None
    
    target_system = batocera_system
    downloaded_media = []
    
    try:
        # Fetch game details from download endpoint (requires game to be in queue)
        game_data = get_game_details_from_api(download_id)
        if not game_data:
            logger.warning(f"Could not fetch game details for {game_id}, skipping media download")
            return downloaded_media, None
        
        # List of media types to download
        media_types = [
            'thumbnail', 'image', 'boxart', 'boxback', 'marquee', 
            'fanart', 'cartridge', 'titleshot', 'video', 'screenshot', 
            'wheel', 'mix'
        ]
        
        # Download each media type
        for media_type in media_types:
            media_path = game_data.get(media_type, '')
            if not media_path:
                continue  # Skip missing media
            
            # Normalize the media path
            normalized_path = normalize_media_path(media_path)
            if not normalized_path:
                continue
            
            # Construct HTTP URL for media file
            # Media files are served at /media endpoint
            # The path from API is like "system/media/thumbnails/game.png"
            # We need to construct: {API_URL}/media/system/media/thumbnails/game.png
            # Use the original media_path for the URL (it already has the system prefix)
            media_url = f"{API_URL}/media/{media_path}"
            
            # Remove system prefix from normalized_path for local storage
            # We need just the relative path from the system directory for local storage
            if normalized_path.startswith(f"{system}/"):
                normalized_path = normalized_path[len(system) + 1:]
            
            # Destination path: ROMS_PATH/batocera_system/{normalized_path}
            dest_path = os.path.join(ROMS_PATH, target_system, normalized_path)
            
            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            try:
                ensure_directory_exists(dest_dir)
            except Exception as e:
                logger.warning(f"Failed to create directory for {media_type}: {e}")
                continue
            
            # Skip if file already exists
            if os.path.exists(dest_path):
                logger.debug(f"Media file already exists: {dest_path}")
                downloaded_media.append(normalized_path)
                continue
            
            # Download media file
            logger.info(f"Downloading {media_type} from {media_url} to {dest_path}")
            try:
                success = download_file_via_http(
                    media_url,
                    dest_path,
                    resume_from=0,
                    expected_size=None,
                    bytes_transferred_ref=None,
                    chunk_size=1024 * 1024,  # 1MB chunks
                    paused_ref=None,
                    existing_response=None
                )
                
                if success:
                    logger.info(f"Successfully downloaded {media_type}: {normalized_path}")
                    downloaded_media.append(normalized_path)
                else:
                    logger.warning(f"Failed to download {media_type} from {media_url}")
            except Exception as e:
                logger.warning(f"Error downloading {media_type}: {e}")
                continue
        
        logger.info(f"Downloaded {len(downloaded_media)} media files for {game_id}")
        return downloaded_media, game_data
        
    except Exception as e:
        logger.error(f"Error in download_game_media: {e}", exc_info=True)
        return downloaded_media, None

def update_gamelist_xml(batocera_system, game_id, game_data, media_paths):
    """Update or create gamelist.xml with the downloaded game entry.
    
    Args:
        batocera_system: Batocera system directory name (e.g., "atari2600")
        game_id: Game ID (rompath, e.g., "apshai.zip")
        game_data: Full game data from API (dict)
        media_paths: Dict mapping media types to downloaded paths (relative to system directory)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        gamelist_path = os.path.join(ROMS_PATH, batocera_system, 'gamelist.xml')
        
        # Parse existing XML or create new
        if os.path.exists(gamelist_path):
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
            except ET.ParseError as e:
                logger.warning(f"Failed to parse existing gamelist.xml: {e}, creating new one")
                root = ET.Element('gameList')
                tree = ET.ElementTree(root)
        else:
            # Create new XML structure
            root = ET.Element('gameList')
            tree = ET.ElementTree(root)
            logger.info(f"Creating new gamelist.xml at {gamelist_path}")
        
        # Find existing game entry by path
        game_element = None
        for game in root.findall('.//game'):
            path_text = game.findtext('path', '')
            # Normalize paths for comparison
            normalized_path = normalize_media_path(path_text)
            normalized_game_id = normalize_media_path(game_id)
            if normalized_path == normalized_game_id or path_text == game_id or path_text == f'./{normalized_game_id}':
                game_element = game
                logger.info(f"Found existing game entry in gamelist.xml: {game_id}")
                break
        
        # Create new game element if not found
        if game_element is None:
            game_element = ET.SubElement(root, 'game')
            logger.info(f"Creating new game entry in gamelist.xml: {game_id}")
        
        # Update game path (format correctly: add ./ for root files, keep subdirectory paths as is)
        formatted_path = format_path_for_xml(game_id)
        path_elem = game_element.find('path')
        if path_elem is None:
            path_elem = ET.SubElement(game_element, 'path')
        path_elem.text = formatted_path
        
        # Update name
        name_elem = game_element.find('name')
        if name_elem is None:
            name_elem = ET.SubElement(game_element, 'name')
        name_elem.text = game_data.get('name', '')
        
        # Update description
        desc_elem = game_element.find('desc')
        if desc_elem is None:
            desc_elem = ET.SubElement(game_element, 'desc')
        desc_elem.text = game_data.get('description', '')
        
        # Update metadata fields
        metadata_fields = {
            'developer': 'developer',
            'publisher': 'publisher',
            'genre': 'genre',
            'releaseDate': 'releasedate',
            'players': 'players',
            'rating': 'rating',
            'region': 'region',
            'lang': 'lang'
        }
        
        for api_field, xml_field in metadata_fields.items():
            value = game_data.get(api_field, '')
            if value:
                elem = game_element.find(xml_field)
                if elem is None:
                    elem = ET.SubElement(game_element, xml_field)
                elem.text = value
        
        # Update media paths
        # Use the paths from game_data, but normalize them
        media_fields = {
            'thumbnail': 'thumbnail',
            'image': 'image',
            'boxart': 'boxart',
            'boxback': 'boxback',
            'marquee': 'marquee',
            'fanart': 'fanart',
            'cartridge': 'cartridge',
            'titleshot': 'titleshot',
            'video': 'video',
            'screenshot': 'screenshot',
            'wheel': 'wheel',
            'mix': 'mix'
        }
        
        # Get system ID from game_data for parsing media paths
        system = game_data.get('system', '')
        
        for api_field, xml_field in media_fields.items():
            # Get path from game_data
            media_path = game_data.get(api_field, '')
            if media_path:
                # Normalize the path (remove system prefix and leading ./)
                normalized = normalize_media_path(media_path)
                if system and normalized.startswith(f"{system}/"):
                    normalized = normalized[len(system) + 1:]
                
                # Format path for XML (add ./ prefix for media paths)
                formatted_media_path = format_media_path_for_xml(normalized)
                
                # Use formatted path in XML (relative to system directory)
                elem = game_element.find(xml_field)
                if elem is None:
                    elem = ET.SubElement(game_element, xml_field)
                elem.text = formatted_media_path
        
        # Ensure directory exists
        ensure_directory_exists(os.path.dirname(gamelist_path))
        
        # Write XML back to file with proper formatting
        # Use UTF-8 encoding
        try:
            # ET.indent is available in Python 3.9+
            ET.indent(tree, space='  ')  # Pretty print with 2-space indent
        except AttributeError:
            # Python < 3.9 doesn't have ET.indent, skip pretty printing
            logger.debug("ET.indent not available (Python < 3.9), writing XML without indentation")
        tree.write(gamelist_path, encoding='utf-8', xml_declaration=True)
        
        logger.info(f"Successfully updated gamelist.xml at {gamelist_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating gamelist.xml: {e}", exc_info=True)
        return False

def download_game(download_info):
    """Download a game file or directory via HTTP with progress reporting and resume support."""
    try:
        download_id = download_info['download_id']
        game_id = download_info['game_id']  # This is the rompath (e.g., "apshai.zip" or "board/chess/")
        system = download_info.get('system', '')  # System ID (e.g., "atari2600") - used for API calls
        batocera_system = download_info.get('batocera_system', '')  # Batocera system directory name - used for local paths
        expected_file_size = download_info.get('file_size')
        bytes_already_transferred = download_info.get('bytes_transferred', 0)
        http_url = download_info.get('file_url')  # HTTP URL provided by backend
        
        # Validate required fields
        if not http_url:
            logger.error(f"Missing file_url in download_info")
            return False
        
        if not system or not game_id:
            logger.error(f"Missing system or game_id: system={system}, game_id={game_id}")
            return False
        
        if not batocera_system:
            logger.error(f"Missing batocera_system in download_info for system: {system}")
            return False
        
        target_system = batocera_system
        
        logger.info(f"Downloading via HTTP")
        logger.info(f"  HTTP URL: {http_url}")
        logger.info(f"  Download ID: {download_id}")
        logger.info(f"  Game ID: {game_id}")
        logger.info(f"  System: {system}")
        logger.info(f"  Batocera System: {target_system}")
        
        # Determine destination base path: ROMS_PATH/batocera_system/rompath
        if target_system:
            dest_base_path = os.path.join(ROMS_PATH, target_system, game_id)
            logger.info(f"Destination base path: {dest_base_path}")
        else:
            logger.warning(f"Target system not provided in download_info, using game_id only: {game_id}")
            dest_base_path = os.path.join(ROMS_PATH, game_id)
            logger.info(f"Destination base path: {dest_base_path}")
        
        # First, check if it's a directory by checking Content-Type header
        # Use stream=True from the start to avoid downloading the entire file just to check headers
        # For files, we can reuse this streamed response directly
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
        }
        
        # Add Range header for resume if needed (will be handled in download_file_via_http if it's a file)
        file_response = None
        is_directory = False
        
        try:
            # Make a GET request with stream=True to check Content-Type header
            # This allows us to check headers without downloading the entire body
            response = http_session.get(http_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '').lower()
            logger.debug(f"Initial request Content-Type: {content_type}, Status: {response.status_code}")
            
            # Check Content-Type to determine if it's a directory (JSON) or file (octet-stream)
            if 'application/json' in content_type:
                # It's a directory listing - read the JSON response
                is_directory = True
                try:
                    # Read the response content (should be small JSON)
                    dir_info = response.json()
                    response.close()  # Close the connection
                    
                    logger.debug(f"Successfully parsed as JSON. Keys: {list(dir_info.keys()) if isinstance(dir_info, dict) else 'Not a dict'}")
                    if isinstance(dir_info, dict) and dir_info.get('is_directory'):
                        # It's a directory listing
                        files_list = dir_info.get('files', [])
                        logger.info(f"✓ Directory download detected: {len(files_list)} files, {dir_info.get('total_size', 0)} bytes")
                        
                        # Calculate already downloaded bytes by checking existing files
                        bytes_already_downloaded = 0
                        for file_info in files_list:
                            rel_path = file_info['relative_path']
                            dest_file_path = os.path.join(dest_base_path, rel_path)
                            if os.path.exists(dest_file_path):
                                existing_size = os.path.getsize(dest_file_path)
                                if existing_size == file_info['size']:
                                    bytes_already_downloaded += existing_size
                                elif existing_size < file_info['size']:
                                    bytes_already_downloaded += existing_size
                        
                        # Use the larger of bytes_already_transferred or bytes_already_downloaded
                        if bytes_already_downloaded > bytes_already_transferred:
                            bytes_already_transferred = bytes_already_downloaded
                        
                        # Extract base URL from http_url
                        from urllib.parse import urlparse
                        parsed = urlparse(http_url)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        
                        paused = [False]
                        success = download_directory_recursive(
                            download_id, system, game_id, base_url, dest_base_path,
                            files_list, bytes_already_transferred, paused
                        )
                        if success:
                            # Download media files and update gamelist.xml after successful game download
                            media_and_gamelist_success = False
                            try:
                                logger.info(f"Download completed successfully, downloading media files for {game_id}")
                                downloaded_media, game_data = download_game_media(system, game_id, download_id, batocera_system=target_system)
                                
                                # Use game_data returned from download_game_media (avoids duplicate API call)
                                if game_data:
                                    # Update gamelist.xml with game entry
                                    gamelist_success = update_gamelist_xml(target_system, game_id, game_data, downloaded_media)
                                    if gamelist_success:
                                        media_and_gamelist_success = True
                                        logger.info(f"Media download and gamelist.xml update completed successfully for {game_id}")
                                    else:
                                        logger.warning(f"Gamelist.xml update failed for {game_id}")
                                else:
                                    logger.warning(f"Could not fetch game details for gamelist.xml update: download {download_id}")
                            except Exception as e:
                                logger.error(f"Error downloading media or updating gamelist.xml (download still successful): {e}", exc_info=True)
                            
                            # Restart emulationstation if media and gamelist.xml were successfully updated
                            if media_and_gamelist_success:
                                try:
                                    logger.info("Restarting emulationstation after successful download with media and gamelist.xml")
                                    result = subprocess.run(
                                        ['killall', '-9', 'emulationstation'],
                                        capture_output=True,
                                        text=True,
                                        timeout=5
                                    )
                                    if result.returncode == 0:
                                        logger.info("Successfully restarted emulationstation")
                                    else:
                                        # killall returns non-zero if process not found, which is OK
                                        logger.debug(f"killall emulationstation returned {result.returncode}: {result.stderr}")
                                except subprocess.TimeoutExpired:
                                    logger.warning("Timeout while trying to restart emulationstation")
                                except Exception as e:
                                    logger.error(f"Error restarting emulationstation: {e}", exc_info=True)
                        return success
                except (ValueError, requests.exceptions.JSONDecodeError) as json_err:
                    # Failed to parse as JSON, treat as file
                    logger.debug(f"Failed to parse as JSON despite Content-Type: {content_type}, Error: {json_err}")
                    response.close()
                    is_directory = False
            else:
                # It's a file (application/octet-stream or other) - keep the response for reuse
                logger.debug(f"Content-Type indicates file (not directory): {content_type}")
                file_response = response  # Save for reuse in download_file_via_http
        except requests.exceptions.RequestException as e:
            logger.error(f"Error checking if directory: {e}")
            # Continue with single file download
        
        # Single file download (existing logic)
        dest_path = dest_base_path
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        # Check if file already exists (for resume)
        resume_from = 0
        if os.path.exists(dest_path) and os.path.isfile(dest_path):
            existing_size = os.path.getsize(dest_path)
            if expected_file_size and existing_size < expected_file_size:
                resume_from = existing_size
                logger.info(f"Resuming download from byte {resume_from} (existing file: {existing_size} bytes)")
            elif expected_file_size and existing_size == expected_file_size:
                logger.info(f"File already complete: {dest_path} ({existing_size} bytes)")
                report_progress(download_id, existing_size, 0)
                # Close file_response if we have one
                if file_response:
                    file_response.close()
                
                # Download media files and update gamelist.xml even if file already exists
                # (media might not be downloaded yet)
                media_and_gamelist_success = False
                try:
                    logger.info(f"File already complete, downloading media files for {game_id}")
                    downloaded_media, game_data = download_game_media(system, game_id, download_id, batocera_system=target_system)
                    
                    # Use game_data returned from download_game_media (avoids duplicate API call)
                    if game_data:
                        # Update gamelist.xml with game entry
                        gamelist_success = update_gamelist_xml(target_system, game_id, game_data, downloaded_media)
                        if gamelist_success:
                            media_and_gamelist_success = True
                            logger.info(f"Media download and gamelist.xml update completed successfully for {game_id}")
                        else:
                            logger.warning(f"Gamelist.xml update failed for {game_id}")
                    else:
                        logger.warning(f"Could not fetch game details for gamelist.xml update: download {download_id}")
                except Exception as e:
                    logger.error(f"Error downloading media or updating gamelist.xml (download still successful): {e}", exc_info=True)
                
                # Restart emulationstation if media and gamelist.xml were successfully updated
                if media_and_gamelist_success:
                    try:
                        logger.info("Restarting emulationstation after successful download with media and gamelist.xml")
                        result = subprocess.run(
                            ['killall', '-9', 'emulationstation'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0:
                            logger.info("Successfully restarted emulationstation")
                        else:
                            # killall returns non-zero if process not found, which is OK
                            logger.debug(f"killall emulationstation returned {result.returncode}: {result.stderr}")
                    except subprocess.TimeoutExpired:
                        logger.warning("Timeout while trying to restart emulationstation")
                    except Exception as e:
                        logger.error(f"Error restarting emulationstation: {e}", exc_info=True)
                
                return True
        
        # Use bytes_already_transferred from API if available and larger
        if bytes_already_transferred > resume_from:
            resume_from = bytes_already_transferred
            logger.info(f"Using progress from API: resuming from byte {resume_from}")
        
        # If we need to resume, we can't reuse the existing response (need Range header)
        if resume_from > 0 and file_response:
            file_response.close()
            file_response = None
        
        if resume_from > 0:
            logger.info(f"Resuming download: {game_id} from {resume_from} bytes")
        else:
            logger.info(f"Starting new download: {game_id} ({expected_file_size or 'unknown'} bytes), throttling handled server-side")
        
        bytes_transferred_this_session = [0]
        total_bytes_transferred = resume_from
        start_time = time.time()
        last_report_time = start_time
        progress_thread_running = True
        
        paused = [False]
        
        def progress_reporter():
            """Background thread to report progress periodically and check for pause."""
            nonlocal last_report_time, progress_thread_running, total_bytes_transferred
            while progress_thread_running:
                time.sleep(BANDWIDTH_UPDATE_INTERVAL)
                elapsed = time.time() - last_report_time
                if elapsed > 0:
                    # Accumulate bytes from this session into total
                    total_bytes_transferred += bytes_transferred_this_session[0]
                    
                    if bytes_transferred_this_session[0] > 0:
                        bytes_per_second = int(bytes_transferred_this_session[0] / elapsed)
                    else:
                        bytes_per_second = 0
                    
                    # Report progress - check return value
                    progress_result = report_progress(download_id, total_bytes_transferred, bytes_per_second)
                    if progress_result is None:
                        # Download was removed from queue (likely completed) - stop reporting
                        logger.debug(f"Download {download_id} was removed from queue (likely completed), stopping progress reporter")
                        paused[0] = True
                        progress_thread_running = False
                        break
                    elif progress_result is False:
                        # Download is paused
                        logger.info(f"Download {download_id} is paused - checking status...")
                        paused[0] = True
                        progress_thread_running = False
                        break
                    
                    last_report_time = time.time()
                    bytes_transferred_this_session[0] = 0
        
        progress_thread = threading.Thread(target=progress_reporter, daemon=True)
        progress_thread.start()
        
        # Download file via HTTP
        chunk_size = 1024 * 1024  # 1MB chunks
        try:
            success = download_file_via_http(
                http_url, 
                dest_path, 
                resume_from=resume_from,
                expected_size=expected_file_size,
                bytes_transferred_ref=bytes_transferred_this_session,
                chunk_size=chunk_size,
                paused_ref=paused,
                existing_response=file_response  # Reuse the response we already have
            )
            
            # Check if file not found (404)
            if success is None:
                logger.error(f"File not found (404) for download {download_id}")
                logger.info("Backend will handle removal of this download from queue")
                progress_thread_running = False
                progress_thread.join(timeout=1)
                return False
            
            if not success:
                progress_thread_running = False
                progress_thread.join(timeout=1)
                if paused[0]:
                    logger.info(f"Download {download_id} was paused at {total_bytes_transferred} bytes")
                    if total_bytes_transferred > 0:
                        report_progress(download_id, total_bytes_transferred, 0)
                    return False
                if total_bytes_transferred > 0:
                    report_progress(download_id, total_bytes_transferred, 0)
                return False
        
        except Exception as e:
            logger.error(f"Error during HTTP download, partial file kept for resume: {e}")
            progress_thread_running = False
            progress_thread.join(timeout=1)
            if total_bytes_transferred > 0:
                report_progress(download_id, total_bytes_transferred, 0)
            return False
        
        # Stop progress reporter thread before marking as completed
        progress_thread_running = False
        # Wait a bit longer to ensure the thread has time to exit its sleep and check the flag
        progress_thread.join(timeout=BANDWIDTH_UPDATE_INTERVAL + 1)
        
        # Verify file size
        if os.path.exists(dest_path) and os.path.isfile(dest_path):
            final_size = os.path.getsize(dest_path)
            if expected_file_size and final_size != expected_file_size:
                logger.error(f"File size mismatch after download: {final_size} != {expected_file_size}")
                # Don't report progress if we're about to mark as completed
                try:
                    report_progress(download_id, final_size, 0)
                except Exception:
                    pass  # Ignore errors if download is already removed
                return False
            
            # Skip final progress report - mark_completed will handle completion
            # This avoids 410 errors when the download is removed from queue
            total_time = time.time() - start_time
            logger.debug(f"Download completed, skipping final progress report (will be handled by mark_completed)")
            
            logger.info(f"Successfully downloaded: {game_id}")
            logger.info(f"  HTTP URL: {http_url}")
            logger.info(f"  Destination: {dest_path}")
            logger.info(f"  Size: {final_size} bytes ({final_size / (1024*1024):.2f} MB)")
            logger.info(f"  Time: {total_time:.2f}s")
            logger.info(f"  Resumed from: {resume_from} bytes")
            
            # Download media files and update gamelist.xml after successful game download
            media_and_gamelist_success = False
            try:
                logger.info(f"Download completed successfully, downloading media files for {game_id}")
                downloaded_media, game_data = download_game_media(system, game_id, download_id, batocera_system=target_system)
                
                # Use game_data returned from download_game_media (avoids duplicate API call)
                if game_data:
                    # Update gamelist.xml with game entry
                    gamelist_success = update_gamelist_xml(target_system, game_id, game_data, downloaded_media)
                    if gamelist_success:
                        media_and_gamelist_success = True
                        logger.info(f"Media download and gamelist.xml update completed successfully for {game_id}")
                    else:
                        logger.warning(f"Gamelist.xml update failed for {game_id}")
                else:
                    logger.warning(f"Could not fetch game details for gamelist.xml update: download {download_id}")
            except Exception as e:
                logger.error(f"Error downloading media or updating gamelist.xml (download still successful): {e}", exc_info=True)
            
            # Restart emulationstation if media and gamelist.xml were successfully updated
            if media_and_gamelist_success:
                try:
                    logger.info("Restarting emulationstation after successful download with media and gamelist.xml")
                    result = subprocess.run(
                        ['killall', '-9', 'emulationstation'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        logger.info("Successfully restarted emulationstation")
                    else:
                        # killall returns non-zero if process not found, which is OK
                        logger.debug(f"killall emulationstation returned {result.returncode}: {result.stderr}")
                except subprocess.TimeoutExpired:
                    logger.warning("Timeout while trying to restart emulationstation")
                except Exception as e:
                    logger.error(f"Error restarting emulationstation: {e}", exc_info=True)
            
            return True
        else:
            logger.error(f"Downloaded file not found: {dest_path}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to download {game_id}: {e}", exc_info=True)
        return False

def mark_completed(download_id):
    """Mark a download as completed in the queue."""
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        response = http_session.post(
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
    # Request download - backend will determine queue type from user's role
    download_info = request_download(queue_type=None)
    
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
    
    # Main loop: poll for downloads
    while True:
        try:
            # Process queue - connection errors will be handled by request_download
            process_queue()
            
            # POLLING_INTERVAL is dynamically updated from backend responses
            # Wait for POLLING_INTERVAL to be set from backend before sleeping
            if POLLING_INTERVAL is None:
                logger.warning("POLLING_INTERVAL not yet set by backend, using temporary 60s interval")
                time.sleep(60)
            else:
                time.sleep(POLLING_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutting down download service...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            # Use POLLING_INTERVAL if set, otherwise temporary fallback
            sleep_interval = POLLING_INTERVAL if POLLING_INTERVAL is not None else 60
            time.sleep(sleep_interval)

if __name__ == "__main__":
    main() 
