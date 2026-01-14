"""P2P client service for serving ROM files to other clients."""
import os
import logging
import threading
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from pathlib import Path
import json
import re

logger = logging.getLogger(__name__)

# Global P2P server instance
_p2p_server = None
_p2p_server_lock = threading.Lock()


def create_p2p_handler(roms_path):
    """Factory function to create P2P request handler with roms_path."""
    class P2PRequestHandler(BaseHTTPRequestHandler):
        """HTTP request handler for P2P file serving."""
        
        def do_GET(self):
            """Handle GET requests for file serving and checksums."""
            try:
                parsed_path = urlparse(self.path)
                path_parts = parsed_path.path.strip('/').split('/')
                
                if len(path_parts) < 2:
                    self.send_error(400, "Invalid path")
                    return
                
                if path_parts[0] == 'p2p':
                    if len(path_parts) == 3 and path_parts[1] == 'checksum':
                        # GET /p2p/checksum/{system}/{rom_path}
                        self._handle_checksum(path_parts[2:], roms_path)
                    elif len(path_parts) == 3 and path_parts[1] == 'file':
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
            # Create handler class with roms_path bound
            HandlerClass = create_p2p_handler(self.roms_path)
            self.server = HTTPServer(('', self.port), HandlerClass)
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
