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
        """Get Redis key for reverse index (which clients have this ROM)."""
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
            # Note: Old entries expire naturally via TTL (48 hours)
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
            logger.debug(f"Updated P2P client connection info for token_id {token_id}")
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

