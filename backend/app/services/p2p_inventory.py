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
    def _get_index_key(system: str, rom_path: str) -> str:
        """Get Redis key for reverse index (which clients have this ROM).
        
        Args:
            system: System identifier
            rom_path: ROM path
        """
        return f"p2p:index:{system}/{rom_path}"
    
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
            # Add new inventory entries to index
            for system, paths in inventory.items():
                for rom_path in paths:
                    index_key = P2PInventoryService._get_index_key(system, rom_path)
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
            index_key = P2PInventoryService._get_index_key(system, rom_path)
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
        """Rebuild the entire p2p_index by computing all keys from current state.
        
        Process:
        1. Scan all existing p2p:index:* keys (including versioned ones for cleanup)
        2. Collect all ROM paths and their token_ids
        3. Rewrite all keys in place (update existing, keep valid ones)
        4. Delete keys that no longer have any token_ids
        5. Clean up any versioned keys (p2p:index_v1:*, p2p:index_v2:*)
        
        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            logger.info("Starting p2p_index rebuild")
            
            # Step 1: Collect all index data from all possible key formats
            # Scan for: p2p:index:* (current format) and p2p:index_v*:* (old versioned format)
            all_patterns = ["p2p:index:*", "p2p:index_v1:*", "p2p:index_v2:*"]
            consolidated_index = {}  # {rom_key: set of token_ids}
            all_keys_found = set()
            
            for pattern in all_patterns:
                cursor = 0
                while True:
                    cursor, keys = await redis_client.scan(cursor, match=pattern, count=1000)
                    for key in keys:
                        all_keys_found.add(key)
                        # Extract rom_key from any format
                        if key.startswith("p2p:index:"):
                            # Current format: p2p:index:{system}/{rom_path}
                            rom_key = key.replace("p2p:index:", "", 1)
                        elif ":" in key:
                            # Versioned format: p2p:index_v1:{system}/{rom_path} or p2p:index_v2:{system}/{rom_path}
                            parts = key.split(":", 2)
                            if len(parts) >= 3:
                                rom_key = parts[2]
                            else:
                                continue  # Skip malformed keys
                        else:
                            continue
                        
                        # Get all token_ids for this ROM
                        token_ids = await redis_client.smembers(key)
                        token_id_set = {tid for tid in token_ids if tid.isdigit()}
                        
                        # Merge with existing data (same ROM might be in multiple formats)
                        if rom_key in consolidated_index:
                            consolidated_index[rom_key].update(token_id_set)
                        else:
                            consolidated_index[rom_key] = token_id_set
                    
                    if cursor == 0:
                        break
            
            logger.info(f"Scanned {len(all_keys_found)} index keys, found {len(consolidated_index)} unique ROM paths")
            
            # Step 2: Rewrite all keys in place (compute new keys, rewrite existing, delete missing)
            keys_updated = 0
            keys_deleted = 0
            pipeline = redis_client.pipeline()
            pipeline_count = 0
            
            # Process all consolidated ROM paths
            for rom_key, token_ids in consolidated_index.items():
                index_key = f"p2p:index:{rom_key}"
                
                if token_ids:
                    # Rewrite key with current token_ids
                    pipeline.delete(index_key)  # Clear existing
                    pipeline.sadd(index_key, *[str(tid) for tid in token_ids])
                    pipeline.expire(index_key, 48 * 3600)
                    keys_updated += 1
                    pipeline_count += 3
                else:
                    # Delete empty keys
                    pipeline.delete(index_key)
                    keys_deleted += 1
                    pipeline_count += 1
                
                # Execute pipeline in batches to avoid memory issues
                if pipeline_count >= 3000:  # ~1000 ROMs per batch
                    await pipeline.execute()
                    pipeline = redis_client.pipeline()
                    pipeline_count = 0
            
            # Execute remaining pipeline operations
            if pipeline_count > 0:
                await pipeline.execute()
            
            logger.info(f"Updated {keys_updated} index keys, deleted {keys_deleted} empty keys")
            
            # Step 3: Delete all old versioned keys (cleanup)
            versioned_keys_to_delete = []
            for pattern in ["p2p:index_v1:*", "p2p:index_v2:*"]:
                cursor = 0
                while True:
                    cursor, keys = await redis_client.scan(cursor, match=pattern, count=1000)
                    versioned_keys_to_delete.extend(keys)
                    if cursor == 0:
                        break
            
            if versioned_keys_to_delete:
                # Delete in batches
                batch_size = 1000
                for i in range(0, len(versioned_keys_to_delete), batch_size):
                    batch = versioned_keys_to_delete[i:i + batch_size]
                    await redis_client.delete(*batch)
                logger.info(f"Deleted {len(versioned_keys_to_delete)} old versioned index keys")
            
            # Step 4: Delete version pointer if it exists
            try:
                await redis_client.delete("p2p:index_version")
            except Exception:
                pass
            
            logger.info(f"p2p_index rebuild completed: {keys_updated} keys updated, {keys_deleted} keys deleted")
            return True
            
        except Exception as e:
            logger.error(f"Error rebuilding p2p_index: {e}", exc_info=True)
            return False

