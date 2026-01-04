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
    Path(DOWNLOAD_PATH).mkdir(parents=True, exist_ok=True)
    logger.info(f"Download directory ensured: {DOWNLOAD_PATH}")

def test_api_connection():
    """Test connection to the API and verify it's accessible."""
    try:
        logger.info(f"Testing API connection to {API_URL}...")
        response = http_session.get(
            f"{API_URL}/health",
            timeout=5
        )
        response.raise_for_status()
        logger.info(f"✓ Successfully connected to API at {API_URL}")
        return True
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"⚠ Cannot connect to API at {API_URL}")
        logger.debug(f"  Connection error: {e}")
        logger.debug(f"  Will retry in main loop. Please verify:")
        logger.debug(f"    1. The backend API is running")
        logger.debug(f"    2. API_URL in .env is correct (should be backend URL, typically http://localhost:8000)")
        logger.debug(f"    3. The backend is accessible from this machine")
        return False
    except requests.exceptions.Timeout:
        logger.warning(f"⚠ Connection to API at {API_URL} timed out")
        logger.debug(f"  Will retry in main loop. Please verify the backend is running and accessible")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"API health check returned error: {e}")
        logger.warning(f"  This might be OK if the /health endpoint doesn't exist")
        # Try a simple request to see if API is reachable
        try:
            response = http_session.get(f"{API_URL}/", timeout=5)
            logger.info(f"✓ API is reachable at {API_URL} (health endpoint may not exist)")
            return True
        except:
            logger.warning(f"⚠ API at {API_URL} is not reachable, will retry in main loop")
            return False

def request_download(queue_type=None):
    """Request next available download from the API."""
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
        # If it's a 410 Gone, the download was removed from queue - stop downloading
        if e.response and e.response.status_code == 410:
            logger.info(f"Progress report returned 410 Gone - download {download_id} was removed from queue, stopping download")
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

def download_file_via_http(http_url, dest_path, resume_from=0, expected_size=None, bytes_transferred_ref=None, chunk_size=1024*1024, paused_ref=None):
    """Download a file via HTTP with resume support. Throttling is handled server-side.
    
    Args:
        paused_ref: Optional list to check if download should be paused. If [False] becomes [True], download stops.
    
    Note: For streaming downloads, we use a separate requests.get() call instead of the session
    to avoid connection pool issues with long-lived streaming connections.
    """
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
    }
    
    # Add Range header for resume
    if resume_from > 0:
        headers['Range'] = f'bytes={resume_from}-'
    
    try:
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
                total_bytes_downloaded = bytes_already_transferred + bytes_transferred_this_session[0]
                
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
                logger.error(f"File not found (404) for {relative_path} in download {download_id}, removing from queue")
                progress_thread_running = False
                progress_thread.join(timeout=1)
                # Remove download from queue
                remove_download_from_queue(download_id)
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

def download_game(download_info):
    """Download a game file or directory via HTTP with progress reporting and resume support."""
    try:
        download_id = download_info['download_id']
        game_id = download_info['game_id']  # This is the rompath (e.g., "apshai.zip" or "board/chess/")
        system = download_info.get('system', '')  # System ID (e.g., "atari2600")
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
        
        logger.info(f"Downloading via HTTP")
        logger.info(f"  HTTP URL: {http_url}")
        logger.info(f"  Download ID: {download_id}")
        logger.info(f"  Game ID: {game_id}")
        logger.info(f"  System: {system}")
        
        # Determine destination base path: DOWNLOAD_PATH/system/rompath
        if system:
            dest_base_path = os.path.join(DOWNLOAD_PATH, system, game_id)
            logger.info(f"Destination base path: {dest_base_path}")
        else:
            logger.warning(f"System not provided in download_info, using game_id only: {game_id}")
            dest_base_path = os.path.join(DOWNLOAD_PATH, game_id)
            logger.info(f"Destination base path: {dest_base_path}")
        
        # First, check if it's a directory by requesting the base URL
        headers = {}
        
        try:
            # Make a GET request to check if it's a directory (JSON response) or a file
            # Don't use stream=True initially so we can check the response type
            # Use http_session for keep-alive support
            response = http_session.get(http_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '').lower()
            logger.info(f"Initial request Content-Type: {content_type}, Status: {response.status_code}")
            
            # Try to parse as JSON - directories return JSON, files return binary/octet-stream
            # First check the response text to see if it looks like JSON
            response_text = response.text
            logger.debug(f"Response preview (first 200 chars): {response_text[:200]}")
            
            try:
                dir_info = response.json()
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
                    return download_directory_recursive(
                        download_id, system, game_id, base_url, dest_base_path,
                        files_list, bytes_already_transferred, paused
                    )
            except (ValueError, requests.exceptions.JSONDecodeError, AttributeError) as json_err:
                # Not JSON, it's a file - but we've already consumed the response
                # We need to re-download it as a stream for the actual file download
                logger.debug(f"Response is not JSON, treating as single file. Content-Type: {content_type}, Error: {json_err}")
                # The response body has been consumed, so we'll need to download again
                # This will happen in the single file download section below
                # Close the response to free resources
                response.close()
                pass
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
                return True
        
        # Use bytes_already_transferred from API if available and larger
        if bytes_already_transferred > resume_from:
            resume_from = bytes_already_transferred
            logger.info(f"Using progress from API: resuming from byte {resume_from}")
        
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
                    total_bytes_transferred = resume_from + bytes_transferred_this_session[0]
                    
                    if bytes_transferred_this_session[0] > 0:
                        bytes_per_second = int(bytes_transferred_this_session[0] / elapsed)
                    else:
                        bytes_per_second = 0
                    
                    # Report progress - check return value
                    progress_result = report_progress(download_id, total_bytes_transferred, bytes_per_second)
                    if progress_result is None:
                        # Download was removed from queue - stop downloading
                        logger.info(f"Download {download_id} was removed from queue, stopping download")
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
                paused_ref=paused
            )
            
            # Check if file not found (404)
            if success is None:
                logger.error(f"File not found (404) for download {download_id}, removing from queue")
                progress_thread_running = False
                progress_thread.join(timeout=1)
                # Remove download from queue
                remove_download_from_queue(download_id)
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
        
        progress_thread_running = False
        progress_thread.join(timeout=1)
        
        # Verify file size
        if os.path.exists(dest_path) and os.path.isfile(dest_path):
            final_size = os.path.getsize(dest_path)
            if expected_file_size and final_size != expected_file_size:
                logger.error(f"File size mismatch after download: {final_size} != {expected_file_size}")
                report_progress(download_id, final_size, 0)
                return False
            
            # Final progress report
            total_time = time.time() - start_time
            final_bytes_per_second = int(bytes_transferred_this_session[0] / total_time) if total_time > 0 else 0
            try:
                report_progress(download_id, final_size, final_bytes_per_second)
            except Exception as e:
                logger.debug(f"Final progress report failed (download may already be completed): {e}")
            
            logger.info(f"Successfully downloaded: {game_id}")
            logger.info(f"  HTTP URL: {http_url}")
            logger.info(f"  Destination: {dest_path}")
            logger.info(f"  Size: {final_size} bytes ({final_size / (1024*1024):.2f} MB)")
            logger.info(f"  Time: {total_time:.2f}s")
            logger.info(f"  Resumed from: {resume_from} bytes")
            return True
        else:
            logger.error(f"Downloaded file not found: {dest_path}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to download {game_id}: {e}", exc_info=True)
        return False

def remove_download_from_queue(download_id):
    """Remove a download from the queue (e.g., when file doesn't exist)."""
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        # Use the remove endpoint which doesn't update statistics
        response = http_session.post(
            f"{API_URL}/api/download/remove",
            json={'download_id': download_id},
            headers=headers
        )
        # Even if it fails (already deleted), log it
        if response.status_code == 404:
            logger.warning(f"Download {download_id} already removed from queue")
        else:
            response.raise_for_status()
        logger.info(f"Removed download {download_id} from queue (file not found)")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to remove download from queue: {e}")
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

    # Test API connection before starting (but don't exit if it fails)
    api_connected = test_api_connection()
    if not api_connected:
        logger.warning("API connection failed on startup, but continuing. Will retry in main loop.")
    
    # Main loop: poll for downloads
    last_connection_check = time.time()
    connection_check_interval = 60  # Check connection every 60 seconds
    
    while True:
        try:
            # Periodically check API connection
            current_time = time.time()
            if current_time - last_connection_check >= connection_check_interval:
                if test_api_connection():
                    if not api_connected:
                        logger.info("✓ API connection restored!")
                        api_connected = True
                else:
                    if api_connected:
                        logger.warning("⚠ API connection lost, will retry...")
                        api_connected = False
                last_connection_check = current_time
            
            # Only try to process queue if API is connected
            if api_connected:
                process_queue()
            else:
                logger.debug("Skipping queue processing - API not connected")
            
            time.sleep(POLLING_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutting down download service...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(POLLING_INTERVAL)

if __name__ == "__main__":
    main() 
