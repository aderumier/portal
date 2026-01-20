"""WebSocket connection manager for download service notifications."""
import logging
import os
import json
from typing import Dict, Optional, List, Tuple
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime, timezone, timedelta
import asyncio
from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis client for websocket connections (initialized on first use)
_redis_ws_client = None

# Redis pub/sub channel for cross-process WebSocket notifications
WS_PUBSUB_CHANNEL = "ws:notifications"


def get_redis_ws_client():
    """Get or create Redis client for websocket connection tracking."""
    global _redis_ws_client
    
    if _redis_ws_client is not None:
        return _redis_ws_client
    
    try:
        import redis.asyncio as aioredis
        redis_url = settings.REDIS_URL
        # Use database 4 for websocket connections (sessions=0, cache=1, downloads=2, p2p=3)
        db_num = settings.REDIS_WS_DB
        if '/0' in redis_url or '/1' in redis_url or '/2' in redis_url or '/3' in redis_url or '/4' in redis_url:
            # Replace existing database number
            import re
            redis_url = re.sub(r'/\d+$', f'/{db_num}', redis_url)
        elif redis_url.endswith('/'):
            redis_url = redis_url + str(db_num)
        else:
            redis_url = redis_url + f'/{db_num}'
        
        _redis_ws_client = aioredis.from_url(
            redis_url,
            decode_responses=True,  # Websocket connections use text (JSON)
            encoding='utf-8'
        )
        logger.info(f"Redis websocket client initialized (URL: {redis_url})")
        return _redis_ws_client
    except ImportError:
        logger.warning("Redis not available for websocket tracking (redis library not installed)")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize Redis websocket client: {e}")
        return None


class WebSocketManager:
    """Manages WebSocket connections for download service clients.
    
    Maintains one connection per token_id. New connections replace old ones.
    Tracks connection metadata in Redis, websocket objects in memory.
    """
    
    def __init__(self):
        """Initialize the WebSocket manager."""
        # Only store websocket objects in memory (not serializable)
        self._websocket_objects: Dict[int, WebSocket] = {}
        self._lock = asyncio.Lock()
        self._process_id = os.getpid()
        # Try to get worker ID from environment if set
        worker_id = os.getenv('WORKER_ID')
        if worker_id:
            try:
                self._process_id = int(worker_id)
            except ValueError:
                logger.warning(f"Invalid WORKER_ID environment variable: {worker_id}, using PID {self._process_id}")
        
        # Check Redis availability on initialization
        self._redis_available = False
        self._check_redis_availability()
        
        # Pub/sub for cross-process notifications
        self._pubsub_task: Optional[asyncio.Task] = None
        self._pubsub_running = False
        self._pubsub = None  # Redis pubsub object
    
    def _check_redis_availability(self) -> bool:
        """Check if Redis is available."""
        redis_client = get_redis_ws_client()
        if redis_client is None:
            self._redis_available = False
            return False
        
        # Try to ping Redis
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, we can't use run_until_complete
                # We'll check on first use instead
                self._redis_available = True  # Assume available, will check on first use
            else:
                result = loop.run_until_complete(redis_client.ping())
                self._redis_available = result is True
        except Exception as e:
            logger.warning(f"Failed to check Redis availability: {e}")
            self._redis_available = False
        
        return self._redis_available
    
    async def _ensure_redis_available(self) -> bool:
        """Ensure Redis is available, check if needed."""
        if not self._redis_available:
            redis_client = get_redis_ws_client()
            if redis_client is None:
                return False
            try:
                await redis_client.ping()
                self._redis_available = True
                return True
            except Exception as e:
                logger.error(f"Redis not available: {e}")
                self._redis_available = False
                return False
        return True
    
    async def start_pubsub_listener(self) -> bool:
        """Start the Redis pub/sub listener for cross-process notifications.
        
        This should be called once when the application starts.
        
        Returns:
            True if listener started successfully, False otherwise
        """
        if self._pubsub_running:
            logger.debug("Pub/sub listener already running")
            return True
        
        if not await self._ensure_redis_available():
            logger.warning("Cannot start pub/sub listener: Redis not available")
            return False
        
        try:
            # Create a separate Redis client for pub/sub (it blocks during subscribe)
            import redis.asyncio as aioredis
            redis_url = settings.REDIS_URL
            db_num = settings.REDIS_WS_DB
            if '/0' in redis_url or '/1' in redis_url or '/2' in redis_url or '/3' in redis_url or '/4' in redis_url:
                import re
                redis_url = re.sub(r'/\d+$', f'/{db_num}', redis_url)
            elif redis_url.endswith('/'):
                redis_url = redis_url + str(db_num)
            else:
                redis_url = redis_url + f'/{db_num}'
            
            pubsub_client = aioredis.from_url(
                redis_url,
                decode_responses=True,
                encoding='utf-8'
            )
            
            self._pubsub = pubsub_client.pubsub()
            await self._pubsub.subscribe(WS_PUBSUB_CHANNEL)
            
            # Start the listener task
            self._pubsub_running = True
            self._pubsub_task = asyncio.create_task(self._pubsub_listener_loop())
            
            logger.info(f"Pub/sub listener started for process {self._process_id} on channel {WS_PUBSUB_CHANNEL}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start pub/sub listener: {e}", exc_info=True)
            self._pubsub_running = False
            return False
    
    async def stop_pubsub_listener(self) -> None:
        """Stop the Redis pub/sub listener."""
        self._pubsub_running = False
        
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None
        
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(WS_PUBSUB_CHANNEL)
                await self._pubsub.close()
            except Exception as e:
                logger.debug(f"Error closing pubsub: {e}")
            self._pubsub = None
        
        logger.info(f"Pub/sub listener stopped for process {self._process_id}")
    
    async def _pubsub_listener_loop(self) -> None:
        """Background task that listens for pub/sub messages."""
        logger.info(f"Pub/sub listener loop started for process {self._process_id}")
        
        try:
            while self._pubsub_running and self._pubsub:
                try:
                    message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message['type'] == 'message':
                        await self._handle_pubsub_message(message['data'])
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in pub/sub listener: {e}", exc_info=True)
                    await asyncio.sleep(1)  # Brief pause before retry
        finally:
            logger.info(f"Pub/sub listener loop ended for process {self._process_id}")
    
    async def _handle_pubsub_message(self, data: str) -> None:
        """Handle a message received via pub/sub.
        
        Args:
            data: JSON string containing the notification
        """
        try:
            payload = json.loads(data)
            target_token_id = payload.get('token_id')
            source_process = payload.get('source_process')
            message = payload.get('message')
            
            if not target_token_id or not message:
                logger.warning(f"Invalid pub/sub message: missing token_id or message")
                return
            
            # Skip if this message was sent by us (avoid echo)
            if source_process == self._process_id:
                return
            
            # Check if we have this websocket locally
            async with self._lock:
                websocket = self._websocket_objects.get(target_token_id)
            
            if websocket:
                try:
                    await websocket.send_json(message)
                    logger.info(f"Pub/sub: Forwarded notification to token_id {target_token_id} (type: {message.get('type', 'unknown')}, from process {source_process})")
                except Exception as e:
                    logger.warning(f"Pub/sub: Failed to send to token_id {target_token_id}: {e}")
            else:
                logger.debug(f"Pub/sub: token_id {target_token_id} not on this process ({self._process_id})")
                
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in pub/sub message: {e}")
        except Exception as e:
            logger.error(f"Error handling pub/sub message: {e}", exc_info=True)
    
    async def _publish_notification(self, token_id: int, message: dict) -> bool:
        """Publish a notification via Redis pub/sub for cross-process delivery.
        
        Args:
            token_id: Target token ID
            message: The message to send
            
        Returns:
            True if published successfully, False otherwise
        """
        if not await self._ensure_redis_available():
            return False
        
        redis_client = get_redis_ws_client()
        if not redis_client:
            return False
        
        try:
            payload = json.dumps({
                'token_id': token_id,
                'source_process': self._process_id,
                'message': message
            })
            
            await redis_client.publish(WS_PUBSUB_CHANNEL, payload)
            logger.debug(f"Published notification via pub/sub for token_id {token_id} (type: {message.get('type', 'unknown')})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish notification via pub/sub: {e}", exc_info=True)
            return False
    
    def _get_redis_key(self, token_id: int) -> str:
        """Get Redis key for a connection."""
        return f"ws:connections:{token_id}"
    
    def _get_process_set_key(self) -> str:
        """Get Redis set key for tracking connections by process."""
        return f"ws:process:{self._process_id}:connections"
    
    async def update_connection_info_port_check(self, token_id: int, p2p_port_accessible: bool):
        """Update connection info with P2P port accessibility result.
        
        Args:
            token_id: The API token ID
            p2p_port_accessible: True if P2P port is accessible, False otherwise
        """
        if not await self._ensure_redis_available():
            logger.warning(f"Redis unavailable, cannot update port check for token_id {token_id}")
            return
        
        redis_client = get_redis_ws_client()
        if not redis_client:
            return
        
        try:
            key = self._get_redis_key(token_id)
            await redis_client.hset(key, 'p2p_port_accessible', 'true' if p2p_port_accessible else 'false')
            logger.debug(f"Updated port check result for token_id {token_id}: {p2p_port_accessible}")
        except Exception as e:
            logger.warning(f"Failed to update port check in Redis for token_id {token_id}: {e}")
    
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
        # Check Redis availability first - reject if unavailable
        if not await self._ensure_redis_available():
            logger.error(f"Redis unavailable, rejecting websocket connection for token_id {token_id}")
            return (False, "Redis unavailable - websocket connections require Redis")
        
        redis_client = get_redis_ws_client()
        if not redis_client:
            return (False, "Redis client not available")
        
        async with self._lock:
            # Check if connection already exists in Redis
            try:
                key = self._get_redis_key(token_id)
                existing = await redis_client.exists(key)
                if existing:
                    # Check if the existing entry is valid (has required fields)
                    conn_data = await redis_client.hgetall(key)
                    has_process_id = bool(conn_data.get('process_id'))
                    has_connected_at = bool(conn_data.get('connected_at'))
                    has_last_updated = bool(conn_data.get('last_updated'))
                    
                    # If entry is missing all required fields, it's invalid/partial - clean it up
                    if not (has_process_id or has_connected_at or has_last_updated):
                        logger.warning(f"Found invalid/partial connection entry for token_id {token_id} - cleaning up and allowing new connection")
                        await redis_client.delete(key)
                        # Also remove from process set if it exists
                        process_set_key = self._get_process_set_key()
                        await redis_client.srem(process_set_key, str(token_id))
                    else:
                        logger.warning(f"Connection rejected for token_id {token_id}: another client is already connected")
                        return (False, f"Another client is already connected with this token (token_id: {token_id})")
            except Exception as e:
                logger.error(f"Error checking existing connection in Redis: {e}")
                return (False, "Error checking connection status")
            
            # Store connection metadata in Redis Hash
            try:
                connected_at = datetime.now(timezone.utc).isoformat()
                connection_data = {
                    'token_id': str(token_id),
                    'token_string': token_string or "unknown",
                    'ip': ip or "unknown",
                    'source_port': str(source_port) if source_port else '',
                    'client_version': client_version or "unknown",
                    'platform': platform or "unknown",
                    'connected_at': connected_at,
                    'last_updated': connected_at,  # Track last heartbeat for multi-worker cleanup
                    'process_id': str(self._process_id),
                    'p2p_port_accessible': '',
                    'upload_bandwidth': '',
                    'download_bandwidth': ''
                }
                
                # Store in Redis Hash with 24 hour expiration
                await redis_client.hset(key, mapping=connection_data)
                await redis_client.expire(key, 86400)  # 24 hours
                
                # Add to process set for tracking
                process_set_key = self._get_process_set_key()
                await redis_client.sadd(process_set_key, str(token_id))
                await redis_client.expire(process_set_key, 86400)  # 24 hours
                
                # Store websocket object in memory
                self._websocket_objects[token_id] = websocket
                
                logger.info(f"WebSocket connection added for token_id {token_id}, websocket_id={id(websocket)}, ip={ip}, platform={platform}, process_id={self._process_id}")
                
            except Exception as e:
                logger.error(f"Error storing connection in Redis: {e}", exc_info=True)
                return (False, f"Error storing connection: {e}")
        
        return (True, None)
    
    async def remove_connection(self, token_id: int, websocket: WebSocket) -> None:
        """Remove a WebSocket connection.
        
        Args:
            token_id: The API token ID
            websocket: The WebSocket connection to remove
        """
        logger.info(f"remove_connection called: token_id={token_id}, websocket={websocket}, websocket_id={id(websocket)}")
        
        async with self._lock:
            # Only remove if it's the same connection
            current_websocket = self._websocket_objects.get(token_id)
            if current_websocket == websocket:
                # Remove from memory
                del self._websocket_objects[token_id]
                logger.info(f"WebSocket connection removed from memory for token_id {token_id}")
            else:
                logger.warning(f"WebSocket connection for token_id {token_id} was already replaced (current != removed). Current websocket_id={id(current_websocket) if current_websocket else 'None'}, removed websocket_id={id(websocket)}")
        
        # Remove from Redis (gracefully handle unavailability)
        if await self._ensure_redis_available():
            redis_client = get_redis_ws_client()
            if redis_client:
                try:
                    key = self._get_redis_key(token_id)
                    await redis_client.delete(key)
                    
                    # Remove from process set
                    process_set_key = self._get_process_set_key()
                    await redis_client.srem(process_set_key, str(token_id))
                    
                    logger.info(f"WebSocket connection removed from Redis for token_id {token_id}")
                except Exception as e:
                    logger.warning(f"Error removing connection from Redis for token_id {token_id}: {e}")
        else:
            logger.debug(f"Redis unavailable, connection {token_id} removed from memory only")
    
    async def send_notification(self, token_id: int, message: dict) -> bool:
        """Send a notification to a connected client.
        
        If the client is connected to this process, sends directly.
        If connected to another process, publishes via Redis pub/sub.
        
        Args:
            token_id: The API token ID
            message: The message to send (will be JSON serialized)
            
        Returns:
            True if message was sent successfully (or published via pub/sub), 
            False if no connection exists or send failed
        """
        # Check local memory first (fast path)
        async with self._lock:
            websocket = self._websocket_objects.get(token_id)
        
        if websocket:
            # Send via local websocket
            try:
                await websocket.send_json(message)
                logger.debug(f"Notification sent to token_id {token_id}: {message.get('type', 'unknown')}")
                return True
            except RuntimeError as e:
                # RuntimeError usually means connection is closed
                logger.warning(f"Failed to send notification to token_id {token_id} (connection closed): {e}")
                # Remove the connection if it's dead
                await self.remove_connection(token_id, websocket)
                return False
            except Exception as e:
                logger.error(f"Failed to send notification to token_id {token_id}: {e}", exc_info=True)
                return False
        
        # Connection not in local memory - check Redis to see if it exists on another process
        if await self._ensure_redis_available():
            redis_client = get_redis_ws_client()
            if redis_client:
                try:
                    key = self._get_redis_key(token_id)
                    conn_data = await redis_client.hgetall(key)
                    
                    if conn_data and conn_data.get('process_id'):
                        # Connection exists on another process - use pub/sub
                        target_process = conn_data.get('process_id')
                        logger.info(f"Token {token_id} connected on process {target_process}, publishing via pub/sub (type: {message.get('type', 'unknown')})")
                        return await self._publish_notification(token_id, message)
                except Exception as e:
                    logger.error(f"Error checking Redis for token_id {token_id}: {e}")
        
        logger.debug(f"No WebSocket connection found for token_id {token_id}")
        return False
    
    def has_connection(self, token_id: int) -> bool:
        """Check if there's an active connection for a token_id.
        
        Args:
            token_id: The API token ID
            
        Returns:
            True if a connection exists, False otherwise
        """
        # Check local memory first (fast path)
        if token_id in self._websocket_objects:
            return True
        
        # Check Redis (synchronous check - might not be accurate if Redis is slow)
        # For async operations, use get_all_connections() instead
        return False
    
    def get_connection_count(self) -> int:
        """Get the number of active connections in local memory.
        
        Returns:
            Number of active WebSocket connections in this process
        """
        return len(self._websocket_objects)
    
    def get_local_token_ids(self) -> list:
        """Get the list of token_ids connected to this worker's WebSocket.
        
        Returns:
            List of token_ids with active WebSocket connections on this process
        """
        return list(self._websocket_objects.keys())
    
    async def send_notification_direct(self, token_id: int, message: dict) -> bool:
        """Send a notification directly to a local WebSocket connection (no pub/sub).
        
        Only sends if the client is connected to THIS worker. Does not use pub/sub.
        
        Args:
            token_id: The API token ID
            message: The message to send (will be JSON serialized)
            
        Returns:
            True if message was sent successfully, False if no local connection
        """
        async with self._lock:
            websocket = self._websocket_objects.get(token_id)
        
        if websocket:
            try:
                await websocket.send_json(message)
                logger.debug(f"Direct notification sent to token_id {token_id}: {message.get('type', 'unknown')}")
                return True
            except Exception as e:
                logger.warning(f"Failed to send direct notification to token_id {token_id}: {e}")
                return False
        
        return False
    
    async def refresh_ttl_for_active_connections(self) -> int:
        """Refresh TTL and last_updated for all connections owned by this worker.
        
        This should be called periodically (e.g., every 60 seconds) to keep
        connections alive in Redis and allow other workers to detect stale
        connections from crashed workers.
        
        Returns:
            Number of connections refreshed
        """
        if not await self._ensure_redis_available():
            return 0
        
        redis_client = get_redis_ws_client()
        if not redis_client:
            return 0
        
        refreshed_count = 0
        now = datetime.now(timezone.utc).isoformat()
        
        for token_id, websocket in list(self._websocket_objects.items()):
            try:
                # Only refresh if websocket is still connected
                is_connected = True
                if hasattr(websocket, 'client_state'):
                    from fastapi.websockets import WebSocketState
                    if websocket.client_state != WebSocketState.CONNECTED:
                        is_connected = False
                
                if is_connected:
                    key = self._get_redis_key(token_id)
                    # Update last_updated timestamp and refresh TTL
                    await redis_client.hset(key, 'last_updated', now)
                    await redis_client.expire(key, 600)  # 10 minute TTL
                    refreshed_count += 1
                else:
                    # Websocket is disconnected, remove it
                    logger.info(f"Found disconnected websocket during refresh for token_id {token_id}")
                    await self.remove_connection(token_id, websocket)
            except Exception as e:
                logger.debug(f"Error refreshing TTL for token_id {token_id}: {e}")
        
        if refreshed_count > 0:
            logger.debug(f"Refreshed TTL for {refreshed_count} active connections (worker {self._process_id})")
        
        return refreshed_count
    
    async def get_all_connections(self) -> List[Dict]:
        """Get all connected clients with their info from Redis.
        
        Returns:
            List of connection info dicts with token_id, ip, client_version, connected_at, etc.
            (websocket object is excluded from the returned dicts)
        """
        if not await self._ensure_redis_available():
            logger.warning("Redis unavailable, returning empty connection list")
            return []
        
        redis_client = get_redis_ws_client()
        if not redis_client:
            return []
        
        connections = []
        dead_connections = []
        
        try:
            # Get all connection keys
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match="ws:connections:*", count=100)
                
                for key in keys:
                    try:
                        # Extract token_id from key
                        token_id_str = key.split(':')[-1]
                        token_id = int(token_id_str)
                        
                        # Get connection data from Redis Hash
                        conn_data = await redis_client.hgetall(key)
                        if not conn_data:
                            dead_connections.append(token_id)
                            continue
                        
                        # Check if entry is valid (has required fields)
                        has_process_id = bool(conn_data.get('process_id'))
                        has_connected_at = bool(conn_data.get('connected_at'))
                        has_last_updated = bool(conn_data.get('last_updated'))
                        
                        # If missing all required fields, it's an invalid/partial entry - mark as dead
                        if not (has_process_id or has_connected_at or has_last_updated):
                            logger.info(f"Connection {token_id} is invalid/partial (missing required fields) - marking dead")
                            dead_connections.append(token_id)
                            continue
                        
                        # Multi-worker cleanup: check process_id and last_updated
                        conn_process_id = conn_data.get('process_id', '')
                        last_updated_str = conn_data.get('last_updated', '')
                        is_dead = False
                        
                        if conn_process_id == str(self._process_id):
                            # Connection owned by THIS worker - check local memory
                            websocket = self._websocket_objects.get(token_id)
                            if not websocket:
                                # Not in our memory but claims to be ours - stale entry
                                logger.info(f"Connection {token_id} claims worker {self._process_id} but not in local memory - marking dead")
                                is_dead = True
                            else:
                                # Check websocket state
                                try:
                                    if hasattr(websocket, 'client_state'):
                                        from fastapi.websockets import WebSocketState
                                        if websocket.client_state != WebSocketState.CONNECTED:
                                            is_dead = True
                                except Exception as e:
                                    logger.debug(f"Error checking websocket state for token_id {token_id}: {e}")
                        else:
                            # Connection owned by ANOTHER worker - check last_updated timestamp
                            if last_updated_str:
                                try:
                                    last_updated = datetime.fromisoformat(last_updated_str)
                                    # Use 5 minutes as stale threshold (refresh happens every 60s)
                                    stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
                                    if last_updated < stale_threshold:
                                        logger.info(f"Connection {token_id} from worker {conn_process_id} is stale (last_updated: {last_updated_str}) - marking dead")
                                        is_dead = True
                                except (ValueError, TypeError) as e:
                                    logger.debug(f"Error parsing last_updated for token_id {token_id}: {e}")
                            else:
                                # No last_updated field - legacy connection, check connected_at
                                connected_at_str = conn_data.get('connected_at', '')
                                if connected_at_str:
                                    try:
                                        connected_at = datetime.fromisoformat(connected_at_str)
                                        stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=10)
                                        if connected_at < stale_threshold:
                                            logger.info(f"Legacy connection {token_id} from worker {conn_process_id} is stale - marking dead")
                                            is_dead = True
                                    except (ValueError, TypeError):
                                        pass
                        
                        if is_dead:
                            dead_connections.append(token_id)
                            continue
                        
                        # Convert Redis Hash data to dict
                        connection_dict = {
                            'token_id': int(conn_data.get('token_id', token_id_str)),
                            'token_string': conn_data.get('token_string', 'unknown'),
                            'ip': conn_data.get('ip', 'unknown'),
                            'source_port': int(conn_data.get('source_port')) if conn_data.get('source_port') else None,
                            'client_version': conn_data.get('client_version', 'unknown'),
                            'platform': conn_data.get('platform', 'unknown'),
                            'connected_at': conn_data.get('connected_at', ''),
                            'p2p_port_accessible': conn_data.get('p2p_port_accessible') == 'true' if conn_data.get('p2p_port_accessible') else None,
                            'upload_bandwidth': float(conn_data.get('upload_bandwidth')) if conn_data.get('upload_bandwidth') else None,
                            'download_bandwidth': float(conn_data.get('download_bandwidth')) if conn_data.get('download_bandwidth') else None
                        }
                        connections.append(connection_dict)
                    except (ValueError, KeyError) as e:
                        logger.debug(f"Error processing connection key {key}: {e}")
                        dead_connections.append(token_id if 'token_id' in locals() else None)
                
                if cursor == 0:
                    break
            
            # Remove dead connections
            for token_id in dead_connections:
                if token_id:
                    try:
                        key = self._get_redis_key(token_id)
                        await redis_client.delete(key)
                        process_set_key = self._get_process_set_key()
                        await redis_client.srem(process_set_key, str(token_id))
                        logger.info(f"Removed dead WebSocket connection from Redis for token_id {token_id}")
                    except Exception as e:
                        logger.warning(f"Error removing dead connection {token_id}: {e}")
        
        except Exception as e:
            logger.error(f"Error getting all connections from Redis: {e}", exc_info=True)
        
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
