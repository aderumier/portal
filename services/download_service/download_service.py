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
import configparser
from pathlib import Path
from logging.handlers import RotatingFileHandler
import asyncio
import websockets
from urllib.parse import urlparse

# Client version
CLIENT_VERSION = "0.1"

def read_config_ini(config_path):
    """Read config.ini file and return a dictionary of settings.
    
    Args:
        config_path: Path to config.ini file
        
    Returns:
        Dictionary with config values, or empty dict if file doesn't exist
    """
    config = {}
    if config_path.exists():
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding='utf-8')
            if 'Service' in parser:
                for key, value in parser['Service'].items():
                    config[key.upper()] = value
        except Exception as e:
            # If config.ini exists but can't be read, log to stderr since logger isn't set up yet
            print(f"Warning: Failed to read config.ini at {config_path}: {e}", file=sys.stderr)
    return config

# Determine paths based on platform
if platform.system() == 'Windows':
    # Windows paths
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        SERVICE_DIR = Path(sys.executable).parent
    else:
        # Running as script
        SERVICE_DIR = Path(__file__).parent
else:
    # Linux/Batocera paths
    SERVICE_DIR = Path(__file__).parent

# Read config.ini if it exists
config_ini_path = SERVICE_DIR / 'config.ini'
config = read_config_ini(config_ini_path)

# Setup logging - check config.ini first, then environment variables, then defaults
log_level = config.get('LOG_LEVEL') or os.getenv('LOG_LEVEL', 'INFO')
log_level = log_level.upper()

# Determine log file path
# Priority: LOG_FILE env var > LOG_DIR from config.ini/env > default
if platform.system() == 'Windows':
    # Windows paths
    if os.getenv('LOG_FILE'):
        log_file_path = os.path.abspath(os.getenv('LOG_FILE'))
    elif config.get('LOG_DIR'):
        log_dir = config.get('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
    elif os.getenv('LOG_DIR'):
        log_dir = os.getenv('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
    else:
        # Default Windows location
        appdata = os.getenv('APPDATA', os.path.expanduser('~'))
        log_dir = os.path.join(appdata, 'RGS', 'logs')
        log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
else:
    # Linux/Batocera paths
    if os.getenv('LOG_FILE'):
        log_file_path = os.path.abspath(os.getenv('LOG_FILE'))
    elif config.get('LOG_DIR'):
        log_dir = config.get('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
    elif os.getenv('LOG_DIR'):
        log_dir = os.getenv('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
    else:
        # Default Linux location
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
if config_ini_path.exists():
    logger.info(f"Configuration loaded from: {config_ini_path}")

# Custom handler for capturing download task logs
class DownloadLogHandler(logging.Handler):
    """Custom logging handler that captures logs for a specific download."""
    def __init__(self, download_id):
        super().__init__()
        self.download_id = download_id
        self.logs = []
        self.setLevel(logging.DEBUG)
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
    
    def emit(self, record):
        """Capture log record."""
        try:
            msg = self.format(record)
            self.logs.append(msg)
        except Exception:
            self.handleError(record)
    
    def get_logs(self):
        """Get all captured logs as a string."""
        return '\n'.join(self.logs)
    
    def clear(self):
        """Clear captured logs."""
        self.logs = []

# Global dictionary to store download log handlers
_download_log_handlers = {}

# Global dictionary to track paused downloads (download_id -> paused_ref)
# This allows WebSocket notifications to immediately pause downloads
_active_download_pause_refs = {}

# Configuration - read from config.ini first, then environment variables, then defaults
# Priority: config.ini > environment variable > default

API_URL = config.get('API_URL') or os.getenv('API_URL', 'https://rgs-retro.ddns.net')

# Set ROMS_PATH based on platform
if platform.system() == 'Windows':
    DEFAULT_ROMS_PATH = os.path.join(os.getenv('PROGRAMDATA', 'C:\\ProgramData'), 'RGS', 'roms')
else:
    DEFAULT_ROMS_PATH = '/userdata/roms'

ROMS_PATH = config.get('ROMS_PATH') or os.getenv('ROMS_PATH', DEFAULT_ROMS_PATH)

# BANDWIDTH_UPDATE_INTERVAL will be fetched from backend on first request_download call
# No fallback - must be set by backend
BANDWIDTH_UPDATE_INTERVAL = None
SERVICE_ID = config.get('SERVICE_ID') or os.getenv('SERVICE_ID', socket.gethostname())

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
logger.info(f"  BANDWIDTH_UPDATE_INTERVAL: Will be set from backend on first connection")

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

def update_bandwidth_update_interval(new_interval):
    """Update the global BANDWIDTH_UPDATE_INTERVAL value.
    
    Args:
        new_interval: New bandwidth update interval in seconds (int)
    """
    global BANDWIDTH_UPDATE_INTERVAL
    if isinstance(new_interval, int) and new_interval > 0:
        if BANDWIDTH_UPDATE_INTERVAL is None:
            logger.info(f"Setting BANDWIDTH_UPDATE_INTERVAL to {new_interval} seconds (from backend)")
            BANDWIDTH_UPDATE_INTERVAL = new_interval
        elif BANDWIDTH_UPDATE_INTERVAL != new_interval:
            logger.info(f"Updating BANDWIDTH_UPDATE_INTERVAL from {BANDWIDTH_UPDATE_INTERVAL} to {new_interval} seconds")
            BANDWIDTH_UPDATE_INTERVAL = new_interval
    else:
        logger.warning(f"Invalid bandwidth update interval received: {new_interval}, keeping current value: {BANDWIDTH_UPDATE_INTERVAL}")

def request_download(queue_type=None):
    """Request next available download from the API.
    
    Also updates BANDWIDTH_UPDATE_INTERVAL from the backend response.
    
    Returns:
        dict: Download info dict, or None if no download available
    
    Raises:
        SystemExit: If API token is invalid (401 Unauthorized)
    """
    try:
        logger.info(f"Requesting download from {API_URL}/api/download/request")
        headers = {
            'Content-Type': 'application/json'
        }
        # Determine platform based on system
        client_platform = 'windows' if platform.system() == 'Windows' else 'linux'
        data = {
            'service_id': SERVICE_ID,
            'platform': client_platform,
            'client_version': CLIENT_VERSION
        }
        if queue_type:
            data['queue_type'] = queue_type
        
        logger.info(f"Sending request with data: service_id={SERVICE_ID}, platform={client_platform}, client_version={CLIENT_VERSION}, queue_type={queue_type}")
        logger.info(f"Using API_TOKEN (length: {len(API_TOKEN) if API_TOKEN else 0} chars, first 8: {API_TOKEN[:8] if API_TOKEN and len(API_TOKEN) >= 8 else 'N/A'}...)")
        logger.info(f"Making HTTP POST request (timeout=30s)...")
        # Use explicit timeout tuple: (connect_timeout, read_timeout)
        response = http_session.post(
            f"{API_URL}/api/download/request",
            json=data,
            headers=headers,
            timeout=(10, 30)  # 10s connect, 30s read
        )
        logger.info(f"Received response: status_code={response.status_code}")
        
        try:
            response.raise_for_status()
            
            # Parse JSON response
            try:
                result = response.json()
            except (ValueError, json.JSONDecodeError) as json_err:
                logger.error(f"Failed to parse JSON response: {json_err}")
                logger.error(f"Response text (first 500 chars): {response.text[:500] if hasattr(response, 'text') else 'N/A'}")
                response.close()
                return None
            
            # Log the full response for debugging (but truncate large responses)
            result_str = json.dumps(result, indent=2)
            if len(result_str) > 1000:
                logger.info(f"Response JSON (truncated): {result_str[:1000]}...")
            else:
                logger.info(f"Response JSON: {result_str}")
            
            # Always update bandwidth update interval from backend response (required, no fallback)
            bandwidth_update_interval = result.get('bandwidth_update_interval')
            if bandwidth_update_interval is not None:
                update_bandwidth_update_interval(int(bandwidth_update_interval))
            else:
                logger.error("Backend did not return bandwidth_update_interval in response!")
            
            download_info = result.get('download')
            logger.info(f"Extracted download_info from response: {'Found' if download_info else 'None (no downloads available)'}")
            
            return download_info
        finally:
            # Explicitly close response to free connection
            response.close()
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
    except requests.exceptions.Timeout as e:
        logger.error(f"Request to API at {API_URL} timed out after 30 seconds")
        logger.error(f"Timeout details: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to request download: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"  Response status: {e.response.status_code}")
            # Don't log response body for server errors (5xx) to avoid noise
            if e.response.status_code < 500:
                logger.error(f"  Response body: {e.response.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in request_download: {e}", exc_info=True)
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
            'bytes_per_second': bytes_per_second,
            'client_version': CLIENT_VERSION
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
            return None  # Return None to indicate download was removed/completed, not True
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

def download_file_via_http(http_url, dest_path, resume_from=0, expected_size=None, bytes_transferred_ref=None, chunk_size=1024*1024, paused_ref=None, existing_response=None, max_retries=5):
    """Download a file via HTTP with resume support. Throttling is handled server-side.
    
    Args:
        paused_ref: Optional list to check if download should be paused. If [False] becomes [True], download stops.
        existing_response: Optional existing response object to reuse (avoids duplicate request for single file downloads)
        max_retries: Maximum number of retries for chunked encoding errors (default: 5)
    
    Note: For streaming downloads, we use a separate requests.get() call instead of the session
    to avoid connection pool issues with long-lived streaming connections.
    """
    current_resume_from = resume_from
    retry_count = 0
    total_bytes_downloaded = resume_from  # Initialize for exception handlers
    
    while retry_count <= max_retries:
        # Check if download is paused before making any request
        if paused_ref and paused_ref[0]:
            logger.info(f"Download paused - aborting before retry attempt {retry_count}")
            return False
        
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
        }
        
        # Add Range header for resume (only if we need to make a new request)
        if current_resume_from > 0 and existing_response is None:
            headers['Range'] = f'bytes={current_resume_from}-'
        
        try:
            # On retry, we can't reuse the existing response
            if retry_count > 0:
                if existing_response:
                    existing_response.close()
                    existing_response = None
                if current_resume_from > 0:
                    headers['Range'] = f'bytes={current_resume_from}-'
                logger.info(f"Retrying download from byte {current_resume_from} (attempt {retry_count}/{max_retries})")
            
            # Reuse existing response if provided (avoids duplicate request for single file downloads)
            if existing_response is not None:
                response = existing_response
                # If we need to resume, we can't reuse the existing response
                if current_resume_from > 0:
                    logger.warning(f"Cannot reuse existing response for resume, making new request")
                    existing_response.close()
                    headers['Range'] = f'bytes={current_resume_from}-'
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
            if current_resume_from > 0 and response.status_code != 206:
                logger.warning(f"Server doesn't support range requests, starting from beginning")
                current_resume_from = 0
            
            # Get file size from Content-Length or Content-Range header
            content_length = None
            if 'Content-Length' in response.headers:
                content_length = int(response.headers['Content-Length'])
            elif 'Content-Range' in response.headers:
                # Parse Content-Range: bytes 0-1023/2048
                content_range = response.headers['Content-Range']
                if '/' in content_range:
                    content_length = int(content_range.split('/')[-1])
        
            # Initialize tracking variables - on retry, resume from where we left off
            total_bytes_downloaded = current_resume_from
                
            # Open destination file
            mode = 'ab' if current_resume_from > 0 else 'wb'
            bytes_downloaded_this_session = 0  # Track bytes downloaded in this session only
            chunk_count = 0
            download_start_time = time.time()
            last_log_time = download_start_time
            last_pause_check = download_start_time
            
            # Track recent download rate (last 10 seconds) for more accurate current rate display
            recent_bytes_window = []  # List of (timestamp, bytes) tuples for last 10 seconds
            recent_rate_window_seconds = 10.0
            
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
                            f.flush()  # Ensure data is written to disk
                            bytes_written = len(chunk)
                            total_bytes_downloaded += bytes_written
                            bytes_downloaded_this_session += bytes_written
                            chunk_count += 1
                            
                            if bytes_transferred_ref:
                                bytes_transferred_ref[0] += bytes_written
                            
                            # Track recent download rate for accurate current rate display
                            current_time = time.time()
                            recent_bytes_window.append((current_time, bytes_written))
                            # Remove entries older than the window
                            cutoff_time = current_time - recent_rate_window_seconds
                            recent_bytes_window = [(ts, bytes) for ts, bytes in recent_bytes_window if ts >= cutoff_time]
                            
                            # Log progress every 5 seconds or every 10MB
                            if current_time - last_log_time >= 5.0 or (chunk_count % 100 == 0):
                                # Calculate rate based on recent window (last 10 seconds) for current rate
                                if len(recent_bytes_window) > 1:
                                    window_start_time = recent_bytes_window[0][0]
                                    window_end_time = recent_bytes_window[-1][0]
                                    window_duration = window_end_time - window_start_time
                                    window_bytes = sum(bytes for _, bytes in recent_bytes_window)
                                    if window_duration > 0:
                                        current_rate = window_bytes / window_duration
                                    else:
                                        # Fallback to session average if window is too small
                                        elapsed_total = current_time - download_start_time
                                        current_rate = bytes_downloaded_this_session / elapsed_total if elapsed_total > 0 else 0
                                else:
                                    # Fallback to session average if not enough data
                                    elapsed_total = current_time - download_start_time
                                    current_rate = bytes_downloaded_this_session / elapsed_total if elapsed_total > 0 else 0
                                
                                logger.info(f"Downloaded {total_bytes_downloaded} bytes ({total_bytes_downloaded / (1024*1024):.2f} MB), {chunk_count} chunks this session, rate: {current_rate / 125000:.2f} Mbits/s")
                                last_log_time = current_time
                        elif chunk is None:
                            # Empty chunk might indicate end of stream, but continue
                            continue
                except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
                    # Handle chunked encoding errors (connection broken during transfer)
                    response.close()
                    
                    # Check if download is paused before retrying
                    if paused_ref and paused_ref[0]:
                        logger.info(f"Download was paused during chunked encoding error handling")
                        return False
                    
                    # Check if we made progress - if so, we can retry from current position
                    if total_bytes_downloaded > current_resume_from:
                        logger.warning(f"Chunked encoding error at {total_bytes_downloaded} bytes: {e}")
                        logger.info(f"Progress saved, will retry from byte {total_bytes_downloaded}")
                        current_resume_from = total_bytes_downloaded
                        retry_count += 1
                        if retry_count <= max_retries:
                            # Wait a bit before retrying (exponential backoff: 1s, 2s, 4s, 8s, 16s)
                            wait_time = min(2 ** (retry_count - 1), 16)
                            logger.info(f"Waiting {wait_time} seconds before retry...")
                            time.sleep(wait_time)
                            # Check again if paused before making the retry request
                            if paused_ref and paused_ref[0]:
                                logger.info(f"Download was paused during retry wait, aborting")
                                return False
                            continue  # Retry the download
                        else:
                            logger.error(f"Max retries ({max_retries}) exceeded for chunked encoding errors")
                            return False
                    else:
                        # No progress made, don't retry
                        logger.error(f"Chunked encoding error with no progress: {e}", exc_info=True)
                        return False
                except Exception as e:
                    response.close()
                    logger.error(f"Error during download iteration: {e}", exc_info=True)
                    raise
        
            # Explicitly close the response to free the connection
            response.close()
            
            # Check if stream ended unexpectedly (before all bytes were received)
            # This can happen if the server paused the download mid-stream
            if content_length and total_bytes_downloaded < (current_resume_from + content_length):
                logger.warning(f"Stream ended unexpectedly: received {total_bytes_downloaded} bytes, expected {current_resume_from + content_length} bytes")
                # Check if download is paused
                if paused_ref and paused_ref[0]:
                    logger.info(f"Download was paused - stream ended at {total_bytes_downloaded} bytes")
                    return False  # Return False to indicate pause
                # If not paused, this might be a network error - retry if we have retries left
                if retry_count < max_retries:
                    logger.info(f"Stream ended unexpectedly, will retry from byte {total_bytes_downloaded}")
                    current_resume_from = total_bytes_downloaded
                    retry_count += 1
                    wait_time = min(2 ** (retry_count - 1), 16)
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    # Check again if paused before making the retry request
                    if paused_ref and paused_ref[0]:
                        logger.info(f"Download was paused during retry wait, aborting")
                        return False
                    continue  # Retry the download
                else:
                    logger.warning(f"Stream ended unexpectedly but download is not paused - max retries exceeded")
                    return False
            
            logger.info(f"Download completed: {chunk_count} chunks, {total_bytes_downloaded} bytes")
            
            # Verify file size
            final_size = os.path.getsize(dest_path)
            if expected_size and final_size != expected_size:
                logger.error(f"File size mismatch: {final_size} != {expected_size}")
                # Don't delete file here - let caller handle deletion and error reporting
                # This allows caller to distinguish between 404 and size mismatch
                return None  # None indicates size mismatch (caller should handle deletion and error reporting)
            
            # Success - break out of retry loop
            return True
            
        except requests.exceptions.HTTPError as e:
            # Handle 410 errors - download was removed from queue, abort immediately
            if e.response and e.response.status_code == 410:
                logger.info(f"Download removed from queue (410 Gone) for URL: {http_url}")
                logger.info(f"Aborting download as it was removed from queue")
                # Close response if it exists
                if 'response' in locals() and response:
                    try:
                        response.close()
                    except:
                        pass
                # Return None to indicate download was removed (should abort immediately, no retry)
                return None  # None indicates download was removed (different from False which indicates pause)
            # Handle 403 errors - download is paused
            # IMPORTANT: Return immediately without retrying - 403 means download is paused
            if e.response and e.response.status_code == 403:
                logger.info(f"Download paused (403) for URL: {http_url} - aborting immediately, no retry")
                if paused_ref:
                    paused_ref[0] = True
                # Close response if it exists
                if 'response' in locals() and response:
                    try:
                        response.close()
                    except:
                        pass
                # Return immediately - exit function and while loop, no retry
                return False  # Return False immediately - do NOT retry on pause
            # Handle 404 errors - file doesn't exist, remove from queue
            if e.response and e.response.status_code == 404:
                logger.error(f"File not found (404) for URL: {http_url}")
                logger.error(f"This indicates the file doesn't exist on the server. The download should be removed from queue.")
                # Close response if it exists
                if 'response' in locals() and response:
                    try:
                        response.close()
                    except:
                        pass
                # Return a special value to indicate file not found
                return None  # None indicates file not found (different from False which indicates pause/failure)
            logger.error(f"HTTP download error: {e}", exc_info=True)
            # Close response on error
            if 'response' in locals() and response:
                try:
                    response.close()
                except:
                    pass
            # Retry on HTTP errors if we have retries left (except for 403/404 which return immediately above)
            if retry_count < max_retries:
                retry_count += 1
                wait_time = min(2 ** (retry_count - 1), 16)
                logger.info(f"HTTP error occurred, will retry in {wait_time} seconds (attempt {retry_count}/{max_retries})")
                time.sleep(wait_time)
                continue
            return False
        except requests.exceptions.RequestException as e:
            # Retry on connection errors if we have retries left
            # Check if we have a variable total_bytes_downloaded set from the try block
            if 'total_bytes_downloaded' in locals() and retry_count < max_retries and total_bytes_downloaded > current_resume_from:
                logger.warning(f"Connection error at {total_bytes_downloaded} bytes: {e}")
                logger.info(f"Progress saved, will retry from byte {total_bytes_downloaded}")
                current_resume_from = total_bytes_downloaded
                retry_count += 1
                wait_time = min(2 ** (retry_count - 1), 16)
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                continue  # Retry the download
            logger.error(f"HTTP download error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error during HTTP download: {e}", exc_info=True)
            return False
    
    # If we exit the while loop without returning, max retries exceeded
    logger.error(f"Max retries ({max_retries}) exceeded for download")
    return False

def download_directory_recursive(download_id, system, game_id, base_url, dest_base_path, files_list, bytes_already_transferred, paused_ref):
    """Download all files in a directory recursively."""
    import urllib.parse
    
    # Reset paused_ref to False at the start (in case this is a resumed download)
    if paused_ref:
        paused_ref[0] = False
    
    total_bytes_downloaded = bytes_already_transferred
    bytes_transferred_this_session = [0]
    start_time = time.time()
    last_report_time = start_time
    progress_thread_running = True
    
    def progress_reporter():
        """Background thread to report progress periodically and check for pause."""
        nonlocal last_report_time, progress_thread_running, total_bytes_downloaded
        # Use BANDWIDTH_UPDATE_INTERVAL if set, otherwise fallback to 5 seconds
        interval = BANDWIDTH_UPDATE_INTERVAL if BANDWIDTH_UPDATE_INTERVAL is not None else 5
        while progress_thread_running:
            time.sleep(interval)
            elapsed = time.time() - last_report_time
            if elapsed > 0:
                # Accumulate bytes from this session into total
                total_bytes_downloaded += bytes_transferred_this_session[0]
                
                if bytes_transferred_this_session[0] > 0:
                    bytes_per_second = int(bytes_transferred_this_session[0] / elapsed)
                else:
                    bytes_per_second = 0
                
                # Check if thread should stop before attempting to report
                if not progress_thread_running:
                    break
                
                # Report progress - check return value
                try:
                    progress_result = report_progress(download_id, total_bytes_downloaded, bytes_per_second)
                    if progress_result is None:
                        # Download was removed from queue (likely completed) - stop reporting
                        logger.debug(f"Download {download_id} was removed from queue (likely completed), stopping progress reporter")
                        paused_ref[0] = False  # Not paused, just completed
                        progress_thread_running = False
                        break
                    elif progress_result is False:
                        # Download is paused
                        logger.info(f"Download {download_id} is paused - checking status...")
                        paused_ref[0] = True
                        progress_thread_running = False
                        break
                except requests.exceptions.HTTPError as e:
                    # Handle HTTP errors - check if it's a 410 Gone (download completed/removed)
                    if e.response and e.response.status_code == 410:
                        logger.debug(f"Progress report returned 410 Gone - download {download_id} was removed from queue (likely completed)")
                        paused_ref[0] = False  # Not paused, just completed
                        progress_thread_running = False
                        break
                    # For other HTTP errors, check if thread should still run
                    if not progress_thread_running:
                        break
                except Exception as e:
                    # If reporting fails, check if thread should still run
                    logger.debug(f"Progress report failed (download may be completed): {e}")
                    if not progress_thread_running:
                        break
                
                last_report_time = time.time()
                bytes_transferred_this_session[0] = 0
    
    progress_thread = threading.Thread(target=progress_reporter, daemon=True)
    progress_thread.start()
    
    # Track files with errors
    files_with_errors = []
    
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
            # Only remove './' prefix if present, preserve paths starting with '.zfs'
            clean_game_id = game_id[2:] if game_id.startswith('./') else game_id
            encoded_game_id = urllib.parse.quote(clean_game_id, safe='/')
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
                    # Verify size of existing file
                    if existing_size != file_size:
                        logger.error(f"Existing file size mismatch for {relative_path}: {existing_size} bytes, expected {file_size} bytes")
                        try:
                            os.remove(dest_file_path)
                            logger.info(f"Deleted corrupted existing file: {dest_file_path}")
                            # Need to download it
                        except Exception as e:
                            logger.error(f"Failed to delete corrupted existing file {dest_file_path}: {e}")
                            files_with_errors.append((relative_path, f"Existing file size mismatch: {existing_size} != {file_size}"))
                            continue
                    else:
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
            
            # Check if file not found (404), removed from queue (410), or size mismatch (None)
            if success is None:
                # None can mean 404, 410 (removed), or size mismatch
                # Check if file exists to determine which case
                if os.path.exists(dest_file_path):
                    # Size mismatch case - file exists but wrong size
                    final_size = os.path.getsize(dest_file_path)
                    logger.error(f"File size mismatch for {relative_path}: downloaded {final_size} bytes, expected {file_size} bytes")
                    
                    # Delete only this corrupted file
                    try:
                        os.remove(dest_file_path)
                        logger.info(f"Deleted corrupted file: {dest_file_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete corrupted file {dest_file_path}: {e}")
                    
                    # Track this error but continue with other files
                    files_with_errors.append((relative_path, f"File size mismatch: {final_size} != {file_size}"))
                    continue
                else:
                    # 404 or 410 case - file not found or download removed
                    # For 410 (removed from queue), we should abort immediately
                    # For 404 (file not found), we should also abort as the file doesn't exist
                    logger.error(f"File not available (404/410) for {relative_path} in download {download_id} - download was likely removed from queue or file doesn't exist")
                    logger.info(f"Aborting download as file is no longer available")
                    # Stop progress reporter thread immediately
                    progress_thread_running = False
                    progress_thread.join(timeout=1)
                    return False  # Abort the entire download
            
            if not success:
                # Check if this was a pause - only log if not already completed
                if paused_ref and paused_ref[0]:
                    # Check if download is still in queue (not completed)
                    # If paused, stop progress reporter and return
                    logger.info(f"Download {download_id} was paused")
                    progress_thread_running = False
                    progress_thread.join(timeout=1)
                    return False
                # Not paused, just failed
                logger.error(f"Failed to download file: {relative_path}")
                files_with_errors.append((relative_path, "Download failed"))
                continue
            
            # Verify file size after successful download
            if os.path.exists(dest_file_path):
                actual_size = os.path.getsize(dest_file_path)
                if actual_size != file_size:
                    logger.error(f"File size mismatch for {relative_path} after download: {actual_size} bytes, expected {file_size} bytes")
                    try:
                        os.remove(dest_file_path)
                        logger.info(f"Deleted corrupted file: {dest_file_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete corrupted file {dest_file_path}: {e}")
                    files_with_errors.append((relative_path, f"File size mismatch: {actual_size} != {file_size}"))
                    continue
                else:
                    logger.debug(f"File size verified for {relative_path}: {actual_size} bytes")
        
        # Stop progress reporter thread immediately
        progress_thread_running = False
        progress_thread.join(timeout=1)
        
        # Clear paused_ref immediately on successful completion to prevent false pause logs
        if paused_ref:
            paused_ref[0] = False
        
        # If any files had errors, report to backend
        if files_with_errors:
            error_details = "; ".join([f"{path}: {error}" for path, error in files_with_errors])
            error_msg = f"Download completed with errors for {len(files_with_errors)} file(s): {error_details}"
            logger.error(f"Failed to download {game_id}: {error_msg}")
            try:
                mark_error(download_id, error_msg)
            except Exception as e:
                logger.error(f"Failed to report error to backend: {e}")
            return False
        
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
    """Normalize media paths for local storage (remove snapshot paths and leading `./`, keep system prefix).
    
    Media files should always be saved to {ROM_PATH}/{system}/media/... regardless of whether
    they come from WIP or Releases catalog. Snapshot paths must be removed from destination paths.
    The system prefix should be preserved.
    
    Args:
        path: Media path from backend (e.g., "system/media/thumbnails/game.png" or 
              "system/.zfs/snapshot/v1/media/thumbnails/game.png")
    
    Returns:
        str: Normalized path without snapshot paths or leading `./`, but with system prefix
        (e.g., "system/media/thumbnails/game.png")
    """
    if not path:
        return ''
    
    # Remove leading ./
    normalized = path.lstrip('./')
    
    # Remove snapshot paths (e.g., "system/.zfs/snapshot/v1/media/..." -> "system/media/...")
    # Pattern: system/.zfs/snapshot/v(anything)/media/... -> system/media/...
    import re
    # Match pattern: system/.zfs/snapshot/v(anything)/path
    snapshot_pattern = r'^([^/]+)/\.zfs/snapshot/v[^/]+/(.+)$'
    match = re.match(snapshot_pattern, normalized)
    if match:
        system_name = match.group(1)
        path_after_snapshot = match.group(2)
        normalized = f"{system_name}/{path_after_snapshot}"
    
    return normalized

def remove_snapshot_path_from_game_id(game_id):
    """Remove snapshot path from game_id for destination path construction.
    
    Args:
        game_id: Game ID that may include snapshot path (e.g., ".zfs/snapshot/v1/game.rom")
    
    Returns:
        str: Game ID without snapshot path (e.g., "game.rom")
    """
    if not game_id:
        return game_id
    
    # Remove leading ./
    normalized = game_id.lstrip('./')
    
    # Remove snapshot paths (e.g., ".zfs/snapshot/v1/game.rom" -> "game.rom")
    import re
    # Match pattern: .zfs/snapshot/v(anything)/path
    pattern = r'^\.zfs/snapshot/v[^/]+/(.+)$'
    match = re.match(pattern, normalized)
    if match:
        normalized = match.group(1)
    
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
            # Get original media path from game_data (already in original format from gamelist.xml)
            media_path = game_data.get(media_type, '')
            if not media_path:
                continue  # Skip missing media
            
            # Get download URL if provided by backend (preferred)
            download_url_key = f"{media_type}_download_url"
            media_url = game_data.get(download_url_key, '')
            
            # If download URL not provided, construct it from media_path
            # This is a fallback for backwards compatibility
            if not media_url:
                # Remove leading ./ if present
                clean_media_path = media_path.lstrip('./')
                
                # Ensure system prefix is present for URL construction
                if not clean_media_path.startswith(f"{system}/"):
                    clean_media_path = f"{system}/{clean_media_path}"
                
                # Construct URL: /media/{mediaPath}
                media_url = f"{API_URL}/media/{clean_media_path}"
            
            # For destination path, use original path from game_data
            # Remove ./ prefix if present, then construct: ROMS_PATH/batocera_system/original_path
            original_path = media_path.lstrip('./')
            
            # Remove system prefix if present (since we'll add batocera_system later)
            if original_path.startswith(f"{system}/"):
                original_path = original_path[len(system) + 1:]
            
            # Also remove snapshot path if present (for Releases catalog)
            # Original path might be: ".zfs/snapshot/vX/media/..." -> "media/..."
            if '/.zfs/snapshot/' in original_path:
                parts = original_path.split('/.zfs/snapshot/', 1)
                if len(parts) > 1:
                    after_snapshot = parts[1]
                    # Extract part after snapshot version
                    if '/' in after_snapshot:
                        original_path = '/'.join(after_snapshot.split('/')[1:])
                    else:
                        original_path = after_snapshot
            
            # For destination path, construct from original path
            # Destination: ROMS_PATH/batocera_system/original_path (without ./ and without system prefix)
            # Remove ./ prefix if present
            dest_path_relative = original_path.lstrip('./')
            
            # Remove system prefix if present (we'll use batocera_system instead)
            if dest_path_relative.startswith(f"{system}/"):
                dest_path_relative = dest_path_relative[len(system) + 1:]
            
            # Remove snapshot path if present (for Releases catalog)
            # Original path might be: ".zfs/snapshot/vX/media/..." -> "media/..."
            if '/.zfs/snapshot/' in dest_path_relative:
                parts = dest_path_relative.split('/.zfs/snapshot/', 1)
                if len(parts) > 1:
                    after_snapshot = parts[1]
                    # Extract part after snapshot version
                    if '/' in after_snapshot:
                        dest_path_relative = '/'.join(after_snapshot.split('/')[1:])
                    else:
                        dest_path_relative = after_snapshot
            
            if not dest_path_relative:
                continue
            
            # Destination path: ROMS_PATH/batocera_system/original_path
            # Media files always go to {ROM_PATH}/{batocera_system}/media/... (never .zfs directories)
            # This ensures consistent paths for both WIP and Releases catalog
            dest_path = os.path.join(ROMS_PATH, target_system, dest_path_relative)
            
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
                downloaded_media.append(dest_path_relative)
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
                    logger.info(f"Successfully downloaded {media_type}: {dest_path_relative}")
                    downloaded_media.append(dest_path_relative)
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

def add_game_to_batocera_api(batocera_system, game_id, game_data, media_paths):
    """Add/update game in Batocera via EmulationStation HTTP API.
    
    Args:
        batocera_system: Batocera system directory name (e.g., "atari2600")
        game_id: Game ID (rompath, e.g., "apshai.zip")
        game_data: Full game data from API (dict)
        media_paths: Dict mapping media types to downloaded paths (relative to system directory)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from xml.dom import minidom
        
        # Build game metadata dict for Batocera API
        # Include ALL fields from game_data (except system-specific metadata)
        batocera_game = {}
        
        # Fields to exclude from the API call (system-specific metadata and website-only fields)
        exclude_fields = {'id', 'system', 'systemName', 'catalog_image'}
        
        # Add ALL fields from game_data to batocera_game
        # Paths should already be in original gamelist.xml format from backend (no restoration needed)
        for field_name, value in game_data.items():
            # Skip excluded fields and internal metadata
            if field_name in exclude_fields or field_name.endswith('_download_url'):
                continue
            
            # Skip empty values
            if not value:
                continue
            
            # Use value as-is from game_data (already in original gamelist.xml format)
            batocera_game[field_name] = str(value)
        
        # All fields including path and media paths are already in original gamelist.xml format from backend
        # No path manipulation needed - use as-is
        # Log the path field value for debugging
        logger.info(f"Using original path from gamelist.xml: '{batocera_game.get('path', 'NOT SET')}'")
        
        # Create XML structure
        root = ET.Element("gameList")
        game_elem = ET.SubElement(root, "game")
        
        # Add all fields to XML
        for key, value in batocera_game.items():
            if value:  # Only add non-empty fields
                elem = ET.SubElement(game_elem, key)
                elem.text = str(value)
        
        # Pretty print XML
        def prettify_xml(elem):
            """Return a pretty-printed XML string for the Element."""
            rough_string = ET.tostring(elem, encoding='unicode')
            reparsed = minidom.parseString(rough_string)
            return reparsed.toprettyxml(indent="  ")
        
        xml_content = prettify_xml(root)
        
        # Log all parameters being sent
        logger.info(f"=== Batocera API Request Parameters ===")
        logger.info(f"URL: http://127.0.0.1:1234/addgames/{batocera_system}")
        logger.info(f"Game ID: {game_id}")
        logger.info(f"Batocera System: {batocera_system}")
        logger.info(f"Game Name: {game_data.get('name', 'N/A')}")
        logger.info(f"Path field: {batocera_game.get('path', 'NOT SET')}")
        logger.info(f"All fields being sent:")
        for key, value in batocera_game.items():
            if key == 'path':
                logger.info(f"  {key}: {value} [PATH FIELD - CHECK THIS]")
            else:
                logger.info(f"  {key}: {value}")
        logger.info(f"XML Content:\n{xml_content}")
        logger.info(f"=== End Batocera API Request Parameters ===")
        
        # Send POST request to Batocera API
        batocera_api_url = "http://127.0.0.1:1234"
        url = f"{batocera_api_url}/addgames/{batocera_system}"
        headers = {'Content-Type': 'application/xml'}
        
        logger.info(f"Sending game '{game_data.get('name', game_id)}' to Batocera API at {url}")
        response = requests.post(url, data=xml_content, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Successfully added/updated game in Batocera system '{batocera_system}'")
            return True
        elif response.status_code == 201:
            logger.info(f"Successfully added/updated game in Batocera system '{batocera_system}' (system will reload on next access)")
            return True
        elif response.status_code == 204:
            logger.info(f"No games were added/updated in Batocera system '{batocera_system}' (game may already exist)")
            return True  # Not an error, just no changes
        elif response.status_code == 400:
            logger.error(f"Bad request when adding game to Batocera: {response.text}")
            return False
        elif response.status_code == 404:
            logger.error(f"System '{batocera_system}' not found in Batocera")
            return False
        elif response.status_code == 403:
            logger.error(f"Forbidden when adding game to Batocera (PublicWebAccess may be disabled)")
            return False
        else:
            logger.error(f"Unexpected status code {response.status_code} when adding game to Batocera: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        logger.warning(f"Could not connect to Batocera HTTP server at http://127.0.0.1:1234 (EmulationStation may not be running)")
        return False
    except requests.exceptions.Timeout:
        logger.warning(f"Request to Batocera HTTP server timed out")
        return False
    except Exception as e:
        logger.error(f"Error adding game to Batocera via API: {e}", exc_info=True)
        return False

def download_game(download_info):
    """Download a game file or directory via HTTP with progress reporting and resume support."""
    download_id = download_info.get('download_id')
    
    # Create and attach log handler for this download
    # Use root logger to capture all log messages during download
    log_handler = DownloadLogHandler(download_id)
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    _download_log_handlers[download_id] = log_handler
    
    # Log start of download
    logger.info(f"=== Starting download task for download_id: {download_id} ===")
    
    try:
        game_id = download_info['game_id']  # Original game_id (may include snapshot path) - used for URL construction
        system = download_info.get('system', '')  # System ID (e.g., "atari2600") - used for API calls
        batocera_system = download_info.get('batocera_system', '')  # Batocera system directory name - used for local paths
        game_details = download_info.get('game_details', {})  # Full game data with original paths
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
        
        # Get original path from game_details (from gamelist.xml)
        # Fallback to game_id if path not in game_details
        original_path = game_details.get('path', game_id)
        
        # Remove ./ prefix if present
        clean_original_path = original_path.lstrip('./')
        
        # Remove system prefix if present (since we'll add batocera_system)
        if clean_original_path.startswith(f"{system}/"):
            clean_original_path = clean_original_path[len(system) + 1:]
        
        # Remove snapshot path if present (for Releases catalog)
        # Original path might be: ".zfs/snapshot/vX/game.rom" -> "game.rom"
        if clean_original_path.startswith('.zfs/snapshot/'):
            parts = clean_original_path.split('/', 3)  # Split into ['.zfs', 'snapshot', 'version', 'path']
            if len(parts) > 3:
                clean_original_path = parts[3]
        
        target_system = batocera_system
        
        logger.info(f"Downloading via HTTP")
        logger.info(f"  HTTP URL: {http_url}")
        logger.info(f"  Download ID: {download_id}")
        logger.info(f"  Game ID: {game_id}")
        logger.info(f"  Original Path: {original_path}")
        logger.info(f"  Clean Path: {clean_original_path}")
        logger.info(f"  System: {system}")
        logger.info(f"  Batocera System: {target_system}")
        
        # Determine destination base path: ROMS_PATH/batocera_system/original_path
        if target_system:
            dest_base_path = os.path.join(ROMS_PATH, target_system, clean_original_path)
            logger.info(f"Destination base path: {dest_base_path}")
        else:
            logger.warning(f"Target system not provided in download_info, using game_id only: {game_id}")
            dest_base_path = os.path.join(ROMS_PATH, clean_original_path)
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
                        # It's a multi-file download (directory, .m3u, .cue, .xbox360, etc.)
                        files_list = dir_info.get('files', [])
                        base_path_type = dir_info.get('base_path_type', 'directory')
                        source_file = dir_info.get('source_file', 'directory')
                        download_type = source_file if source_file != 'directory' else "directory"
                        logger.info(f"✓ {download_type} download detected: {len(files_list)} files, {dir_info.get('total_size', 0)} bytes")
                        
                        # For special files with base_path_type='file' (.m3u, .cue, etc.),
                        # dest_base_path should be the directory containing the source file
                        # (not the file itself, since relative_path values are relative to the file's directory)
                        if base_path_type == 'file':
                            # dest_base_path currently points to the source file, change it to its directory
                            dest_base_path = os.path.dirname(dest_base_path)
                            logger.info(f"Adjusted dest_base_path for {source_file} to directory: {dest_base_path}")
                        
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
                        # Register this download's pause_ref so WebSocket notifications can pause it immediately
                        _active_download_pause_refs[download_id] = paused
                        try:
                            success = download_directory_recursive(
                                download_id, system, game_id, base_url, dest_base_path,
                                files_list, bytes_already_transferred, paused
                            )
                        finally:
                            # Clear paused_ref before cleanup to prevent false pause logs from old threads
                            if paused:
                                paused[0] = False
                            # Clean up pause_ref when download finishes (success or failure)
                            if download_id in _active_download_pause_refs:
                                del _active_download_pause_refs[download_id]
                        if success:
                            # Download media files and update gamelist.xml after successful game download
                            media_and_gamelist_success = False
                            try:
                                logger.info(f"Download completed successfully, downloading media files for {game_id}")
                                downloaded_media, game_data = download_game_media(system, game_id, download_id, batocera_system=target_system)
                                
                                # Use game_data returned from download_game_media (avoids duplicate API call)
                                if game_data:
                                    # Update gamelist.xml with game entry
                                    # Use clean_original_path (derived from original path in game_data)
                                    gamelist_success = add_game_to_batocera_api(target_system, clean_original_path, game_data, downloaded_media)
                                    if gamelist_success:
                                        media_and_gamelist_success = True
                                        logger.info(f"Media download and gamelist.xml update completed successfully for {game_id}")
                                    else:
                                        logger.warning(f"Gamelist.xml update failed for {game_id}")
                                else:
                                    logger.warning(f"Could not fetch game details for gamelist.xml update: download {download_id}")
                            except Exception as e:
                                logger.error(f"Error downloading media or updating gamelist.xml (download still successful): {e}", exc_info=True)
                            
                            return True
                        else:
                            # Download failed - check if it was due to pause (might be old state)
                            # Only log error if download_id is still active (not completed)
                            if download_id in _active_download_pause_refs:
                                # Error should have been reported by download_directory_recursive
                                # But if mark_error wasn't called, report it now as a fallback
                                logger.error(f"Download failed for {game_id} (download_id: {download_id})")
                                # Note: mark_error should already be called in download_directory_recursive for size mismatches
                                # But we'll log it here in case it wasn't
                            else:
                                # Download is no longer active - likely already completed or cleaned up
                                logger.debug(f"Download {download_id} already completed/cleaned up, ignoring failure status")
                            return False
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
            elif expected_file_size and existing_size > expected_file_size:
                # File is larger than expected - corrupted, delete it
                logger.error(f"Existing file size mismatch for {dest_path}: {existing_size} bytes, expected {expected_file_size} bytes")
                try:
                    os.remove(dest_path)
                    logger.info(f"Deleted corrupted existing file: {dest_path}")
                    resume_from = 0  # Start fresh
                except Exception as e:
                    logger.error(f"Failed to delete corrupted existing file {dest_path}: {e}")
                    # Report error and return
                    error_msg = f"Existing file size mismatch: {existing_size} != {expected_file_size}"
                    mark_error(download_id, error_msg)
                    if download_id in _active_download_pause_refs:
                        del _active_download_pause_refs[download_id]
                    return False
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
                        # Use clean_original_path (derived from original path in game_data)
                        gamelist_success = add_game_to_batocera_api(target_system, clean_original_path, game_data, downloaded_media)
                        if gamelist_success:
                            media_and_gamelist_success = True
                            logger.info(f"Media download and gamelist.xml update completed successfully for {game_id}")
                        else:
                            logger.warning(f"Gamelist.xml update failed for {game_id}")
                    else:
                        logger.warning(f"Could not fetch game details for gamelist.xml update: download {download_id}")
                except Exception as e:
                    logger.error(f"Error downloading media or updating gamelist.xml (download still successful): {e}", exc_info=True)
                
                
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
        # Register this download's pause_ref so WebSocket notifications can pause it immediately
        _active_download_pause_refs[download_id] = paused
        
        def progress_reporter():
            """Background thread to report progress periodically and check for pause."""
            nonlocal last_report_time, progress_thread_running, total_bytes_transferred
            # Use BANDWIDTH_UPDATE_INTERVAL if set, otherwise fallback to 5 seconds
            interval = BANDWIDTH_UPDATE_INTERVAL if BANDWIDTH_UPDATE_INTERVAL is not None else 5
            while progress_thread_running:
                time.sleep(interval)
                
                # Check if thread should stop (download completed) before doing anything
                if not progress_thread_running:
                    break
                
                elapsed = time.time() - last_report_time
                if elapsed > 0:
                    # Accumulate bytes from this session into total
                    total_bytes_transferred += bytes_transferred_this_session[0]
                    
                    if bytes_transferred_this_session[0] > 0:
                        bytes_per_second = int(bytes_transferred_this_session[0] / elapsed)
                    else:
                        bytes_per_second = 0
                    
                    # Report progress - check return value
                    # Check if thread should stop before attempting to report
                    if not progress_thread_running:
                        break
                    
                    try:
                        progress_result = report_progress(download_id, total_bytes_transferred, bytes_per_second)
                        if progress_result is None:
                            # Download was removed from queue (likely completed) - stop reporting
                            logger.debug(f"Download {download_id} was removed from queue (likely completed), stopping progress reporter")
                            paused[0] = False  # Not paused, just completed
                            progress_thread_running = False
                            break
                        elif progress_result is False:
                            # Download is paused
                            logger.info(f"Download {download_id} is paused - checking status...")
                            paused[0] = True
                            progress_thread_running = False
                            break
                    except requests.exceptions.HTTPError as e:
                        # Handle HTTP errors - check if it's a 410 Gone (download completed/removed)
                        if e.response and e.response.status_code == 410:
                            logger.debug(f"Progress report returned 410 Gone - download {download_id} was removed from queue (likely completed)")
                            paused[0] = False  # Not paused, just completed
                            progress_thread_running = False
                            break
                        # For other HTTP errors, check if thread should still run
                        logger.debug(f"Progress report failed (download may be completed): {e}")
                        if not progress_thread_running:
                            break
                    except Exception as e:
                        # If reporting fails, check if thread should still run
                        logger.debug(f"Progress report failed (download may be completed): {e}")
                        if not progress_thread_running:
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
            
            # Check if file not found (404) or size mismatch (None)
            if success is None:
                # None can mean either 404 or size mismatch
                # Check if file exists to determine which case
                if os.path.exists(dest_path) and expected_file_size:
                    # Size mismatch case - file exists but wrong size
                    final_size = os.path.getsize(dest_path)
                    logger.error(f"File size mismatch: downloaded {final_size} bytes, expected {expected_file_size} bytes")
                    # Delete corrupted file
                    try:
                        os.remove(dest_path)
                        logger.info(f"Deleted corrupted file: {dest_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete corrupted file {dest_path}: {e}")
                    # Report error to backend
                    error_msg = f"File size mismatch: downloaded {final_size} bytes, expected {expected_file_size} bytes"
                    mark_error(download_id, error_msg)
                    progress_thread_running = False
                    progress_thread.join(timeout=1)
                    return False
                else:
                    # 404 case - file not found (or no expected size to verify)
                    logger.error(f"File not found (404) for download {download_id}")
                    logger.info("Backend will handle removal of this download from queue")
                    progress_thread_running = False
                    progress_thread.join(timeout=1)
                    # Clean up pause_ref on 404
                    if download_id in _active_download_pause_refs:
                        del _active_download_pause_refs[download_id]
                    return False
            
            if not success:
                progress_thread_running = False
                progress_thread.join(timeout=1)
                # Only check paused flag if download didn't complete (not if it was removed from queue)
                if paused[0]:
                    logger.info(f"Download {download_id} was paused at {total_bytes_transferred} bytes")
                    if total_bytes_transferred > 0:
                        report_progress(download_id, total_bytes_transferred, 0)
                    # Clean up pause_ref
                    if download_id in _active_download_pause_refs:
                        del _active_download_pause_refs[download_id]
                    return False
                # If paused[0] is False and success is False, it might have been removed from queue
                # Don't report progress if download was removed
                if total_bytes_transferred > 0 and paused[0] is not False:
                    try:
                        report_progress(download_id, total_bytes_transferred, 0)
                    except Exception:
                        pass  # Ignore if download was removed
                # Clean up pause_ref on failure
                if download_id in _active_download_pause_refs:
                    del _active_download_pause_refs[download_id]
                return False
        
        except Exception as e:
            logger.error(f"Error during HTTP download, partial file kept for resume: {e}")
            progress_thread_running = False
            progress_thread.join(timeout=1)
            # Clean up pause_ref on exception
            if download_id in _active_download_pause_refs:
                del _active_download_pause_refs[download_id]
            # Don't report progress on error - the download will be retried or marked as error
            return False
        
        # Stop progress reporter thread immediately before marking as completed
        # This prevents any further progress reports after completion
        progress_thread_running = False
        # Wait for thread to finish (with timeout)
        interval = BANDWIDTH_UPDATE_INTERVAL if BANDWIDTH_UPDATE_INTERVAL is not None else 5
        progress_thread.join(timeout=interval + 1)
        
        # Clear paused flag since download completed successfully
        paused[0] = False
        
        # Verify file size
        if os.path.exists(dest_path) and os.path.isfile(dest_path):
            final_size = os.path.getsize(dest_path)
            if expected_file_size and final_size != expected_file_size:
                logger.error(f"File size mismatch after download: {final_size} != {expected_file_size}")
                # Delete corrupted file
                try:
                    os.remove(dest_path)
                    logger.info(f"Deleted corrupted file: {dest_path}")
                except Exception as e:
                    logger.error(f"Failed to delete corrupted file {dest_path}: {e}")
                
                # Report error to backend
                error_msg = f"File size mismatch: downloaded {final_size} bytes, expected {expected_file_size} bytes"
                mark_error(download_id, error_msg)
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
                    # Use clean_original_path (derived from original path in game_data)
                    gamelist_success = add_game_to_batocera_api(target_system, clean_original_path, game_data, downloaded_media)
                    if gamelist_success:
                        media_and_gamelist_success = True
                        logger.info(f"Media download and gamelist.xml update completed successfully for {game_id}")
                    else:
                        logger.warning(f"Gamelist.xml update failed for {game_id}")
                else:
                    logger.warning(f"Could not fetch game details for gamelist.xml update: download {download_id}")
            except Exception as e:
                logger.error(f"Error downloading media or updating gamelist.xml (download still successful): {e}", exc_info=True)
            
            
            # Clean up pause_ref when download finishes
            if download_id in _active_download_pause_refs:
                del _active_download_pause_refs[download_id]            
            # Clean up pause_ref when download finishes successfully
            if download_id in _active_download_pause_refs:
                del _active_download_pause_refs[download_id]
            return True
        else:
            logger.error(f"Downloaded file not found: {dest_path}")
            # Clean up pause_ref on error
            if download_id in _active_download_pause_refs:
                del _active_download_pause_refs[download_id]
            return False
            
    except Exception as e:
        logger.error(f"Failed to download {game_id}: {e}", exc_info=True)
        # Clean up pause_ref on exception
        if download_id in _active_download_pause_refs:
            del _active_download_pause_refs[download_id]
        return False
    finally:
        # Ensure cleanup even if something goes wrong
        if download_id in _active_download_pause_refs:
            del _active_download_pause_refs[download_id]

def mark_completed(download_id):
    """Mark a download as completed in the queue and send logs."""
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Collect logs for this download if available
        log_content = None
        if download_id in _download_log_handlers:
            log_handler = _download_log_handlers[download_id]
            log_content = log_handler.get_logs()
            # Clean up handler
            log_handler.clear()
            # Remove handler from global dict after collecting logs
            del _download_log_handlers[download_id]
        
        data = {
            'download_id': download_id,
            'client_version': CLIENT_VERSION
        }
        
        if log_content:
            data['log_content'] = log_content
        
        response = http_session.post(
            f"{API_URL}/api/download/complete",
            json=data,
            headers=headers
        )
        response.raise_for_status()
        logger.info(f"Marked download {download_id} as completed")
        return True
    except requests.exceptions.HTTPError as e:
        # If 404, the download was already removed from queue (likely completed by another process or auto-removed)
        # This is acceptable - the download is completed locally
        if e.response and e.response.status_code == 404:
            logger.debug(f"Download {download_id} already removed from queue (likely completed) - this is OK")
            return True  # Treat as success since download is completed locally
        logger.error(f"Failed to mark download as completed: {e}")
        # Clean up handler even if request failed
        if download_id in _download_log_handlers:
            del _download_log_handlers[download_id]
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to mark download as completed: {e}")
        # Clean up handler even if request failed
        if download_id in _download_log_handlers:
            del _download_log_handlers[download_id]
        return False

def mark_error(download_id, error_message):
    """Mark a download as error in the queue and send logs."""
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Collect logs for this download if available
        log_content = None
        if download_id in _download_log_handlers:
            log_handler = _download_log_handlers[download_id]
            log_content = log_handler.get_logs()
            # Clean up handler
            log_handler.clear()
            # Remove handler from global dict after collecting logs
            del _download_log_handlers[download_id]
        
        data = {
            'download_id': download_id,
            'error_message': error_message,
            'client_version': CLIENT_VERSION
        }
        
        if log_content:
            data['log_content'] = log_content
        
        response = http_session.post(
            f"{API_URL}/api/download/error",
            json=data,
            headers=headers
        )
        response.raise_for_status()
        logger.info(f"Marked download {download_id} as error: {error_message}")
        return True
    except requests.exceptions.HTTPError as e:
        # If 404, the download was already removed from queue
        if e.response and e.response.status_code == 404:
            logger.debug(f"Download {download_id} already removed from queue - this is OK")
            return True  # Treat as success since download is already removed
        logger.error(f"Failed to mark download as error: {e}")
        # Clean up handler even if request failed
        if download_id in _download_log_handlers:
            del _download_log_handlers[download_id]
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to mark download as error: {e}")
        # Clean up handler even if request failed
        if download_id in _download_log_handlers:
            del _download_log_handlers[download_id]
        return False

def process_queue():
    """Process downloads from the queue."""
    try:
        logger.info("Processing queue - requesting download from backend")
        # Request download - backend will determine queue type from user's role
        download_info = request_download(queue_type=None)
        logger.info(f"Request completed, download_info: {'received' if download_info else 'None (no downloads available)'}")
        
        if not download_info:
            logger.info("No downloads available, will poll again after interval")
            return

        logger.info(f"Got download: {download_info.get('game_name', 'Unknown')} (ID: {download_info['download_id']})")
        
        if download_game(download_info):
            mark_completed(download_info['download_id'])
        else:
            logger.error(f"Failed to download {download_info.get('game_id', 'Unknown')}")
    except Exception as e:
        logger.error(f"Error in process_queue: {e}", exc_info=True)

async def websocket_client():
    """WebSocket client for receiving download notifications."""
    # Build WebSocket URL
    parsed_url = urlparse(API_URL)
    ws_scheme = "wss" if parsed_url.scheme == "https" else "ws"
    # Use netloc if available (includes host:port), otherwise use path
    ws_host = parsed_url.netloc if parsed_url.netloc else parsed_url.path
    ws_path = "/api/download/ws"
    # Determine platform based on system
    client_platform = 'windows' if platform.system() == 'Windows' else 'linux'
    ws_url = f"{ws_scheme}://{ws_host}{ws_path}?token={API_TOKEN}&version={CLIENT_VERSION}&platform={client_platform}"
    
    logger.info(f"Connecting to WebSocket: {ws_url.replace(API_TOKEN, '***')}")
    
    reconnect_delay = 1  # Start with 1 second
    max_reconnect_delay = 60  # Max 60 seconds
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                logger.info("WebSocket connected successfully")
                reconnect_delay = 1  # Reset delay on successful connection
                
                # Handle messages
                while True:
                    try:
                        # Wait for messages with timeout for ping handling
                        message = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                        
                        try:
                            data = json.loads(message)
                            message_type = data.get("type")
                            
                            if message_type == "connected":
                                logger.info(f"WebSocket connection confirmed: {data.get('message', '')}")
                                token_id = data.get("token_id")
                                if token_id:
                                    logger.info(f"Connected with token_id: {token_id}")
                                
                                # Check if there are downloads available on connection
                                has_downloads = data.get("has_downloads", False)
                                has_user_queue = data.get("has_user_queue", False)
                                has_resumable = data.get("has_resumable", False)
                                
                                if has_downloads:
                                    logger.info(f"Downloads available on connection: user_queue={has_user_queue}, resumable={has_resumable}")
                                    # Trigger download request - use None for queue_type to search all queues
                                    asyncio.create_task(handle_download_notification(None))
                                else:
                                    logger.info("No downloads available on connection")
                            
                            elif message_type == "download_available":
                                queue_type = data.get("queue_type")
                                logger.info(f"Received download notification: queue_type={queue_type}")
                                # Request download in a separate thread to avoid blocking WebSocket
                                asyncio.create_task(handle_download_notification(queue_type))
                            
                            elif message_type == "download_paused":
                                download_id = data.get("download_id")
                                logger.info(f"Received pause notification for download {download_id}")
                                # Immediately set pause flag if this download is active
                                if download_id in _active_download_pause_refs:
                                    paused_ref = _active_download_pause_refs[download_id]
                                    paused_ref[0] = True
                                    logger.info(f"Immediately paused download {download_id} via WebSocket notification")
                                else:
                                    logger.debug(f"Download {download_id} not found in active downloads (may have already stopped)")
                            
                            elif message_type == "ping":
                                # Respond to ping
                                await websocket.send(json.dumps({"type": "pong"}))
                            
                            else:
                                logger.debug(f"Received unknown message type: {message_type}")
                        
                        except json.JSONDecodeError:
                            logger.warning(f"Received non-JSON message: {message[:100]}")
                    
                    except asyncio.TimeoutError:
                        # Send ping to keep connection alive
                        try:
                            await websocket.send(json.dumps({"type": "ping"}))
                        except Exception as e:
                            logger.debug(f"Error sending ping: {e}")
                            break  # Connection may be dead
                
        except websockets.exceptions.InvalidStatusCode as e:
            if e.status_code == 4001:
                logger.critical("=" * 80)
                logger.critical("FATAL ERROR: WebSocket authentication failed (invalid token)")
                logger.critical("=" * 80)
                logger.critical("The download service will now stop.")
                logger.critical("Please verify your API_TOKEN.txt file contains a valid token.")
                logger.critical("=" * 80)
                sys.exit(1)
            elif e.status_code == 4002:
                logger.critical("=" * 80)
                logger.critical("FATAL ERROR: Another download service instance is already connected")
                logger.critical("=" * 80)
                logger.critical("Only one instance can be connected with this token at a time.")
                logger.critical("Please stop the other instance before starting this one.")
                logger.critical("=" * 80)
                sys.exit(1)
            else:
                logger.error(f"WebSocket connection failed with status {e.status_code}")
        except websockets.exceptions.ConnectionClosed as e:
            # Check if connection was closed due to rejection (code 4002)
            if e.code == 4002:
                logger.critical("=" * 80)
                logger.critical("FATAL ERROR: Connection rejected by server")
                logger.critical("=" * 80)
                logger.critical(f"Reason: {e.reason or 'Another instance is already connected'}")
                logger.critical("Only one download service instance can be connected with this token at a time.")
                logger.critical("Please stop the other instance before starting this one.")
                logger.critical("=" * 80)
                sys.exit(1)
            else:
                logger.warning(f"WebSocket connection closed (code: {e.code}, reason: {e.reason})")
        except Exception as e:
            logger.error(f"WebSocket error: {e}", exc_info=True)
        
        # Reconnect with exponential backoff
        logger.info(f"Reconnecting in {reconnect_delay} seconds...")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)


async def handle_download_notification(queue_type):
    """Handle download notification by requesting and processing download."""
    try:
        # Run request_download in thread pool since it uses requests (synchronous)
        loop = asyncio.get_event_loop()
        download_info = await loop.run_in_executor(None, request_download, queue_type)
        
        if download_info:
            logger.info(f"Got download: {download_info.get('game_name', 'Unknown')} (ID: {download_info['download_id']})")
            # Run download_game in thread pool since it's synchronous
            success = await loop.run_in_executor(None, download_game, download_info)
            if success:
                await loop.run_in_executor(None, mark_completed, download_info['download_id'])
            else:
                logger.error(f"Failed to download {download_info.get('game_id', 'Unknown')}")
        else:
            logger.debug("No download available after notification")
    except Exception as e:
        logger.error(f"Error handling download notification: {e}", exc_info=True)


def main():
    """Main function to run the download service."""
    if not API_TOKEN:
        logger.error("API_TOKEN not set in environment variables")
        logger.error("Please set API_TOKEN in your .env file")
        return

    logger.info(f"Starting download service (Service ID: {SERVICE_ID})...")
    ensure_directories()
    
    # Run WebSocket client
    try:
        asyncio.run(websocket_client())
    except KeyboardInterrupt:
        logger.info("Shutting down download service...")
    except Exception as e:
        logger.error(f"Fatal error in download service: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 
