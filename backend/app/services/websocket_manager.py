"""WebSocket connection manager for download service notifications."""
import logging
from typing import Dict, Optional, List, Tuple
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
import asyncio

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections for download service clients.
    
    Maintains one connection per token_id. New connections replace old ones.
    Tracks connection info in active_connections dict for admin monitoring.
    """
    
    def __init__(self):
        """Initialize the WebSocket manager."""
        # Structure: {token_id: {'websocket': WebSocket, 'token_id': int, 'token_string': str, 
        #                        'ip': str, 'source_port': Optional[int], 'client_version': Optional[str],
        #                        'platform': Optional[str], 'connected_at': str, 
        #                        'p2p_port_accessible': Optional[bool], 
        #                        'upload_bandwidth': Optional[float], 'download_bandwidth': Optional[float]}}
        self.active_connections: Dict[int, Dict] = {}
        self._lock = asyncio.Lock()
    
    async def update_connection_info_port_check(self, token_id: int, p2p_port_accessible: bool):
        """Update connection info with P2P port accessibility result.
        
        Args:
            token_id: The API token ID
            p2p_port_accessible: True if P2P port is accessible, False otherwise
        """
        async with self._lock:
            if token_id in self.active_connections:
                self.active_connections[token_id]['p2p_port_accessible'] = p2p_port_accessible
                logger.debug(f"Updated port check result for token_id {token_id}: {p2p_port_accessible}")
            else:
                logger.debug(f"Connection not found for token_id {token_id}, cannot update port check")
    
    async def add_connection(self, token_id: int, websocket: WebSocket, ip: Optional[str] = None, source_port: Optional[int] = None, client_version: Optional[str] = None, token_string: Optional[str] = None, platform: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Add a WebSocket connection for a token_id.
        
        Only one connection per token_id is allowed. If a connection already exists,
        the new connection will be rejected.
        
        Args:
            token_id: The API token ID
            websocket: The WebSocket connection
            ip: Client IP address (optional)
            source_port: Client source port (optional)
            client_version: Client version string (optional)
            token_string: The token string for tracking (optional)
            platform: Client platform (linux/windows) (optional)
            
        Returns:
            Tuple of (accepted: bool, reason: Optional[str])
            - (True, None) if connection was accepted
            - (False, "reason") if connection was rejected
        """
        async with self._lock:
            if token_id in self.active_connections:
                existing_ip = ip  # We don't have access to old IP easily, but log what we know
                logger.warning(f"Connection rejected for token_id {token_id}: another client is already connected from {existing_ip}")
                return (False, f"Another client is already connected with this token (token_id: {token_id})")
            
            # Store connection info directly in active_connections dict
            self.active_connections[token_id] = {
                'websocket': websocket,
                'token_id': token_id,
                'token_string': token_string or "unknown",
                'ip': ip or "unknown",
                'source_port': source_port,
                'client_version': client_version or "unknown",
                'platform': platform or "unknown",
                'connected_at': datetime.now(timezone.utc).isoformat(),
                'p2p_port_accessible': None,
                'upload_bandwidth': None,
                'download_bandwidth': None
            }
            logger.info(f"WebSocket connection added for token_id {token_id}")
        
        return (True, None)
    
    async def _close_connection_safely(self, websocket: WebSocket):
        """Close a connection safely without blocking."""
        try:
            await websocket.close(code=1000, reason="Replaced by new connection")
        except Exception as e:
            logger.debug(f"Error closing connection (may already be closed): {e}")
    
    async def remove_connection(self, token_id: int, websocket: WebSocket) -> None:
        """Remove a WebSocket connection.
        
        Args:
            token_id: The API token ID
            websocket: The WebSocket connection to remove
        """
        async with self._lock:
            # Only remove if it's the same connection (avoid removing a new connection)
            conn_info = self.active_connections.get(token_id)
            if conn_info:
                current_websocket = conn_info.get('websocket')
                if current_websocket == websocket:
                    del self.active_connections[token_id]
                    logger.info(f"WebSocket connection removed for token_id {token_id}")
                else:
                    logger.debug(f"WebSocket connection for token_id {token_id} was already replaced (current != removed)")
            else:
                logger.debug(f"Connection for token_id {token_id} already removed from active_connections")
    
    async def send_notification(self, token_id: int, message: dict) -> bool:
        """Send a notification to a connected client.
        
        Args:
            token_id: The API token ID
            message: The message to send (will be JSON serialized)
            
        Returns:
            True if message was sent successfully, False if no connection exists or send failed
        """
        async with self._lock:
            conn_info = self.active_connections.get(token_id)
            if not conn_info:
                logger.debug(f"No WebSocket connection found for token_id {token_id}")
                return False
            websocket = conn_info.get('websocket')
        
        # Send outside the lock to avoid blocking other operations
        try:
            await websocket.send_json(message)
            logger.debug(f"Notification sent to token_id {token_id}: {message.get('type', 'unknown')}")
            return True
        except RuntimeError as e:
            # RuntimeError usually means connection is closed
            logger.warning(f"Failed to send notification to token_id {token_id} (connection closed): {e}")
            # Remove the connection if it's dead
            async with self._lock:
                conn_info = self.active_connections.get(token_id)
                if conn_info and conn_info.get('websocket') == websocket:
                    del self.active_connections[token_id]
            return False
        except Exception as e:
            logger.error(f"Failed to send notification to token_id {token_id}: {e}", exc_info=True)
            # Don't remove connection on other errors - might be temporary
            return False
    
    def has_connection(self, token_id: int) -> bool:
        """Check if there's an active connection for a token_id.
        
        Args:
            token_id: The API token ID
            
        Returns:
            True if a connection exists, False otherwise
        """
        return token_id in self.active_connections
    
    def get_connection_count(self) -> int:
        """Get the number of active connections.
        
        Returns:
            Number of active WebSocket connections
        """
        return len(self.active_connections)
    
    async def get_all_connections(self) -> List[Dict]:
        """Get all connected clients with their info from active_connections.
        
        Returns:
            List of connection info dicts with token_id, ip, client_version, connected_at, etc.
            (websocket object is excluded from the returned dicts)
        """
        async with self._lock:
            connections = []
            for token_id, conn_info in self.active_connections.items():
                # Create a copy without the websocket object for API responses
                connection_dict = {
                    'token_id': conn_info.get('token_id'),
                    'token_string': conn_info.get('token_string'),
                    'ip': conn_info.get('ip'),
                    'source_port': conn_info.get('source_port'),
                    'client_version': conn_info.get('client_version'),
                    'platform': conn_info.get('platform'),
                    'connected_at': conn_info.get('connected_at'),
                    'p2p_port_accessible': conn_info.get('p2p_port_accessible'),
                    'upload_bandwidth': conn_info.get('upload_bandwidth'),
                    'download_bandwidth': conn_info.get('download_bandwidth')
                }
                connections.append(connection_dict)
        
        return connections


# Global singleton instance
_websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance.
    
    Returns:
        The WebSocketManager singleton
    """
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager

