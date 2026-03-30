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
import re
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, time as dt_time
import asyncio
import websockets
from urllib.parse import urlparse, quote
import hashlib
import tarfile
import tempfile
import io
import random
import struct

# Client version
CLIENT_VERSION = "0.9"

# Configure stdout/stderr for Windows to handle non-ASCII characters gracefully
# This prevents encoding errors when third-party libraries (like internetspeedtest) print emojis
if platform.system() == 'Windows':
    class ASCIISafeStream:
        """Wrapper for stdout/stderr that strips non-ASCII characters."""
        def __init__(self, original_stream):
            self.original_stream = original_stream
            # Preserve original encoding attribute if it exists
            if hasattr(original_stream, 'encoding'):
                self.encoding = original_stream.encoding
        
        def write(self, text):
            # Convert to ASCII-safe string before writing
            if isinstance(text, str):
                # Encode to ASCII with 'replace' error handling, then decode back
                # This removes any non-ASCII characters
                ascii_text = text.encode('ascii', 'replace').decode('ascii')
                # Remove the replacement character for cleaner output
                ascii_text = ascii_text.replace('\ufffd', '')
                return self.original_stream.write(ascii_text)
            else:
                # For bytes, pass through (shouldn't happen with TextIOWrapper)
                return self.original_stream.write(text)
        
        def flush(self):
            return self.original_stream.flush()
        
        def __getattr__(self, name):
            # Forward any other attribute access to the original stream
            return getattr(self.original_stream, name)
    
    # Wrap stdout and stderr to sanitize non-ASCII characters
    if not isinstance(sys.stdout, ASCIISafeStream):
        sys.stdout = ASCIISafeStream(sys.stdout)
    if not isinstance(sys.stderr, ASCIISafeStream):
        sys.stderr = ASCIISafeStream(sys.stderr)

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
        log_file_path = os.path.abspath(os.path.join(str(SERVICE_DIR), log_dir, 'rgs_download.log'))
    elif os.getenv('LOG_DIR'):
        log_dir = os.getenv('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(str(SERVICE_DIR), log_dir, 'rgs_download.log'))
    else:
        # Default Windows location
        appdata = os.getenv('APPDATA', os.path.expanduser('~'))
        log_dir = '../../../'
        log_file_path = os.path.abspath(os.path.join(str(SERVICE_DIR), log_dir, 'rgs_download.log'))
else:
    # Linux/Batocera paths
    if os.getenv('LOG_FILE'):
        log_file_path = os.path.abspath(os.getenv('LOG_FILE'))
    elif config.get('LOG_DIR'):
        log_dir = config.get('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(str(SERVICE_DIR), log_dir, 'rgs_download.log'))
    elif os.getenv('LOG_DIR'):
        log_dir = os.getenv('LOG_DIR')
        log_file_path = os.path.abspath(os.path.join(str(SERVICE_DIR), log_dir, 'rgs_download.log'))
    else:
        # Default Linux location...skipping...
        log_file_path = os.path.abspath(os.getenv('LOG_FILE', '/userdata/system/logs/rgs_download.log'))

# Ensure log directory exists
log_dir = os.path.dirname(log_file_path)
os.makedirs(log_dir, exist_ok=True)

# Custom formatter that strips non-ASCII characters for Windows compatibility
class ASCIIFormatter(logging.Formatter):
    """Formatter that converts log messages to ASCII-only for Windows compatibility."""
    def format(self, record):
        # Get the formatted message from parent
        formatted = super().format(record)
        # Remove or replace non-ASCII characters
        # Replace common emojis with ASCII equivalents, then remove any remaining non-ASCII
        ascii_safe = formatted.encode('ascii', 'replace').decode('ascii')
        # Replace replacement character (?) with empty string for cleaner output
        ascii_safe = ascii_safe.replace('\ufffd', '')
        return ascii_safe

# Configure root logger with file handler only (no console output)
logger = logging.getLogger()
logger.setLevel(getattr(logging, log_level, logging.INFO))

# Remove any existing handlers to avoid duplicates
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Add rotating file handler with UTF-8 encoding (fixes Unicode encoding issues on Windows)
# Rotate daily at midnight and keep 7 days of logs
file_handler = TimedRotatingFileHandler(
    log_file_path,
    when='midnight',
    interval=1,
    backupCount=7,
    encoding='utf-8'  # Use UTF-8 encoding to support Unicode characters
)
file_handler.setLevel(getattr(logging, log_level, logging.INFO))
file_handler.setFormatter(ASCIIFormatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(file_handler)

# Rotate log at service start if needed (if log file exists and is from a previous day)
if os.path.exists(log_file_path):
    try:
        # Get the modification time of the current log file
        log_mtime = os.path.getmtime(log_file_path)
        log_mtime_dt = datetime.fromtimestamp(log_mtime)
        
        # Get today's midnight
        today = datetime.now().date()
        today_midnight = datetime.combine(today, dt_time.min)
        
        # If log file was last modified before today's midnight, rotate it
        if log_mtime_dt < today_midnight:
            file_handler.doRollover()
    except Exception as e:
        # If rotation check fails, log to stderr since logger might not be ready
        print(f"Warning: Failed to check/rotate log file at startup: {e}", file=sys.stderr)

# Get logger for this module
logger = logging.getLogger(__name__)
logger.info(f"Logging initialized. Log file: {log_file_path}")
if config_ini_path.exists():
    logger.info(f"Configuration loaded from: {config_ini_path}")

# Custom handler for capturing startup logs
class StartupLogHandler(logging.Handler):
    """Custom logging handler that captures startup logs until WebSocket connection."""
    def __init__(self):
        super().__init__()
        self.logs = []
        self.setLevel(logging.DEBUG)
        self.setFormatter(ASCIIFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self.capturing = True  # Stop capturing after logs are sent
    
    def emit(self, record):
        """Capture log record."""
        if self.capturing:
            try:
                msg = self.format(record)
                self.logs.append(msg)
            except Exception:
                self.handleError(record)
    
    def get_logs(self):
        """Get all captured logs as a string."""
        return '\n'.join(self.logs)
    
    def stop_capturing(self):
        """Stop capturing new logs."""
        self.capturing = False
    
    def clear(self):
        """Clear captured logs."""
        self.logs = []

# Custom handler for capturing download task logs
class DownloadLogHandler(logging.Handler):
    """Custom logging handler that captures logs for a specific download."""
    def __init__(self, download_id):
        super().__init__()
        self.download_id = download_id
        self.logs = []
        self.setLevel(logging.DEBUG)
        self.setFormatter(ASCIIFormatter(
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

# Global startup log handler
_startup_log_handler = StartupLogHandler()
logger.addHandler(_startup_log_handler)

# Global dictionary to store download log handlers
_download_log_handlers = {}

# Global dictionary to track paused downloads (download_id -> paused_ref)
# This allows WebSocket notifications to immediately pause downloads
_active_download_pause_refs = {}
_active_websocket = None  # Global reference to active WebSocket connection
_websocket_lock = threading.Lock()  # Lock for thread-safe access
_websocket_event_loop = None  # Event loop for WebSocket operations
_websocket_recv_lock = None  # Async lock for coordinating message reception (initialized in websocket_client)
_archive_download_active = False  # Flag to indicate if archive download is in progress

# Global UPnP connection info (set during setup, used for each WebSocket connection)
_p2p_connection_info = {
    "external_ip": None,
    "external_port": None,
    "internal_port": None,
    "upnp_enabled": False
}

async def download_directory_via_websocket_async(
    download_id, remaining_files_list, dest_base_path, system, 
    files_list, bytes_already_transferred, paused_ref, download_info
):
    """Async function to download directory via WebSocket.
    
    This function handles the WebSocket communication and delegates to
    a helper that processes binary data.
    
    Retries once for files with size mismatches.
    """
    import json
    
    with _websocket_lock:
        websocket = _active_websocket
    
    if not websocket:
        logger.warning("WebSocket not available, cannot use WebSocket for archive download")
        return False
    
    try:
        max_attempts = 2  # Original attempt + 1 retry
        attempt = 0
        files_to_download = remaining_files_list
        all_failed_files = []  # Track all files that failed across attempts
        current_files_list = files_list  # Files to process (may be filtered on retry)
        
        while attempt < max_attempts:
            attempt += 1
            if attempt > 1:
                logger.info(f"Retrying WebSocket archive download for {len(files_to_download)} file(s) (attempt {attempt}/{max_attempts})")
                # Filter files_list to only include files we're retrying (for path resolution)
                retry_files_set = set(files_to_download)
                current_files_list = [f for f in files_list if f['relative_path'] in retry_files_set]
            
            # Set flag to indicate archive download is active (prevents websocket_client from receiving)
            global _archive_download_active
            _archive_download_active = True
            
            try:
                # Send request via WebSocket
                request_msg = {
                    "type": "request_archive",
                    "download_id": download_id,
                    "files": files_to_download if files_to_download else None  # None means all files
                }
                await websocket.send(json.dumps(request_msg))
                logger.info(f"Sent archive request via WebSocket for download_id={download_id}, files={len(files_to_download) if files_to_download else 'all'}")
                
                # Now wait for archive_start, then receive binary data, then archive_complete/error
                # We'll parse the binary stream similar to HTTP version
                success, failed_files = await process_websocket_archive_stream(
                    download_id, websocket, dest_base_path, system, 
                    current_files_list, bytes_already_transferred, paused_ref
                )
            finally:
                # Always clear the flag when done
                _archive_download_active = False
            
            # Filter failed files to only those with size mismatches for retry
            size_mismatch_files = [path for path, error in failed_files if 'Size mismatch' in error or 'size mismatch' in error.lower()]
            other_errors = [(path, error) for path, error in failed_files if 'Size mismatch' not in error and 'size mismatch' not in error.lower()]
            
            # Add other errors to all_failed_files (these won't be retried)
            all_failed_files.extend(other_errors)
            
            if success:
                # Success - if we had retries, some files succeeded on retry
                if all_failed_files:
                    logger.warning(f"WebSocket download completed with {len(all_failed_files)} non-retryable error(s): {all_failed_files}")
                    return False
                return True
            elif size_mismatch_files and attempt < max_attempts:
                # Retry files with size mismatches
                logger.info(f"Retrying {len(size_mismatch_files)} file(s) with size mismatches: {size_mismatch_files}")
                files_to_download = size_mismatch_files
                # Continue to retry loop
            else:
                # No more retries or no size mismatch files to retry
                if size_mismatch_files:
                    all_failed_files.extend([(path, error) for path, error in failed_files if path in size_mismatch_files])
                break
        
        # All attempts exhausted - report all failures
        if all_failed_files:
            error_details = "; ".join([f"{path}: {error}" for path, error in all_failed_files])
            logger.error(f"WebSocket download completed with errors after {max_attempts} attempts: {error_details}")
        return False
        
    except Exception as e:
        logger.error(f"Error in WebSocket archive download: {e}", exc_info=True)
        return False

async def process_websocket_archive_stream(
    download_id, websocket, dest_base_path, system, 
    files_list, bytes_already_transferred, paused_ref
):
    """Process WebSocket archive stream with detailed logging."""
    import time as time_module
    stream_start_time = time_module.time()
    last_status_log_time = stream_start_time
    status_log_interval = 30.0  # Log status every 30 seconds
    import shutil
    import threading
    
    # Get the async receive lock to coordinate with websocket_client
    with _websocket_lock:
        recv_lock = _websocket_recv_lock
    
    if not recv_lock:
        logger.error("WebSocket receive lock not available")
        return False, [("unknown", "WebSocket receive lock not available")]
    
    # Wait for archive_start message (acquire lock to prevent websocket_client from receiving)
    try:
        async with recv_lock:
            start_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        if isinstance(start_message, str):
            start_data = json.loads(start_message)
            if start_data.get("type") != "archive_start":
                logger.error(f"Unexpected message type: {start_data.get('type')}")
                return False, [("unknown", f"Unexpected message type: {start_data.get('type')}")]
        else:
            # Binary data received before archive_start - might be valid, continue
            pass
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for archive_start message")
        return False, [("unknown", "Timeout waiting for archive_start message")]
    
    # Similar parsing logic to HTTP version but using async WebSocket receive
    total_bytes_downloaded = bytes_already_transferred
    bytes_transferred_this_session = [0]
    start_time = time.time()
    last_report_time = start_time
    files_with_errors = []
    extracted_files = set()
    
    # Add progress reporting thread (more frequent than HTTP version)
    progress_thread_running = True
    
    def progress_reporter():
        """Background thread to report progress periodically.
        
        Reports more frequently for WebSocket (every 1-2 seconds) to match HTTP stream responsiveness.
        """
        nonlocal last_report_time, progress_thread_running, total_bytes_downloaded
        # Use shorter interval for WebSocket (1-2 seconds) for more frequent updates
        # Still respect BANDWIDTH_UPDATE_INTERVAL if it's set to a shorter value
        if BANDWIDTH_UPDATE_INTERVAL is not None:
            interval = min(BANDWIDTH_UPDATE_INTERVAL, 2)  # Use BANDWIDTH_UPDATE_INTERVAL if <= 2, otherwise cap at 2
        else:
            interval = 2  # Default to 2 seconds for WebSocket (more frequent than HTTP's 5 seconds)
        
        while progress_thread_running:
            time.sleep(interval)
            elapsed = time.time() - last_report_time
            if elapsed > 0:
                total_bytes_downloaded += bytes_transferred_this_session[0]
                bytes_per_second = int(bytes_transferred_this_session[0] / elapsed) if bytes_transferred_this_session[0] > 0 else 0
                
                if not progress_thread_running:
                    break
                
                try:
                    progress_result = report_progress(download_id, total_bytes_downloaded, bytes_per_second)
                    if progress_result is None:
                        logger.debug(f"Download {download_id} was removed from queue")
                        paused_ref[0] = False
                        progress_thread_running = False
                        break
                    elif progress_result is False:
                        logger.info(f"Download {download_id} is paused")
                        paused_ref[0] = True
                        progress_thread_running = False
                        break
                except requests.exceptions.HTTPError as e:
                    if e.response and e.response.status_code == 410:
                        logger.debug(f"Progress report returned 410 Gone - download {download_id} removed")
                        paused_ref[0] = False
                        progress_thread_running = False
                        break
                    if not progress_thread_running:
                        break
                except Exception as e:
                    logger.debug(f"Progress report failed: {e}")
                    if not progress_thread_running:
                        break
                
                last_report_time = time.time()
                bytes_transferred_this_session[0] = 0
    
    progress_thread = threading.Thread(target=progress_reporter, daemon=True)
    progress_thread.start()
    
    # Buffer for parsing binary format
    buffer = b''
    current_file_info = None
    current_file_relative_path = None
    current_file_size = None
    current_file_bytes_remaining = None
    current_dest_file = None
    current_file_skip = False
    
    # If we received binary data in start_message, add it to buffer
    if isinstance(start_message, bytes):
        buffer = start_message
        bytes_transferred_this_session[0] += len(start_message)
    
    # Create a mapping of relative_path to file_info for quick lookup
    files_dict = {f['relative_path']: f for f in files_list}
    remaining_files_set = set(f['relative_path'] for f in files_list)
    
    try:
        # Receive binary chunks from WebSocket
        while True:
            # Periodic status logging
            current_time = time_module.time()
            if current_time - last_status_log_time >= status_log_interval:
                elapsed = current_time - stream_start_time
                # Calculate file progress info
                file_remaining_str = 'N/A'
                file_progress_str = ''
                if current_file_info:
                    if current_file_bytes_remaining is not None:
                        # Validate that remaining doesn't exceed file size
                        if current_file_bytes_remaining > current_file_size:
                            logger.warning(f"WebSocket: Invalid file_remaining ({current_file_bytes_remaining}) > file_size ({current_file_size}) for {current_file_relative_path}")
                            file_remaining_str = f"{current_file_bytes_remaining} (INVALID)"
                        else:
                            file_remaining_str = str(current_file_bytes_remaining)
                            bytes_written = current_file_size - current_file_bytes_remaining
                            progress_pct = (bytes_written / current_file_size * 100) if current_file_size > 0 else 0
                            file_progress_str = f", file_progress={bytes_written}/{current_file_size} ({progress_pct:.1f}%)"
                    else:
                        file_remaining_str = 'None'
                
                logger.info(f"WebSocket stream status (download_id={download_id}, elapsed={elapsed:.1f}s): "
                          f"total_received={bytes_transferred_this_session[0]}, "
                          f"buffer_size={len(buffer)}, "
                          f"current_file={current_file_relative_path if current_file_info else 'None'}, "
                          f"file_bytes_remaining={file_remaining_str}{file_progress_str}, "
                          f"files_completed={len(extracted_files)}")
                last_status_log_time = current_time
            
            # Check for pause
            if paused_ref and paused_ref[0]:
                logger.info(f"Download {download_id} was paused during WebSocket streaming")
                if current_dest_file:
                    current_dest_file.close()
                progress_thread_running = False
                progress_thread.join(timeout=10)
                return False, [("unknown", "Download paused")]
            
            # Wait for next message (with timeout to check for pause)
            # Use the receive lock to coordinate with websocket_client
            try:
                async with recv_lock:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                logger.debug(f"WebSocket: Received message, type: {type(message).__name__}, size: {len(message) if isinstance(message, bytes) else 'N/A'}")
            except asyncio.TimeoutError:
                # Timeout - check pause and continue
                if current_file_info:
                    logger.debug(f"WebSocket: Receive timeout, current file: {current_file_relative_path}, remaining: {current_file_bytes_remaining}, buffer: {len(buffer)}")
                continue
            except Exception as e:
                logger.error(f"WebSocket: Error receiving message: {e}", exc_info=True)
                raise
            
            # Check if it's a control message (JSON) or binary data
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "archive_complete":
                        # Stream complete
                        break
                    elif msg_type == "archive_error":
                        error = data.get("error", "Unknown error")
                        logger.error(f"Archive error from server: {error}")
                        progress_thread_running = False
                        progress_thread.join(timeout=10)
                        return False, [("unknown", f"Server error: {error}")]
                    elif msg_type == "ping":
                        # Respond to ping to keep connection alive
                        try:
                            await websocket.send(json.dumps({"type": "pong"}))
                        except Exception as e:
                            logger.debug(f"Failed to send pong response: {e}")
                        continue
                    elif msg_type == "pong":
                        # Server responded to our ping, continue
                        continue
                    # Other JSON messages can be ignored
                    continue
                except json.JSONDecodeError:
                    # Not JSON, treat as binary (shouldn't happen but handle gracefully)
                    pass
            
            # Binary message - add to buffer
            if isinstance(message, bytes):
                chunk_size = len(message)
                bytes_transferred_this_session[0] += chunk_size
                buffer += message
                logger.debug(f"WebSocket: Received {chunk_size} bytes, buffer size now: {len(buffer)}, total received this session: {bytes_transferred_this_session[0]}")
                
                # Parse buffer (same logic as HTTP version)
                parse_iterations = 0
                max_parse_iterations = 1000  # Prevent infinite loops
                while True:
                    parse_iterations += 1
                    if parse_iterations > max_parse_iterations:
                        logger.error(f"WebSocket: Parse loop exceeded {max_parse_iterations} iterations, buffer size: {len(buffer)}, current_file: {current_file_relative_path if current_file_info else 'None'}")
                        break
                    
                    if current_file_info is None:
                        # Waiting for file header
                        if len(buffer) < 4:
                            logger.debug(f"WebSocket: Not enough data for header (need 4 bytes, have {len(buffer)})")
                            break  # Not enough data
                        
                        path_length = struct.unpack('>I', buffer[:4])[0]
                        logger.debug(f"WebSocket: Parsing file header, path_length={path_length}, buffer_size={len(buffer)}")
                        
                        # Check for end marker
                        if path_length == 0:
                            logger.info("WebSocket: Received end marker, stream complete")
                            buffer = buffer[4:]
                            break  # End of stream
                        
                        # Need full header
                        header_size_needed = 4 + path_length + 8
                        if len(buffer) < header_size_needed:
                            logger.debug(f"WebSocket: Waiting for full header, have {len(buffer)} bytes, need {header_size_needed} bytes (path_length={path_length})")
                            break
                        
                        # Extract path and file_size
                        path_bytes = buffer[4:4+path_length]
                        relative_path = path_bytes.decode('utf-8')
                        file_size = struct.unpack('>Q', buffer[4+path_length:4+path_length+8])[0]
                        
                        # Consume header
                        buffer = buffer[4+path_length+8:]
                        
                        # Find file info
                        file_info = files_dict.get(relative_path)
                        if not file_info:
                            logger.warning(f"Unexpected file in stream: {relative_path}, skipping {file_size} bytes")
                            current_file_info = None
                            current_file_relative_path = relative_path
                            current_file_size = file_size
                            current_file_bytes_remaining = file_size
                            current_file_skip = True
                            continue
                        
                        # Determine destination path
                        if 'destination_rom_path' in file_info:
                            dest_rom_path = file_info['destination_rom_path']
                            dest_system = file_info.get('destination_system', system)
                            dest_file_path = os.path.join(ROMS_PATH, dest_system, dest_rom_path)
                        else:
                            dest_file_path = os.path.join(dest_base_path, relative_path)
                        
                        # Create directory and open file
                        dest_file_dir = os.path.dirname(dest_file_path)
                        os.makedirs(dest_file_dir, exist_ok=True)
                        
                        try:
                            current_file_info = file_info
                            current_file_relative_path = relative_path
                            current_file_size = file_size
                            current_file_bytes_remaining = file_size
                            current_file_skip = False
                            current_dest_file = open(dest_file_path, 'wb')
                            # Removed info log - only log failures
                        except Exception as e:
                            logger.error(f"Failed to open file {relative_path}: {e}")
                            files_with_errors.append((relative_path, f"File open error: {e}"))
                            current_file_info = None
                            current_file_relative_path = relative_path
                            current_file_size = file_size
                            current_file_bytes_remaining = file_size
                            current_file_skip = True
                            current_dest_file = None
                    
                    # Write file data
                    if current_file_info is not None:
                        # We have a current file - check if it's complete first
                        if current_file_bytes_remaining == 0:
                            # File is complete, handle completion
                            logger.info(f"WebSocket: File complete: {current_file_relative_path} ({current_file_size} bytes)")
                            if current_dest_file:
                                try:
                                    current_dest_file.close()
                                    logger.debug(f"WebSocket: Closed file: {current_file_relative_path}")
                                except Exception as e:
                                    logger.error(f"WebSocket: Error closing file {current_file_relative_path}: {e}")
                                current_dest_file = None
                            
                            if not current_file_skip and current_file_info:
                                # Verify file size
                                if 'destination_rom_path' in current_file_info:
                                    dest_file_path = os.path.join(ROMS_PATH, current_file_info.get('destination_system', system), current_file_info['destination_rom_path'])
                                else:
                                    dest_file_path = os.path.join(dest_base_path, current_file_relative_path)
                                
                                if os.path.exists(dest_file_path):
                                    actual_size = os.path.getsize(dest_file_path)
                                    expected_size = int(current_file_info['size'])
                                    if actual_size == expected_size:
                                        extracted_files.add(current_file_relative_path)
                                        # Removed info log - only log failures
                                    else:
                                        logger.error(f"Failed file {current_file_relative_path}: Size mismatch (local={actual_size}, expected={expected_size})")
                                        files_with_errors.append((current_file_relative_path, f"Size mismatch: {actual_size} != {expected_size}"))
                                        try:
                                            os.remove(dest_file_path)
                                        except:
                                            pass
                                else:
                                    logger.error(f"Failed file {current_file_relative_path}: File not created")
                                    files_with_errors.append((current_file_relative_path, "File not created"))
                            
                            # Reset for next file
                            current_file_info = None
                            current_file_relative_path = None
                            current_file_size = None
                            current_file_bytes_remaining = None
                            current_file_skip = False
                            logger.debug(f"WebSocket: Reset for next file, remaining buffer: {len(buffer)} bytes")
                            # Continue parsing to look for next file header in buffer
                            continue
                        
                        # File is not complete, write data
                        if current_file_bytes_remaining is not None and current_file_bytes_remaining > 0:
                            bytes_to_write = min(len(buffer), current_file_bytes_remaining)
                            if bytes_to_write > 0:
                                if current_file_skip:
                                    logger.debug(f"WebSocket: Skipping {bytes_to_write} bytes for {current_file_relative_path} (remaining: {current_file_bytes_remaining})")
                                    buffer = buffer[bytes_to_write:]
                                    current_file_bytes_remaining -= bytes_to_write
                                else:
                                    if current_dest_file:
                                        try:
                                            current_dest_file.write(buffer[:bytes_to_write])
                                            logger.debug(f"WebSocket: Wrote {bytes_to_write} bytes to {current_file_relative_path} (remaining: {current_file_bytes_remaining - bytes_to_write}/{current_file_size})")
                                            buffer = buffer[bytes_to_write:]
                                            current_file_bytes_remaining -= bytes_to_write
                                        except Exception as e:
                                            logger.error(f"WebSocket: Error writing to file {current_file_relative_path}: {e}", exc_info=True)
                                            files_with_errors.append((current_file_relative_path, f"Write error: {e}"))
                                            # Close file and mark for skip
                                            try:
                                                current_dest_file.close()
                                            except:
                                                pass
                                            current_dest_file = None
                                            current_file_skip = True
                                            buffer = buffer[bytes_to_write:]
                                            current_file_bytes_remaining -= bytes_to_write
                                    else:
                                        logger.warning(f"WebSocket: No file handle for {current_file_relative_path}, skipping {bytes_to_write} bytes")
                                        buffer = buffer[bytes_to_write:]
                                        current_file_bytes_remaining -= bytes_to_write
                                
                                # Check if file is now complete after writing
                                if current_file_bytes_remaining == 0:
                                    # File is complete, handle completion (will be handled in next iteration)
                                    continue
                            else:
                                # No more data to write for current file, wait for more buffer
                                logger.debug(f"WebSocket: No more data to write, buffer exhausted. File: {current_file_relative_path if current_file_info else 'None'}, remaining: {current_file_bytes_remaining if current_file_info else 'N/A'}, buffer: {len(buffer)}")
                                break
                        else:
                            # Invalid state - file info exists but bytes_remaining is None or <= 0
                            logger.warning(f"WebSocket: Invalid state - file_info exists but bytes_remaining is {current_file_bytes_remaining}")
                            break
                    else:
                        # No current file, waiting for header - this should be handled at the top of the loop
                        # But if we reach here, it means we've already tried to parse and didn't find a header
                        logger.debug(f"WebSocket: No current file, waiting for header. Buffer: {len(buffer)} bytes")
                        break
        
        # Cleanup
        if current_dest_file:
            current_dest_file.close()
        
        # Stop progress reporter
        progress_thread_running = False
        progress_thread.join(timeout=10)
        
        # Final progress report
        if total_bytes_downloaded > 0:
            try:
                final_bytes_per_second = int(total_bytes_downloaded / (time.time() - start_time)) if (time.time() - start_time) > 0 else 0
                report_progress(download_id, total_bytes_downloaded, final_bytes_per_second)
            except Exception as e:
                logger.debug(f"Final progress report failed: {e}")
        
        # Verify all files were extracted
        if len(extracted_files) != len(remaining_files_set):
            missing = remaining_files_set - extracted_files
            for missing_file in missing:
                # Only add if not already in files_with_errors
                if not any(path == missing_file for path, _ in files_with_errors):
                    logger.error(f"Failed file {missing_file}: Not extracted from stream")
                    files_with_errors.append((missing_file, "Not extracted from stream"))
        
        # Log failed files only (one per line for clarity)
        if files_with_errors:
            logger.error(f"WebSocket download completed with {len(files_with_errors)} failed file(s):")
            for path, error in files_with_errors:
                logger.error(f"  - {path}: {error}")
            # Return False with list of failed files for retry logic
            return False, files_with_errors
        
        logger.info(f"Successfully downloaded and extracted {len(extracted_files)} files via WebSocket")
        return True, []
        
    except Exception as e:
        logger.error(f"Error in WebSocket archive stream processing: {e}", exc_info=True)
        progress_thread_running = False
        progress_thread.join(timeout=10)
        if current_dest_file:
            current_dest_file.close()
        # Return False with error info
        error_info = [("unknown", f"Stream processing error: {str(e)}")]
        return False, error_info
    finally:
        # Ensure progress thread is stopped
        progress_thread_running = False
        progress_thread.join(timeout=10)

# Configuration - read from config.ini first, then environment variables, then defaults
# Priority: config.ini > environment variable > default

API_URL = config.get('API_URL') or os.getenv('API_URL', 'https://rgs-retro.ddns.net')

def verify_p2p_download_id(download_id, system, rom_path):
    """Verify download_id exists in Redis via backend API.
    
    Returns True if download_id is valid and matches system/rom_path, False otherwise.
    """
    try:
        verify_url = f"{API_URL}/api/download/verify-p2p-download"
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        data = {
            'download_id': download_id,
            'system': system,
            'rom_path': rom_path
        }
        
        # Use short timeout for verification (2 seconds)
        response = http_session.post(verify_url, json=data, headers=headers, timeout=2)
        if response.status_code == 200:
            result = response.json()
            return result.get('valid', False)
        else:
            logger.debug(f"Download verification returned status {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        logger.warning(f"Download verification timeout for download_id {download_id}")
        # On timeout, allow the request (fail open for availability)
        return True
    except Exception as e:
        logger.warning(f"Error verifying download_id {download_id}: {e}")
        # On error, allow the request (fail open for availability)
        return True

# Set ROMS_PATH based on platform
if platform.system() == 'Windows':
    DEFAULT_ROMS_PATH = '../../../roms'
    DEFAULT_SAVEDIR = '../../../saves'
    DEFAULT_CONFIGDIR = '../../../configs'
else:
    DEFAULT_ROMS_PATH = '/userdata/roms'
    DEFAULT_SAVEDIR = '/userdata/saves'
    DEFAULT_CONFIGDIR = '/userdata/system/configs'

ROMS_PATH = config.get('ROMS_PATH') or os.getenv('ROMS_PATH', DEFAULT_ROMS_PATH)
if ROMS_PATH and not os.path.isabs(ROMS_PATH):
    ROMS_PATH = os.path.abspath(os.path.join(str(SERVICE_DIR), ROMS_PATH))

SAVEDIR = config.get('SAVEDIR') or os.getenv('SAVEDIR', DEFAULT_SAVEDIR)
if SAVEDIR and not os.path.isabs(SAVEDIR):
    SAVEDIR = os.path.abspath(os.path.join(str(SERVICE_DIR), SAVEDIR))

CONFIGDIR = config.get('CONFIGDIR') or os.getenv('CONFIGDIR', DEFAULT_CONFIGDIR) if DEFAULT_CONFIGDIR else None
if CONFIGDIR and not os.path.isabs(CONFIGDIR):
    CONFIGDIR = os.path.abspath(os.path.join(str(SERVICE_DIR), CONFIGDIR))

# BANDWIDTH_UPDATE_INTERVAL will be fetched from backend on first request_download call
# No fallback - must be set by backend
BANDWIDTH_UPDATE_INTERVAL = None
SERVICE_ID = config.get('SERVICE_ID') or os.getenv('SERVICE_ID', socket.gethostname())

# P2P server configuration
P2P_PORT = int(config.get('P2P_PORT') or os.getenv('P2P_PORT', '8765'))

# Read API_TOKEN from environment variable or API_TOKEN.txt file
# Priority: Environment Variable > File
API_TOKEN = os.getenv('API_TOKEN')
api_token_path = SERVICE_DIR / 'API_TOKEN.txt'

if API_TOKEN:
    logger.info(f"API_TOKEN loaded from environment variable (length: {len(API_TOKEN)} characters)")
elif api_token_path.exists():
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

# Import P2P client module (after logger is initialized)
try:
    from p2p_client import get_p2p_server, stop_p2p_server
    P2P_CLIENT_AVAILABLE = True
except ImportError as e:
    P2P_CLIENT_AVAILABLE = False
    logger.warning(f"P2P client module not available: {e}")

# Import UPnP helper module (after logger is initialized)
try:
    from upnp_helper import get_upnp_helper, UPnPHelper
    # Ensure upnp_helper logger also uses StartupLogHandler to capture its logs
    upnp_logger = logging.getLogger('upnp_helper')
    if _startup_log_handler not in upnp_logger.handlers:
        upnp_logger.addHandler(_startup_log_handler)
    upnp_logger.propagate = True
    UPNP_HELPER_AVAILABLE = True
except ImportError as e:
    UPNP_HELPER_AVAILABLE = False
    logger.warning(f"UPnP helper module not available: {e}")

# Log configuration on startup
logger.info(f"Download service configuration:")
logger.info(f"  API_URL: {API_URL}")
logger.info(f"  ROMS_PATH: {ROMS_PATH}")
logger.info(f"  SAVEDIR: {SAVEDIR}")
if CONFIGDIR:
    logger.info(f"  CONFIGDIR: {CONFIGDIR}")
logger.info(f"  SERVICE_ID: {SERVICE_ID}")
logger.info(f"  P2P_PORT: {P2P_PORT}")
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
    for name, dirpath in [("ROMs", ROMS_PATH), ("Saves", SAVEDIR)] + ([("Config", CONFIGDIR)] if CONFIGDIR else []):
        try:
            Path(dirpath).mkdir(parents=True, exist_ok=True)
            logger.info(f"{name} directory ensured: {dirpath}")
        except OSError as e:
            # On Windows services running as SYSTEM, drives may not be
            # accessible (WinError 1326) when stat() is called internally
            # by exist_ok. Try without exist_ok to avoid the stat() call.
            try:
                Path(dirpath).mkdir(parents=True, exist_ok=False)
                logger.info(f"{name} directory created: {dirpath}")
            except FileExistsError:
                logger.info(f"{name} directory already exists: {dirpath}")
            except OSError:
                logger.warning(f"Cannot verify or create {name} directory: {dirpath} ({e}). Assuming it exists.")

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

def extract_rom_paths_from_gamelist(gamelist_path):
    """Extract ROM paths from all games in gamelist.xml.
    
    Args:
        gamelist_path: Path to the gamelist.xml file
        
    Returns:
        List of ROM paths (strings), or empty list if error
    """
    try:
        # Parse the original gamelist.xml
        tree = ET.parse(gamelist_path)
        root = tree.getroot()
        
        # Find all game elements
        games = root.findall('game')
        
        # Extract path from all games (not just those with playcount > 0)
        rom_paths = []
        for game in games:
            path_elem = game.find('path')
            if path_elem is not None and path_elem.text:
                # Get path text, removing leading ./
                path = path_elem.text.lstrip('./')
                if path:
                    rom_paths.append(path)
        
        return rom_paths
        
    except Exception as e:
        logger.error(f"Error extracting ROM paths from {gamelist_path}: {e}")
        return []

def filter_gamelist_for_upload(gamelist_path):
    """Parse gamelist.xml and filter games with playcount > 0, keeping only specific fields.
    
    Args:
        gamelist_path: Path to the gamelist.xml file
        
    Returns:
        BytesIO object containing filtered XML, or None if no games match
    """
    try:
        # Parse the original gamelist.xml
        tree = ET.parse(gamelist_path)
        root = tree.getroot()
        
        # Find all game elements
        games = root.findall('game')
        
        # Filter games: only those with playcount > 0
        filtered_games = []
        fields_to_keep = ['path', 'playcount', 'gametime', 'lastplayed']
        
        for game in games:
            # Check if playcount exists and is > 0
            playcount_elem = game.find('playcount')
            if playcount_elem is not None and playcount_elem.text:
                try:
                    playcount_value = int(playcount_elem.text)
                    if playcount_value > 0:
                        # Create a new game element with only the fields we want
                        new_game = ET.Element('game')
                        for field in fields_to_keep:
                            field_elem = game.find(field)
                            if field_elem is not None:
                                # Copy the field element
                                new_field = ET.SubElement(new_game, field)
                                new_field.text = field_elem.text
                                # Copy attributes if any (like <path> might have special characters)
                                if field_elem.attrib:
                                    new_field.attrib.update(field_elem.attrib)
                        filtered_games.append(new_game)
                except (ValueError, TypeError):
                    # Invalid playcount value, skip this game
                    continue
        
        # If no games match, return None
        if not filtered_games:
            return None
        
        # Create new XML structure
        new_root = ET.Element('gameList')
        for game in filtered_games:
            new_root.append(game)
        
        # Convert to XML string
        xml_str = ET.tostring(new_root, encoding='utf-8', xml_declaration=True)
        
        # Return as BytesIO
        return io.BytesIO(xml_str)
        
    except Exception as e:
        logger.error(f"Error filtering gamelist.xml from {gamelist_path}: {e}")
        return None

def upload_p2p_inventory():
    """Extract ROM paths from all gamelist.xml files and upload inventory to server.
    
    Scans ROMS_PATH for all gamelist.xml files, extracts ROM paths from ALL games
    (not just those with playcount > 0), builds JSON structure, gzip compresses it,
    and uploads to the P2P inventory endpoint.
    """
    try:
        if not ROMS_PATH or not os.path.exists(ROMS_PATH):
            logger.warning(f"ROMS_PATH does not exist: {ROMS_PATH}, skipping P2P inventory upload")
            return
        
        logger.info(f"Extracting ROM paths for P2P inventory from {ROMS_PATH}")
        
        # Build inventory: {system: [path1, path2, ...], system2: [path1, path2, ...], ...}
        inventory = {}
        total_paths = 0
        
        # Scan all system directories in ROMS_PATH
        for system_dir in os.listdir(ROMS_PATH):
            system_path = os.path.join(ROMS_PATH, system_dir)
            
            # Skip if not a directory
            if not os.path.isdir(system_path):
                continue
            
            # Check for gamelist.xml in this system directory
            gamelist_path = os.path.join(system_path, 'gamelist.xml')
            
            if os.path.exists(gamelist_path) and os.path.isfile(gamelist_path):
                try:
                    # Extract ROM paths from all games (not just those with playcount > 0)
                    rom_paths = extract_rom_paths_from_gamelist(gamelist_path)
                    if rom_paths:
                        inventory[system_dir] = rom_paths
                        total_paths += len(rom_paths)
                        logger.debug(f"Extracted {len(rom_paths)} ROM paths from system '{system_dir}'")
                except Exception as e:
                    logger.error(f"Error extracting ROM paths from {gamelist_path}: {e}")
        
        if not inventory:
            logger.info("No ROM paths found in any gamelist.xml files, skipping P2P inventory upload")
            return
        
        # Convert inventory to JSON
        json_data = json.dumps(inventory)
        json_bytes = json_data.encode('utf-8')
        
        # Gzip compress
        import gzip
        gzip_data = gzip.compress(json_bytes)
        
        logger.info(f"Prepared P2P inventory: {len(inventory)} systems, {total_paths} ROM paths, {len(gzip_data)} bytes compressed (from {len(json_bytes)} bytes)")
        
        # Upload to server
        try:
            url = f"{API_URL}/api/download/p2p/inventory"
            headers = {
                'Authorization': f'Bearer {API_TOKEN}',
                'Content-Type': 'application/json',
                'Content-Encoding': 'gzip'
            }
            
            response = http_session.post(
                url,
                data=gzip_data,
                headers=headers,
                timeout=120  # Increased timeout for larger files
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                logger.info(f"Successfully uploaded P2P inventory ({result.get('systems_count', 0)} systems, {result.get('total_paths', 0)} ROM paths)")
            else:
                logger.warning(f"Failed to upload P2P inventory: {result.get('message', 'Unknown error')}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error uploading P2P inventory: {e}")
        except Exception as e:
            logger.error(f"Unexpected error uploading P2P inventory: {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"Error preparing P2P inventory: {e}", exc_info=True)

def send_startup_logs(token_id):
    """Send startup logs to the backend for storage with gzip compression.
    
    Args:
        token_id: The token ID received from WebSocket connection
    """
    try:
        import gzip
        import base64
        
        # Get startup logs
        startup_logs = _startup_log_handler.get_logs()
        
        if not startup_logs:
            logger.debug("No startup logs to send")
            return
        
        # Stop capturing new logs after sending
        _startup_log_handler.stop_capturing()
        
        # Compress logs with gzip
        log_bytes = startup_logs.encode('utf-8')
        gzip_data = gzip.compress(log_bytes)
        
        # Base64 encode for JSON transmission
        log_content_compressed = base64.b64encode(gzip_data).decode('utf-8')
        
        # Send to backend
        url = f"{API_URL}/api/download/client-logs"
        data = {
            'token_id': str(token_id),
            'log_content_compressed': log_content_compressed
        }
        
        response = http_session.post(url, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if result.get('success'):
            logger.info(f"Successfully sent startup logs to backend (token_id: {token_id}, {len(log_bytes)} bytes uncompressed, {len(gzip_data)} bytes compressed)")
        else:
            logger.warning(f"Failed to send startup logs: {result.get('message', 'Unknown error')}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending startup logs: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending startup logs: {e}", exc_info=True)

def upload_all_gamelist_files():
    """Scan ROMS_PATH for all gamelist.xml files, filter games with playcount > 0, 
    create a tar.gz archive, and upload it to the server.
    
    Only includes games with playcount > 0, keeping only fields: path, playcount, gametime, lastplayed.
    Creates a single tar.gz archive containing filtered gamelist.xml files from all systems
    and uploads it to data/users_gamelist/<token_id>/gamelists.tar.gz
    """
    try:
        if not ROMS_PATH or not os.path.exists(ROMS_PATH):
            logger.warning(f"ROMS_PATH does not exist: {ROMS_PATH}, skipping gamelist.xml upload")
            return
        
        logger.info(f"Scanning for gamelist.xml files in {ROMS_PATH}")
        
        # Create tar.gz archive in memory with default compression
        tar_buffer = io.BytesIO()
        files_added = 0
        total_games_filtered = 0
        
        with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
            # Scan all system directories in ROMS_PATH
            for system_dir in os.listdir(ROMS_PATH):
                system_path = os.path.join(ROMS_PATH, system_dir)
                
                # Skip if not a directory
                if not os.path.isdir(system_path):
                    continue
                
                # Check for gamelist.xml in this system directory
                gamelist_path = os.path.join(system_path, 'gamelist.xml')
                
                if os.path.exists(gamelist_path) and os.path.isfile(gamelist_path):
                    try:
                        # Filter the gamelist.xml to only include games with playcount > 0
                        filtered_xml = filter_gamelist_for_upload(gamelist_path)
                        
                        if filtered_xml is not None:
                            # Count games in filtered XML
                            filtered_xml.seek(0)
                            filtered_tree = ET.parse(filtered_xml)
                            game_count = len(filtered_tree.getroot().findall('game'))
                            total_games_filtered += game_count
                            
                            # Reset to beginning for tarfile
                            filtered_xml.seek(0)
                            
                            # Create tarinfo for the file
                            tarinfo = tarfile.TarInfo(name=f"{system_dir}/gamelist.xml")
                            filtered_xml.seek(0, 2)  # Seek to end to get size
                            tarinfo.size = filtered_xml.tell()
                            filtered_xml.seek(0)  # Reset to beginning
                            
                            # Add filtered XML to archive
                            tar.addfile(tarinfo, filtered_xml)
                            files_added += 1
                            logger.debug(f"Added filtered gamelist.xml for system '{system_dir}' ({game_count} games with playcount > 0)")
                        else:
                            logger.debug(f"No games with playcount > 0 in system '{system_dir}', skipping")
                            
                    except Exception as e:
                        logger.error(f"Error processing gamelist.xml for system '{system_dir}': {e}")
        
        if files_added == 0:
            logger.info("No gamelist.xml files with games (playcount > 0) found, skipping upload")
            return
        
        # Get the tar.gz content
        tar_buffer.seek(0)
        tar_content = tar_buffer.getvalue()
        tar_buffer.close()
        
        logger.info(f"Created tar.gz archive with {files_added} gamelist.xml files ({total_games_filtered} total games with playcount > 0, {len(tar_content)} bytes)")
        
        # Upload to server
        try:
            url = f"{API_URL}/api/download/gamelist/upload"
            files = {
                'file': ('gamelists.tar.gz', tar_content, 'application/gzip')
            }
            # No system parameter needed since all files are in one archive
            
            response = http_session.post(url, files=files, timeout=120)  # Increased timeout for larger files
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                logger.info(f"Successfully uploaded gamelist.tar.gz archive ({files_added} files, {total_games_filtered} games, {len(tar_content)} bytes)")
            else:
                logger.warning(f"Failed to upload gamelist.tar.gz: {result.get('message', 'Unknown error')}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error uploading gamelist.tar.gz archive: {e}")
        except Exception as e:
            logger.error(f"Unexpected error uploading gamelist.tar.gz archive: {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"Error creating and uploading gamelist.tar.gz archive: {e}", exc_info=True)

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
        # Calculate stats for logging
        bytes_mb = bytes_transferred / (1024 * 1024)
        speed_mbits = (bytes_per_second * 8) / (1024 * 1024) if bytes_per_second > 0 else 0
        
        # Log progress with bandwidth stats
        logger.info(f"Progress API call: download_id={download_id}, bytes_transferred={bytes_mb:.2f} MB ({bytes_transferred} bytes), speed={speed_mbits:.2f} Mbits/s ({bytes_per_second} bytes/s)")
        
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
            # When resuming, use 'r+b' mode to seek to the resume position and overwrite from there
            # This ensures we don't append to a file that might be larger than expected
            if current_resume_from > 0:
                # Ensure file exists and is at least as large as resume position
                if not os.path.exists(dest_path):
                    # File doesn't exist, create it and start from beginning
                    mode = 'wb'
                    current_resume_from = 0
                    total_bytes_downloaded = 0
                    logger.warning(f"Resume position {current_resume_from} specified but file doesn't exist, starting from beginning")
                else:
                    # File exists - open in r+b mode, truncate to resume position, then seek there
                    mode = 'r+b'
            else:
                mode = 'wb'  # Write mode for new files
            
            bytes_downloaded_this_session = 0  # Track bytes downloaded in this session only
            chunk_count = 0
            download_start_time = time.time()
            last_log_time = download_start_time
            last_pause_check = download_start_time
            
            # Track recent download rate (last 10 seconds) for more accurate current rate display
            recent_bytes_window = []  # List of (timestamp, bytes) tuples for last 10 seconds
            recent_rate_window_seconds = 10.0
            
            with open(dest_path, mode) as f:
                # If resuming, truncate to resume position and seek there
                if current_resume_from > 0:
                    f.truncate(current_resume_from)
                    f.seek(current_resume_from)
                    logger.debug(f"Opened file for resume: truncated to {current_resume_from} bytes, positioned at {current_resume_from}")
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
                                
                                bytes_downloaded_this_chunk_session = total_bytes_downloaded - current_resume_from
                                logger.info(f"Downloaded {bytes_downloaded_this_chunk_session} bytes this session ({total_bytes_downloaded / (1024*1024):.2f} MB total, resumed from {current_resume_from / (1024*1024):.2f} MB), {chunk_count} chunks, rate: {current_rate / 125000:.2f} Mbits/s")
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
            # File is automatically flushed and closed when exiting the 'with' block above
            
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
            
            bytes_downloaded_this_session = total_bytes_downloaded - current_resume_from
            logger.info(f"Download completed: {chunk_count} chunks, {bytes_downloaded_this_session} bytes downloaded this session (total: {total_bytes_downloaded} bytes including {current_resume_from} bytes from resume)")
            
            # Verify file size - check if file exists first (it might have been deleted by another process/thread)
            if not os.path.exists(dest_path):
                logger.error(f"File not found after download completion (may have been deleted): {dest_path}")
                return None  # File was deleted, treat as error
            
            try:
                final_size = os.path.getsize(dest_path)
            except FileNotFoundError:
                logger.error(f"File was deleted during size verification: {dest_path}")
                return None  # File was deleted, treat as error
            except Exception as e:
                logger.error(f"Error getting file size: {e}")
                return None
            
            # When resuming, total_bytes_downloaded includes resume_from, so compare final_size with expected_size
            # expected_size should be the TOTAL file size, not just the remaining bytes
            # Ensure both are integers for proper comparison
            if expected_size is not None and int(final_size) != int(expected_size):
                logger.error(f"File size mismatch: final_size={final_size} != expected_size={expected_size} (resumed from {current_resume_from}, downloaded {bytes_downloaded_this_session} bytes this session, total_bytes_downloaded={total_bytes_downloaded})")
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
            # Handle 404 errors - file doesn't exist, don't retry
            # For media files, 404 means the file doesn't exist on the server (no point in retrying)
            # For ROM files, 404 should also not be retried (file doesn't exist)
            if e.response and e.response.status_code == 404:
                logger.warning(f"File not found (404) for URL: {http_url} - skipping (no retry)")
                # Close response if it exists
                if 'response' in locals() and response:
                    try:
                        response.close()
                    except:
                        pass
                # Return None immediately - do NOT retry on 404
                return None  # None indicates file not found (different from False which indicates pause/failure)
            logger.error(f"HTTP download error: {e}", exc_info=True)
            # Close response on error
            if 'response' in locals() and response:
                try:
                    response.close()
                except:
                    pass
            # Retry on HTTP errors if we have retries left (except for 403/404/410 which return immediately above)
            # 410 (Gone) means download was removed from queue - should NOT retry
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

def download_directory_as_tar(download_id, system, game_id, base_url, dest_base_path, files_list, bytes_already_transferred, paused_ref, download_info=None):
    """Download all files in a directory as a streaming binary archive (hybrid approach with file-level tracking).
    
    This function uses binary streaming to reduce HTTP overhead. It tracks which files are complete
    and only requests remaining files on resume. Files are extracted on-the-fly as they arrive.
    
    Binary format:
    - For each file:
      - 4 bytes (uint32 BE): path_length
      - N bytes: path (UTF-8)
      - 8 bytes (uint64 BE): file_size
      - M bytes: file_data
    - End marker: 4 zero bytes
    
    Args:
        download_id: Download ID for progress tracking
        system: System name
        game_id: Game ID
        base_url: Base API URL
        dest_base_path: Base destination path for files
        files_list: List of file info dicts with 'relative_path' and 'size'
        bytes_already_transferred: Bytes already downloaded (for progress tracking)
        paused_ref: Reference to pause flag [False] or [True]
        download_info: Optional download_info dict containing download_id for URL construction
    """
    import json
    import shutil
    
    # Reset paused_ref to False at the start
    if paused_ref:
        paused_ref[0] = False
    
    # Step 1: Check which files already exist and are complete
    completed_files = {}  # {relative_path: file_size}
    remaining_files = []
    
    for file_info in files_list:
        relative_path = file_info['relative_path']
        expected_size = int(file_info['size'])
        
        # Determine destination path
        if 'destination_rom_path' in file_info:
            dest_rom_path = file_info['destination_rom_path']
            dest_system = file_info.get('destination_system', system)
            dest_file_path = os.path.join(ROMS_PATH, dest_system, dest_rom_path)
        else:
            dest_file_path = os.path.join(dest_base_path, relative_path)
        
        if os.path.exists(dest_file_path):
            try:
                existing_size = os.path.getsize(dest_file_path)
                if existing_size == expected_size:
                    # File is complete, skip it
                    completed_files[relative_path] = existing_size
                    logger.debug(f"File already complete: {relative_path}")
                    continue
                elif existing_size > expected_size:
                    # File is larger than expected (corrupted), delete it
                    logger.warning(f"File size mismatch for {relative_path}: local={existing_size} bytes, server={expected_size} bytes (too large, deleting)")
                    try:
                        os.remove(dest_file_path)
                        logger.info(f"Deleted oversized file: {relative_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete oversized file {dest_file_path}: {e}")
            except Exception as e:
                logger.warning(f"Error checking file {relative_path}: {e}")
        
        # File is missing or incomplete, needs to be downloaded
        remaining_files.append(file_info)
    
    if not remaining_files:
        logger.info(f"All {len(completed_files)} files already complete!")
        return True
    
    logger.info(f"Streaming binary archive: {len(completed_files)} files already complete, {len(remaining_files)} remaining")
    
    # Step 2: Request binary stream with ONLY remaining files
    # Build list of relative paths for the request
    remaining_paths = [f['relative_path'] for f in remaining_files]
    
    # Check if WebSocket is available and prefer it over HTTP
    use_websocket = False
    with _websocket_lock:
        if _active_websocket is not None:
            use_websocket = True
            logger.info("Using WebSocket for archive download (avoids reverse proxy timeouts)")
    
    if use_websocket:
        # Try to use WebSocket for download
        try:
            # Use the stored event loop from WebSocket connection
            with _websocket_lock:
                loop = _websocket_event_loop
            
            if loop and loop.is_running():
                # Loop is running (in WebSocket thread), use run_coroutine_threadsafe
                import concurrent.futures
                future = asyncio.run_coroutine_threadsafe(
                    download_directory_via_websocket_async(
                        download_id, remaining_paths, dest_base_path, system,
                        remaining_files, bytes_already_transferred, paused_ref, download_info
                    ),
                    loop
                )
                result = future.result(timeout=3600)  # 1 hour timeout
                return result
            else:
                logger.error("WebSocket event loop not available or not running, cannot download archive")
                return False
        except Exception as e:
            logger.error(f"WebSocket archive download failed: {e}", exc_info=True)
            return False
    else:
        logger.error("WebSocket not available, cannot download archive")
        return False

def download_directory_recursive(download_id, system, game_id, base_url, dest_base_path, files_list, bytes_already_transferred, paused_ref, download_info=None):
    """Download all files in a directory recursively.
    
    Uses tar streaming for better performance when multiple files need to be downloaded.
    Falls back to individual file downloads if tar streaming fails.
    
    Args:
        download_info: Optional download_info dict containing download_id for URL construction
    """
    import urllib.parse
    
    # Try binary streaming for directory downloads (always, as it's more efficient)
    if download_info and 'download_id' in download_info and len(files_list) > 0:
        logger.info(f"Attempting binary streaming for {len(files_list)} files")
        try:
            result = download_directory_as_tar(
                download_id, system, game_id, base_url, dest_base_path, 
                files_list, bytes_already_transferred, paused_ref, download_info
            )
            if result:
                return result
            # If binary streaming returns False, fall through to individual downloads
            logger.warning("Binary streaming failed, falling back to individual file downloads")
        except Exception as e:
            logger.error(f"Error in binary streaming, falling back to individual downloads: {e}", exc_info=True)
    
    # Fallback to individual file downloads
    logger.info("Using individual file downloads")
    
    # Reset paused_ref to False at the start (in case this is a resumed download)
    if paused_ref:
        paused_ref[0] = False
    
    # Calculate total bytes already downloaded from local files (don't use API value)
    # This ensures we only rely on actual file sizes on disk, not potentially incorrect API values
    total_bytes_downloaded = 0
    for file_info in files_list:
        rel_path = file_info['relative_path']
        dest_file_path = os.path.join(dest_base_path, rel_path)
        if os.path.exists(dest_file_path):
            existing_size = os.path.getsize(dest_file_path)
            file_size = int(file_info['size'])  # Ensure integer type
            if existing_size <= file_size:
                # Count existing file size (complete or partial)
                total_bytes_downloaded += existing_size
            # If file is larger than expected, it will be deleted later, so don't count it
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
    
    # Pre-check phase: Validate all files and delete files with size mismatches
    # This handles both new downloads and resuming downloads
    # For special files (.m3u, .cue, .xbox360), files_list includes the special file + all referenced files
    # Logic:
    # - If existing_size > expected_size: Delete (corrupted, restart from 0)
    # - If existing_size < expected_size: Keep (will resume in download loop)
    # - If existing_size == expected_size: Keep (will skip in download loop)
    logger.info(f"Pre-checking {len(files_list)} files for size validation...")
    deleted_files_count = 0
    for file_info in files_list:
        relative_path = file_info['relative_path']
        expected_size = int(file_info['size'])  # Ensure integer type
        # Check if file_info has destination_rom_path override (e.g., for .psvita file that should go to roms)
        if 'destination_rom_path' in file_info:
            # File should be saved to roms directory instead of save directory
            dest_rom_path = file_info['destination_rom_path']
            dest_system = file_info.get('destination_system', system)
            dest_file_path = os.path.join(ROMS_PATH, dest_system, dest_rom_path)
        else:
            dest_file_path = os.path.join(dest_base_path, relative_path)
        
        # Check if file exists
        if os.path.exists(dest_file_path):
            try:
                existing_size = os.path.getsize(dest_file_path)
                # Delete files that are larger than expected (corrupted)
                # Keep files that are smaller (will resume) or equal (will skip)
                if existing_size > expected_size:
                    logger.warning(f"File size mismatch for {relative_path}: local={existing_size} bytes, server={expected_size} bytes (too large, deleting)")
                    try:
                        os.remove(dest_file_path)
                        deleted_files_count += 1
                        logger.info(f"Deleted oversized file: {relative_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete oversized file {dest_file_path}: {e}")
                        files_with_errors.append((relative_path, f"Failed to delete oversized file: {e}"))
                elif existing_size < expected_size:
                    logger.debug(f"File {relative_path} is partial: {existing_size}/{expected_size} bytes - will resume")
                elif existing_size == expected_size:
                    logger.debug(f"File size matches for {relative_path}: {existing_size} bytes - will skip if complete")
            except Exception as e:
                logger.warning(f"Error checking file size for {relative_path}: {e}")
                # Continue with other files even if one fails
                continue
    
    if deleted_files_count > 0:
        logger.info(f"Pre-check complete: Deleted {deleted_files_count} file(s) that were larger than expected")
    else:
        logger.debug(f"Pre-check complete: No oversized files found")
    
    try:
        # Download each file in the directory
        for file_info in files_list:
            if paused_ref[0]:
                logger.info(f"Download {download_id} was paused")
                progress_thread_running = False
                progress_thread.join(timeout=1)
                return False
            
            relative_path = file_info['relative_path']
            file_size = int(file_info['size'])  # Ensure integer type
            
            # Construct URL for this file
            # Only remove './' prefix if present, preserve paths starting with '.zfs'
            clean_game_id = game_id[2:] if game_id.startswith('./') else game_id
            encoded_game_id = urllib.parse.quote(clean_game_id, safe='/')
            encoded_system = urllib.parse.quote(system, safe='')
            encoded_rel_path = urllib.parse.quote(relative_path, safe='/')
            # Prefer download_id from download_info if available (simpler and more reliable)
            if download_info and 'download_id' in download_info:
                file_url = f"{base_url}/api/download/file?download_id={download_info['download_id']}&relative_path={encoded_rel_path}"
            else:
                file_url = f"{base_url}/api/download/file?system={encoded_system}&game_id={encoded_game_id}&relative_path={encoded_rel_path}"
            
            # Destination path preserving directory structure
            # Check if file_info has destination_rom_path override (e.g., for .psvita file that should go to roms)
            if 'destination_rom_path' in file_info:
                # File should be saved to roms directory instead of save directory
                dest_rom_path = file_info['destination_rom_path']
                dest_system = file_info.get('destination_system', system)
                dest_file_path = os.path.join(ROMS_PATH, dest_system, dest_rom_path)
            else:
                dest_file_path = os.path.join(dest_base_path, relative_path)
            dest_file_dir = os.path.dirname(dest_file_path)
            os.makedirs(dest_file_dir, exist_ok=True)
            
            # Check if file already exists (for resume)
            # After pre-check phase, files with size mismatches should have been deleted
            # So if file exists here, it either has correct size (complete) or was not checked in pre-check
            resume_from = 0
            if os.path.exists(dest_file_path):
                try:
                    existing_size = os.path.getsize(dest_file_path)
                    if existing_size > file_size:
                        # File is larger than expected - should have been caught in pre-check, but handle defensively
                        logger.error(f"File size mismatch for {relative_path}: {existing_size} bytes, expected {file_size} bytes (file is too large, deleting)")
                        try:
                            os.remove(dest_file_path)
                            logger.info(f"Deleted corrupted existing file: {dest_file_path}")
                            resume_from = 0  # Start fresh
                        except Exception as e:
                            logger.error(f"Failed to delete corrupted existing file {dest_file_path}: {e}")
                            files_with_errors.append((relative_path, f"File size mismatch: {existing_size} > {file_size}"))
                            continue
                    elif existing_size < file_size:
                        # File is smaller - partial download, resume from here
                        resume_from = existing_size
                        logger.info(f"Resuming file {relative_path} from byte {resume_from} (partial download)")
                    elif existing_size == file_size:
                        # File is complete - skip it
                        logger.info(f"File already complete: {relative_path}")
                        total_bytes_downloaded += file_size
                        continue
                except FileNotFoundError:
                    # File was deleted between pre-check and here (shouldn't happen, but handle gracefully)
                    logger.debug(f"File {relative_path} was deleted between pre-check and download loop")
                    resume_from = 0
                except Exception as e:
                    logger.error(f"Error checking file size for {relative_path}: {e}")
                    files_with_errors.append((relative_path, f"Error checking file: {e}"))
                    continue
            
            logger.info(f"Downloading file: {relative_path} ({file_size} bytes)")
            
            # Retry logic for file size mismatches (retry once)
            max_attempts = 2  # Original attempt + 1 retry
            attempt = 0
            file_downloaded_successfully = False
            current_resume_from = resume_from
            
            while attempt < max_attempts and not file_downloaded_successfully:
                attempt += 1
                if attempt > 1:
                    logger.info(f"Retrying download for {relative_path} (attempt {attempt}/{max_attempts})")
                    # On retry, start from beginning (delete partial file if it exists)
                    if os.path.exists(dest_file_path):
                        try:
                            os.remove(dest_file_path)
                            logger.info(f"Deleted partial/corrupted file before retry: {dest_file_path}")
                        except Exception as e:
                            logger.error(f"Failed to delete file before retry {dest_file_path}: {e}")
                    current_resume_from = 0
                
                # Download this file
                success = download_file_via_http(
                    file_url,
                    dest_file_path,
                    resume_from=current_resume_from,
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
                        # Ensure both are integers for proper comparison
                        final_size_int = int(final_size)
                        file_size_int = int(file_size)
                        if final_size_int != file_size_int:
                            logger.error(f"File size mismatch for {relative_path}: downloaded {final_size} bytes, expected {file_size} bytes (attempt {attempt}/{max_attempts})")
                            
                            # Delete only this corrupted file
                            try:
                                os.remove(dest_file_path)
                                logger.info(f"Deleted corrupted file: {dest_file_path}")
                            except Exception as e:
                                logger.error(f"Failed to delete corrupted file {dest_file_path}: {e}")
                            
                            # Retry once if this is the first attempt
                            if attempt < max_attempts:
                                continue  # Retry
                            else:
                                # Track this error after all retries exhausted
                                files_with_errors.append((relative_path, f"File size mismatch: {final_size} != {file_size} (after {max_attempts} attempts)"))
                                break  # Exit retry loop
                        else:
                            # Sizes match but download_file_via_http returned None - likely a different issue (404/410)
                            # Don't treat as size mismatch, don't retry
                            logger.warning(f"download_file_via_http returned None for {relative_path} but file size matches ({final_size} bytes) - may be 404/410")
                            break  # Exit retry loop, will continue to next file
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
                    # Not paused, just failed - don't retry for non-size-mismatch failures
                    logger.error(f"Failed to download file: {relative_path} (attempt {attempt}/{max_attempts})")
                    if attempt >= max_attempts:
                        files_with_errors.append((relative_path, "Download failed"))
                    break  # Exit retry loop
                
                # Verify file size after successful download
                if os.path.exists(dest_file_path):
                    actual_size = os.path.getsize(dest_file_path)
                    # Ensure both are integers for proper comparison
                    if int(actual_size) != int(file_size):
                        logger.error(f"File size mismatch for {relative_path} after download: {actual_size} bytes, expected {file_size} bytes (attempt {attempt}/{max_attempts})")
                        try:
                            os.remove(dest_file_path)
                            logger.info(f"Deleted corrupted file: {dest_file_path}")
                        except Exception as e:
                            logger.error(f"Failed to delete corrupted file {dest_file_path}: {e}")
                        
                        # Retry once if this is the first attempt
                        if attempt < max_attempts:
                            continue  # Retry
                        else:
                            # Track this error after all retries exhausted
                            files_with_errors.append((relative_path, f"File size mismatch: {actual_size} != {file_size} (after {max_attempts} attempts)"))
                            break  # Exit retry loop
                    else:
                        # File size is correct - download successful
                        logger.debug(f"File size verified for {relative_path}: {actual_size} bytes")
                        file_downloaded_successfully = True
                        break  # Exit retry loop
                else:
                    # File doesn't exist after successful download - shouldn't happen, but handle it
                    logger.warning(f"File {relative_path} doesn't exist after successful download notification")
                    if attempt >= max_attempts:
                        files_with_errors.append((relative_path, "File missing after download"))
                    break  # Exit retry loop
            
            # Continue to next file if this one didn't succeed after all retries
            if not file_downloaded_successfully:
                continue
        
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
                    existing_response=None,
                    max_retries=0  # Don't retry media downloads - 404 means file doesn't exist
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
        
        # Build game metadata dict for Batocera API
        # Include ALL fields from game_data (except system-specific metadata)
        batocera_game = {}
        
        # Fields to exclude from the API call (system-specific metadata and website-only fields)
        exclude_fields = {'id', 'system', 'systemName', 'catalog_image', '_original_batocera_path', '_original_retrobat_path'}
        
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
        
        # Override the 'path' field with the resolved game_id (which has the correct extension for the platform)
        # The game_id parameter contains the resolved ROM path (e.g., "game.m3u" for Linux, "game.xbox360" for Windows)
        # Format it for gamelist.xml with './' prefix if not already present
        resolved_path = game_id  # This is clean_original_path, which is the resolved ROM path
        if not resolved_path.startswith('./'):
            resolved_path = f'./{resolved_path}'
        batocera_game['path'] = resolved_path
        logger.info(f"Using resolved path with correct extension: '{resolved_path}' (platform-specific)")
        
        # Create XML structure
        root = ET.Element("gameList")
        game_elem = ET.SubElement(root, "game")
        
        # Add all fields to XML
        for key, value in batocera_game.items():
            if value:  # Only add non-empty fields
                elem = ET.SubElement(game_elem, key)
                elem.text = str(value)
        
        # Pretty print XML using only ElementTree
        def prettify_xml(elem):
            """Return a pretty-printed XML string for the Element using only ElementTree."""
            # Create a copy to avoid modifying the original element
            from copy import deepcopy
            root = deepcopy(elem)
            
            # Use ET.indent() (Python 3.9+) for pretty printing
            ET.indent(root, space="  ")
            
            # Convert to string
            xml_str = ET.tostring(root, encoding='unicode')
            
            # Add XML declaration with UTF-8 encoding
            return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
        
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
        headers = {'Content-Type': 'application/xml; charset=utf-8'}
        
        logger.info(f"Sending game '{game_data.get('name', game_id)}' to Batocera API at {url}")
        # Encode XML content to UTF-8 bytes to ensure proper encoding
        response = requests.post(url, data=xml_content.encode('utf-8'), headers=headers, timeout=10)
        
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
        logger.info(f"Falling back to manual gamelist.xml update")
        return _update_gamelist_xml_manually(batocera_system, game_id, xml_content)
    except requests.exceptions.Timeout:
        logger.warning(f"Request to Batocera HTTP server timed out")
        logger.info(f"Falling back to manual gamelist.xml update")
        return _update_gamelist_xml_manually(batocera_system, game_id, xml_content)
    except Exception as e:
        logger.error(f"Error adding game to Batocera via API: {e}", exc_info=True)
        return False


def _update_gamelist_xml_manually(batocera_system, game_id, xml_content):
    """Fallback: Manually update gamelist.xml file when API is unavailable.
    
    Args:
        batocera_system: Batocera system directory name (e.g., "atari2600")
        game_id: Game ID (rompath, e.g., "apshai.zip")
        xml_content: Full XML content for the game entry (includes <gameList><game>...</game></gameList>)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from xml.etree import ElementTree as ET
        
        # Build path to gamelist.xml file
        gamelist_path = os.path.join(ROMS_PATH, batocera_system, 'gamelist.xml')
        
        # Parse the provided XML content to extract the game element
        # xml_content contains: <gameList><game>...</game></gameList>
        root_from_content = ET.fromstring(xml_content)
        new_game_elem = root_from_content.find('game')
        if new_game_elem is None:
            logger.error(f"Could not find <game> element in provided XML content")
            return False
        
        # Get the path from the new game element (this is the key for matching)
        path_elem = new_game_elem.find('path')
        if path_elem is None or not path_elem.text:
            logger.error(f"Game entry missing 'path' field, cannot update gamelist.xml")
            return False
        
        game_path = path_elem.text.strip()
        logger.info(f"Updating gamelist.xml manually for game path: '{game_path}'")
        
        # Parse existing gamelist.xml or create new one
        if os.path.exists(gamelist_path):
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
            except ET.ParseError as e:
                logger.error(f"Error parsing existing gamelist.xml: {e}. Creating new file.")
                root = ET.Element("gameList")
        else:
            # Create new gamelist.xml
            root = ET.Element("gameList")
            logger.info(f"Creating new gamelist.xml at {gamelist_path}")
        
        # Find existing game with same path
        existing_game = None
        for game in root.findall('game'):
            path_elem_existing = game.find('path')
            if path_elem_existing is not None and path_elem_existing.text:
                existing_path = path_elem_existing.text.strip()
                # Compare paths directly
                if existing_path == game_path:
                    existing_game = game
                    logger.info(f"Found existing game entry with path '{existing_path}', will update it")
                    break
        
        if existing_game is not None:
            # Update existing game: replace all children with new game's children
            root.remove(existing_game)
            root.append(new_game_elem)
            logger.info(f"Updated existing game entry in gamelist.xml")
        else:
            # Add new game at the end
            root.append(new_game_elem)
            logger.info(f"Added new game entry to gamelist.xml")
        
        # Pretty print the XML using only ElementTree
        def prettify_xml(elem):
            """Return a pretty-printed XML string for the Element using only ElementTree."""
            # Create a copy to avoid modifying the original element
            from copy import deepcopy
            root = deepcopy(elem)
            
            # Use ET.indent() (Python 3.9+) for pretty printing
            ET.indent(root, space="  ")
            
            # Convert to string
            xml_str = ET.tostring(root, encoding='unicode')
            
            # Add XML declaration with UTF-8 encoding
            return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
        
        # Write to file
        pretty_xml = prettify_xml(root)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(gamelist_path), exist_ok=True)
        
        # Write with UTF-8 encoding
        with open(gamelist_path, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
        
        logger.info(f"Successfully updated gamelist.xml manually at {gamelist_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating gamelist.xml manually: {e}", exc_info=True)
        return False

# ============================================================================
# P2P Download Helper Functions
# ============================================================================

def calculate_partial_checksum(file_path, chunk_size=2097152):
    """Calculate partial SHA-256 checksum of a file (beginning + end chunks + file size).
    
    For files smaller than chunk_size * 2, computes full SHA-256.
    For larger files, computes SHA-256 of first chunk_size bytes and last chunk_size bytes.
    
    Args:
        file_path: Path to the file
        chunk_size: Size of chunks to read for partial checksum (default: 2MB)
        
    Returns:
        Dictionary with checksum data:
        - For small files (< chunk_size * 2): {file_size, full_hash}
        - For large files: {file_size, beginning_hash, end_hash, chunk_size}
        Returns None on error
    """
    if not os.path.exists(file_path):
        logger.warning(f"File not found for checksum calculation: {file_path}")
        return None
    
    try:
        file_size = os.path.getsize(file_path)
        
        # For small files, compute full SHA-256
        if file_size < chunk_size * 2:
            sha256_hash = hashlib.sha256()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)  # 8KB chunks
                    if not chunk:
                        break
                    sha256_hash.update(chunk)
            return {
                "file_size": file_size,
                "full_hash": sha256_hash.hexdigest()
            }
        
        # For large files, compute SHA-256 of beginning and end chunks
        beginning_hash = hashlib.sha256()
        end_hash = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            # Read and hash first chunk_size bytes
            bytes_read = 0
            while bytes_read < chunk_size:
                chunk = f.read(min(8192, chunk_size - bytes_read))
                if not chunk:
                    break
                beginning_hash.update(chunk)
                bytes_read += len(chunk)
            
            # Seek to end and read last chunk_size bytes
            f.seek(max(0, file_size - chunk_size))
            bytes_read = 0
            while bytes_read < chunk_size:
                chunk = f.read(min(8192, chunk_size - bytes_read))
                if not chunk:
                    break
                end_hash.update(chunk)
                bytes_read += len(chunk)
        
        return {
            "file_size": file_size,
            "beginning_hash": beginning_hash.hexdigest(),
            "end_hash": end_hash.hexdigest(),
            "chunk_size": chunk_size
        }
    except Exception as e:
        logger.error(f"Error calculating checksum for {file_path}: {e}", exc_info=True)
        return None

def get_server_checksum(system, rom_path):
    """Get partial SHA-256 checksum from server.
    
    Args:
        system: System identifier
        rom_path: ROM file path (relative to system directory)
        
    Returns:
        Dictionary with checksum data:
        - For small files: {file_size, full_hash}
        - For large files: {file_size, beginning_hash, end_hash, chunk_size}
        Returns None on error
    """
    try:
        # URL encode the rom_path for the API endpoint
        encoded_rom_path = quote(rom_path, safe='')
        
        url = f"{API_URL}/api/download/p2p/md5/{system}/{encoded_rom_path}"
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
        }
        
        response = http_session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if result.get('success'):
            checksum_data = result.get('checksum')
            if checksum_data:
                logger.debug(f"Retrieved checksum from server for {system}/{rom_path}: file_size={checksum_data.get('file_size')}")
                return checksum_data
            else:
                logger.error(f"Server returned success but no checksum data for {system}/{rom_path}")
                return None
        else:
            logger.error(f"Server returned error for checksum request: {result.get('message', 'Unknown error')}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error requesting checksum from server for {system}/{rom_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error requesting checksum from server: {e}", exc_info=True)
        return None

# Global set for tracking cancelled reverse uploads (by download_id)
_cancelled_reverse_uploads = set()
import threading as _threading_for_cancel  # Import for lock
_cancelled_reverse_uploads_lock = _threading_for_cancel.Lock()

class ReverseUploadCancelled(Exception):
    """Exception raised when reverse upload is cancelled by remote client."""
    pass

def cancel_reverse_upload(download_id: int):
    """Mark a P2P upload as cancelled so it will abort (used for reverse P2P uploads)."""
    with _cancelled_reverse_uploads_lock:
        _cancelled_reverse_uploads.add(download_id)
        logger.info(f"Marked P2P upload for download_id={download_id} as cancelled (will abort reverse P2P if active)")

def is_reverse_upload_cancelled(download_id: int) -> bool:
    """Check if a reverse upload should be cancelled."""
    with _cancelled_reverse_uploads_lock:
        return download_id in _cancelled_reverse_uploads

def clear_reverse_upload_cancelled(download_id: int):
    """Clear the cancelled flag for a reverse upload."""
    with _cancelled_reverse_uploads_lock:
        _cancelled_reverse_uploads.discard(download_id)

def handle_reverse_p2p_upload(target_ip, target_port, target_path, system, rom_path, resume_from=0, expected_size=None, expected_checksum=None, download_id=None, request_id=None, target_token_id=None):
    """Handle reverse P2P upload: push file to another client.
    
    Args:
        target_ip: IP address of target client (Client A)
        target_port: Port where target client is listening
        target_path: URL path for reverse connection (e.g., "/reverse/{request_id}")
        system: System identifier
        rom_path: ROM file path (relative to system directory)
        resume_from: Byte position to resume from (default: 0)
        expected_size: Expected file size in bytes (optional)
        expected_checksum: Expected checksum data (optional, for validation before upload)
        download_id: Download ID for tracking (optional)
        request_id: Unique request ID for feedback mechanism (optional)
        target_token_id: Token ID of the target client for feedback (optional)
    """
    success = False
    error_message = None
    
    try:
        # Verify download_id if available (P2P security check)
        if download_id:
            if not verify_p2p_download_id(download_id, system, rom_path):
                logger.warning(f"Reverse P2P upload rejected: download_id {download_id} verification failed for {system}/{rom_path}")
                error_message = "Download ID verification failed"
                return
        # Build source file path
        if not ROMS_PATH or not os.path.exists(ROMS_PATH):
            logger.error(f"ROMS_PATH does not exist: {ROMS_PATH}, cannot serve file via reverse connection")
            error_message = "ROMS_PATH does not exist"
            return
        
        file_path = os.path.join(ROMS_PATH, system, rom_path.lstrip('./'))
        
        # Security check: ensure path is within ROMS_PATH
        try:
            roms_path_abs = os.path.abspath(ROMS_PATH)
            file_path_abs = os.path.abspath(file_path)
            if not str(file_path_abs).startswith(str(roms_path_abs)):
                logger.error(f"Access denied: file path outside ROMS_PATH")
                error_message = "Access denied: path outside ROMS_PATH"
                return
        except Exception:
            logger.error(f"Access denied: invalid path")
            error_message = "Access denied: invalid path"
            return
        
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            logger.error(f"File not found for reverse connection: {file_path}")
            error_message = "File not found"
            return
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Validate file size against expected_size if provided
        if expected_size and file_size != expected_size:
            logger.error(f"File size mismatch on sender side: local file is {file_size} bytes, expected {expected_size} bytes for {system}/{rom_path}")
            error_message = f"File size mismatch: local={file_size}, expected={expected_size}"
            return
        
        # Validate checksum against expected_checksum if provided
        if expected_checksum:
            logger.info(f"Validating checksum before upload for {system}/{rom_path}")
            local_checksum = calculate_partial_checksum(file_path)
            if not local_checksum:
                logger.error(f"Failed to calculate checksum for local file: {file_path}")
                error_message = "Failed to calculate local file checksum"
                return
            
            # Compare file sizes first
            if local_checksum['file_size'] != expected_checksum.get('file_size'):
                logger.error(f"Checksum validation failed: size mismatch - local={local_checksum['file_size']}, expected={expected_checksum.get('file_size')}")
                error_message = f"Checksum validation failed: size mismatch"
                return
            
            # For small files, compare full_hash
            if 'full_hash' in expected_checksum:
                if 'full_hash' not in local_checksum:
                    logger.error(f"Checksum validation failed: format mismatch - expected full_hash, got partial checksum")
                    error_message = "Checksum validation failed: format mismatch"
                    return
                if local_checksum['full_hash'].lower() != expected_checksum['full_hash'].lower():
                    logger.error(f"Checksum validation failed: hash mismatch - local={local_checksum['full_hash']}, expected={expected_checksum['full_hash']}")
                    error_message = f"Checksum validation failed: hash mismatch"
                    return
            else:
                # For large files, compare beginning_hash and end_hash
                if 'beginning_hash' not in local_checksum or 'end_hash' not in local_checksum:
                    logger.error(f"Checksum validation failed: format mismatch - expected partial checksum, got full_hash")
                    error_message = "Checksum validation failed: format mismatch"
                    return
                if local_checksum['beginning_hash'].lower() != expected_checksum.get('beginning_hash', '').lower():
                    logger.error(f"Checksum validation failed: beginning hash mismatch")
                    error_message = "Checksum validation failed: beginning hash mismatch"
                    return
                if local_checksum['end_hash'].lower() != expected_checksum.get('end_hash', '').lower():
                    logger.error(f"Checksum validation failed: end hash mismatch")
                    error_message = "Checksum validation failed: end hash mismatch"
                    return
            
            logger.info(f"Checksum validation passed for {system}/{rom_path}")
        
        # Calculate bytes to send (from resume_from to end)
        if resume_from > 0:
            bytes_to_send = file_size - resume_from
        else:
            bytes_to_send = file_size
        
        if bytes_to_send <= 0:
            logger.warning(f"Nothing to send: resume_from={resume_from}, file_size={file_size}")
            error_message = "Nothing to send"
            return
        
        # Build target URL (use target_path provided)
        target_url = f"http://{target_ip}:{target_port}{target_path}"
        
        logger.info(f"Starting reverse P2P upload: {system}/{rom_path} -> {target_url} (sending {bytes_to_send} bytes from byte {resume_from}, file_size={file_size})")
        
        # Use 1MB chunks to match normal download chunk size
        chunk_size_bytes = 1024 * 1024  # 1MB
        connect_timeout = 5
        read_timeout = 60  # Per-chunk timeout (applies to final response)
        
        # Create generator for streaming upload
        # requests.put with a generator automatically uses chunked transfer encoding
        def file_chunk_generator():
            """Generator that yields file data in 1MB chunks for streaming upload."""
            nonlocal error_message
            import time
            bytes_sent = 0
            start_time = time.time()
            last_log_time = start_time
            log_interval = 5.0  # Log progress every 5 seconds
            
            with open(file_path, 'rb') as f:
                if resume_from > 0:
                    f.seek(resume_from)
                
                remaining = bytes_to_send
                while remaining > 0:
                    # Check for cancellation before each chunk
                    if download_id and is_reverse_upload_cancelled(download_id):
                        logger.info(f"Reverse P2P upload cancelled by remote client for download_id={download_id}")
                        clear_reverse_upload_cancelled(download_id)
                        raise ReverseUploadCancelled(f"Upload cancelled by remote client for download_id={download_id}")
                    
                    # Read up to 1MB chunk
                    read_size = min(chunk_size_bytes, remaining)
                    chunk = f.read(read_size)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    bytes_sent += len(chunk)
                    
                    # Log progress periodically
                    current_time = time.time()
                    if current_time - last_log_time >= log_interval:
                        elapsed = current_time - start_time
                        speed_mbps = (bytes_sent * 8) / (elapsed * 1000000) if elapsed > 0 else 0
                        progress_pct = (bytes_sent / bytes_to_send * 100) if bytes_to_send > 0 else 0
                        logger.info(f"Reverse P2P upload progress: {bytes_sent / (1024*1024):.1f}/{bytes_to_send / (1024*1024):.1f} MB ({progress_pct:.1f}%), speed={speed_mbps:.2f} Mbits/s, target={target_ip}:{target_port}")
                        last_log_time = current_time
                    
                    yield chunk
        
        # Send file via PUT request with streaming (chunked encoding)
        # requests automatically uses chunked transfer encoding when a generator is provided
        headers = {
            'Content-Type': 'application/octet-stream',
            'Expect': '100-continue'  # Request periodic acknowledgments from Client A
        }
        
        # Use tuple format for timeout: (connect_timeout, read_timeout)
        # read_timeout applies to waiting for the final response
        # HTTP 100 Continue responses from Client A will keep the connection alive
        timeout_tuple = (connect_timeout, read_timeout)
        
        logger.info(f"Reverse P2P upload: connect_timeout={connect_timeout}s, read_timeout={read_timeout}s (per-chunk), using streaming with 1MB chunks")
        
        try:
            response = requests.put(
                target_url,
                data=file_chunk_generator(),
                headers=headers,
                timeout=timeout_tuple,
                stream=True  # Enable streaming mode
            )
            response.raise_for_status()
            
            # Read response body (if any)
            response_body = response.content
            
            logger.info(f"Reverse P2P upload completed: {system}/{rom_path} -> {target_url} ({bytes_to_send} bytes sent)")
            success = True
        except ReverseUploadCancelled as e:
            logger.info(f"Reverse P2P upload aborted: {e}")
            error_message = "Upload cancelled by remote client"
            success = False
        except requests.exceptions.ChunkedEncodingError as e:
            # This can happen when the generator raises an exception
            if download_id and is_reverse_upload_cancelled(download_id):
                logger.info(f"Reverse P2P upload cancelled (caught as ChunkedEncodingError) for download_id={download_id}")
                error_message = "Upload cancelled by remote client"
                clear_reverse_upload_cancelled(download_id)
            else:
                logger.error(f"Reverse P2P upload chunked encoding error: {e}")
                error_message = f"Upload encoding error: {e}"
            success = False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Reverse P2P upload connection error to {target_url}: {e}")
            error_message = f"Connection error: {e}"
            success = False
        except requests.exceptions.Timeout as e:
            logger.error(f"Reverse P2P upload timeout to {target_url}: {e}")
            error_message = f"Upload timeout: {e}"
            success = False
        except requests.exceptions.HTTPError as e:
            logger.error(f"Reverse P2P upload HTTP error to {target_url}: {e}")
            error_message = f"HTTP error: {e}"
            success = False
        except requests.exceptions.RequestException as e:
            logger.error(f"Reverse P2P upload request error to {target_url}: {e}")
            error_message = f"Request error: {e}"
            success = False
        except Exception as e:
            logger.error(f"Reverse P2P upload unexpected error to {target_url}: {e}", exc_info=True)
            error_message = f"Unexpected error: {e}"
            success = False
    except ReverseUploadCancelled as e:
        logger.info(f"Reverse P2P upload aborted (outer): {e}")
        error_message = "Upload cancelled by remote client"
        success = False
    finally:
        # Report result to backend for feedback to Client A
        if request_id and target_token_id:
            _report_reverse_connection_result(request_id, target_token_id, success, error_message)

def _report_reverse_connection_result(request_id, target_token_id, success, error_message=None):
    """Report reverse connection result to backend.
    
    Args:
        request_id: Unique request ID
        target_token_id: Token ID of the target client (Client A)
        success: Whether the upload succeeded
        error_message: Error message if failed
    """
    try:
        url = f"{API_URL}/api/download/p2p/reverse-connection-result"
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "request_id": request_id,
            "target_token_id": target_token_id,
            "success": success,
            "error_message": error_message
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=5)
        response.raise_for_status()
        logger.debug(f"Reported reverse connection result for request_id={request_id}: success={success}")
    except Exception as e:
        logger.warning(f"Failed to report reverse connection result: {e}")

def try_reverse_p2p_download(source_token_id, system, rom_path, dest_path, resume_from=0, expected_size=None, expected_checksum=None, download_id=None, bytes_transferred_ref=None, paused_ref=None):
    """Try to download a file via reverse P2P connection.
    
    Starts a temporary listener and requests the source peer to push the file.
    
    Args:
        source_token_id: Token ID of the peer that should send the file (Client B)
        system: System identifier
        rom_path: ROM file path (relative to system directory)
        dest_path: Destination file path
        resume_from: Byte position to resume from (default: 0)
        expected_size: Expected file size in bytes (optional)
        expected_checksum: Expected checksum data (optional, for verification)
        download_id: Download ID for tracking (optional)
        bytes_transferred_ref: Optional list to track bytes transferred
        paused_ref: Optional list to check if download should be paused
    
    Returns:
        True if download succeeded and checksum verification passed, False otherwise
    """
    try:
        from p2p_client import get_p2p_server, get_local_ip, register_reverse_connection_request, unregister_reverse_connection_request, cancel_reverse_download
        import uuid
        import time
        
        # Get existing P2P server and its port
        p2p_server = get_p2p_server(ROMS_PATH, P2P_PORT)
        actual_port = p2p_server.get_port()
        
        # Get local IP address
        local_ip = get_local_ip()
        
        # Determine resume position (check existing file)
        if os.path.exists(dest_path):
            existing_size = os.path.getsize(dest_path)
            if expected_size and existing_size < expected_size:
                resume_from = existing_size
                logger.info(f"Reverse P2P: Resuming from byte {resume_from} (existing file: {existing_size} bytes)")
        
        # Generate unique request ID for this reverse connection
        request_id = str(uuid.uuid4())
        success_ref = [False]
        failed_ref = [False]  # Set by WebSocket handler when upload fails
        last_activity_ref = [time.time()]  # Track last chunk received for per-chunk timeout
        
        # Register reverse connection request (include download_id for verification)
        register_reverse_connection_request(
            request_id=request_id,
            dest_path=dest_path,
            expected_size=expected_size,
            resume_from=resume_from,
            success_ref=success_ref,
            failed_ref=failed_ref,
            download_id=download_id,
            system=system,
            rom_path=rom_path,
            bytes_transferred_ref=bytes_transferred_ref,
            last_activity_ref=last_activity_ref
        )
        
        logger.info(f"Registered reverse connection request {request_id} on port {actual_port} for {system}/{rom_path}")
        
        # Note: Progress reporting is handled by the caller (try_p2p_download_from_list)
        # which already has a progress reporter thread using bytes_transferred_ref
        
        # Initialize transfer_start_time before try block
        transfer_start_time = None
        
        try:
            # Request reverse connection from backend
            url = f"{API_URL}/api/download/p2p/reverse-connection"
            headers = {
                'Authorization': f'Bearer {API_TOKEN}',
                'Content-Type': 'application/json'
            }
            
            # Include request_id in the URL path that Client B should use
            reverse_url_path = f"/reverse/{request_id}"
            
            data = {
                "source_token_id": source_token_id,
                "target_ip": local_ip,
                "target_port": actual_port,
                "target_path": reverse_url_path,  # Path for reverse connection
                "system": system,
                "rom_path": rom_path,
                "resume_from": resume_from,
                "expected_size": expected_size,
                "expected_checksum": expected_checksum,  # For validation on sender side
                "download_id": download_id,
                "request_id": request_id  # For feedback mechanism
            }
            
            logger.info(f"Sending reverse connection request to backend: source_token_id={source_token_id}, resume_from={resume_from}, expected_size={expected_size}, has_checksum={expected_checksum is not None}")
            response = requests.post(url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if not result.get('success'):
                logger.error(f"Reverse connection request failed: {result.get('message', 'Unknown error')}")
                unregister_reverse_connection_request(request_id)
                return False
            
            logger.info(f"Reverse connection request sent to backend for source_token_id={source_token_id}, waiting for upload...")
            
            # Wait for connection to complete with per-chunk timeout
            # Also check failed_ref which is set via WebSocket when upload fails
            transfer_start_time = time.time()  # Set when we start waiting for the transfer
            per_chunk_timeout = 60  # Timeout if no chunk received within 60 seconds
            while not success_ref[0] and not failed_ref[0]:
                # Check if download is paused - if so, cancel the reverse connection
                if paused_ref and paused_ref[0]:
                    logger.info(f"Reverse P2P download paused for request_id={request_id}, cancelling connection")
                    cancel_reverse_download(request_id)
                    unregister_reverse_connection_request(request_id)
                    return False
                
                # Check per-chunk timeout: if no data received recently, timeout
                time_since_last_activity = time.time() - last_activity_ref[0]
                if time_since_last_activity > per_chunk_timeout:
                    total_elapsed = time.time() - transfer_start_time
                    logger.warning(f"Reverse connection timeout: no data received for {time_since_last_activity:.1f}s (per-chunk timeout: {per_chunk_timeout}s, total elapsed: {total_elapsed:.1f}s)")
                    break
                time.sleep(0.1)
            
            # Check if upload failed (reported via WebSocket)
            if failed_ref[0]:
                from p2p_client import get_reverse_connection_error
                peer_error = get_reverse_connection_error(request_id)
                logger.warning(f"Reverse connection upload failed (reported by source peer): {peer_error}")
                unregister_reverse_connection_request(request_id)
                return False
            
            # Unregister request
            unregister_reverse_connection_request(request_id)
            
            success = success_ref[0]
            if not success:
                logger.error("Reverse connection did not complete successfully")
                return False
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error requesting reverse connection: {e}")
            unregister_reverse_connection_request(request_id)
            return False
        except Exception as e:
            logger.error(f"Error during reverse connection: {e}", exc_info=True)
            unregister_reverse_connection_request(request_id)
            return False
        
        # Verify file size if expected_size provided
        if expected_size:
            if not os.path.exists(dest_path):
                logger.error(f"Reverse P2P download: File does not exist after transfer: {dest_path}")
                return False
            final_size = os.path.getsize(dest_path)
            if final_size != expected_size:
                logger.error(f"Reverse P2P download size mismatch: downloaded {final_size} bytes, expected {expected_size} bytes")
                return False
        
        # Verify checksum if expected_checksum provided
        if expected_checksum:
            logger.info(f"Verifying checksum for reverse P2P downloaded file: {dest_path}")
            actual_checksum = calculate_partial_checksum(dest_path)
            if not actual_checksum:
                logger.error(f"Failed to calculate checksum for reverse P2P downloaded file: {dest_path}")
                return False
            
            # Compare file sizes
            if actual_checksum['file_size'] != expected_checksum['file_size']:
                logger.error(f"Reverse P2P download size mismatch: expected {expected_checksum['file_size']}, got {actual_checksum['file_size']}")
                return False
            
            # For small files, compare full_hash
            if 'full_hash' in expected_checksum:
                if 'full_hash' not in actual_checksum:
                    logger.error(f"Reverse P2P download checksum format mismatch: expected full_hash, got partial checksum")
                    return False
                if actual_checksum['full_hash'].lower() != expected_checksum['full_hash'].lower():
                    logger.error(f"Reverse P2P download checksum mismatch: expected {expected_checksum['full_hash']}, got {actual_checksum['full_hash']}")
                    return False
            else:
                # For large files, compare beginning_hash and end_hash
                if 'beginning_hash' not in actual_checksum or 'end_hash' not in actual_checksum:
                    logger.error(f"Reverse P2P download checksum format mismatch: expected partial checksum, got full_hash")
                    return False
                if actual_checksum['beginning_hash'].lower() != expected_checksum['beginning_hash'].lower():
                    logger.error(f"Reverse P2P download beginning hash mismatch: expected {expected_checksum['beginning_hash']}, got {actual_checksum['beginning_hash']}")
                    return False
                if actual_checksum['end_hash'].lower() != expected_checksum['end_hash'].lower():
                    logger.error(f"Reverse P2P download end hash mismatch: expected {expected_checksum['end_hash']}, got {actual_checksum['end_hash']}")
                    return False
            
            logger.info(f"Reverse P2P checksum verification passed")
        
        # Report final progress if download_id is provided
        if download_id and bytes_transferred_ref and os.path.exists(dest_path):
            final_size = os.path.getsize(dest_path)
            bytes_received = final_size - resume_from
            if bytes_received > 0:
                # Calculate final bytes per second (approximate)
                if transfer_start_time is not None:
                    total_time = time.time() - transfer_start_time
                else:
                    total_time = 1.0  # Default if transfer_start_time wasn't set
                final_bytes_per_second = int(bytes_received / total_time) if total_time > 0 else 0
                try:
                    report_progress(download_id, final_size, final_bytes_per_second)
                except Exception as e:
                    logger.debug(f"Final progress report failed: {e}")
        
        logger.info(f"Successfully downloaded file via reverse P2P connection: {dest_path}")
        return True
        
    except Exception as e:
        logger.error(f"Unexpected error during reverse P2P download: {e}", exc_info=True)
        return False

def store_p2p_remote_token_in_redis(download_id: int, p2p_remote_token_id: int):
    """Store p2p_remote_token_id in Redis at the start of a P2P download.
    
    This enables:
    1. Cancellation notifications to the uploader
    2. Displaying active uploads on the uploader's Downloads page
    
    Args:
        download_id: Download ID
        p2p_remote_token_id: Token ID of the peer serving the file
    """
    try:
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        response = http_session.post(
            f"{API_URL}/api/download/p2p/store-remote-token",
            json={'download_id': download_id, 'p2p_remote_token_id': p2p_remote_token_id},
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            logger.info(f"Stored p2p_remote_token_id={p2p_remote_token_id} in Redis for download_id={download_id}")
            return True
        else:
            logger.warning(f"Failed to store p2p_remote_token_id in Redis: {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Error storing p2p_remote_token_id in Redis: {e}")
        return False

def download_file_via_p2p(peer_url, system, rom_path, dest_path, resume_from=0, expected_size=None, expected_checksum=None, paused_ref=None, download_id=None, bytes_transferred_ref=None, chunk_size=1024*1024, connect_timeout=5, read_timeout=300):
    """Download a file from a peer via HTTP.
    
    Args:
        peer_url: Base URL of the peer (e.g., "http://192.168.1.100:8080")
        system: System identifier
        rom_path: ROM file path (relative to system directory)
        dest_path: Destination file path
        resume_from: Byte position to resume from (default: 0)
        expected_size: Expected file size in bytes (optional)
        expected_checksum: Expected checksum data (optional, for verification after download)
                          Dictionary with checksum data: {file_size, full_hash} or {file_size, beginning_hash, end_hash, chunk_size}
        paused_ref: Optional list to check if download should be paused
        download_id: Download ID for progress reporting (optional)
        bytes_transferred_ref: Optional list to track bytes transferred
        chunk_size: Size of chunks to read (default: 1MB)
        connect_timeout: Connection timeout in seconds (default: 5)
        read_timeout: Read timeout in seconds (default: 300)
        
    Returns:
        True if download succeeded and checksum verification passed (if expected_checksum provided), False otherwise
    """
    try:
        # Build peer file URL
        encoded_system = quote(system, safe='')
        encoded_rom_path = quote(rom_path, safe='')
        peer_file_url = f"{peer_url}/p2p/file/{encoded_system}/{encoded_rom_path}"
        
        current_resume_from = resume_from
        total_bytes_downloaded = resume_from
        
        headers = {}
        if current_resume_from > 0:
            headers['Range'] = f'bytes={current_resume_from}-'
        
        # Add download_id header for P2P verification (if available)
        if download_id is not None:
            headers['X-Download-ID'] = str(download_id)
        
        # Use tuple format for timeout: (connect_timeout, read_timeout)
        timeout_tuple = (connect_timeout, read_timeout)
        
        logger.info(f"Downloading from peer: {peer_file_url} (resume from {current_resume_from} bytes, connect_timeout={connect_timeout}s, read_timeout={read_timeout}s)")
        
        response = requests.get(peer_file_url, headers=headers, stream=True, timeout=timeout_tuple)
        response.raise_for_status()
        
        # Check if server supports range requests
        if current_resume_from > 0 and response.status_code != 206:
            logger.warning(f"Peer doesn't support range requests, starting from beginning")
            current_resume_from = 0
            total_bytes_downloaded = 0
            response.close()
            response = requests.get(peer_file_url, stream=True, timeout=timeout_tuple)
            response.raise_for_status()
        
        # Get file size from Content-Length or Content-Range header
        content_length = None
        if 'Content-Length' in response.headers:
            content_length = int(response.headers['Content-Length'])
        elif 'Content-Range' in response.headers:
            content_range = response.headers['Content-Range']
            if '/' in content_range:
                content_length = int(content_range.split('/')[-1])
        
        # Open destination file
        mode = 'r+b' if current_resume_from > 0 and os.path.exists(dest_path) else 'wb'
        
        bytes_downloaded_this_session = 0
        download_start_time = time.time()
        last_pause_check = download_start_time
        
        with open(dest_path, mode) as f:
            if current_resume_from > 0:
                f.truncate(current_resume_from)
                f.seek(current_resume_from)
            
            try:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    # Check if download is paused (every 2 seconds)
                    if paused_ref and time.time() - last_pause_check >= 2.0:
                        if paused_ref[0]:
                            logger.info(f"P2P download paused - stopping at {total_bytes_downloaded} bytes")
                            response.close()
                            return False
                        last_pause_check = time.time()
                    
                    if chunk:
                        f.write(chunk)
                        bytes_written = len(chunk)
                        total_bytes_downloaded += bytes_written
                        bytes_downloaded_this_session += bytes_written
                        
                        if bytes_transferred_ref:
                            bytes_transferred_ref[0] += bytes_written
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
                logger.warning(f"P2P download connection error: {e}")
                response.close()
                return False
            finally:
                response.close()
        
        # Verify file size if expected_size provided
        if expected_size and total_bytes_downloaded != expected_size:
            logger.error(f"P2P download size mismatch: downloaded {total_bytes_downloaded} bytes, expected {expected_size} bytes")
            return False
        
        # Verify checksum if expected_checksum provided
        if expected_checksum:
            logger.info(f"Verifying checksum for downloaded file: {dest_path}")
            actual_checksum = calculate_partial_checksum(dest_path)
            if not actual_checksum:
                logger.error(f"Failed to calculate checksum for downloaded file: {dest_path}")
                return False
            
            # Compare file sizes
            if actual_checksum['file_size'] != expected_checksum['file_size']:
                logger.error(f"P2P download size mismatch: expected {expected_checksum['file_size']}, got {actual_checksum['file_size']}")
                return False
            
            # For small files, compare full_hash
            if 'full_hash' in expected_checksum:
                if 'full_hash' not in actual_checksum:
                    logger.error(f"P2P download checksum format mismatch: expected full_hash, got partial checksum")
                    return False
                if actual_checksum['full_hash'].lower() != expected_checksum['full_hash'].lower():
                    logger.error(f"P2P download checksum mismatch: expected {expected_checksum['full_hash']}, got {actual_checksum['full_hash']}")
                    return False
            else:
                # For large files, compare beginning_hash and end_hash
                if 'beginning_hash' not in actual_checksum or 'end_hash' not in actual_checksum:
                    logger.error(f"P2P download checksum format mismatch: expected partial checksum, got full_hash")
                    return False
                if actual_checksum['beginning_hash'].lower() != expected_checksum['beginning_hash'].lower():
                    logger.error(f"P2P download beginning hash mismatch: expected {expected_checksum['beginning_hash']}, got {actual_checksum['beginning_hash']}")
                    return False
                if actual_checksum['end_hash'].lower() != expected_checksum['end_hash'].lower():
                    logger.error(f"P2P download end hash mismatch: expected {expected_checksum['end_hash']}, got {actual_checksum['end_hash']}")
                    return False
            
            logger.info(f"Checksum verification passed")
        
        logger.info(f"Successfully downloaded file from peer: {dest_path} ({total_bytes_downloaded} bytes)")
        return True
        
    except requests.exceptions.HTTPError as e:
        # For 404 errors, return a special value to indicate the file doesn't exist on this peer
        if e.response and e.response.status_code == 404:
            logger.warning(f"P2P download failed from {peer_url}: File not found (404)")
            return None  # Return None to indicate 404 (file doesn't exist on this peer)
        logger.warning(f"P2P download failed from {peer_url}: {e}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"P2P download failed from {peer_url}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during P2P download: {e}", exc_info=True)
        return False

def try_p2p_download_from_list(p2p_peers, system, rom_path, game_id, dest_path, expected_size, expected_checksum, paused_ref, download_id, bytes_transferred_ref, client_p2p_port_accessible=None):
    """Try to download a file via P2P from a list of peers.
    
    Attempts to download from peers in the provided list (already sorted by upload bandwidth).
    Falls back to server download if all peers fail.
    
    Args:
        p2p_peers: List of peer dictionaries, each containing: external_ip, external_port, token_id
        system: System identifier
        rom_path: ROM file path (relative to system directory)
        game_id: Game ID
        dest_path: Destination file path
        expected_size: Expected file size in bytes (optional)
        expected_checksum: Expected checksum data (dictionary from server)
        paused_ref: Optional list to check if download should be paused
        download_id: Download ID for progress reporting (optional)
        bytes_transferred_ref: Optional list to track bytes transferred
        client_p2p_port_accessible: Client's own port accessibility status (True/False/None), if known from peer list
    
    Returns:
        token_id (int) of the successful peer if download succeeded via P2P, False otherwise (should fall back to server)
    """
    # Set up progress reporting thread if download_id and bytes_transferred_ref are provided
    progress_thread_running = False
    progress_thread = None
    
    try:
        if not p2p_peers:
            logger.debug(f"No P2P peers provided for {system}/{rom_path}")
            return False
        
        logger.info(f"Attempting P2P download for {system}/{rom_path} from {len(p2p_peers)} peer(s)")
        
        # Check if file already exists and is complete - verify checksum before trying any peers
        if os.path.exists(dest_path):
            existing_size = os.path.getsize(dest_path)
            if expected_size and existing_size == expected_size:
                # File already complete - verify checksum before deciding to re-download
                logger.info(f"File already exists with correct size ({existing_size} bytes), verifying checksum...")
                if expected_checksum:
                    actual_checksum = calculate_partial_checksum(dest_path)
                    if actual_checksum:
                        # Compare file sizes
                        if actual_checksum['file_size'] == expected_checksum['file_size']:
                            # For small files, compare full_hash
                            if 'full_hash' in expected_checksum:
                                if 'full_hash' in actual_checksum:
                                    if actual_checksum['full_hash'].lower() == expected_checksum['full_hash'].lower():
                                        logger.info(f"File already complete and checksum verified - skipping download")
                                        # Return first peer's token_id if available, otherwise True
                                        if p2p_peers and p2p_peers[0].get('token_id') is not None:
                                            return p2p_peers[0].get('token_id')
                                        return True  # File is valid, no need to download
                                    else:
                                        logger.warning(f"File exists but checksum mismatch - will re-download")
                                        try:
                                            os.remove(dest_path)
                                            logger.info(f"Deleted existing file with mismatched checksum: {dest_path}")
                                        except Exception as e:
                                            logger.warning(f"Failed to delete existing file: {e}")
                                else:
                                    logger.warning(f"Could not calculate full_hash for existing file - will re-download")
                                    try:
                                        os.remove(dest_path)
                                    except Exception:
                                        pass
                            else:
                                # For large files, compare beginning_hash and end_hash
                                if 'beginning_hash' in actual_checksum and 'end_hash' in actual_checksum:
                                    if (actual_checksum['beginning_hash'].lower() == expected_checksum['beginning_hash'].lower() and
                                        actual_checksum['end_hash'].lower() == expected_checksum['end_hash'].lower()):
                                        logger.info(f"File already complete and checksum verified - skipping download")
                                        # Return first peer's token_id if available, otherwise True
                                        if p2p_peers and p2p_peers[0].get('token_id') is not None:
                                            return p2p_peers[0].get('token_id')
                                        return True  # File is valid, no need to download
                                    else:
                                        logger.warning(f"File exists but checksum mismatch - will re-download")
                                        try:
                                            os.remove(dest_path)
                                            logger.info(f"Deleted existing file with mismatched checksum: {dest_path}")
                                        except Exception as e:
                                            logger.warning(f"Failed to delete existing file: {e}")
                                else:
                                    logger.warning(f"Could not calculate partial checksum for existing file - will re-download")
                                    try:
                                        os.remove(dest_path)
                                    except Exception:
                                        pass
                        else:
                            logger.warning(f"File size mismatch in checksum - will re-download")
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass
                    else:
                        logger.warning(f"Could not calculate checksum for existing file - will re-download")
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                else:
                    # No checksum available - assume file is valid if size matches
                    logger.info(f"File already complete (no checksum to verify) - skipping download")
                    # Return first peer's token_id if available, otherwise True
                    if p2p_peers and p2p_peers[0].get('token_id') is not None:
                        return p2p_peers[0].get('token_id')
                    return True  # File size matches, assume it's valid
            elif expected_size and existing_size > expected_size:
                # File is larger than expected - might be corrupted, delete it
                logger.warning(f"File exists but is larger than expected ({existing_size} > {expected_size}) - deleting")
                try:
                    os.remove(dest_path)
                    logger.info(f"Deleted oversized file: {dest_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete existing file: {e}")
        
        # Determine initial resume point (before starting downloads)
        initial_resume_from = 0
        if os.path.exists(dest_path):
            existing_size = os.path.getsize(dest_path)
            if expected_size and existing_size < expected_size:
                initial_resume_from = existing_size
        
        # Set up progress reporting thread if download_id and bytes_transferred_ref are provided
        if download_id and bytes_transferred_ref is not None:
            import threading
            import time
            progress_thread_running = True
            total_bytes_transferred = initial_resume_from
            last_report_time = time.time()
            
            def progress_reporter():
                """Background thread to report progress periodically."""
                nonlocal total_bytes_transferred, last_report_time, progress_thread_running
                while progress_thread_running:
                    time.sleep(5.0)  # Report every 5 seconds
                    
                    if not progress_thread_running:
                        break
                    
                    elapsed = time.time() - last_report_time
                    if elapsed > 0:
                        # Accumulate bytes from this session into total
                        total_bytes_transferred += bytes_transferred_ref[0]
                        
                        if bytes_transferred_ref[0] > 0:
                            bytes_per_second = int(bytes_transferred_ref[0] / elapsed)
                        else:
                            bytes_per_second = 0
                        
                        # Report progress - check return value
                        if not progress_thread_running:
                            break
                        
                        try:
                            progress_result = report_progress(download_id, total_bytes_transferred, bytes_per_second)
                            if progress_result is None:
                                # Download was removed from queue (likely completed) - stop reporting
                                logger.debug(f"Download {download_id} was removed from queue (likely completed), stopping progress reporter")
                                progress_thread_running = False
                                break
                            elif progress_result is False:
                                # Download is paused
                                logger.info(f"Download {download_id} is paused - stopping progress reporter")
                                if paused_ref:
                                    paused_ref[0] = True
                                progress_thread_running = False
                                break
                        except requests.exceptions.HTTPError as e:
                            # Handle HTTP errors - check if it's a 410 Gone (download completed/removed)
                            if e.response and e.response.status_code == 410:
                                logger.debug(f"Progress report returned 410 Gone - download {download_id} was removed from queue (likely completed)")
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
                        bytes_transferred_ref[0] = 0
            
            progress_thread = threading.Thread(target=progress_reporter, daemon=True)
            progress_thread.start()
        
        # Try each peer in the list (already sorted by upload bandwidth)
        for peer_idx, peer in enumerate(p2p_peers):
            # Check if download is paused
            if paused_ref and paused_ref[0]:
                logger.info("P2P download paused")
                return False
            
            external_ip = peer.get('external_ip')
            external_port = peer.get('external_port')
            
            if not external_ip or not external_port:
                logger.warning(f"Peer {peer_idx + 1} missing external_ip or external_port: {peer}")
                continue
            
            # Build peer URL
            peer_url = f"http://{external_ip}:{external_port}"
            
            logger.info(f"Trying peer {peer_idx + 1}/{len(p2p_peers)}: {peer_url}")
            
            # Determine resume point (file may have been partially downloaded from previous peer attempt)
            resume_from = 0
            if os.path.exists(dest_path):
                existing_size = os.path.getsize(dest_path)
                if expected_size and existing_size < expected_size:
                    resume_from = existing_size
                    logger.info(f"Resuming P2P download from byte {resume_from}")
            
            # Check if peer's port is known to be inaccessible - skip direct download and try reverse connection
            peer_port_accessible = peer.get('p2p_port_accessible', True)  # Default to True for backwards compatibility
            source_token_id = peer.get('token_id')
            
            # Store p2p_remote_token_id in Redis at the start of P2P download
            # This enables cancellation notifications and active uploads display
            if download_id and source_token_id:
                store_p2p_remote_token_in_redis(download_id, source_token_id)
            
            if peer_port_accessible is False:
                # Peer's port is known to be closed - skip direct download attempt
                logger.info(f"Peer {peer_idx + 1} port is not accessible (p2p_port_accessible=False), skipping direct download")
                
                # Check if we can do reverse connection
                if client_p2p_port_accessible is True and source_token_id:
                    logger.info(f"Attempting reverse connection directly (Client A port is accessible)")
                    reverse_result = try_reverse_p2p_download(
                        source_token_id=source_token_id,
                        system=system,
                        rom_path=rom_path,
                        dest_path=dest_path,
                        resume_from=resume_from,
                        expected_size=expected_size,
                        expected_checksum=expected_checksum,
                        download_id=download_id,
                        bytes_transferred_ref=bytes_transferred_ref,
                        paused_ref=paused_ref
                    )
                    
                    if reverse_result:
                        logger.info(f"Successfully downloaded via reverse P2P connection from peer {source_token_id}")
                        # Stop progress reporting thread before returning
                        if progress_thread_running:
                            progress_thread_running = False
                            if progress_thread:
                                progress_thread.join(timeout=1)
                        # Report final progress
                        if download_id and bytes_transferred_ref and os.path.exists(dest_path):
                            final_size = os.path.getsize(dest_path)
                            if final_size > 0:
                                try:
                                    report_progress(download_id, final_size, 0)
                                except Exception as e:
                                    logger.debug(f"Final progress report failed: {e}")
                        return source_token_id
                    else:
                        # Check if it failed due to pause - if so, stop entirely
                        if paused_ref and paused_ref[0]:
                            logger.info(f"Reverse P2P connection stopped due to pause - not retrying")
                            if progress_thread_running:
                                progress_thread_running = False
                                if progress_thread:
                                    progress_thread.join(timeout=1)
                            return False
                        logger.warning(f"Reverse P2P connection failed for peer {source_token_id}, trying next peer")
                elif client_p2p_port_accessible is False:
                    logger.warning(f"Peer port not accessible and Client A port also not accessible, cannot do P2P with this peer, trying next peer")
                elif client_p2p_port_accessible is None:
                    logger.warning(f"Peer port not accessible and Client A port accessibility unknown, skipping this peer")
                else:
                    logger.warning(f"Peer port not accessible but missing token_id, cannot try reverse connection, trying next peer")
                
                # Delete partial/corrupted file if any
                if os.path.exists(dest_path):
                    try:
                        file_size_before_delete = os.path.getsize(dest_path)
                        os.remove(dest_path)
                        logger.info(f"Deleted partial/corrupted file after P2P failure: {dest_path} ({file_size_before_delete} bytes)")
                    except Exception as del_err:
                        logger.warning(f"Failed to delete partial file {dest_path}: {del_err}")
                continue
            
            # Peer's port is accessible (or unknown) - try direct download
            result = download_file_via_p2p(
                peer_url=peer_url,
                system=system,
                rom_path=rom_path,
                dest_path=dest_path,
                resume_from=resume_from,
                expected_size=expected_size,
                expected_checksum=expected_checksum,
                paused_ref=paused_ref,
                download_id=download_id,
                bytes_transferred_ref=bytes_transferred_ref
            )
            
            if result is True:
                logger.info(f"Successfully downloaded via P2P from {peer_url}")
                # Stop progress reporting thread before returning
                if progress_thread_running:
                    progress_thread_running = False
                    if progress_thread:
                        progress_thread.join(timeout=1)
                # Report final progress
                if download_id and bytes_transferred_ref and os.path.exists(dest_path):
                    final_size = os.path.getsize(dest_path)
                    if final_size > 0:
                        try:
                            report_progress(download_id, final_size, 0)
                        except Exception as e:
                            logger.debug(f"Final progress report failed: {e}")
                peer_token_id = peer.get('token_id')
                return peer_token_id if peer_token_id is not None else True
            elif result is None:
                # 404 error - file doesn't exist on this peer, try next peer
                logger.warning(f"P2P download failed from {peer_url}: File not found (404), trying next peer")
                # Delete partial file if download failed
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                continue
            else:
                # Direct download failed - check if it was due to pause
                if paused_ref and paused_ref[0]:
                    logger.info(f"P2P download from {peer_url} stopped due to pause - not retrying")
                    # Stop progress reporting thread
                    if progress_thread_running:
                        progress_thread_running = False
                        if progress_thread:
                            progress_thread.join(timeout=1)
                    return False
                
                # Direct download failed - peer_port_accessible was True (or unknown) but connection still failed
                # This could be a network issue, temporary failure, or the port check was wrong
                # Try reverse connection as fallback if client's port is accessible
                if client_p2p_port_accessible is True and source_token_id:
                    logger.warning(f"P2P download failed from {peer_url} (connection error despite port being accessible), attempting reverse connection as fallback")
                    reverse_result = try_reverse_p2p_download(
                        source_token_id=source_token_id,
                        system=system,
                        rom_path=rom_path,
                        dest_path=dest_path,
                        resume_from=resume_from,
                        expected_size=expected_size,
                        expected_checksum=expected_checksum,
                        download_id=download_id,
                        bytes_transferred_ref=bytes_transferred_ref,
                        paused_ref=paused_ref
                    )
                    
                    if reverse_result:
                        logger.info(f"Successfully downloaded via reverse P2P connection from peer {source_token_id}")
                        # Stop progress reporting thread before returning
                        if progress_thread_running:
                            progress_thread_running = False
                            if progress_thread:
                                progress_thread.join(timeout=1)
                        # Report final progress
                        if download_id and bytes_transferred_ref and os.path.exists(dest_path):
                            final_size = os.path.getsize(dest_path)
                            if final_size > 0:
                                try:
                                    report_progress(download_id, final_size, 0)
                                except Exception as e:
                                    logger.debug(f"Final progress report failed: {e}")
                        return source_token_id
                    else:
                        # Check if it failed due to pause - if so, stop entirely
                        if paused_ref and paused_ref[0]:
                            logger.info(f"Reverse P2P connection (fallback) stopped due to pause - not retrying")
                            if progress_thread_running:
                                progress_thread_running = False
                                if progress_thread:
                                    progress_thread.join(timeout=1)
                            return False
                        logger.warning(f"Reverse P2P connection also failed for peer {source_token_id}, trying next peer")
                else:
                    logger.warning(f"P2P download failed from {peer_url} (connection error), trying next peer")
                
                # Delete partial file if download failed
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                continue
        
        logger.info(f"All P2P attempts failed for {system}/{rom_path}, falling back to server download")
        return False
        
    except Exception as e:
        logger.error(f"Error during P2P download attempt: {e}", exc_info=True)
        return False
    finally:
        # Stop progress reporting thread (only if it was started)
        if progress_thread_running:
            progress_thread_running = False
            if progress_thread:
                progress_thread.join(timeout=1)

# ============================================================================
# End of P2P Download Helper Functions
# ============================================================================

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
        download_id = download_info['download_id']  # Download ID for URL construction
        game_id = download_info['game_id']  # Resolved game_id - used for destination paths
        system = download_info.get('system', '')  # System ID (e.g., "atari2600") - used for API calls
        batocera_system = download_info.get('batocera_system', '')  # Batocera system directory name - used for local paths
        game_details = download_info.get('game_details', {})  # Full game data with original paths
        expected_file_size = download_info.get('file_size')
        bytes_already_transferred = download_info.get('bytes_transferred', 0)
        http_url = download_info.get('file_url')  # HTTP URL provided by backend (uses download_id)
        
        # Validate required fields
        if not http_url:
            logger.error(f"Missing file_url in download_info")
            return False
        
        if not system or not game_id:
            logger.error(f"Missing system or game_id: system={system}, game_id={game_id}")
            return False
        
        # Backend now resolves unified ROM keys automatically based on platform
        # No client-side resolution needed
        
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
        
        # Prepare server path for checksum request (preserve snapshot path for releases)
        # Server stores release files in .zfs/snapshot/vX/ directory, so we need the full path
        # P2P clients store files without snapshot path, so clean_original_path is used for P2P transfers
        # Use removeprefix instead of lstrip to preserve .zfs prefix (lstrip would corrupt .zfs to zfs)
        server_rom_path = game_id.removeprefix('./')
        # Remove system prefix if present, but preserve snapshot path
        if server_rom_path.startswith(f"{system}/"):
            server_rom_path = server_rom_path[len(system) + 1:]
        
        target_system = batocera_system
        
        logger.info(f"Downloading via HTTP")
        logger.info(f"  HTTP URL: {http_url}")
        logger.info(f"  Download ID: {download_id}")
        logger.info(f"  Game ID: {game_id}")
        logger.info(f"  Original Path: {original_path}")
        logger.info(f"  Clean Path: {clean_original_path}")
        logger.info(f"  System: {system}")
        logger.info(f"  Batocera System: {target_system}")
        
        # Check if save_location is provided (for .psvita files and .psn files on Windows)
        save_location = download_info.get('save_location')
        # Check if config_location is provided (for .psn files on Linux)
        config_location = download_info.get('config_location')
        
        if config_location:
            # Use CONFIGDIR with config_location for .psn files on Linux
            if not CONFIGDIR:
                logger.error(f"Received config_location '{config_location}' but CONFIGDIR is not configured")
                raise ValueError("CONFIGDIR must be configured for .psn files on Linux")
            logger.info(f"Received config_location from backend: '{config_location}'")
            logger.info(f"CONFIGDIR is: '{CONFIGDIR}'")
            dest_base_path = os.path.join(CONFIGDIR, config_location)
            logger.info(f"Using config_location, destination base path: {dest_base_path}")
        elif save_location:
            # Use SAVEDIR with save_location for special save files (.psvita files and .psn files on Windows)
            logger.info(f"Received save_location from backend: '{save_location}'")
            logger.info(f"SAVEDIR is: '{SAVEDIR}'")
            dest_base_path = os.path.join(SAVEDIR, save_location)
            logger.info(f"Using save_location, destination base path: {dest_base_path}")
        else:
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
                        logger.info(f"[*] {download_type} download detected: {len(files_list)} files, {dir_info.get('total_size', 0)} bytes")
                        
                        # For special files with base_path_type='file' (.m3u, .cue, etc.),
                        # dest_base_path should be the directory containing the source file
                        # (not the file itself, since relative_path values are relative to the file's directory)
                        # BUT: If save_location or config_location is provided (e.g., for .psvita or .psn files), don't adjust it
                        # because save_location/config_location already contains the correct target directory path
                        if base_path_type == 'file' and not save_location and not config_location:
                            # dest_base_path currently points to the source file, change it to its directory
                            dest_base_path = os.path.dirname(dest_base_path)
                            logger.info(f"Adjusted dest_base_path for {source_file} to directory: {dest_base_path}")
                        elif base_path_type == 'file' and (save_location or config_location):
                            location_type = "save_location" if save_location else "config_location"
                            logger.info(f"Using {location_type} for {source_file}, dest_base_path remains: {dest_base_path}")
                        
                        # Extract base URL from http_url
                        from urllib.parse import urlparse
                        parsed = urlparse(http_url)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        
                        paused = [False]
                        # Register this download's pause_ref so WebSocket notifications can pause it immediately
                        _active_download_pause_refs[download_id] = paused
                        try:
                            # Pass 0 as bytes_already_transferred - download_directory_recursive will calculate from local files
                            success = download_directory_recursive(
                                download_id, system, game_id, base_url, dest_base_path,
                                files_list, 0, paused, download_info  # Pass download_info for download_id in URLs
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
        
        # Single file download
        # Check if P2P is enabled - if not, skip P2P and use server download
        p2p_enabled = download_info.get('p2p_enabled', False)
        if not p2p_enabled:
            logger.info("P2P downloads are disabled - using server download")
        
        dest_path = dest_base_path
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Try P2P download if enabled (before checking file existence for resume)
        p2p_download_success = False
        p2p_peers = download_info.get('p2p_peers', [])
        logger.info(f"Download {download_id}: P2P check - p2p_enabled={p2p_enabled}, p2p_peers count={len(p2p_peers) if p2p_peers else 0}")
        if p2p_enabled and p2p_peers:
            # Set up pause tracking for P2P download
            paused = [False]
            _active_download_pause_refs[download_id] = paused
            bytes_transferred_this_session = [0]
            
            try:
                logger.info(f"Attempting P2P download for {target_system}/{clean_original_path} from {len(p2p_peers)} peer(s)")
                
                # Get checksum from server first
                # Use server_rom_path which includes snapshot path for releases (server stores files in snapshot)
                # P2P transfers use clean_original_path (without snapshot) since clients don't have snapshot paths
                expected_checksum = get_server_checksum(system, server_rom_path)
                if not expected_checksum:
                    logger.warning(f"Could not get checksum from server for {system}/{server_rom_path}, skipping P2P")
                    p2p_download_success = False
                else:
                    logger.info(f"Retrieved checksum from server: file_size={expected_checksum.get('file_size')}")
                    
                    # Get client's port accessibility from download_info (provided by backend)
                    client_p2p_port_accessible = download_info.get('client_p2p_port_accessible')
                    
                    if client_p2p_port_accessible is None:
                        logger.warning(f"client_p2p_port_accessible is None in download_info for download_id {download_id}, cannot determine if reverse P2P is possible")
                    
                    p2p_result = try_p2p_download_from_list(
                        p2p_peers=p2p_peers,
                        system=target_system,
                        rom_path=clean_original_path,
                        game_id=game_id,
                        dest_path=dest_path,
                        expected_size=expected_file_size,
                        expected_checksum=expected_checksum,
                        paused_ref=paused,
                        download_id=download_id,
                        bytes_transferred_ref=bytes_transferred_this_session,
                        client_p2p_port_accessible=client_p2p_port_accessible
                    )
                    # p2p_result is token_id (int) if successful P2P download, True if file already existed (no transfer), False otherwise
                    p2p_download_success = bool(p2p_result)
                    # Only track P2P stats if we have an actual token_id (int), not True (file already existed)
                    p2p_remote_token_id = p2p_result if isinstance(p2p_result, int) else None
                    logger.info(f"P2P download result for download_id={download_id}: p2p_result={p2p_result} (type={type(p2p_result).__name__}), p2p_download_success={p2p_download_success}, p2p_remote_token_id={p2p_remote_token_id}")
                
                if p2p_download_success:
                    logger.info(f"P2P download successful for {target_system}/{clean_original_path}")
                    # Clean up pause_ref
                    if download_id in _active_download_pause_refs:
                        del _active_download_pause_refs[download_id]
                    # Close file_response if we have one (no longer needed)
                    if file_response:
                        file_response.close()
                        file_response = None
                else:
                    logger.info(f"P2P download failed, falling back to server download for {target_system}/{clean_original_path}")
                    # Clean up pause_ref (will be recreated for server download)
                    if download_id in _active_download_pause_refs:
                        del _active_download_pause_refs[download_id]
            except Exception as e:
                logger.error(f"Error during P2P download attempt: {e}", exc_info=True)
                p2p_download_success = False
                # Clean up pause_ref on error
                if download_id in _active_download_pause_refs:
                    del _active_download_pause_refs[download_id]
        else:
            if not p2p_enabled:
                logger.info(f"Download {download_id}: P2P not attempted - P2P is disabled")
            elif not p2p_peers:
                logger.info(f"Download {download_id}: P2P not attempted - No P2P peers available")
        
        # If P2P download succeeded, skip server download and proceed with media/gamelist
        if p2p_download_success:
            # Verify file size
            if os.path.exists(dest_path) and os.path.isfile(dest_path):
                final_size = os.path.getsize(dest_path)
                if expected_file_size and final_size != expected_file_size:
                    logger.error(f"P2P downloaded file size mismatch: {final_size} != {expected_file_size}")
                    # Delete corrupted file
                    try:
                        os.remove(dest_path)
                    except Exception as e:
                        logger.error(f"Failed to delete corrupted file: {e}")
                    # Report error and fall back to server
                    error_msg = f"P2P downloaded file size mismatch: {final_size} != {expected_file_size}"
                    mark_error(download_id, error_msg)
                    p2p_download_success = False  # Fall back to server download
                else:
                    # P2P download successful - download media and update gamelist
                    logger.info(f"Successfully downloaded via P2P: {game_id}")
                    logger.info(f"  Destination: {dest_path}")
                    logger.info(f"  Size: {final_size} bytes ({final_size / (1024*1024):.2f} MB)")
                    
                    # Download media files and update gamelist.xml after successful P2P download
                    media_and_gamelist_success = False
                    try:
                        logger.info(f"P2P download completed successfully, downloading media files for {game_id}")
                        downloaded_media, game_data = download_game_media(system, game_id, download_id, batocera_system=target_system)
                        
                        # Use game_data returned from download_game_media
                        if game_data:
                            # Update gamelist.xml with game entry
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
                    
                    # Store p2p_remote_token_id in download_info for mark_completed
                    # Note: p2p_remote_token_id is already stored in Redis at the start of P2P download
                    if p2p_remote_token_id is not None:
                        download_info['p2p_remote_token_id'] = p2p_remote_token_id
                        logger.info(f"P2P download successful: p2p_remote_token_id={p2p_remote_token_id} for download_id={download_id}")
                    else:
                        logger.warning(f"P2P download successful but p2p_remote_token_id is None for download_id={download_id} (p2p_result was {p2p_result})")
                    return True
            else:
                logger.error(f"P2P downloaded file not found: {dest_path}")
                p2p_download_success = False  # Fall back to server download
        
        # If P2P download failed or was disabled, continue with server download (existing code below)

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

def mark_completed(download_id, download_info=None):
    """Mark a download as completed in the queue and send logs.
    
    Args:
        download_id: Download ID
        download_info: Optional download info dict (used to pass p2p_remote_token_id)
                       Note: Backend handles p2p_index registration automatically
    """
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
        
        # Get p2p_remote_token_id from download_info if provided
        if download_info and 'p2p_remote_token_id' in download_info:
            p2p_remote_token_id = download_info.get('p2p_remote_token_id')
            if p2p_remote_token_id is not None:
                data['p2p_remote_token_id'] = p2p_remote_token_id
                logger.info(f"mark_completed: Including p2p_remote_token_id={p2p_remote_token_id} for download_id={download_id}")
            else:
                logger.info(f"mark_completed: p2p_remote_token_id in download_info but is None for download_id={download_id}")
        else:
            if download_info:
                logger.info(f"mark_completed: download_info provided but no 'p2p_remote_token_id' key for download_id={download_id}, keys={list(download_info.keys())}")
            else:
                logger.info(f"mark_completed: No download_info provided for download_id={download_id}")
        
        logger.info(f"mark_completed: Sending completion request for download_id={download_id} with data keys: {list(data.keys())}")
        response = http_session.post(
            f"{API_URL}/api/download/complete",
            json=data,
            headers=headers
        )
        
        # Check for 404 before raising - download may have already been removed/completed
        # This can happen if the backend auto-completes the download or it was removed
        if response.status_code == 404:
            logger.debug(f"Download {download_id} already removed from queue (404) - treating as success since download completed locally")
            return True  # Treat as success since download is completed locally
        
        response.raise_for_status()
        logger.info(f"Marked download {download_id} as completed")
        
        # Note: Backend now handles p2p_index registration automatically in complete_download
        # No need to call add_rom_to_p2p_inventory here anymore
        
        return True
    except requests.exceptions.HTTPError as e:
        # Handle other HTTP errors (shouldn't reach here for 404 since we handle it above, but keep as fallback)
        if e.response and e.response.status_code == 404:
            logger.debug(f"Download {download_id} already removed from queue (404 in exception handler) - treating as success")
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
            mark_completed(download_info['download_id'], download_info)
        else:
            logger.error(f"Failed to download {download_info.get('game_id', 'Unknown')}")
    except Exception as e:
        logger.error(f"Error in process_queue: {e}", exc_info=True)

async def periodic_gamelist_upload():
    """Periodically upload gamelist.xml files and P2P inventory every 24 hours."""
    while True:
        try:
            # Wait 24 hours (86400 seconds)
            await asyncio.sleep(86400)
            logger.info("Starting periodic gamelist.xml upload (24h interval)")
            # Run upload in executor since it's synchronous
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, upload_all_gamelist_files)
            # Also upload P2P inventory
            logger.info("Starting periodic P2P inventory upload (24h interval)")
            await loop.run_in_executor(None, upload_p2p_inventory)
        except asyncio.CancelledError:
            logger.info("Periodic gamelist upload task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in periodic gamelist upload: {e}", exc_info=True)

async def websocket_client():
    """WebSocket client for receiving download notifications."""
    # Start periodic upload task (runs every 24 hours) when WebSocket client starts
    periodic_task = asyncio.create_task(periodic_gamelist_upload())
    
    try:
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
        
        base_delay = 60  # Base delay of 60 seconds
        backoff_delay = 0  # Backoff starts at 0, will increase on each reconnection
        max_backoff_delay = 240  # Max backoff of 240 seconds (4 minutes), total max will be 60+240=300s
        random_jitter_max = 30  # Random jitter up to 30 seconds
        is_first_connection = True  # Track if this is the first connection (upload gamelist only on first connection)
        
        while True:
            try:
                # Set max_size to 10MB to handle larger archive chunks (default is 1MB)
                async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as websocket:
                    logger.info("WebSocket connected successfully")
                    backoff_delay = 0  # Reset backoff to 0 on successful connection
                    
                    # Store websocket and event loop globally for use by download functions
                    with _websocket_lock:
                        global _active_websocket, _websocket_event_loop, _websocket_recv_lock
                        _active_websocket = websocket
                        _websocket_event_loop = asyncio.get_event_loop()
                        # Initialize async lock for coordinating message reception
                        if _websocket_recv_lock is None:
                            _websocket_recv_lock = asyncio.Lock()
                    
                    try:
                        # Handle messages
                        while True:
                            try:
                                # Skip receiving if archive download is active (archive handler will receive)
                                if _archive_download_active:
                                    await asyncio.sleep(0.1)  # Short sleep to avoid busy waiting
                                    continue
                                
                                # Acquire lock before receiving to coordinate with archive downloads
                                async with _websocket_recv_lock:
                                    # Wait for messages with timeout for ping handling
                                    message = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                                
                                # Check if message is bytes (binary) or str (JSON)
                                if isinstance(message, bytes):
                                    # Binary message - could be archive data
                                    # This will be handled by the archive download handler
                                    # For now, we'll let download_directory_as_tar handle it directly
                                    continue
                                
                                try:
                                    data = json.loads(message)
                                    message_type = data.get("type")
                                    
                                    if message_type == "connected":
                                        logger.info(f"WebSocket connection confirmed: {data.get('message', '')}")
                                        token_id = data.get("token_id")
                                        if token_id:
                                            logger.info(f"Connected with token_id: {token_id}")
                                        
                                        # Declare global variable at the start of this handler
                                        global _p2p_connection_info
                                        
                                        # Check if UPnP should be skipped (custom public port configured)
                                        skip_upnp = data.get("skip_upnp", False)
                                        
                                        # Set up UPnP port mapping if not skipped (only on first connection)
                                        if P2P_CLIENT_AVAILABLE and is_first_connection:
                                            if skip_upnp:
                                                logger.info("Skipping UPnP setup: custom public port is configured for this token")
                                                # Initialize P2P connection info without UPnP
                                                _p2p_connection_info = {
                                                    "external_ip": None,
                                                    "external_port": None,
                                                    "internal_port": P2P_PORT,
                                                    "upnp_enabled": False
                                                }
                                            else:
                                                # Set up UPnP port mapping
                                                try:
                                                    logger.info("Setting up UPnP port mapping for P2P server...")
                                                    await setup_upnp_port_mapping(P2P_PORT)
                                                    # setup_upnp_port_mapping updates _p2p_connection_info globally
                                                    if _p2p_connection_info.get("upnp_enabled"):
                                                        logger.info("UPnP port mapping setup completed successfully")
                                                    else:
                                                        logger.info("UPnP port mapping setup skipped or failed (service will continue without UPnP)")
                                                except Exception as e:
                                                    logger.error(f"Error setting up UPnP port mapping: {e}", exc_info=True)
                                                    logger.info("Continuing without UPnP port mapping...")
                                                    # Initialize P2P connection info without UPnP if not already set
                                                    if not _p2p_connection_info.get("upnp_enabled"):
                                                        _p2p_connection_info = {
                                                            "external_ip": None,
                                                            "external_port": None,
                                                            "internal_port": P2P_PORT,
                                                            "upnp_enabled": False
                                                        }
                                        
                                        # Register P2P client connection info on each WebSocket connection
                                        if P2P_CLIENT_AVAILABLE:
                                            try:
                                                # Use stored UPnP info, or default to internal port only
                                                if _p2p_connection_info.get("internal_port"):
                                                    await register_p2p_client(
                                                        external_ip=_p2p_connection_info.get("external_ip"),
                                                        external_port=_p2p_connection_info.get("external_port"),
                                                        internal_port=_p2p_connection_info.get("internal_port"),
                                                        upnp_enabled=_p2p_connection_info.get("upnp_enabled", False)
                                                    )
                                            except Exception as e:
                                                logger.error(f"Error registering P2P client on WebSocket connection: {e}", exc_info=True)
                                        
                                        # Send startup logs on first connection
                                        if is_first_connection:
                                            logger.info("First connection detected - sending startup logs to server...")
                                            try:
                                                # Run in executor since it's a synchronous function
                                                loop = asyncio.get_event_loop()
                                                await loop.run_in_executor(None, send_startup_logs, token_id)
                                            except Exception as e:
                                                logger.error(f"Error sending startup logs on first connection: {e}", exc_info=True)
                                        
                                        # Upload all gamelist.xml files and P2P inventory only on first connection (not on reconnections)
                                        if is_first_connection:
                                            logger.info("First connection detected - uploading all local gamelist.xml files to server...")
                                            try:
                                                # Run in executor since it's a synchronous function
                                                loop = asyncio.get_event_loop()
                                                await loop.run_in_executor(None, upload_all_gamelist_files)
                                            except Exception as e:
                                                logger.error(f"Error uploading gamelist.xml files on first connection: {e}", exc_info=True)
                                            logger.info("First connection detected - uploading P2P inventory to server...")
                                            try:
                                                # Run in executor since it's a synchronous function
                                                loop = asyncio.get_event_loop()
                                                await loop.run_in_executor(None, upload_p2p_inventory)
                                            except Exception as e:
                                                logger.error(f"Error uploading P2P inventory on first connection: {e}", exc_info=True)
                                            is_first_connection = False  # Mark that first connection upload is done
                                        else:
                                            logger.debug("Reconnection detected - skipping gamelist.xml and P2P inventory upload (will upload after 24h)")
                                        
                                        # Check if bandwidth test is needed
                                        bandwidth_test_needed = data.get("bandwidth_test_needed", False)
                                        if bandwidth_test_needed:
                                            logger.info("Bandwidth test requested by server")
                                            # Perform bandwidth test in background (don't block WebSocket)
                                            asyncio.create_task(perform_bandwidth_test())
                                        
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
                                    
                                    elif message_type == "archive_start":
                                        # Archive download started - client should prepare to receive binary data
                                        download_id = data.get("download_id")
                                        logger.info(f"Archive download started via WebSocket: download_id={download_id}")
                                        # The binary data will come in subsequent binary messages
                                    
                                    elif message_type == "archive_complete":
                                        # Archive download completed
                                        download_id = data.get("download_id")
                                        logger.info(f"Archive download completed via WebSocket: download_id={download_id}")
                                    
                                    elif message_type == "archive_error":
                                        # Archive download error
                                        download_id = data.get("download_id")
                                        error = data.get("error", "Unknown error")
                                        logger.error(f"Archive download error via WebSocket: download_id={download_id}, error={error}")
                                    
                                    elif message_type == "reverse_p2p_download":
                                        # Reverse P2P download request - push file to another client
                                        target_token_id = data.get("target_token_id")
                                        target_ip = data.get("target_ip")
                                        target_port = data.get("target_port")
                                        target_path = data.get("target_path", "/reverse/")  # URL path for reverse connection
                                        system = data.get("system")
                                        rom_path = data.get("rom_path")
                                        resume_from = data.get("resume_from", 0)
                                        expected_size = data.get("expected_size")
                                        expected_checksum = data.get("expected_checksum")  # For validation before upload
                                        download_id = data.get("download_id")
                                        request_id = data.get("request_id")  # For feedback mechanism
                                        
                                        logger.info(f"Received reverse P2P download request: push {system}/{rom_path} to {target_ip}:{target_port}{target_path} (resume_from={resume_from}, request_id={request_id}, has_checksum={expected_checksum is not None})")
                                        
                                        # Handle reverse connection in a separate thread to avoid blocking WebSocket
                                        import threading
                                        reverse_thread = threading.Thread(
                                            target=handle_reverse_p2p_upload,
                                            args=(target_ip, target_port, target_path, system, rom_path, resume_from, expected_size, expected_checksum, download_id, request_id, target_token_id),
                                            daemon=True
                                        )
                                        reverse_thread.start()
                                    
                                    elif message_type == "reverse_p2p_result":
                                        # Result of reverse P2P upload from Client B
                                        request_id = data.get("request_id")
                                        upload_success = data.get("success", False)
                                        error_msg = data.get("error_message")
                                        
                                        if upload_success:
                                            logger.info(f"Reverse P2P upload succeeded for request_id={request_id}")
                                        else:
                                            logger.warning(f"Reverse P2P upload failed for request_id={request_id}: {error_msg}")
                                            # Mark the request as failed so try_reverse_p2p_download can stop waiting
                                            from p2p_client import mark_reverse_connection_failed
                                            mark_reverse_connection_failed(request_id, error_msg)
                                    
                                    elif message_type == "p2p_download_cancelled":
                                        # Remote client cancelled their download - stop any active reverse P2P upload for this download_id
                                        # Note: For normal P2P, the upload stops when the connection is closed (no action needed here)
                                        cancelled_download_id = data.get("download_id")
                                        cancel_message = data.get("message", "Download cancelled")
                                        
                                        if cancelled_download_id:
                                            logger.info(f"Received p2p_download_cancelled notification for download_id={cancelled_download_id}: {cancel_message}")
                                            # This only affects reverse P2P uploads - normal P2P uploads stop when connection closes
                                            cancel_reverse_upload(cancelled_download_id)
                                        else:
                                            logger.warning(f"Received p2p_download_cancelled but no download_id provided")
                                    
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
                            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as e:
                                # Connection closed - handle gracefully
                                close_code = getattr(e, 'code', None)
                                close_reason = getattr(e, 'reason', 'Unknown reason')
                                
                                # 1012 (service restart) is expected when server restarts - not an error
                                if close_code == 1012:
                                    logger.info(f"WebSocket connection closed by server (service restart) - will reconnect")
                                else:
                                    logger.info(f"WebSocket connection closed (code: {close_code}, reason: {close_reason})")
                                break  # Exit inner loop to trigger reconnection
                    finally:
                        # Ensure websocket and event loop are cleared on exit
                        with _websocket_lock:
                            _active_websocket = None
                            _websocket_event_loop = None
            except websockets.exceptions.InvalidStatusCode as e:
                # Handle HTTP status codes from WebSocket handshake
                # Clear websocket references
                with _websocket_lock:
                    _active_websocket = None
                    _websocket_event_loop = None
                
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
                elif e.status_code in [502, 503, 504]:
                    # 502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout
                    # These are retryable errors (server/reverse proxy issues)
                    logger.warning(f"WebSocket connection failed with HTTP {e.status_code} (server temporarily unavailable) - will retry")
                else:
                    # Other HTTP errors - log and retry (not fatal unless authentication-related)
                    logger.warning(f"WebSocket connection failed with HTTP {e.status_code} - will retry")
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as e:
                # Check if connection was closed due to rejection (code 4002)
                close_code = getattr(e, 'code', None)
                close_reason = getattr(e, 'reason', 'Unknown reason')
                
                if close_code == 4002:
                    logger.critical("=" * 80)
                    logger.critical("FATAL ERROR: Connection rejected by server")
                    logger.critical("=" * 80)
                    logger.critical(f"Reason: {close_reason or 'Another instance is already connected'}")
                    logger.critical("Only one download service instance can be connected with this token at a time.")
                    logger.critical("Please stop the other instance before starting this one.")
                    logger.critical("=" * 80)
                    sys.exit(1)
                elif close_code == 4003:
                    logger.critical("=" * 80)
                    logger.critical("FATAL ERROR: Too many consecutive invalid token attempts")
                    logger.critical("=" * 80)
                    logger.critical("The server has rejected this client after 3 consecutive authentication failures.")
                    logger.critical("Please verify your API_TOKEN.txt file contains a valid token.")
                    logger.critical("The download service will now stop.")
                    logger.critical("=" * 80)
                    sys.exit(1)
                elif close_code == 1012:
                    # 1012 (service restart) is expected when server restarts - not an error, just reconnect
                    logger.info(f"WebSocket connection closed by server (service restart, code 1012) - will reconnect")
                else:
                    logger.info(f"WebSocket connection closed (code: {close_code}, reason: {close_reason}) - will reconnect")
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)
            
            # Reconnect with exponential backoff + random jitter
            # Calculate delay: base (60s) + backoff + random jitter
            random_jitter = random.uniform(0, random_jitter_max)
            reconnect_delay = base_delay + backoff_delay + random_jitter
            
            logger.info(f"Reconnecting in {reconnect_delay:.1f} seconds (base: {base_delay}s, backoff: {backoff_delay:.1f}s, jitter: {random_jitter:.1f}s)...")
            await asyncio.sleep(reconnect_delay)
            
            # Increase backoff exponentially (double it) up to max_backoff_delay
            backoff_delay = min(backoff_delay * 2 if backoff_delay > 0 else base_delay, max_backoff_delay)
    
    finally:
        # Cancel periodic task when exiting
        periodic_task.cancel()
        try:
            await periodic_task
        except asyncio.CancelledError:
            pass


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
                # Pass download_info to include p2p_remote_token_id for P2P stats
                await loop.run_in_executor(None, lambda: mark_completed(download_info['download_id'], download_info))
            else:
                logger.error(f"Failed to download {download_info.get('game_id', 'Unknown')}")
        else:
            logger.debug("No download available after notification")
    except Exception as e:
        logger.error(f"Error handling download notification: {e}", exc_info=True)


async def perform_bandwidth_test():
    """Perform bandwidth test using internetspeedtest library and submit results to backend.
    
    This function is called when the server requests a bandwidth test.
    Runs in background without blocking WebSocket operations.
    """
    try:
        logger.info("Starting bandwidth test...")
        
        # Import internetspeedtest library
        try:
            from internetspeedtest import SpeedTest
        except ImportError:
            logger.error("internetspeedtest library not available, skipping bandwidth test")
            return
        
        # Run bandwidth test in executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_bandwidth_test_sync)
        
        if result:
            upload_mbps, download_mbps = result
            logger.info(f"Bandwidth test completed: upload={upload_mbps:.2f} Mbits/s, download={download_mbps:.2f} Mbits/s")
            
            # Submit results to backend
            await submit_bandwidth_test_results(upload_mbps, download_mbps)
        else:
            logger.warning("Bandwidth test failed, not submitting results")
            
    except Exception as e:
        logger.error(f"Error performing bandwidth test: {e}", exc_info=True)

def _run_bandwidth_test_sync():
    """Synchronous wrapper for bandwidth test (runs in executor).

    Returns:
        Tuple of (upload_mbps, download_mbps) or None on error
    """
    try:
        from internetspeedtest import SpeedTest

        st = SpeedTest()

        # Get available servers
        servers = st.get_servers()
        if not servers:
            logger.error("No speedtest servers available")
            return None

        # Find the best server
        best_server = st.find_best_server(servers)
        if not best_server:
            logger.error("Could not find best server for speed test")
            return None

        server_name = getattr(best_server, 'name', None) or getattr(best_server, 'host', None) or 'Unknown'
        logger.info(f"Running bandwidth test against server: {server_name}")

        # download() and upload() return (speed_mbps, bytes_transferred)
        download_mbps, _ = st.download(best_server)
        upload_mbps, _ = st.upload(best_server)

        return (upload_mbps, download_mbps)

    except Exception as e:
        logger.error(f"Error in bandwidth test: {e}", exc_info=True)
        return None

async def submit_bandwidth_test_results(upload_bandwidth: float, download_bandwidth: float):
    """Submit bandwidth test results to backend.
    
    Args:
        upload_bandwidth: Upload speed in Mbits/s
        download_bandwidth: Download speed in Mbits/s
    """
    try:
        url = f"{API_URL}/api/download/bandwidth-test"
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "upload_bandwidth": upload_bandwidth,
            "download_bandwidth": download_bandwidth
        }
        
        response = http_session.post(url, json=data, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if result.get("success"):
            logger.info(f"Successfully submitted bandwidth test results: upload={upload_bandwidth:.2f} Mbits/s, download={download_bandwidth:.2f} Mbits/s")
        else:
            logger.warning(f"Backend returned success=false for bandwidth test submission: {result.get('message', 'Unknown error')}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to submit bandwidth test results: {e}")
    except Exception as e:
        logger.error(f"Error submitting bandwidth test results: {e}", exc_info=True)

async def register_p2p_client(external_ip: str, external_port: int, internal_port: int, upnp_enabled: bool):
    """Register P2P client connection info with backend.
    
    Args:
        external_ip: External IP address (from UPnP)
        external_port: External port (same as internal for UPnP)
        internal_port: Internal port (P2P port)
        upnp_enabled: Whether UPnP is enabled
    
    Returns:
        True if successful, False otherwise
    """
    try:
        import requests
        import json
        
        url = f"{API_URL}/api/download/p2p/register"
        headers = {
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        }
        data = {
            'external_ip': external_ip,
            'external_port': external_port,
            'internal_port': internal_port,
            'upnp_enabled': upnp_enabled
        }
        
        logger.info(f"Registering P2P client with backend: {external_ip}:{external_port}, UPnP: {upnp_enabled}")
        response = requests.post(url, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        if result.get('success'):
            logger.info(f"P2P client registered successfully with backend")
            return True
        else:
            logger.warning(f"P2P client registration returned non-success: {result}")
            return False
            
    except Exception as e:
        logger.error(f"Error registering P2P client with backend: {e}", exc_info=True)
        return False


async def setup_upnp_port_mapping(port: int):
    """Set up UPnP port mapping for P2P server.
    
    Args:
        port: Port number to forward
        
    Returns:
        UPnPHelper instance if successful, None otherwise
    """
    if not UPNP_HELPER_AVAILABLE:
        logger.info("UPnP helper not available, skipping UPnP port mapping setup")
        return None
    
    try:
        logger.info(f"Starting UPnP port mapping setup for port {port}...")
        upnp_helper = get_upnp_helper()
        
        # Check if UPnP is available
        if not upnp_helper.is_available():
            logger.info("UPnP library not available (miniupnpc not installed), skipping UPnP setup")
            return None
        
        # Discover router
        logger.info("UPnP: Discovering router...")
        router_discovered = await upnp_helper.discover_router()
        if not router_discovered:
            logger.warning("UPnP: Router discovery failed, continuing without UPnP port mapping")
            return None
        
        logger.info("UPnP: Router discovered successfully")
        
        # Get external IP
        logger.info("UPnP: Getting external IP address...")
        external_ip = await upnp_helper.get_external_ip()
        if external_ip:
            logger.info(f"UPnP: External IP address: {external_ip}")
        else:
            logger.warning("UPnP: Could not get external IP address")
            return None
        
        # Add port mapping with service name in description
        hostname = socket.gethostname()
        description = f"RGS-{hostname}"
        logger.info(f"UPnP: Adding port mapping for port {port} with description: {description}")
        mapping_success = await upnp_helper.add_port_mapping(
            internal_port=port,
            external_port=port,
            description=description
        )
        
        if mapping_success:
            # Get the actual external port (may differ from requested port if there was a conflict)
            actual_external_port = upnp_helper.external_port or port
            if actual_external_port != port:
                logger.info(f"UPnP: Port mapping added successfully on port {actual_external_port} (requested {port} was in use)")
            else:
                logger.info(f"UPnP: Port mapping added successfully (port {port})")
            
            # Store UPnP connection info globally (will be used for each WebSocket connection)
            global _p2p_connection_info
            _p2p_connection_info = {
                "external_ip": external_ip,
                "external_port": actual_external_port,
                "internal_port": port,
                "upnp_enabled": True
            }
            
            return upnp_helper
        else:
            logger.warning(f"UPnP: Failed to add port mapping for port {port}")
            return None
            
    except Exception as e:
        logger.error(f"UPnP: Error during port mapping setup: {e}", exc_info=True)
        return None


def main():
    """Main function to run the download service."""
    global _p2p_connection_info
    
    if not API_TOKEN:
        logger.error("API_TOKEN not set in environment variables")
        logger.error("Please set API_TOKEN in your .env file")
        return

    logger.info(f"Starting download service (Service ID: {SERVICE_ID})...")
    ensure_directories()
    
    # Start P2P server if available
    p2p_server_started = False
    upnp_helper = None
    if P2P_CLIENT_AVAILABLE:
        try:
            logger.info(f"Starting P2P server on port {P2P_PORT}...")
            get_p2p_server(ROMS_PATH, P2P_PORT)
            p2p_server_started = True
            logger.info(f"P2P server started successfully on port {P2P_PORT}")
            
            # Initialize P2P connection info (UPnP setup will happen after WebSocket connection)
            _p2p_connection_info = {
                "external_ip": None,
                "external_port": None,
                "internal_port": P2P_PORT,
                "upnp_enabled": False
            }
        except Exception as e:
            logger.error(f"Failed to start P2P server: {e}", exc_info=True)
            logger.warning("Continuing without P2P server...")
    else:
        logger.info("P2P server not available (p2p_client module not found)")
    
    # Run WebSocket client
    try:
        asyncio.run(websocket_client())
    except KeyboardInterrupt:
        logger.info("Shutting down download service...")
    except Exception as e:
        logger.error(f"Fatal error in download service: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Remove UPnP port mapping on shutdown
        if upnp_helper and UPNP_HELPER_AVAILABLE:
            try:
                logger.info(f"UPnP: Removing port mapping for port {P2P_PORT}...")
                asyncio.run(upnp_helper.delete_port_mapping(P2P_PORT))
                logger.info(f"UPnP: Port mapping removed successfully (port {P2P_PORT})")
            except Exception as e:
                logger.error(f"UPnP: Error removing port mapping: {e}", exc_info=True)
        
        # Stop P2P server on shutdown
        if p2p_server_started and P2P_CLIENT_AVAILABLE:
            try:
                logger.info("Stopping P2P server...")
                stop_p2p_server()
                logger.info("P2P server stopped")
            except Exception as e:
                logger.error(f"Error stopping P2P server: {e}", exc_info=True)

if __name__ == "__main__":
    main() 
