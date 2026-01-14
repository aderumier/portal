"""WebSocket connection manager for download service notifications."""
import logging
import json
from typing import Dict, Optional, List, Tuple
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
import asyncio

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections for download service clients.
    
    Maintains one connection per token_id. New connections replace old ones.
    Tracks connection info in Redis for admin monitoring.
    """
    
    def __init__(self):
        """Initialize the WebSocket manager."""
        self.active_connections: Dict[int, WebSocket] = {}
        self._lock = asyncio.Lock()
        self._redis_client = None
        self._redis_key_prefix = "ws_client:"
    
    async def _get_redis_client(self):
        """Get Redis client for tracking connections."""
        if self._redis_client is None:
            try:
                from app.services.discord import get_redis_cache_client
                # Use cache client (decode_responses=True) for JSON storage
                self._redis_client = get_redis_cache_client()
            except Exception as e:
                logger.debug(f"Redis not available for connection tracking: {e}")
        return self._redis_client
    
    async def _store_connection_info(self, token_id: int, ip: str, client_version: Optional[str] = None, token_string: Optional[str] = None, platform: Optional[str] = None):
        """Store connection info in Redis."""
        redis_client = await self._get_redis_client()
        if not redis_client:
            return
        
        try:
            connection_info = {
                "token_id": token_id,
                "token_string": token_string or "unknown",
                "ip": ip,
                "client_version": client_version or "unknown",
                "platform": platform or "unknown",
                "connected_at": datetime.now(timezone.utc).isoformat()
            }
            redis_key = f"{self._redis_key_prefix}{token_id}"
            await redis_client.setex(redis_key, 86400, json.dumps(connection_info))  # 24 hour TTL
            logger.debug(f"Stored connection info in Redis for token_id {token_id}")
        except Exception as e:
            logger.warning(f"Failed to store connection info in Redis: {e}")
    
    async def update_connection_info_port_check(self, token_id: int, p2p_port_accessible: bool):
        """Update connection info in Redis with P2P port accessibility result.
        
        Args:
            token_id: The API token ID
            p2p_port_accessible: True if P2P port is accessible, False otherwise
        """
        redis_client = await self._get_redis_client()
        if not redis_client:
            return
        
        try:
            redis_key = f"{self._redis_key_prefix}{token_id}"
            data = await redis_client.get(redis_key)
            if data:
                connection_info = json.loads(data)
                connection_info["p2p_port_accessible"] = p2p_port_accessible
                await redis_client.setex(redis_key, 86400, json.dumps(connection_info))  # 24 hour TTL
                logger.debug(f"Updated port check result in Redis for token_id {token_id}: {p2p_port_accessible}")
            else:
                logger.debug(f"Connection info not found in Redis for token_id {token_id}, cannot update port check")
        except Exception as e:
            logger.warning(f"Failed to update port check in Redis for token_id {token_id}: {e}")
    
    async def _remove_connection_info(self, token_id: int):
        """Remove connection info from Redis."""
        redis_client = await self._get_redis_client()
        if not redis_client:
            logger.debug(f"Redis client not available, skipping Redis cleanup for token_id {token_id}")
            return
        
        try:
            redis_key = f"{self._redis_key_prefix}{token_id}"
            deleted = await redis_client.delete(redis_key)
            if deleted:
                logger.info(f"Removed connection info from Redis for token_id {token_id} (key: {redis_key})")
            else:
                logger.debug(f"Connection info not found in Redis for token_id {token_id} (may have been already removed)")
        except Exception as e:
            logger.warning(f"Failed to remove connection info from Redis for token_id {token_id}: {e}")
    
    async def add_connection(self, token_id: int, websocket: WebSocket, ip: Optional[str] = None, client_version: Optional[str] = None, token_string: Optional[str] = None, platform: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Add a WebSocket connection for a token_id.
        
        Only one connection per token_id is allowed. If a connection already exists,
        the new connection will be rejected.
        
        Args:
            token_id: The API token ID
            websocket: The WebSocket connection
            ip: Client IP address (optional)
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
            
            # Add the new connection
            self.active_connections[token_id] = websocket
            logger.info(f"WebSocket connection added for token_id {token_id}")
            
            # Store connection info in Redis (note: db parameter not available here, will be updated when bandwidth test completes)
            if ip:
                await self._store_connection_info(token_id, ip, client_version, token_string, platform)
        
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
            current_websocket = self.active_connections.get(token_id)
            if current_websocket == websocket:
                del self.active_connections[token_id]
                logger.info(f"WebSocket connection removed for token_id {token_id}")
                # Remove connection info from Redis
                await self._remove_connection_info(token_id)
            else:
                logger.debug(f"WebSocket connection for token_id {token_id} was already replaced (current != removed)")
    
    async def send_notification(self, token_id: int, message: dict) -> bool:
        """Send a notification to a connected client.
        
        Args:
            token_id: The API token ID
            message: The message to send (will be JSON serialized)
            
        Returns:
            True if message was sent successfully, False if no connection exists or send failed
        """
        async with self._lock:
            websocket = self.active_connections.get(token_id)
            
            if not websocket:
                logger.debug(f"No WebSocket connection found for token_id {token_id}")
                return False
        
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
                if token_id in self.active_connections and self.active_connections[token_id] == websocket:
                    del self.active_connections[token_id]
                    await self._remove_connection_info(token_id)
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
        """Get all connected clients with their info from Redis.
        
        Returns:
            List of connection info dicts with token_id, ip, client_version, connected_at
        """
        redis_client = await self._get_redis_client()
        if not redis_client:
            return []
        
        try:
            # Get all keys with the prefix
            pattern = f"{self._redis_key_prefix}*"
            keys = await redis_client.keys(pattern)
            
            connections = []
            for key in keys:
                try:
                    data = await redis_client.get(key)
                    if data:
                        connection_info = json.loads(data)
                        # Only include if still in active_connections (verify it's actually connected)
                        token_id = connection_info.get("token_id")
                        if token_id:
                            try:
                                token_id_int = int(token_id)
                                # Verify connection is still active
                                async with self._lock:
                                    if token_id_int in self.active_connections:
                                        connections.append(connection_info)
                            except (ValueError, TypeError) as e:
                                logger.debug(f"Invalid token_id in connection info: {token_id}, error: {e}")
                except Exception as e:
                    logger.debug(f"Error reading connection info for key {key}: {e}")
            
            return connections
        except Exception as e:
            logger.error(f"Error getting all connections from Redis: {e}")
            return []


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

