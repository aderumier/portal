"""P2P client service for serving ROM files to other clients."""
import os
import logging
import threading
import hashlib
import socket
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from pathlib import Path
import json
import re

logger = logging.getLogger(__name__)

# Global P2P server instance
_p2p_server = None
_p2p_server_lock = threading.Lock()


# Global dictionary to store pending reverse connection requests
# Key: request_id (string), Value: dict with dest_path, expected_size, resume_from, success_ref
_reverse_connection_requests = {}
_reverse_connection_lock = threading.Lock()

def create_p2p_handler(roms_path, api_url=None, api_token=None):
    """Factory function to create P2P request handler with roms_path and optional API credentials."""
    class P2PRequestHandler(BaseHTTPRequestHandler):
        """HTTP request handler for P2P file serving."""
        
        # Socket timeout for each request (seconds)
        # This prevents blocking forever if connection dies mid-transfer
        timeout = 60
        
        def _verify_download_id(self, download_id, system, rom_path):
            """Verify download_id exists in Redis via backend API.
            
            Returns True if download_id is valid and matches system/rom_path, False otherwise.
            """
            if not api_url or not api_token:
                # If API credentials not available, skip verification (backwards compatibility)
                logger.debug(f"API credentials not available for download_id verification")
                return True
            
            try:
                import requests
                verify_url = f"{api_url}/api/download/verify-p2p-download"
                headers = {
                    'Authorization': f'Bearer {api_token}',
                    'Content-Type': 'application/json'
                }
                data = {
                    'download_id': download_id,
                    'system': system,
                    'rom_path': rom_path
                }
                
                # Use short timeout for verification (2 seconds)
                response = requests.post(verify_url, json=data, headers=headers, timeout=2)
                if response.status_code == 200:
                    result = response.json()
                    return result.get('valid', False)
                else:
                    logger.debug(f"Download verification returned status {response.status_code}")
                    return False
            except ImportError:
                # requests not available - allow request (backwards compatibility)
                logger.debug(f"requests library not available for download verification")
                return True
            except requests.exceptions.Timeout:
                logger.warning(f"Download verification timeout for download_id {download_id}")
                # On timeout, allow the request (fail open for availability)
                return True
            except Exception as e:
                logger.warning(f"Error verifying download_id {download_id}: {e}")
                # On error, allow the request (fail open for availability)
                return True
        
        def do_GET(self):
            """Handle GET requests for file serving and checksums."""
            try:
                parsed_path = urlparse(self.path)
                path_parts = parsed_path.path.strip('/').split('/')
                
                if len(path_parts) < 2:
                    self.send_error(400, "Invalid path")
                    return
                
                if path_parts[0] == 'p2p':
                    if len(path_parts) >= 3 and path_parts[1] == 'checksum':
                        # GET /p2p/checksum/{system}/{rom_path}
                        self._handle_checksum(path_parts[2:], roms_path)
                    elif len(path_parts) >= 3 and path_parts[1] == 'file':
                        # GET /p2p/file/{system}/{rom_path}
                        self._handle_file(path_parts[2:], roms_path)
                    else:
                        self.send_error(404, "Not found")
                else:
                    self.send_error(404, "Not found")
                    
            except Exception as e:
                logger.error(f"Error handling P2P request: {e}", exc_info=True)
                try:
                    self.send_error(500, "Internal server error")
                except Exception:
                    pass  # Connection may be closed
        
        def do_PUT(self):
            """Handle PUT requests for reverse P2P connections."""
            self._handle_reverse_connection()
        
        def do_POST(self):
            """Handle POST requests for reverse P2P connections."""
            self._handle_reverse_connection()
        
        def _handle_reverse_connection(self):
            """Handle reverse P2P connection upload."""
            try:
                # Parse request path: /reverse/{request_id}
                parsed_path = urlparse(self.path)
                path_parts = parsed_path.path.strip('/').split('/')
                
                if len(path_parts) < 2 or path_parts[0] != 'reverse':
                    self.send_error(404, "Not found")
                    return
                
                request_id = path_parts[1]
                
                # Look up reverse connection request
                with _reverse_connection_lock:
                    request_info = _reverse_connection_requests.get(request_id)
                
                if not request_info:
                    logger.warning(f"Reverse connection request not found: {request_id}")
                    self.send_error(404, "Request not found")
                    return
                
                dest_path = request_info['dest_path']
                expected_size = request_info.get('expected_size')
                resume_from = request_info.get('resume_from', 0)
                success_ref = request_info.get('success_ref')
                download_id = request_info.get('download_id')
                system = request_info.get('system')
                rom_path = request_info.get('rom_path')
                bytes_transferred_ref = request_info.get('bytes_transferred_ref')
                last_activity_ref = request_info.get('last_activity_ref')
                
                logger.info(f"Reverse connection request found: request_id={request_id}, expected_size={expected_size}, resume_from={resume_from}, dest_path={dest_path}")
                
                # Verify download_id if available (P2P security check)
                if download_id and system and rom_path:
                    if not self._verify_download_id(download_id, system, rom_path):
                        logger.warning(f"Reverse P2P request rejected: download_id {download_id} verification failed for {system}/{rom_path}")
                        self.send_error(403, "Download verification failed")
                        return
                
                # Check for chunked transfer encoding (required)
                transfer_encoding = self.headers.get('Transfer-Encoding', '').lower()
                is_chunked = transfer_encoding == 'chunked'
                expect_100_continue = self.headers.get('Expect', '').lower() == '100-continue'
                
                # Require chunked transfer encoding
                if not is_chunked:
                    logger.warning("Reverse connection: Chunked transfer encoding required")
                    self.send_response(400, "Transfer-Encoding: chunked required")
                    self.end_headers()
                    return
                
                # Handle resume: check existing file size if resume_from > 0
                mode = 'r+b' if resume_from > 0 and os.path.exists(dest_path) else 'wb'
                bytes_written = 0
                
                # Send initial HTTP 100 Continue if Expect: 100-continue header is present
                if expect_100_continue:
                    self.send_response_only(100)  # HTTP 100 Continue
                    self.end_headers()
                    logger.debug("Sent initial HTTP 100 Continue response")
                
                with open(dest_path, mode) as f:
                    if resume_from > 0:
                        # Truncate to resume position and seek there
                        f.truncate(resume_from)
                        f.seek(resume_from)
                        bytes_written = resume_from
                    
                    # Parse chunked transfer encoding
                    chunk_count = 0
                    total_received = 0
                    
                    while True:
                        # Read chunk size line (hex number + \r\n)
                        chunk_size_line = b''
                        while b'\r\n' not in chunk_size_line:
                            byte = self.rfile.read(1)
                            if not byte:
                                raise Exception("Connection closed while reading chunk size")
                            chunk_size_line += byte
                        
                        # Parse chunk size (hex)
                        chunk_size_str = chunk_size_line.strip().decode('ascii', errors='ignore')
                        if not chunk_size_str:
                            continue
                        
                        try:
                            chunk_size = int(chunk_size_str, 16)
                        except ValueError:
                            raise Exception(f"Invalid chunk size: {chunk_size_str}")
                        
                        # Final chunk (size 0)
                        if chunk_size == 0:
                            # Read trailing \r\n
                            self.rfile.read(2)
                            break
                        
                        # Read chunk data (read exactly chunk_size bytes)
                        chunk_data = b''
                        while len(chunk_data) < chunk_size:
                            to_read = chunk_size - len(chunk_data)
                            data = self.rfile.read(to_read)
                            if not data:
                                raise Exception("Connection closed while reading chunk data")
                            chunk_data += data
                        
                        # Read trailing \r\n after chunk data
                        trailing = self.rfile.read(2)
                        if trailing != b'\r\n':
                            raise Exception(f"Invalid chunk format: expected \\r\\n after chunk data")
                        
                        # Write chunk data to file
                        f.write(chunk_data)
                        bytes_written += len(chunk_data)
                        chunk_count += 1
                        total_received += len(chunk_data)
                        
                        # Update bytes_transferred_ref for progress reporting
                        if bytes_transferred_ref is not None:
                            bytes_transferred_ref[0] += len(chunk_data)
                        
                        # Update last_activity_ref for per-chunk timeout tracking
                        if last_activity_ref is not None:
                            import time as time_module
                            last_activity_ref[0] = time_module.time()
                        
                        # Send HTTP 100 Continue after each chunk
                        # This resets the timeout on Client B's side and provides per-chunk acknowledgment
                        if expect_100_continue:
                            try:
                                self.send_response_only(100)  # HTTP 100 Continue
                                self.end_headers()
                                logger.debug(f"Sent HTTP 100 Continue acknowledgment after chunk {chunk_count} ({total_received} bytes received, chunk size: {len(chunk_data)} bytes)")
                            except Exception as e:
                                logger.warning(f"Failed to send HTTP 100 Continue: {e}")
                                # Continue anyway
                
                # Verify file size if expected_size provided
                if expected_size and bytes_written != expected_size:
                    logger.error(f"Reverse connection: File size mismatch: received {bytes_written}, expected {expected_size} (resume_from={resume_from}, total_received={total_received})")
                    # Delete the corrupted oversized file
                    try:
                        os.remove(dest_path)
                        logger.info(f"Deleted corrupted file after size mismatch: {dest_path}")
                    except Exception as del_err:
                        logger.warning(f"Failed to delete corrupted file {dest_path}: {del_err}")
                    self.send_response(400, "File size mismatch")
                    self.end_headers()
                    return
                
                # Mark as successful
                if success_ref is not None:
                    success_ref[0] = True
                
                # Remove request from dictionary
                with _reverse_connection_lock:
                    _reverse_connection_requests.pop(request_id, None)
                
                # Success response
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({"success": True, "bytes_received": bytes_written})
                self.wfile.write(response.encode('utf-8'))
                
                logger.info(f"Reverse connection: Received {bytes_written} bytes and saved to {dest_path}")
                
            except socket.timeout as e:
                logger.warning(f"Reverse connection timed out (socket timeout): {e}")
                try:
                    self.send_error(408, "Request timeout")
                except Exception:
                    pass
            except ConnectionResetError as e:
                logger.warning(f"Reverse connection reset by peer: {e}")
            except BrokenPipeError as e:
                logger.warning(f"Reverse connection broken pipe: {e}")
            except Exception as e:
                logger.error(f"Error handling reverse connection request: {e}", exc_info=True)
                try:
                    self.send_error(500, "Internal server error")
                except Exception:
                    pass
        
        def log_message(self, format, *args):
            """Override to use our logger instead of stderr."""
            logger.debug(f"P2P HTTP {self.address_string()} - {format % args}")
        
        def _handle_checksum(self, path_parts, roms_path):
            """Handle partial SHA-256 checksum request: /p2p/checksum/{system}/{rom_path}"""
            try:
                if len(path_parts) < 2:
                    self.send_error(400, "Invalid path")
                    return
                
                system = unquote(path_parts[0])
                rom_path = unquote('/'.join(path_parts[1:]))
                
                # Build file path
                file_path = os.path.join(roms_path, system, rom_path.lstrip('./'))
                
                # Security check: ensure path is within ROMS_PATH
                try:
                    roms_path_abs = os.path.abspath(roms_path)
                    file_path_abs = os.path.abspath(file_path)
                    if not file_path_abs.startswith(roms_path_abs):
                        self.send_error(403, "Access denied")
                        return
                except Exception:
                    self.send_error(403, "Access denied")
                    return
                
                if not os.path.exists(file_path) or not os.path.isfile(file_path):
                    self.send_error(404, "File not found")
                    return
                
                # Compute partial SHA-256 checksum
                checksum_data = self._calculate_partial_checksum(file_path)
                
                # Return JSON response
                response = {
                    "success": True,
                    "checksum": checksum_data,
                    "system": system,
                    "rom_path": rom_path
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
            except Exception as e:
                logger.error(f"Error handling checksum request: {e}", exc_info=True)
                try:
                    self.send_error(500, "Internal server error")
                except Exception:
                    pass
        
        def _calculate_partial_checksum(self, file_path, chunk_size=2097152):
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
            """
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
        
        def _handle_file(self, path_parts, roms_path):
            """Handle file download request: /p2p/file/{system}/{rom_path}"""
            try:
                if len(path_parts) < 2:
                    self.send_error(400, "Invalid path")
                    return
                
                system = unquote(path_parts[0])
                rom_path = unquote('/'.join(path_parts[1:]))
                
                # Verify download_id if provided (P2P security check)
                download_id_header = self.headers.get('X-Download-ID')
                if download_id_header:
                    try:
                        download_id = int(download_id_header)
                        if not self._verify_download_id(download_id, system, rom_path):
                            logger.warning(f"P2P request rejected: download_id {download_id} verification failed for {system}/{rom_path}")
                            self.send_error(403, "Download verification failed")
                            return
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid X-Download-ID header: {download_id_header}, error: {e}")
                        self.send_error(400, "Invalid download ID")
                        return
                else:
                    # If no download_id provided, log warning but allow (backwards compatibility)
                    logger.debug(f"P2P request without X-Download-ID header for {system}/{rom_path}")
                
                # Build file path
                file_path = os.path.join(roms_path, system, rom_path.lstrip('./'))
                
                # Security check: ensure path is within ROMS_PATH
                try:
                    roms_path_abs = os.path.abspath(roms_path)
                    file_path_abs = os.path.abspath(file_path)
                    if not file_path_abs.startswith(roms_path_abs):
                        self.send_error(403, "Access denied")
                        return
                except Exception:
                    self.send_error(403, "Access denied")
                    return
                
                if not os.path.exists(file_path) or not os.path.isfile(file_path):
                    self.send_error(404, "File not found")
                    return
                
                # Get file size
                file_size = os.path.getsize(file_path)
                
                # Handle Range requests for resume support
                range_header = self.headers.get('Range')
                start_byte = 0
                end_byte = file_size - 1
                
                if range_header:
                    # Parse Range header: "bytes=start-end" or "bytes=start-"
                    match = re.match(r'bytes=(\d+)-(\d*)', range_header)
                    if match:
                        start_byte = int(match.group(1))
                        if match.group(2):
                            end_byte = int(match.group(2))
                        else:
                            end_byte = file_size - 1
                
                content_length = end_byte - start_byte + 1
                
                # Send response
                if range_header:
                    self.send_response(206)  # Partial Content
                    self.send_header('Content-Range', f'bytes {start_byte}-{end_byte}/{file_size}')
                else:
                    self.send_response(200)
                
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(content_length))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                
                # Send file content
                with open(file_path, 'rb') as f:
                    f.seek(start_byte)
                    remaining = content_length
                    while remaining > 0:
                        chunk_size = min(8192, remaining)  # 8KB chunks
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                        
            except Exception as e:
                logger.error(f"Error handling file request: {e}", exc_info=True)
                try:
                    self.send_error(500, "Internal server error")
                except Exception:
                    pass
    
    return P2PRequestHandler


class P2PServer:
    """P2P server for serving ROM files to other clients."""
    
    def __init__(self, roms_path, port=8765):
        self.roms_path = roms_path
        self.port = port
        self.server = None
        self.server_thread = None
        self._running = False
    
    def start(self):
        """Start the P2P server."""
        if self._running:
            logger.warning("P2P server is already running")
            return
        
        try:
            # Create handler class with roms_path and API credentials bound
            # Import here to avoid circular imports
            try:
                from download_service import API_URL, API_TOKEN
                api_url = API_URL
                api_token = API_TOKEN
            except ImportError:
                # If import fails, use None (verification will be skipped)
                api_url = None
                api_token = None
                logger.debug("Could not import API_URL/API_TOKEN for P2P verification")
            
            HandlerClass = create_p2p_handler(self.roms_path, api_url=api_url, api_token=api_token)
            # Use ThreadingHTTPServer to handle multiple concurrent requests
            # This prevents a stuck handler from blocking all other requests
            self.server = ThreadingHTTPServer(('', self.port), HandlerClass)
            # Set socket timeout to detect dead connections faster
            self.server.socket.settimeout(60)
            self._running = True
            
            # Start server in a separate thread
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            logger.info(f"P2P server started on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start P2P server: {e}", exc_info=True)
            self._running = False
            raise
    
    def _run_server(self):
        """Run the HTTP server."""
        try:
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"P2P server error: {e}", exc_info=True)
        finally:
            self._running = False
    
    def stop(self):
        """Stop the P2P server."""
        if not self._running:
            return
        
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            self._running = False
            logger.info("P2P server stopped")
        except Exception as e:
            logger.error(f"Error stopping P2P server: {e}", exc_info=True)
    
    def is_running(self):
        """Check if server is running."""
        return self._running
    
    def get_port(self):
        """Get the server port."""
        return self.port


def get_p2p_server(roms_path, port=8765):
    """Get or create global P2P server instance."""
    global _p2p_server
    
    with _p2p_server_lock:
        if _p2p_server is None or not _p2p_server.is_running():
            _p2p_server = P2PServer(roms_path, port)
            _p2p_server.start()
        return _p2p_server


def stop_p2p_server():
    """Stop the global P2P server."""
    global _p2p_server
    
    with _p2p_server_lock:
        if _p2p_server:
            _p2p_server.stop()
            _p2p_server = None


# Global reverse connection listener instance
_reverse_listener = None
_reverse_listener_lock = threading.Lock()


def create_reverse_handler(dest_path, expected_size=None, resume_from=0, success_ref=None):
    """Factory function to create reverse connection handler with dest_path.
    
    Args:
        dest_path: Destination file path
        expected_size: Expected file size (optional)
        resume_from: Byte position to resume from
        success_ref: List to store success flag [False] - will be set to True on success
    """
    class ReverseConnectionHandler(BaseHTTPRequestHandler):
        """HTTP request handler for receiving files via reverse P2P connection."""
        
        def do_PUT(self):
            """Handle PUT requests for receiving file data (reverse connection)."""
            self.do_POST()  # Use same logic as POST
        
        def do_POST(self):
            """Handle POST requests for receiving file data (reverse connection)."""
            try:
                # Get content length
                content_length = int(self.headers.get('Content-Length', 0))
                
                if content_length == 0:
                    logger.warning("Reverse connection: Received request with Content-Length=0")
                    self.send_response(400, "Content-Length required")
                    self.end_headers()
                    return
                
                # Handle resume: check existing file size if resume_from > 0
                mode = 'r+b' if resume_from > 0 and os.path.exists(dest_path) else 'wb'
                bytes_written = 0
                
                with open(dest_path, mode) as f:
                    if resume_from > 0:
                        # Truncate to resume position and seek there
                        f.truncate(resume_from)
                        f.seek(resume_from)
                        bytes_written = resume_from
                    
                    # Read and write file data
                    remaining = content_length
                    while remaining > 0:
                        chunk_size = min(8192, remaining)  # 8KB chunks
                        chunk = self.rfile.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_written += len(chunk)
                        remaining -= len(chunk)
                
                # Verify file size if expected_size provided
                if expected_size and bytes_written != expected_size:
                    logger.error(f"Reverse connection: File size mismatch: received {bytes_written}, expected {expected_size}")
                    self.send_response(400, "File size mismatch")
                    self.end_headers()
                    return
                
                # Mark as successful
                if success_ref is not None:
                    success_ref[0] = True
                
                # Success response
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({"success": True, "bytes_received": bytes_written})
                self.wfile.write(response.encode('utf-8'))
                
                logger.info(f"Reverse connection: Received {bytes_written} bytes and saved to {dest_path}")
                
            except Exception as e:
                logger.error(f"Error handling reverse connection request: {e}", exc_info=True)
                try:
                    self.send_error(500, "Internal server error")
                except Exception:
                    pass
        
        def log_message(self, format, *args):
            """Override to use our logger instead of stderr."""
            logger.debug(f"Reverse P2P HTTP {self.address_string()} - {format % args}")
    
    return ReverseConnectionHandler


class ReverseConnectionListener:
    """Temporary HTTP listener for receiving files via reverse P2P connection."""
    
    def __init__(self, dest_path, expected_size=None, resume_from=0, port=0):
        """Initialize reverse connection listener.
        
        Args:
            dest_path: Destination file path where received data will be saved
            expected_size: Expected file size in bytes (optional)
            resume_from: Byte position to resume from (default: 0)
            port: Port to listen on (0 = auto-assign)
        """
        self.dest_path = dest_path
        self.expected_size = expected_size
        self.resume_from = resume_from
        self.port = port
        self.server = None
        self.server_thread = None
        self._running = False
        self.actual_port = None
        self.bytes_received = 0
        self.success = False
        self.success_ref = [False]  # Shared reference for handler to update
    
    def start_listening(self):
        """Start the reverse connection listener (non-blocking).
        
        Returns:
            actual_port: The port the server is listening on, or None on error
        """
        if self._running:
            logger.warning("Reverse connection listener is already running")
            return self.actual_port
        
        try:
            # Create handler class with dest_path bound and success reference
            HandlerClass = create_reverse_handler(self.dest_path, self.expected_size, self.resume_from, self.success_ref)
            self.server = HTTPServer(('', self.port), HandlerClass)
            self.actual_port = self.server.server_address[1]
            self._running = True
            self.success = False
            self.success_ref[0] = False
            
            logger.info(f"Reverse connection listener started on port {self.actual_port} for {self.dest_path}")
            
            # Start server in a separate thread
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            return self.actual_port
            
        except Exception as e:
            logger.error(f"Failed to start reverse connection listener: {e}", exc_info=True)
            self._running = False
            self.stop()
            return None
    
    def wait_for_connection(self, timeout=300):
        """Wait for reverse connection to complete.
        
        Args:
            timeout: Maximum time to wait for connection (seconds)
            
        Returns:
            True if file was received successfully, False otherwise
        """
        if not self._running:
            return False
        
        import time
        start_time = time.time()
        while self._running and not self.success_ref[0]:
            if time.time() - start_time > timeout:
                logger.warning(f"Reverse connection listener timeout after {timeout}s")
                break
            time.sleep(0.1)
        
        # Update success from reference
        self.success = self.success_ref[0]
        
        # Clean up
        self.stop()
        
        return self.success
    
    def _run_server(self):
        """Run the HTTP server (called in thread)."""
        try:
            # Set a timeout for the server socket (1 second for polling)
            self.server.socket.settimeout(1.0)
            
            # Keep handling requests until success or timeout
            while self._running and not self.success_ref[0]:
                try:
                    # Handle one request (the file transfer)
                    self.server.handle_request()
                except socket.timeout:
                    # Timeout is expected - continue waiting (check will happen in start())
                    continue
                except OSError as e:
                    # Server closed - break
                    if self._running:
                        logger.debug(f"Reverse connection listener socket error: {e}")
                    break
                except Exception as e:
                    logger.error(f"Reverse connection listener error handling request: {e}", exc_info=True)
                    break
            
            # Check if file was written
            if os.path.exists(self.dest_path):
                self.bytes_received = os.path.getsize(self.dest_path)
        except Exception as e:
            logger.error(f"Reverse connection listener error: {e}", exc_info=True)
        finally:
            self._running = False
    
    def stop(self):
        """Stop the reverse connection listener."""
        if not self._running:
            return
        
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            self._running = False
            logger.info(f"Reverse connection listener stopped (port {self.actual_port})")
        except Exception as e:
            logger.error(f"Error stopping reverse connection listener: {e}", exc_info=True)


def get_local_ip():
    """Get local IP address for reverse connections."""
    try:
        import socket
        # Connect to a remote address (doesn't actually send data)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # Fallback to localhost
        return "127.0.0.1"

def register_reverse_connection_request(request_id, dest_path, expected_size=None, resume_from=0, success_ref=None, failed_ref=None, download_id=None, system=None, rom_path=None, bytes_transferred_ref=None, last_activity_ref=None):
    """Register a reverse connection request.
    
    Args:
        request_id: Unique request identifier
        dest_path: Destination file path
        expected_size: Expected file size (optional)
        resume_from: Byte position to resume from
        success_ref: List to store success flag [False]
        failed_ref: List to store failure flag [False] - set when upload fails
        download_id: Download ID for verification (optional)
        system: System identifier for verification (optional)
        rom_path: ROM path for verification (optional)
        bytes_transferred_ref: Optional list to track bytes transferred for progress reporting
        last_activity_ref: Optional list to track last activity time for per-chunk timeout
    """
    with _reverse_connection_lock:
        _reverse_connection_requests[request_id] = {
            'dest_path': dest_path,
            'expected_size': expected_size,
            'resume_from': resume_from,
            'success_ref': success_ref or [False],
            'failed_ref': failed_ref or [False],
            'download_id': download_id,
            'system': system,
            'rom_path': rom_path,
            'bytes_transferred_ref': bytes_transferred_ref,
            'last_activity_ref': last_activity_ref
        }

def mark_reverse_connection_failed(request_id, error_message=None):
    """Mark a reverse connection request as failed.
    
    Called when Client B reports that the upload failed.
    
    Args:
        request_id: Unique request identifier
        error_message: Error message from Client B (optional)
        
    Returns:
        True if request was found and marked, False otherwise
    """
    with _reverse_connection_lock:
        request_info = _reverse_connection_requests.get(request_id)
        if request_info:
            failed_ref = request_info.get('failed_ref')
            if failed_ref is not None:
                failed_ref[0] = True
                # Store error message for later retrieval
                request_info['error_message'] = error_message
                logger.info(f"Marked reverse connection request {request_id} as failed: {error_message}")
                return True
    return False

def get_reverse_connection_error(request_id):
    """Get the error message for a failed reverse connection request.
    
    Args:
        request_id: Unique request identifier
        
    Returns:
        Error message string or None
    """
    with _reverse_connection_lock:
        request_info = _reverse_connection_requests.get(request_id)
        if request_info:
            return request_info.get('error_message')
    return None

def unregister_reverse_connection_request(request_id):
    """Unregister a reverse connection request.
    
    Args:
        request_id: Unique request identifier
    """
    with _reverse_connection_lock:
        _reverse_connection_requests.pop(request_id, None)
