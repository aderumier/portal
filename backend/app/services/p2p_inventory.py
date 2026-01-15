"""P2P inventory service for tracking client ROM files."""
import json
import logging
from typing import Optional, Dict, Set, List
from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis client for P2P inventory (initialized on first use)
_redis_p2p_client = None

def get_redis_p2p_client():
    """Get or create Redis client for P2P inventory."""
    global _redis_p2p_client
    
    if _redis_p2p_client is not None:
        return _redis_p2p_client
    
    try:
        import redis.asyncio as aioredis
        redis_url = settings.REDIS_URL
        # Use database 3 for P2P to separate from sessions (0), cache (1), downloads (2)
        if '/0' in redis_url:
            redis_url = redis_url.replace('/0', '/3')
        elif '/1' in redis_url:
            redis_url = redis_url.replace('/1', '/3')
        elif '/2' in redis_url:
            redis_url = redis_url.replace('/2', '/3')
        elif redis_url.endswith('/'):
            redis_url = redis_url + '3'
        else:
            redis_url = redis_url + '/3'
        
        _redis_p2p_client = aioredis.from_url(
            redis_url,
            decode_responses=True,  # P2P uses text (JSON)
            encoding='utf-8'
        )
        logger.info(f"Redis P2P client initialized (URL: {redis_url})")
        return _redis_p2p_client
    except ImportError:
        logger.debug("Redis not available for P2P inventory (redis library not installed)")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize Redis P2P client: {e}")
        return None

class P2PInventoryService:
    """Service for managing P2P client ROM inventory in Redis."""
    
    @staticmethod
    async def _get_index_key(system: str, rom_path: str, version: Optional[str] = None) -> str:
        """Get Redis key for reverse index (which clients have this ROM).
        
        Args:
            system: System identifier
            rom_path: ROM path
            version: Optional version suffix (for atomic rebuilds). If None, uses current active version.
        """
        if version:
            return f"p2p:index_{version}:{system}/{rom_path}"
        # Get current version from pointer
        current_version = await P2PInventoryService._get_current_index_version()
        return f"p2p:index_{current_version}:{system}/{rom_path}"
    
    @staticmethod
    async def _get_current_index_version() -> str:
        """Get the current active index version."""
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return "v1"
        
        try:
            version = await redis_client.get("p2p:index_version")
            return version if version else "v1"
        except Exception:
            return "v1"
    
    @staticmethod
    async def _set_index_version(version: str) -> bool:
        """Set the current active index version."""
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            await redis_client.set("p2p:index_version", version)
            return True
        except Exception:
            return False
    
    @staticmethod
    async def update_inventory(token_id: int, inventory: Dict[str, List[str]]) -> bool:
        """Update client ROM inventory.
        
        Args:
            token_id: API token ID of the client
            inventory: Dictionary mapping system to list of ROM paths
                      Format: {system: [path1, path2, ...], system2: [path1, path2, ...], ...}
        
        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            # Get current version to write to correct index
            current_version = await P2PInventoryService._get_current_index_version()
            
            # Add new inventory entries to index
            for system, paths in inventory.items():
                for rom_path in paths:
                    index_key = await P2PInventoryService._get_index_key(system, rom_path, current_version)
                    await redis_client.sadd(index_key, str(token_id))
                    # Set TTL on index key (48 hours)
                    await redis_client.expire(index_key, 48 * 3600)
            
            total_paths = sum(len(paths) for paths in inventory.values())
            logger.info(f"Updated P2P inventory for token_id {token_id}: {len(inventory)} systems, {total_paths} ROM paths")
            return True
        except Exception as e:
            logger.error(f"Error updating P2P inventory for token_id {token_id}: {e}")
            return False
    
    @staticmethod
    async def find_clients_with_rom(system: str, rom_path: str) -> Set[int]:
        """Find all clients that have a specific ROM.
        
        Args:
            system: System identifier
            rom_path: ROM path
        
        Returns:
            Set of token_ids that have this ROM
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return set()
        
        try:
            # Get current version and use it for lookup
            current_version = await P2PInventoryService._get_current_index_version()
            index_key = await P2PInventoryService._get_index_key(system, rom_path, current_version)
            
            token_ids_str = await redis_client.smembers(index_key)
            return {int(token_id) for token_id in token_ids_str if token_id.isdigit()}
        except Exception as e:
            logger.error(f"Error finding clients with ROM {system}/{rom_path}: {e}")
            return set()
    
    @staticmethod
    async def remove_inventory(token_id: int) -> bool:
        """Remove client inventory (when client disconnects or token revoked).
        
        Args:
            token_id: API token ID of the client
        
        Returns:
            True if successful, False otherwise
        
        Note:
            Index entries expire naturally via TTL (48 hours) instead of being cleaned up immediately.
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            # Remove client connection info
            # Note: Index entries expire naturally via TTL (48 hours)
            client_key = f"p2p:client:{token_id}"
            await redis_client.delete(client_key)
            
            logger.info(f"Removed P2P client connection info for token_id {token_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing P2P client connection info for token_id {token_id}: {e}")
            return False
    
    @staticmethod
    async def update_client_connection_info(token_id: int, connection_info: Dict) -> bool:
        """Update client connection info for P2P transfers.
        
        Args:
            token_id: API token ID of the client
            connection_info: Dictionary with connection info (external_ip, external_port, internal_port, upnp_enabled, etc.)
        
        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            client_key = f"p2p:client:{token_id}"
            # Store with 48 hour TTL (clients re-register periodically)
            await redis_client.setex(client_key, 48 * 3600, json.dumps(connection_info))
            logger.info(f"Updated P2P client connection info in Redis for token_id {token_id}: external_ip={connection_info.get('external_ip')}, external_port={connection_info.get('external_port')}, upnp_enabled={connection_info.get('upnp_enabled')}")
            return True
        except Exception as e:
            logger.error(f"Error updating P2P client connection info for token_id {token_id}: {e}")
            return False
    
    @staticmethod
    async def get_client_connection_info(token_id: int) -> Optional[Dict]:
        """Get client connection info for P2P transfers.
        
        Args:
            token_id: API token ID of the client
        
        Returns:
            Connection info dictionary (external_ip, external_port, internal_port, upnp_enabled, etc.) or None if not found
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return None
        
        try:
            client_key = f"p2p:client:{token_id}"
            connection_info_str = await redis_client.get(client_key)
            if connection_info_str:
                return json.loads(connection_info_str)
            return None
        except Exception as e:
            logger.error(f"Error getting P2P client connection info for token_id {token_id}: {e}")
            return None
    
    @staticmethod
    async def find_eligible_peers(system: str, rom_path: str, exclude_token_id: int, limit: int = 20, rom_file_size_bytes: Optional[int] = None) -> List[Dict]:
        """Find eligible P2P peers that have a specific ROM.
        
        Args:
            system: System identifier
            rom_path: ROM path (relative to system directory)
            exclude_token_id: Token ID of the requesting client (to exclude)
            limit: Maximum number of peers to return (default: 20)
            rom_file_size_bytes: Optional ROM file size in bytes (used for filtering slow peers for large files)
        
        Returns:
            List of peer dictionaries, each containing: external_ip, external_port, token_id
            Sorted by upload_bandwidth (descending, None values last)
        """
        redis_p2p_client = get_redis_p2p_client()
        if not redis_p2p_client:
            return []
        
        try:
            # Get Redis cache client for WebSocket connection info (database 1)
            from app.services.discord import get_redis_cache_client
            redis_cache_client = get_redis_cache_client()
            
            # Get requesting client's external IP to exclude
            requesting_client_info = await P2PInventoryService.get_client_connection_info(exclude_token_id)
            requesting_external_ip = requesting_client_info.get('external_ip') if requesting_client_info else None
            
            # Find all clients that have this ROM
            candidate_token_ids = await P2PInventoryService.find_clients_with_rom(system, rom_path)
            
            # Remove the requesting client
            candidate_token_ids.discard(exclude_token_id)
            
            if not candidate_token_ids:
                return []
            
            eligible_peers = []
            
            # For each candidate, get connection info and filter
            for token_id in candidate_token_ids:
                try:
                    # Get P2P connection info (external_ip, external_port)
                    p2p_info = await P2PInventoryService.get_client_connection_info(token_id)
                    if not p2p_info:
                        continue
                    
                    external_ip = p2p_info.get('external_ip')
                    external_port = p2p_info.get('external_port')
                    
                    if not external_ip or not external_port:
                        continue
                    
                    # Exclude if same external IP as requesting client
                    if requesting_external_ip and external_ip == requesting_external_ip:
                        continue
                    
                    # Get WebSocket connection info (upload_bandwidth, p2p_port_accessible)
                    upload_bandwidth = None
                    p2p_port_accessible = False
                    if redis_cache_client:
                        try:
                            ws_key = f"ws_client:{token_id}"
                            ws_info_str = await redis_cache_client.get(ws_key)
                            if ws_info_str:
                                ws_info = json.loads(ws_info_str)
                                upload_bandwidth = ws_info.get('upload_bandwidth')
                                p2p_port_accessible = ws_info.get('p2p_port_accessible', False)
                        except Exception as e:
                            logger.debug(f"Error getting WebSocket info for token_id {token_id}: {e}")
                    
                    # Filter: must have p2p_port_accessible=True
                    if not p2p_port_accessible:
                        continue
                    
                    # Filter: Skip if file is large (>10MB) and peer has slow upload (<20 Mbits/s)
                    if rom_file_size_bytes is not None and rom_file_size_bytes > 10485760:  # 10MB in bytes
                        if upload_bandwidth is None or upload_bandwidth < 20.0:
                            continue  # Skip slow peers for large files
                    
                    eligible_peers.append({
                        'external_ip': external_ip,
                        'external_port': external_port,
                        'token_id': token_id,
                        'upload_bandwidth': upload_bandwidth if upload_bandwidth is not None else 0.0
                    })
                    
                except Exception as e:
                    logger.debug(f"Error processing candidate token_id {token_id}: {e}")
                    continue
            
            # Sort by upload_bandwidth (descending, None values last - but we set None to 0.0 above)
            eligible_peers.sort(key=lambda x: x['upload_bandwidth'], reverse=True)
            
            # Remove upload_bandwidth from results (not needed by client)
            for peer in eligible_peers:
                del peer['upload_bandwidth']
            
            # Return up to limit entries
            return eligible_peers[:limit]
            
        except Exception as e:
            logger.error(f"Error finding eligible peers for {system}/{rom_path}: {e}", exc_info=True)
            return []
    
    @staticmethod
    async def rebuild_index() -> bool:
        """Atomically rebuild the entire p2p_index.
        
        Uses a versioned approach:
        1. Build new index with version suffix (e.g., p2p:index_v2:*)
        2. Atomically switch pointer to new version
        3. Delete old version keys in background
        
        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            # Get current version
            current_version = await P2PInventoryService._get_current_index_version()
            new_version = "v2" if current_version == "v1" else "v1"
            
            logger.info(f"Starting atomic p2p_index rebuild: current={current_version}, new={new_version}")
            
            # Step 1: Collect all current index data
            # Scan all current index keys and build new index structure
            current_pattern = f"p2p:index_{current_version}:*"
            if current_version == "v1":
                # First rebuild - check old format without version
                current_pattern = "p2p:index:*"
            
            new_index = {}  # {rom_key: set of token_ids}
            cursor = 0
            keys_scanned = 0
            
            # Scan current index
            while True:
                cursor, keys = await redis_client.scan(cursor, match=current_pattern, count=1000)
                for key in keys:
                    keys_scanned += 1
                    # Extract system/rom_path from key
                    if current_version == "v1" and not key.startswith("p2p:index_"):
                        # Old format: p2p:index:{system}/{rom_path}
                        rom_key = key.replace("p2p:index:", "", 1)
                    else:
                        # Versioned format: p2p:index_v1:{system}/{rom_path}
                        parts = key.split(":", 2)
                        if len(parts) >= 3:
                            rom_key = parts[2]
                        else:
                            continue  # Skip malformed keys
                    
                    # Get all token_ids for this ROM
                    token_ids = await redis_client.smembers(key)
                    new_index[rom_key] = {tid for tid in token_ids if tid.isdigit()}
                
                if cursor == 0:
                    break
            
            logger.info(f"Scanned {keys_scanned} index keys, found {len(new_index)} unique ROM paths")
            
            # Step 2: Build new index with new version prefix
            new_keys_created = 0
            pipeline = redis_client.pipeline()
            
            for rom_key, token_ids in new_index.items():
                new_index_key = f"p2p:index_{new_version}:{rom_key}"
                # Clear and add all token_ids
                pipeline.delete(new_index_key)  # Clear if exists
                if token_ids:
                    pipeline.sadd(new_index_key, *[str(tid) for tid in token_ids])
                    pipeline.expire(new_index_key, 48 * 3600)
                    new_keys_created += 1
            
            # Execute pipeline to create new index
            await pipeline.execute()
            logger.info(f"Created {new_keys_created} new index keys with version {new_version}")
            
            # Step 3: Atomically switch to new version (this is the atomic operation)
            success = await P2PInventoryService._set_index_version(new_version)
            if not success:
                logger.error("Failed to switch index version pointer")
                return False
            
            logger.info(f"Atomically switched index version to {new_version}")
            
            # Step 4: Delete old version keys in background (non-blocking)
            # This doesn't need to be atomic since we've already switched
            old_pattern = f"p2p:index_{current_version}:*"
            if current_version == "v1":
                old_pattern = "p2p:index:*"  # Also clean up old format
            
            old_keys_to_delete = []
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match=old_pattern, count=1000)
                old_keys_to_delete.extend(keys)
                if cursor == 0:
                    break
            
            # Filter out keys that match new version pattern
            old_keys_to_delete = [k for k in old_keys_to_delete if not k.startswith(f"p2p:index_{new_version}:")]
            
            if old_keys_to_delete:
                # Delete in batches to avoid blocking
                batch_size = 1000
                for i in range(0, len(old_keys_to_delete), batch_size):
                    batch = old_keys_to_delete[i:i + batch_size]
                    await redis_client.delete(*batch)
                logger.info(f"Deleted {len(old_keys_to_delete)} old index keys")
            
            logger.info(f"Atomic p2p_index rebuild completed: switched to version {new_version}")
            return True
            
        except Exception as e:
            logger.error(f"Error rebuilding p2p_index: {e}", exc_info=True)
            return False

